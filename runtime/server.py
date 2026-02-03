"""
TAP Template Agent - A2A Protocol Server

FastAPI server implementing the A2A protocol for Cloud Run deployment.

**STREAMING-ONLY ARCHITECTURE**: TAP Gateway is designed to use only the
streaming endpoint (`/stream`) for SMA invocation. The sync endpoint exists
for local CLI testing but is not used by the platform.

Endpoints:
- GET  /.well-known/agent.json  - Agent card discovery
- POST /                         - JSON-RPC 2.0 A2A endpoint (local CLI testing)
- POST /stream                   - SSE streaming endpoint (GATEWAY USES THIS)
- GET  /health                   - Health check

Gateway invokes SMAs via:
- POST to cloud_run_url/stream   - PRODUCTION (streaming with SSE)
- POST to cloud_run_url (root)   - NOT USED by Gateway (local testing only)

Usage:
    python server.py              # Start server on port 8080
    uvicorn server:app --reload   # Development with auto-reload

Deploy to Cloud Run:
    gcloud run deploy my-agent --source .
"""

import asyncio
import logging
import os
import sys
import time
from typing import Any, Dict, Optional
from uuid import uuid4

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# Load .env file FIRST (before validation, so .env can set GOOGLE_CLOUD_PROJECT)
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines, comments, and lines without '='
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # Handle values that might contain '=' (e.g., API_KEY=abc=def)
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present (common in .env files)
                if value and len(value) >= 2:
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                if key:  # Only set if key is non-empty
                    os.environ.setdefault(key, value)
    except Exception as e:
        # Log but don't fail - .env is optional
        print(f"Warning: Could not load .env file: {e}", file=sys.stderr)

# Validate GOOGLE_CLOUD_PROJECT is set AFTER loading .env (fail fast if not configured)
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    raise RuntimeError(
        "GOOGLE_CLOUD_PROJECT environment variable is required. "
        "Set it in deploy/.env or Cloud Run configuration."
    )

# Add paths
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# =============================================================================
# IMPORTS
# =============================================================================

import json

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from google.adk.runners import InMemoryRunner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

# Developer's agent and schema
from agent import agent, AgentInputSchema

# TAP platform integration (handles mesh tools, validation, agent card)
from tap_wrapper import (
    build_tap_agent,
    setup_tool_context,
    generate_agent_card,
    get_agent_card_dict,
    get_config,
    MissingCredentialsError,
    load_system_manifest,
)

# SMA streaming handler for structured SSE events
from streaming import SMAStreamingHandler, SMAErrorCode

# =============================================================================
# TAP PLATFORM INTEGRATION
# =============================================================================
# This section runs ONCE at server startup to set up the TAP agent.
# The wrapped_agent is reused for all incoming requests (stateless design).

# Get config from tap-agent.yaml (agent metadata, model, version, etc.)
config = get_config()

# =============================================================================
# BUILD WRAPPED AGENT
# =============================================================================
# build_tap_agent() creates a SequentialAgent pipeline:
#
#   1. Injects mesh tools (transfer_to_agent, ask_clarifying_questions, etc.)
#   2. Checks should_use_initialiser() to determine pipeline type:
#      - If system-manifest.yaml exists with personalization enabled:
#        → wrap_with_full_pipeline() creates:
#          SequentialAgent[TapInitialiserAgent, InputValidator, YourAgent]
#      - Otherwise:
#        → wrap_with_validation() creates:
#          SequentialAgent[InputValidator, YourAgent]
#
# The pipeline runs in order for EACH request:
#   TapInitialiserAgent (if enabled) → Sets user preference state variables
#   InputValidator (if schema has required fields) → Validates/collects inputs
#   DeveloperAgent → Your business logic
#
# See tap_wrapper/__init__.py:build_tap_agent() for implementation details.
# See tap_wrapper/initialiser.py for TapInitialiserAgent details.
# See tap_wrapper/validation.py for InputValidator and wrap_with_full_pipeline().
wrapped_agent = build_tap_agent(agent, AgentInputSchema)

# Generate A2A Agent Card from config (includes systemManifest from system-manifest.yaml)
# This is served at /.well-known/agent.json for agent discovery
agent_card = generate_agent_card(AgentInputSchema)

# Configure logging
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# =============================================================================
# GRACEFUL SHUTDOWN SUPPORT
# =============================================================================

from contextlib import asynccontextmanager

