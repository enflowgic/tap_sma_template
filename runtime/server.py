"""
TAP Template Agent - A2A Protocol Server

FastAPI server implementing the A2A protocol for Cloud Run deployment.

Endpoints:
- GET  /.well-known/agent.json  - Agent card discovery
- POST /a2a                      - JSON-RPC 2.0 endpoint
- GET  /health                   - Health check

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
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "your-project-id")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# Load .env file
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# Add paths
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# =============================================================================
# IMPORTS
# =============================================================================

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from google.adk.runners import InMemoryRunner

from agent import root_agent, AGENT_CARD, AGENT_NAME, AgentInputSchema
from agent.definition import setup_tool_context
from agent.exceptions import MissingCredentialsError

# Configure logging
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title=f"TAP Agent - {AGENT_NAME}",
    description="A2A Protocol Server",
    version="1.0.0",
)


# =============================================================================
# TOKEN EXTRACTION
# =============================================================================

def extract_token_counts(events: list) -> tuple[int, int]:
    """Extract token counts from ADK events for billing."""
    input_tokens = 0
    output_tokens = 0

    for event in events:
        if hasattr(event, 'content') and hasattr(event.content, 'usage_metadata'):
            metadata = event.content.usage_metadata
            if hasattr(metadata, 'prompt_token_count'):
                input_tokens += metadata.prompt_token_count or 0
            if hasattr(metadata, 'candidates_token_count'):
                output_tokens += metadata.candidates_token_count or 0

    return input_tokens, output_tokens


# =============================================================================
# AGENT CARD ENDPOINT
# =============================================================================

@app.get("/.well-known/agent.json")
async def agent_card():
    """
    A2A Agent Card discovery endpoint.

    Returns the agent's metadata for discovery and routing.
    """
    # Convert AgentCard to dict
    card_dict = {
        "name": AGENT_CARD.name,
        "displayName": AGENT_CARD.displayName,
        "description": AGENT_CARD.description,
        "version": AGENT_CARD.version,
        "protocolVersion": AGENT_CARD.protocolVersion,
        "capabilities": {
            "streaming": AGENT_CARD.capabilities.streaming,
            "pushNotifications": AGENT_CARD.capabilities.pushNotifications,
            "stateTransitionHistory": AGENT_CARD.capabilities.stateTransitionHistory,
        },
        "skills": [
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "tags": skill.tags,
                "examples": skill.examples,
            }
            for skill in AGENT_CARD.skills
        ],
        "inputSchema": AGENT_CARD.inputSchema,
        "outputSchema": AGENT_CARD.outputSchema,
    }

    if AGENT_CARD.provider:
        card_dict["provider"] = {
            "organization": AGENT_CARD.provider.organization,
            "url": AGENT_CARD.provider.url,
            "email": AGENT_CARD.provider.email,
        }

    if AGENT_CARD.pricing:
        card_dict["pricing"] = {
            "salesPricePer1kTokens": AGENT_CARD.pricing.sales_price_per_1k_tokens,
            "estimatedTokensPerTask": AGENT_CARD.pricing.estimated_tokens_per_task,
            "currency": AGENT_CARD.pricing.currency,
        }

    return JSONResponse(
        content=card_dict,
        headers={"Cache-Control": "public, max-age=300"},
    )


# =============================================================================
# A2A JSON-RPC ENDPOINT
# =============================================================================

@app.post("/a2a")
async def jsonrpc_handler(request: Request):
    """
    A2A JSON-RPC 2.0 endpoint.

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
        if isinstance(message_data, str):
            text = message_data
        elif "text" in message_data:
            text = message_data["text"]
        elif "parts" in message_data:
            # Extract text from parts
            text = ""
            for part in message_data.get("parts", []):
                if part.get("type") == "text":
                    text += part.get("text", "")
        else:
            text = str(message_data)

        if not text:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": "Invalid params: no message text"},
                "id": request_id,
            })

        # Create runner and execute
        runner = InMemoryRunner(agent=root_agent, app_name=AGENT_NAME)

        events = []
        try:
            async for event in runner.run_async(
                user_id=user_id or "anonymous",
                session_id=session_id,
                new_message=text,
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
                    "agent_slug": AGENT_NAME,
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
# HEALTH CHECK
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint for Cloud Run."""
    return {
        "status": "healthy",
        "agent": AGENT_NAME,
        "version": AGENT_CARD.version,
    }


@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "agent": AGENT_NAME,
        "version": AGENT_CARD.version,
        "endpoints": {
            "agent_card": "/.well-known/agent.json",
            "a2a": "/a2a",
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