# Track in-flight requests for graceful shutdown
_in_flight_requests = 0
_shutting_down = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle with graceful shutdown."""
    global _shutting_down

    # Startup
    logger.info(f"Starting TAP Agent: {config.slug} v{config.version}")

    yield

    # Shutdown
    _shutting_down = True
    logger.info("Shutting down gracefully...")

    # Wait for in-flight requests (max 10 seconds)
    for _ in range(100):
        if _in_flight_requests == 0:
            break
        await asyncio.sleep(0.1)

    logger.info(f"Shutdown complete ({_in_flight_requests} requests remaining)")


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title=f"TAP Agent - {config.slug}",
    description="A2A Protocol Server",
    version=config.version,
    lifespan=lifespan,
)


# =============================================================================
# REQUEST TRACKING MIDDLEWARE
# =============================================================================

@app.middleware("http")
async def track_in_flight_requests(request: Request, call_next):
    """Track in-flight requests for graceful shutdown."""
    global _in_flight_requests

    # Reject new requests during shutdown (except health checks)
    if _shutting_down and request.url.path not in ["/health", "/health/ready"]:
        return JSONResponse(
            status_code=503,
            content={"error": "Server is shutting down", "retry_after": 5}
        )

    _in_flight_requests += 1
    try:
        response = await call_next(request)
        return response
    finally:
        _in_flight_requests -= 1


# =============================================================================
# SSE HEARTBEAT HELPER
# =============================================================================

# Heartbeat interval (seconds) - emit heartbeat if no event received within this time
SMA_HEARTBEAT_INTERVAL = float(os.environ.get("SMA_HEARTBEAT_INTERVAL", "15.0"))


def emit_heartbeat() -> str:
    """
    Emit SSE heartbeat comment to keep connection alive.

    SSE comments (lines starting with ':') are ignored by EventSource parsers
    but keep the TCP connection alive and prevent proxy timeouts.
    """
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    return f": heartbeat {timestamp}\n\n"


async def iter_with_heartbeats_and_recovery(
    async_iter,
    heartbeat_interval: float = SMA_HEARTBEAT_INTERVAL,
    max_retries: int = 0,
):
    """
    Wrap an async iterator with heartbeats and optional error recovery.

    During ADK agent processing (e.g., tool execution, LLM thinking), events may not
    arrive for extended periods. This helper injects SSE heartbeat comments to keep
    the TCP connection alive and prevent proxy/load-balancer timeouts.

    Args:
        async_iter: The async iterator to wrap (e.g., runner.run_async())
        heartbeat_interval: Seconds between heartbeats (default: 15s)
        max_retries: Number of retries on transient errors (0 = no retry)

    Yields:
        Tuples of ("event", event), ("heartbeat", str), or ("error", Exception)
    """
    async_it = aiter(async_iter)
    consecutive_errors = 0

    while True:
        try:
            async with asyncio.timeout(heartbeat_interval):
                event = await anext(async_it)
                consecutive_errors = 0  # Reset on success
                yield ("event", event)
        except TimeoutError:
            # No event received within timeout - emit heartbeat
            yield ("heartbeat", emit_heartbeat())
        except StopAsyncIteration:
            break
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors > max_retries:
                yield ("error", e)
                break
            logger.warning(f"Transient error in stream (attempt {consecutive_errors}): {e}")
            yield ("heartbeat", emit_heartbeat())  # Keep connection alive during recovery


# Alias for backwards compatibility
async def iter_with_heartbeats(async_iter, heartbeat_interval: float = SMA_HEARTBEAT_INTERVAL):
    """Backwards-compatible wrapper for iter_with_heartbeats_and_recovery."""
    async for item in iter_with_heartbeats_and_recovery(async_iter, heartbeat_interval, max_retries=0):
        # Filter out error tuples for backwards compat - re-raise instead
        if item[0] == "error":
            raise item[1]
        yield item


# =============================================================================
# TOKEN EXTRACTION
# =============================================================================

def extract_token_counts(events: list) -> tuple[int, int]:
    """
    Extract token counts from ADK events for billing.

    Uses defensive coding to handle various ADK event formats and prevent
    billing failures if token metadata is unavailable.

    BUG FIX: ADK exposes usage_metadata directly on event, not event.content.
    Check both locations for compatibility (MA uses event.usage_metadata).

    Returns:
        tuple[int, int]: (input_tokens, output_tokens)
    """
    input_tokens = 0
    output_tokens = 0

    for event in events:
        try:
            # BUG FIX: Check event.usage_metadata first (what ADK actually uses),
            # then fall back to event.content.usage_metadata for compatibility
            metadata = None
            if hasattr(event, 'usage_metadata') and event.usage_metadata:
                metadata = event.usage_metadata
            elif hasattr(event, 'content') and hasattr(event.content, 'usage_metadata'):
                metadata = event.content.usage_metadata

            if metadata is not None:
                # Safe extraction with multiple fallback attribute names
                # BUG FIX: Use explicit None checks instead of `or` to handle 0 correctly
                # (0 is falsy, so `0 or default` would use default instead of 0)
                prompt_count = getattr(metadata, 'prompt_token_count', None)
                if prompt_count is None:
                    prompt_count = getattr(metadata, 'input_tokens', None)
                if prompt_count is None:
                    prompt_count = 0

                output_count = getattr(metadata, 'candidates_token_count', None)
                if output_count is None:
                    output_count = getattr(metadata, 'output_tokens', None)
                if output_count is None:
                    output_count = 0

                input_tokens += prompt_count
                output_tokens += output_count
        except Exception as e:
            # Log but don't fail - billing should not crash the agent
            logger.warning(f"Token extraction error (continuing): {e}")
            continue

    return input_tokens, output_tokens


# =============================================================================
# AGENT CARD ENDPOINT
# =============================================================================

@app.get("/.well-known/agent.json")
async def agent_card_endpoint():
    """
    A2A Agent Card discovery endpoint.

    Returns the agent's metadata for discovery and routing.
    """
    return JSONResponse(
        content=get_agent_card_dict(AgentInputSchema),
        headers={"Cache-Control": "public, max-age=300"},
    )


# =============================================================================
# A2A JSON-RPC ENDPOINT
# =============================================================================

@app.post("/")
async def jsonrpc_handler(request: Request):
    """
    A2A JSON-RPC 2.0 endpoint (POST to root).

    Gateway sends POST to cloud_run_url (root) for sync invocation.

    Handles:
    - message/send: Process a message

    Returns JSON-RPC response with agent output and token counts.
    """
    start_time = time.time()

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": f"Parse error: {e}"},
            "id": None,
        })

    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")

    # Extract context from params or headers
    org_id = params.get("org_id") or request.headers.get("X-Org-ID", "")
    user_id = params.get("user_id") or request.headers.get("X-User-ID", "")
    session_id = params.get("session_id") or f"sess-{uuid4().hex[:16]}"
    trace_id = params.get("trace_id") or request.headers.get("X-Trace-ID", f"trace-{uuid4().hex[:16]}")

    # Extract OAuth credentials if provided by Gateway
    oauth_credentials = params.get("oauth_credentials", {})

    # Set tool context for mesh tools (including OAuth credentials)
    setup_tool_context({
        "org_id": org_id,
        "user_id": user_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "equipped_abilities": params.get("equipped_abilities", []),
        "oauth_credentials": oauth_credentials,
    })

    logger.info(f"A2A request: method={method}, trace_id={trace_id}")

    if method == "message/send":
        # Extract message
        message_data = params.get("message", {})

        # Support both text and parts format
        # Also extract structured_input from DataPart if present
        structured_input = None

        if isinstance(message_data, str):
            text = message_data
        elif "text" in message_data:
            text = message_data["text"]
        elif "parts" in message_data:
            # Extract text from TextParts and data from DataParts
            text = ""
            for part in message_data.get("parts", []):
                if part.get("type") == "text":
                    text += part.get("text", "")
                elif part.get("type") == "data":
                    # DataPart contains structured_input from Master Agent
                    # This is pre-extracted data matching our input_schema
                    structured_input = part.get("data", {})
        else:
            text = str(message_data)

        # Update tool context with structured_input if received
        if structured_input:
            logger.info(f"Received structured_input with {len(structured_input)} fields")
            setup_tool_context({
                "org_id": org_id,
                "user_id": user_id,
                "session_id": session_id,
                "trace_id": trace_id,
                "equipped_abilities": params.get("equipped_abilities", []),
                "oauth_credentials": oauth_credentials,
                "structured_input": structured_input,  # Make available to agent
            })

            # Validate structured_input against AgentInputSchema
            # If valid, use it directly; if invalid, return INPUT_REQUIRED with prefilled_values
            try:
                validated = AgentInputSchema(**structured_input)
                # Convert validated input to prompt text
                text = validated.to_prompt()
                logger.info(f"Validated structured_input, converted to prompt: {text[:100]}...")
            except Exception as e:
                # Validation failed - return INPUT_REQUIRED with prefilled_values
                logger.warning(f"Structured input validation failed: {e}")
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "result": {
                        "id": f"task-{uuid4().hex[:16]}",
                        "status": "input_required",
                        "input_schema": AgentInputSchema.model_json_schema(),
                        "prefilled_values": structured_input,  # Return partial data for form pre-fill
                        "validation_error": str(e),
                        "metadata": {
                            "agent_slug": config.slug,
                            "trace_id": trace_id,
                        },
                    },
                    "id": request_id,
                })

        if not text:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": "Invalid params: no message text"},
                "id": request_id,
            })

        # Create runner and execute with validation-wrapped agent
        runner = InMemoryRunner(agent=wrapped_agent, app_name=config.slug)

        # Create session if it doesn't exist (InMemoryRunner starts with empty session service)
        # NOTE: Sync endpoint is for local CLI testing only - Gateway uses /stream
        # User preferences are not passed here since CLI testing doesn't have Cognee context
        effective_user_id = user_id or "anonymous"
        session = await runner.session_service.get_session(
            app_name=config.slug,
            user_id=effective_user_id,
            session_id=session_id
        )
        if session is None:
            # Initialize state with preference key defaults (prevents ADK errors from {key} placeholders)
            initial_state = {"sma_interaction_preferences": ""}
            try:
                manifest = load_system_manifest()
                # Use get_preference_keys() to cover all sources (state_schema, personalization, legacy)
                for pref_key in manifest.get_preference_keys():
                    initial_state[pref_key] = ""
            except Exception:
                pass  # Manifest not found, use minimal defaults
            logger.info(f"Creating new session: session_id={session_id}, user_id={effective_user_id}")
            await runner.session_service.create_session(
                app_name=config.slug,
                user_id=effective_user_id,
                state=initial_state,
                session_id=session_id,
            )

        # Create proper Content object for ADK (per ADK docs)
        user_content = types.Content(
            role="user",
            parts=[types.Part(text=text)]
        )

        events = []
        try:
            async for event in runner.run_async(
                user_id=effective_user_id,
                session_id=session_id,
                new_message=user_content,
            ):
                events.append(event)
        except MissingCredentialsError as e:
            # Return structured error for platform to handle OAuth flow
            logger.warning(f"Missing credentials: {e.service}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": str(e),
                    "data": e.to_platform_response()
                },
                "id": request_id,
            })
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": f"Agent error: {e}"},
                "id": request_id,
            })

        # Extract token counts for billing
        input_tokens, output_tokens = extract_token_counts(events)

        # Get final response
        output = ""
        for event in events:
            if event.is_final_response():
                if hasattr(event.content, 'parts'):
                    for part in event.content.parts:
                        if hasattr(part, 'text'):
                            output = part.text
                            break

        duration_ms = (time.time() - start_time) * 1000

        logger.info(f"A2A completed: tokens={input_tokens}/{output_tokens}, duration={duration_ms:.0f}ms")

        return JSONResponse({
            "jsonrpc": "2.0",
            "result": {
                "id": f"task-{uuid4().hex[:16]}",
                "status": "completed",
                "message": output,
                "metadata": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "duration_ms": duration_ms,
                    "agent_slug": config.slug,
                    "trace_id": trace_id,
                },
            },
            "id": request_id,
        })

    # Unknown method
    return JSONResponse({
        "jsonrpc": "2.0",
        "error": {"code": -32601, "message": f"Method not found: {method}"},
        "id": request_id,
    })


# =============================================================================
# A2A STREAMING ENDPOINT (SSE)
# =============================================================================

@app.post("/stream")
async def stream_handler(request: Request):
    """
    A2A Streaming endpoint for SSE responses.

    Receives full context from Gateway including:
    - Full conversation history (shared session)
    - SMA-specific system prompt
    - Delegation context indicating this is a specialist task

    This endpoint streams responses via Server-Sent Events (SSE) for
    real-time user feedback during SMA execution.

    Returns:
        StreamingResponse with SSE events:
        - connected: Initial connection established
        - working: Processing started
        - content: Text chunks (partial responses)
        - agent_step: Sub-agent transitions (for SequentialAgent)
        - tool_call: Tool invocation
        - tool_result: Tool completion
        - thinking: Model reasoning (if supported)
        - token_update: Real-time token counts
        - synthesizing: Creating final response
        - done: Completion with token counts
        - error: Error occurred
    """
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": f"Parse error: {e}"},
            "id": None,
        })

    params = body.get("params", {})
    context = params.get("context", {})
    request_id = body.get("id")

    # Extract context from Gateway-assembled payload
    org_id = context.get("org_id") or request.headers.get("X-Org-ID", "")
    user_id = context.get("user_id") or request.headers.get("X-User-ID", "")
    session_id = context.get("session_id") or f"sess-{uuid4().hex[:16]}"
    trace_id = context.get("trace_id") or request.headers.get("X-Trace-ID", f"trace-{uuid4().hex[:16]}")

    # OAuth credentials from Gateway
    oauth_credentials = context.get("oauth_credentials", {})

    # Shared session data - SMA sees full MA conversation
    history = context.get("history", [])  # Full conversation history
    system_prompt = context.get("system_prompt")  # SMA-specific prompt
    delegation_context = context.get("delegation_context", {})  # Why we're delegating
    is_specialist_delegate = context.get("is_specialist_delegate", False)

    # Log delegation context for debugging (important for SMA development)
    if delegation_context:
        delegated_by = delegation_context.get("delegated_by", "unknown")
        delegation_reason = delegation_context.get("delegation_reason", "not provided")
        delegation_depth = delegation_context.get("delegation_depth", 0)
        # Safely truncate delegation_reason (might not be a string)
        reason_preview = str(delegation_reason)[:100] if delegation_reason else "not provided"
        logger.info(
            f"SMA delegated from {delegated_by}: reason='{reason_preview}', "
            f"depth={delegation_depth}, is_specialist={is_specialist_delegate}"
        )

    # Extract message (the task from Master Agent)
    message_data = params.get("message", {})
    if isinstance(message_data, str):
        text = message_data
    elif "text" in message_data:
        text = message_data["text"]
    elif "parts" in message_data:
        text = "".join(
            p.get("text", "") for p in message_data.get("parts", [])
            if p.get("type") == "text"
        )
    else:
        text = str(message_data)

    # SMA interaction preferences from Cognee knowledge graph
    # Gateway retrieves these from Cognee and passes them as List[Dict] in context
    # Each dict has "content" (the preference text) and "source" (feedback/implicit)
    # We convert to natural language text for TapInitialiserAgent to process
    raw_preferences = context.get("sma_interaction_preferences", [])
    if raw_preferences and isinstance(raw_preferences, list):
        # Convert list of dicts to natural language text
        preference_lines = []
        for pref in raw_preferences:
            if isinstance(pref, dict) and "content" in pref:
                preference_lines.append(f"- {pref['content']}")
            elif isinstance(pref, str):
                preference_lines.append(f"- {pref}")
        sma_interaction_preferences = "\n".join(preference_lines) if preference_lines else ""
        logger.info(f"Received {len(raw_preferences)} SMA interaction preferences")

        # [TRACE: SMA FEEDBACK] Log preferences received by Template Agent
        logger.info(
            f"[TRACE: SMA FEEDBACK] TemplateAgent | PREFERENCES_RECEIVED | "
            f"count={len(raw_preferences)}, agent_slug={config.slug}, trace_id={trace_id}"
        )
    elif isinstance(raw_preferences, str):
        # Already a string (for backwards compatibility or testing)
        sma_interaction_preferences = raw_preferences
        logger.info(f"Received SMA interaction preferences (string format)")

        # [TRACE: SMA FEEDBACK] Log string-format preferences
        logger.info(
            f"[TRACE: SMA FEEDBACK] TemplateAgent | PREFERENCES_RECEIVED | "
            f"count=1, agent_slug={config.slug}, trace_id={trace_id}, format=string"
        )
    else:
        sma_interaction_preferences = ""
        # [TRACE: SMA FEEDBACK] Log no preferences received (empty or None)
        logger.info(
            f"[TRACE: SMA FEEDBACK] TemplateAgent | PREFERENCES_RECEIVED | "
            f"count=0, agent_slug={config.slug}, trace_id={trace_id}, format=none"
        )

    # Long-term memory context from Cognee
    # Convert List[Dict] to bullet-point text for LLM readability
    raw_ltm = context.get("ltm", [])
    if raw_ltm and isinstance(raw_ltm, list):
        ltm_lines = []
        for item in raw_ltm:
            if isinstance(item, dict) and "content" in item:
                ltm_lines.append(f"- {item['content']}")
            elif isinstance(item, str):
                ltm_lines.append(f"- {item}")
        ltm_context = "\n".join(ltm_lines) if ltm_lines else ""
        logger.info(f"Received {len(raw_ltm)} LTM entries from Cognee")
    elif isinstance(raw_ltm, str):
        ltm_context = raw_ltm  # Already a string
    else:
        ltm_context = ""

    # Convert delegation context to readable text
    delegation_text = ""
    if delegation_context and isinstance(delegation_context, dict):
        delegation_parts = []
        if delegation_context.get("delegated_by"):
            delegation_parts.append(f"Delegated by: {delegation_context['delegated_by']}")
        if delegation_context.get("delegation_reason"):
            delegation_parts.append(f"Reason: {delegation_context['delegation_reason']}")
        if delegation_context.get("original_prompt"):
            delegation_parts.append(f"Original request: {delegation_context['original_prompt']}")
        delegation_text = "\n".join(delegation_parts)

    # NOTE: Tool context is now set INSIDE generate() to ensure contextvars
    # propagate correctly to ADK's async execution context. See generate() below.
    # Capture the values needed for setup_tool_context here.
    tool_context_config = {
        "org_id": org_id,
        "user_id": user_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "equipped_abilities": context.get("equipped_abilities", []),
        "oauth_credentials": oauth_credentials,
        # Delegation-specific context
        "is_specialist_delegate": is_specialist_delegate,
        "delegation_context": delegation_text,  # Converted to readable text
        "delegated_by": delegation_context.get("delegated_by") if delegation_context else None,
        "delegation_depth": delegation_context.get("delegation_depth", 0) if delegation_context else 0,
        # Personalization context (from Cognee knowledge graph)
        "sma_interaction_preferences": sma_interaction_preferences,  # For TapInitialiserAgent
        "ltm": ltm_context,  # Long-term memory (converted to readable text)
    }

    logger.info(f"Stream request: trace_id={trace_id}, has_history={len(history) > 0}, is_delegate={is_specialist_delegate}")

    async def generate():
        """SSE event generator with structured events and proper partial flag handling.

        Uses SMAStreamingHandler for:
        - Sequence numbering (dropped event detection)
        - Task ID correlation
        - Elapsed time tracking
        - Structured error codes
        - SSE event IDs for reconnection
        """
        # BUG FIX: Set tool context INSIDE the async generator to ensure contextvars
        # propagate correctly to ADK's async execution context. Previously this was
        # set outside generate(), which caused "Tool context not initialized" errors
        # because ADK's internal task execution didn't inherit the contextvars.
        setup_tool_context(tool_context_config)
        logger.debug(f"Tool context set inside generator: org_id={tool_context_config.get('org_id')}, trace_id={trace_id}")

        # Generate unique task_id for this streaming session
        task_id = f"task-{uuid4().hex[:16]}"

        # Create streaming handler for structured event emission
        handler = SMAStreamingHandler(
            task_id=task_id,
            trace_id=trace_id,
            agent_slug=config.slug,
            org_id=org_id,
            user_id=user_id,
        )

        # Emit connection established (with task_id, sequence, elapsed_ms)
        yield handler.emit_connected()

        # Emit processing started (immediate feedback before ADK init)
        yield handler.emit_working("Processing request")

        # Create runner with validation-wrapped agent
        runner = InMemoryRunner(agent=wrapped_agent, app_name=config.slug)
        accumulated_text = ""
        chunk_index = 0

        # Token accumulators (use += to accumulate, not overwrite)
        total_input_tokens = 0
        total_output_tokens = 0

        # Track sub-agent steps for SequentialAgent patterns
        current_agent = None
        step_number = 0

        # Create session if it doesn't exist (InMemoryRunner starts with empty session service)
        effective_user_id = user_id or "anonymous"
        session = await runner.session_service.get_session(
            app_name=config.slug,
            user_id=effective_user_id,
            session_id=session_id
        )
        if session is None:
            # Initialize session state with context from Gateway
            # TapInitialiserAgent uses these to set up personalization and LTM context
            # This runs BEFORE InputValidator, giving it access to persona snippets
            initial_state = {
                # SMA interaction preferences (from Cognee sma-interaction-preferences endpoint)
                "sma_interaction_preferences": tool_context_config.get("sma_interaction_preferences", ""),
                # Long-term memory entries from Cognee (converted to readable text)
                "ltm": tool_context_config.get("ltm", ""),
                # Delegation context for awareness (converted to readable text)
                "delegation_context": tool_context_config.get("delegation_context", ""),
                "is_specialist_delegate": tool_context_config.get("is_specialist_delegate", False),
            }

            # Initialize preference state keys with empty defaults
            # This prevents ADK from throwing errors if TapInitialiserAgent doesn't run
            # (e.g., when personalization is disabled but prompts have {key} placeholders)
            try:
                manifest = load_system_manifest()
                # Use get_preference_keys() to cover all sources (state_schema, personalization, legacy)
                pref_keys = manifest.get_preference_keys()
                for pref_key in pref_keys:
                    initial_state[pref_key] = ""
                logger.debug(f"Initialized {len(pref_keys)} preference keys with empty defaults")
            except Exception as e:
                logger.debug(f"Could not load manifest for preference key initialization: {e}")
            has_prefs = bool(initial_state.get("sma_interaction_preferences"))
            ltm_count = len(initial_state.get("ltm", []))
            logger.info(f"Creating new session (stream): session_id={session_id}, user_id={effective_user_id}, has_preferences={has_prefs}, ltm_entries={ltm_count}")
            await runner.session_service.create_session(
                app_name=config.slug,
                user_id=effective_user_id,
                state=initial_state,
                session_id=session_id,
            )

        try:
            # Build message with history context for model understanding
            context_message = text
            if history and len(history) > 0:
                # Truncate to last 5 messages with explicit logging
                history_count = min(5, len(history))
                if len(history) > 5:
                    logger.info(f"Truncating history from {len(history)} to {history_count} messages")

                history_summary = "\n".join([
                    f"{m.get('role', 'unknown')} ({m.get('agent_slug', 'user')}): {m.get('content', '')[:500]}"
                    for m in history[-history_count:]
                ])
                context_message = f"Conversation context:\n{history_summary}\n\nCurrent task: {text}"

            # Add delegation awareness if this is a delegated task
            if delegation_context:
                original_prompt = delegation_context.get("original_prompt", "")
                if original_prompt:
                    context_message = f"Original user request: {original_prompt}\n\n{context_message}"

            # Create proper Content object for ADK (per ADK docs)
            user_content = types.Content(
                role="user",
                parts=[types.Part(text=context_message)]
            )

            # Wrap ADK runner with heartbeat injection to keep connections alive
            # during long-running operations (tool calls, LLM thinking, etc.)
            # CRITICAL: Pass run_config with StreamingMode.SSE to enable LLM streaming
            # Without this, ADK uses stream=False (blocking) which causes idle timeouts
            adk_stream = runner.run_async(
                user_id=effective_user_id,
                session_id=session_id,
                new_message=user_content,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            )
            async for event_type, event_or_hb in iter_with_heartbeats(adk_stream):
                # Handle heartbeat events (keep-alive during long processing)
                if event_type == "heartbeat":
                    yield handler.emit_heartbeat()
                    continue

                event = event_or_hb

                # =============================================================
                # TRACK SUB-AGENT STEPS (for SequentialAgent patterns)
                # =============================================================
                if hasattr(event, 'author') and event.author != current_agent:
                    # Mark previous agent as completed (if any)
                    if current_agent is not None:
                        yield handler.emit_agent_step(step_number, current_agent, "completed")

                    step_number += 1
                    current_agent = event.author
                    yield handler.emit_agent_step(step_number, event.author, "started")

                # =============================================================
                # ACCUMULATE TOKEN COUNTS
                # =============================================================
                # BUG FIX: ADK exposes usage_metadata directly on event, not event.content
                # Check both locations for compatibility (MA uses event.usage_metadata)
                metadata = None
                if hasattr(event, 'usage_metadata') and event.usage_metadata:
                    metadata = event.usage_metadata
                elif hasattr(event, 'content') and hasattr(event.content, 'usage_metadata'):
                    metadata = event.content.usage_metadata

                if metadata:
                    new_input = getattr(metadata, 'prompt_token_count', 0) or 0
                    new_output = getattr(metadata, 'candidates_token_count', 0) or 0

                    if new_input > 0 or new_output > 0:
                        total_input_tokens += new_input
                        total_output_tokens += new_output
                        yield handler.emit_token_update(total_input_tokens, total_output_tokens)

                # =============================================================
                # PARSE ADK EVENT PARTS FOR RICH CONTENT
                # =============================================================
                if hasattr(event, 'content') and hasattr(event.content, 'parts'):
                    for part in event.content.parts:
                        # ---------------------------------------------------------
                        # FUNCTION CALL (tool invocation)
                        # ---------------------------------------------------------
                        if hasattr(part, 'function_call') and part.function_call:
                            fc = part.function_call
                            tool_name = getattr(fc, 'name', 'unknown')
                            try:
                                args = dict(fc.args) if hasattr(fc, 'args') and fc.args else {}
                            except Exception:
                                args = {}
                            yield handler.emit_tool_call(tool_name, args)

                        # ---------------------------------------------------------
                        # FUNCTION RESPONSE (tool result)
                        # ---------------------------------------------------------
                        if hasattr(part, 'function_response') and part.function_response:
                            fr = part.function_response
                            tool_name = getattr(fr, 'name', 'unknown')
                            try:
                                result = fr.response if hasattr(fr, 'response') else str(fr)
                                # Truncate large results for preview
                                if isinstance(result, str) and len(result) > 500:
                                    result = result[:500] + "..."
                                elif isinstance(result, dict):
                                    result = str(result)[:200] + "..."
                            except Exception:
                                result = "[result too large]"
                            yield handler.emit_tool_result(tool_name, True, result)

                        # ---------------------------------------------------------
                        # THOUGHT (model reasoning - if model supports it)
                        # ---------------------------------------------------------
                        if hasattr(part, 'thought') and part.thought:
                            thought_text = part.thought
                            if isinstance(thought_text, str) and thought_text.strip():
                                yield handler.emit_thinking(thought_text)

                        # ---------------------------------------------------------
                        # TEXT (streaming content) - CRITICAL: CHECK PARTIAL FLAG
                        # ---------------------------------------------------------
                        # ADK sends two types of text events:
                        #   - partial=True: NEW text chunks (emit these)
                        #   - partial=False: COMPLETE accumulated text (skip these)
                        # Without this check, text gets duplicated!
                        is_partial = getattr(event, 'partial', None)
                        if is_partial and hasattr(part, 'text') and part.text:
                            accumulated_text += part.text
                            yield handler.emit_content(part.text, chunk_index)
                            chunk_index += 1

            # Mark final agent step as completed (if any)
            if current_agent is not None:
                yield handler.emit_agent_step(step_number, current_agent, "completed")

            # Emit synthesizing before done (Gateway expects this)
            yield handler.emit_synthesizing()

            # Emit completion with final token counts for billing reconciliation
            yield handler.emit_done(
                accumulated_text=accumulated_text,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

            logger.info(f"Stream completed: trace_id={trace_id}, task_id={task_id}, tokens={total_input_tokens}/{total_output_tokens}, events={handler.get_event_count()}")

        except MissingCredentialsError as e:
            logger.warning(f"Stream missing credentials: {e.service}")
            yield handler.emit_error(
                str(e),
                SMAErrorCode.MISSING_CREDENTIALS,
                {"service": e.service}
            )

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield handler.emit_error(str(e), SMAErrorCode.EXECUTION_ERROR)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
            "X-Request-ID": trace_id,   # Add request ID for tracing
        },
    )


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health")
async def health():
    """Basic liveness check for Cloud Run."""
    return {
        "status": "healthy",
        "agent": config.slug,
        "version": config.version,
    }


@app.get("/health/ready")
async def readiness_check():
    """
    Deep readiness check for Cloud Run.

    Verifies:
    - Configuration is valid
    - tap_core is importable
    - Agent is properly wrapped
    """
    issues = []

    # Check GCP project
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        issues.append("GOOGLE_CLOUD_PROJECT not set")

    # Check tap_core
    try:
        from tap_core.tools import get_all_tools
    except ImportError as e:
        issues.append(f"tap_core import failed: {e}")

    # Check agent is wrapped
    if wrapped_agent is None:
        issues.append("Agent not initialized")

    if issues:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "issues": issues}
        )

    return {"status": "ready", "agent": config.slug, "version": config.version}


@app.get("/")
async def root():
    """Root endpoint with basic info (GET only - POST goes to jsonrpc_handler)."""
    return {
        "agent": config.slug,
        "version": config.version,
        "endpoints": {
            "agent_card": "/.well-known/agent.json",
            "a2a": "/",  # POST to root for A2A JSON-RPC
            "stream": "/stream",  # SSE streaming endpoint
            "health": "/health",
        },
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting A2A server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
