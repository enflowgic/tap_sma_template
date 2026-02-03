---
name: template-agent
description: TAP Template Agent comprehensive guide. Use when building TAP-compatible Stateless Mesh Agents (SMAs), working with Google ADK, implementing mesh tools, or debugging agent deployment issues. Covers agent definition patterns, input schemas, A2A protocol, and deployment to Vertex AI or Cloud Run.
globs:
  - tap_template_agent/**
  - SMAs/**/agent/**
---

# TAP Template Agent

> **Version**: 1.2.0 | **Framework**: Google ADK + FastAPI | **Updated**: January 2026

---

## Quick Links

| Resource | Location |
|----------|----------|
| **Template Source** | `tap_template_agent/` |
| **ADK Python SDK** | `.claude/skills/template-agent/adk-python/` |
| **ADK Documentation** | `.claude/skills/template-agent/adk-docs/` |
| **ADK Samples** | `.claude/skills/template-agent/adk-samples/` |
| **GCP Starter Pack** | `.claude/skills/template-agent/agent-starter-pack/` |
| **Cognitive Patterns** | `.claude/skills/template-agent/AI_Cognitive_Design_Patterns.md` |

---

## Overview & Jurisdiction

The **TAP Template Agent** is the canonical template for building TAP-compatible Stateless Mesh Agents (SMAs). It wraps Google ADK agents with TAP platform integration via the `tap_core` library.

### What Template Agent DOES:

1. **Provides canonical SMA structure** - Standard directory layout for agent/, runtime/
2. **Demonstrates LlmAgent pattern** - Simple agent with mesh tools integration
3. **Shows A2A protocol implementation** - FastAPI server with JSON-RPC 2.0
4. **Includes local development tools** - Interactive CLI and mock transfers
5. **Demonstrates deployment options** - Local, Vertex AI, and Cloud Run
6. **Shows input/output schema patterns** - UI widgets, conditional fields, to_prompt()
7. **Demonstrates ADK callbacks** - Lifecycle hooks for logging and metrics
8. **Automatic input validation** - Wraps ALL agents with InputValidator that checks required fields

### What Template Agent DOES NOT Do:

1. **Does NOT implement business logic** - That's your job as the developer
2. **Does NOT connect to production backends** - Uses mocks for local testing
3. **Does NOT handle authentication** - Gateway handles auth before calling SMAs
4. **Does NOT implement billing directly** - tap_core intents + Gateway handle billing
5. **Does NOT persist state** - Stateless design; Session Service stores state
6. **Does NOT call LLMs directly in platform** - Gateway routes to SMAs that call LLMs

> **Key Principle:** The template provides structure and patterns. You add the domain-specific logic.

---

## ⚠️ STREAMING-ONLY ARCHITECTURE

> **PLATFORM DESIGN**: TAP Gateway is designed to use **only the streaming endpoint** (`POST /stream`) for SMA invocation.
>
> The sync endpoint (`POST /`) exists for local CLI testing, but **is not used by Gateway**.
>
> When developing your SMA:
> - Focus on the `/stream` endpoint implementation
> - Ensure SSE events are emitted correctly
> - Test streaming locally: `curl -X POST http://localhost:8080/stream ...`
> - The sync endpoint is optional for local CLI convenience

---

## SSE Streaming Architecture (4-Tier Bucket Brigade)

SMAs built from this template are **Tier 4** (origin) in the TAP SSE streaming chain:

```
Tier 1: React Frontend (EventSource consumer)
    ↑
Tier 2: Flask BFF (stream_with_context, Gunicorn)
    ↑
Tier 3: FastAPI Gateway (async httpx streaming)
    ↑
Tier 4: Your SMA (Template) ◄─── YOU ARE HERE (Origin)
```

### SSE Requirements for SMAs

| Requirement | Implementation | File |
|-------------|----------------|------|
| **Content-Type** | `text/event-stream; charset=utf-8` | `runtime/server.py` |
| **X-Accel-Buffering: no** | Response header (disables proxy buffering) | `runtime/server.py` |
| **Cache-Control: no-cache** | Response header (prevents caching) | `runtime/server.py` |
| **Heartbeat every 15s** | SSE comments (`: heartbeat <timestamp>`) | See implementation below |
| **No compression** | Gzip disabled for SSE (breaks real-time) | `cloudbuild.yaml` |

### Heartbeat Implementation for SMAs

SMAs should emit heartbeat comments during long operations to prevent connection drops:

```python
# Add to your SMA's streaming implementation
import asyncio
from datetime import datetime, timezone

HEARTBEAT_INTERVAL = 15.0

def emit_heartbeat() -> str:
    """Emit SSE heartbeat comment to keep connection alive."""
    timestamp = datetime.now(timezone.utc).isoformat()
    return f": heartbeat {timestamp}\n\n"

async def iter_with_heartbeats(async_iter, heartbeat_interval=HEARTBEAT_INTERVAL):
    """Wrap ADK event stream to inject heartbeats during long waits."""
    async_it = aiter(async_iter)
    while True:
        try:
            async with asyncio.timeout(heartbeat_interval):
                event = await anext(async_it)
                yield ("event", event)
        except TimeoutError:
            yield ("heartbeat", emit_heartbeat())
        except StopAsyncIteration:
            break

# In your streaming endpoint:
async def stream_response():
    adk_events = runner.run_async(...)
    async for event_type, event_or_hb in iter_with_heartbeats(adk_events):
        if event_type == "heartbeat":
            yield event_or_hb  # Raw SSE comment string
            continue
        # Process ADK event...
        yield format_sse_event(event)
```

**Why heartbeats matter:**
- Gateway uses idle-based timeout (300s default)
- No events for 300s = stream considered dead
- ADK tool execution can take 30+ seconds
- Heartbeats signal "still alive, processing"

### Cloud Run Configuration

```yaml
# cloudbuild.yaml
# Note: HTTP/2 NOT enabled - Uvicorn uses HTTP/1.1 by default
# SSE streaming works fine with HTTP/1.1
- '--cpu-boost'        # Faster cold starts
- '--timeout=300'      # 5-minute request timeout
- '--concurrency=80'   # Per-instance concurrency
```

> **Why no HTTP/2?** Cloud Run's `--use-http2` flag sends HTTP/2 requests to the container,
> but Uvicorn defaults to HTTP/1.1. This mismatch causes "protocol error" connection resets.
> SSE streaming works correctly with HTTP/1.1.

### SSE Response Headers (runtime/server.py)

```python
from fastapi.responses import StreamingResponse

return StreamingResponse(
    generate_events(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # CRITICAL: Disable proxy buffering
    }
)
```

### Testing SSE Locally

```bash
# Test streaming endpoint with curl
curl -N -X POST http://localhost:8080/stream \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"task/sendSubscribe","params":{...},"id":"1"}'

# Verify you see:
# - Events appearing in real-time (not batched)
# - Heartbeat comments (": heartbeat 2026-01-...") every 15s during waits
# - No long pauses between events
```

### Debugging SSE Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Events arrive in bursts | Buffering enabled | Check X-Accel-Buffering header |
| Gateway timeout after 300s | No heartbeats | Add `iter_with_heartbeats()` wrapper |
| Connection drops mid-stream | No activity signals | Emit heartbeats during tool calls |
| Gzip errors in browser | Compression enabled | Ensure gzip disabled for SSE |

---

## Architecture Diagram

### TAP Platform Integration

```
                     +------------------+
                     |  React Frontend  |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     |   Flask BFF      |
                     +--------+---------+
                              |
                              v
+------------------------------------------------------------------+
|                      TAP GATEWAY                                  |
|  +------------+  +-------------+  +------------+  +------------+  |
|  | Context    |  | Billing     |  | Model      |  | Tool       |  |
|  | Assembler  |  | Tracker     |  | Armor      |  | Executor   |  |
+------------------------------------------------------------------+
         |                |                |               |
         v                v                v               v
+---------------+  +---------------+  +-----------+  +-----------+
| Prompt        |  | Session       |  | Cognee    |  | Your SMA  |
| Library       |  | Service       |  | Registry  |  | (Template)|
+---------------+  +---------------+  +-----------+  +-----------+
                                                           |
                                                           v
                                                    +-----------+
                                                    | Gemini/   |
                                                    | LLM API   |
                                                    +-----------+
```

### Request Flow

```
1. User message → BFF → Gateway
2. Gateway assembles context:
   - System prompt (Prompt Library)
   - History (Session Service)
   - LTM (Cognee)
   - Equipped abilities
3. Gateway invokes SMA with context
4. SMA executes LlmAgent via ADK
5. SMA returns response + token counts
6. Gateway records billing, updates session
7. Response flows back to user
```

### Stateless Design

**Critical**: Your agent is stateless. Each request:
1. Creates a fresh `InMemoryRunner`
2. Receives context from Gateway (in params)
3. Processes and returns response with token counts
4. No state persists between requests

---

## Directory Structure Reference

```
tap_template_agent/
├── tap-agent.yaml              # Agent manifest (REQUIRED)
├── main.py                     # Server entry point (for Cloud Run)
├── README.md                   # Quick start guide
├── Dockerfile                  # Cloud Run container build
├── cloudbuild.yaml             # Cloud Build deployment config
├── requirements.txt            # Python dependencies
│
├── agent/                      # YOUR CODE - Developer customization
│   ├── __init__.py             # Package exports (agent, schemas, prompts)
│   ├── agent.py                # LlmAgent definition (CORE)
│   ├── schemas.py              # Input/output contracts (REQUIRED)
│   ├── prompts.py              # Developer prompts (description, capabilities)
│   ├── callbacks.py            # ADK lifecycle hooks (optional)
│   └── tools/                  # Custom tools directory
│       ├── __init__.py         # Exports custom_tools list
│       └── example.py          # Example tool (delete when ready)
│
├── tap_wrapper/                # PLATFORM CODE - Don't modify
│   ├── __init__.py             # build_tap_agent(), setup_tool_context()
│   ├── config.py               # Parses tap-agent.yaml
│   ├── prompts.py              # Platform prompt boilerplate + composition
│   ├── agent_card.py           # Auto-generates A2A agent card
│   ├── validation.py           # Input validation wrapper
│   ├── mesh_integration.py     # Mesh tools injection
│   ├── exceptions.py           # MissingCredentialsError, etc.
│   └── testing/                # Mock utilities
│       └── mock_transfer.py    # Mock transfer for local testing
│
├── runtime/                    # Runtime infrastructure
│   ├── cli.py                  # Local development CLI (interactive mode)
│   └── server.py               # FastAPI A2A server
│
├── scripts/                    # Utility scripts
│   └── register_agent.py       # TAP registry registration
│
├── deploy/                     # Deployment configuration
│   └── .env.example            # Environment template
│
└── tests/                      # Test suite
    ├── conftest.py             # Pytest fixtures
    ├── test_definition.py      # Agent definition tests
    └── test_tools.py           # Tool tests
```

**Key Insight:** You only work with `agent/` (4-5 files). The `tap_wrapper/` handles all TAP platform integration automatically.

---

## Agent Definition Patterns

### Core Pattern: LlmAgent with Mesh Tools

```python
# agent/agent.py
from google.adk.agents import LlmAgent
from google.genai import types

from tap_wrapper.mesh_integration import get_mesh_tools
from tap_wrapper.prompts import compose_system_prompt
from .callbacks import on_agent_start, on_agent_end
from .tools import custom_tools

MODEL_NAME = os.environ.get("TAP_MODEL_NAME", "gemini-3-flash-preview")

# Agent definition - tap_wrapper handles mesh tools and prompt composition
agent = LlmAgent(
    name="MyAgent",
    model=MODEL_NAME,
    instruction=compose_system_prompt(),  # Combines platform + developer prompts
    tools=[*get_mesh_tools(), *custom_tools],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=4096,
    ),
    before_agent_callback=on_agent_start,
    after_agent_callback=on_agent_end,
)
```

### Critical: Tool Context Setup

**MUST call before every agent execution:**

```python
from tap_wrapper import setup_tool_context

# In cli.py or server.py, before running agent:
setup_tool_context({
    "org_id": gateway_context.get("org_id"),
    "user_id": gateway_context.get("user_id"),
    "session_id": gateway_context.get("session_id"),
    "trace_id": gateway_context.get("trace_id"),
    "equipped_abilities": gateway_context.get("equipped_abilities", []),
    "oauth_credentials": gateway_context.get("oauth_credentials", {}),  # For BYO Auth
})
```

### ADK Agent Types Reference

| Type | Use Case | Example |
|------|----------|---------|
| `LlmAgent` | Single agent with tools | **Default for SMAs** |
| `SequentialAgent` | Multi-step pipeline | Document processing |
| `ParallelAgent` | Concurrent sub-agents | Multi-perspective analysis |
| `LoopAgent` | Iterative processing | Reflection and refinement |

See `.claude/skills/template-agent/AI_Cognitive_Design_Patterns.md` for cognitive patterns.

---

## Input/Output Schema Patterns

### BaseInputSchema Inheritance

**Always inherit from BaseInputSchema** to get platform fields:

```python
# agent/schemas.py
from tap_core.schemas.base import BaseInputSchema
from pydantic import Field

class AgentInputSchema(BaseInputSchema):
    """
    Inherits platform fields from BaseInputSchema:
    - session_id: Optional[str]
    - trace_id: Optional[str]
    - client_id: Optional[str]
    """

    task: str = Field(
        ...,
        min_length=1,
        description="The main task to perform",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "What would you like help with?",
        }
    )

    def to_prompt(self) -> str:
        """Convert structured input to natural language."""
        return f"Task: {self.task}"
```

### UI Widget Reference

| Widget | Description | Usage |
|--------|-------------|-------|
| `textarea` | Multi-line text input | Long-form descriptions |
| `select` | Dropdown selection | Fixed options |
| `number` | Numeric input | Quantities, limits |
| `hidden` | Not visible to user | System fields |
| `date` | Date picker | Date selection |
| `checkbox` | Boolean toggle | Yes/no options |

### Advanced Field Options

```python
field: str = Field(
    ...,
    json_schema_extra={
        "ui_widget": "select",
        "prompt_question": "What type of analysis?",
        "prompt_options": ["quick", "detailed", "comprehensive"],
        "show_if": {"mode": "advanced"},      # Conditional display
        "required_when": {"type": "custom"},  # Conditional requirement
    }
)
```

### Output Schema Pattern

```python
# agent/output_schema.py
from pydantic import BaseModel, Field
from typing import Optional, List

class AgentOutputSchema(BaseModel):
    response: str = Field(..., description="Main response text")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    findings: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None
    follow_up_questions: Optional[List[str]] = None
    status: str = Field(default="completed")
```

---

## Automatic Input Validation (Platform Feature)

The TAP template **automatically wraps ALL developer agents** with an InputValidator that ensures required fields are present before the main agent runs. This is a **zero-effort platform feature** - developers just define their schema and validation happens automatically.

### How It Works

```
User message → server.py → SequentialAgent:
                            ├── InputValidator (validates required fields)
                            │   ├── All fields present? → Continue to main agent
                            │   └── Missing fields? → ask_clarifying_questions()
                            └── DeveloperAgent (your root_agent)
```

### Architecture

```python
# In server.py (automatically applied)
from agent.validation import wrap_with_validation

wrapped_agent = wrap_with_validation(root_agent, AgentInputSchema)
# wrapped_agent is now a SequentialAgent: [InputValidator, root_agent]
```

### What Gets Validated

The wrapper automatically detects **required fields** from your `AgentInputSchema`:

| Detection Method | Example |
|------------------|---------|
| Field with `...` (ellipsis) | `task: str = Field(...)` |
| Field in `required` list | Pydantic's JSON schema |
| Field without default | `name: str` (no `= None` or `= "default"`) |

**Platform fields are skipped:** `session_id`, `trace_id`, `client_id`, `oauth_credentials`

### The `prompt_question` Metadata

When a field is missing, the InputValidator uses `prompt_question` from `json_schema_extra` to ask the user:

```python
class AgentInputSchema(BaseInputSchema):
    task: str = Field(
        ...,
        description="The main task to perform",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "What would you like me to help you with?",  # Used by validator!
        }
    )
```

If `prompt_question` is not defined, it defaults to `"What is the {field_name}?"`.

### Validation Flow Example

**Scenario: User sends vague message**

```
1. User: "help me"
2. InputValidator examines message
3. Required field "task" is missing/unclear
4. InputValidator calls ask_clarifying_questions():
   - "What would you like me to help you with?"
5. Gateway returns CLARIFYING_QUESTIONS intent
6. Frontend shows question modal
7. User answers: "Write a Python function for prime numbers"
8. InputValidator receives answer, validates, proceeds
9. DeveloperAgent runs with validated input
```

**Scenario: User provides complete input**

```
1. User: "Write a Python function that calculates prime numbers"
2. InputValidator examines message
3. Required field "task" is clearly present
4. InputValidator outputs ValidatedInputSchema to state
5. DeveloperAgent runs immediately (no questions asked)
```

### Opting Out of Validation

If your agent doesn't need validation (e.g., all fields are optional), skip it:

```bash
# Environment variable
TAP_SKIP_VALIDATION=true python runtime/server.py
```

Or programmatically:

```python
from agent.validation import wrap_with_validation

# Skip validation for this specific agent
agent = wrap_with_validation(root_agent, schema, skip_validation=True)
```

### Validation Module API

```python
from agent.validation import (
    wrap_with_validation,      # Main wrapper function
    get_required_fields,       # Detect required fields from schema
    create_input_validator,    # Create InputValidator LlmAgent
    generate_validator_prompt, # Generate validator instruction
)

# Detect required fields
fields = get_required_fields(AgentInputSchema)
# Returns: [{"name": "task", "description": "...", "prompt_question": "..."}]

# Create standalone validator (advanced usage)
validator = create_input_validator(fields, agent_name="MyAgent")
```

### ValidatedInputSchema Output

When validation succeeds, the InputValidator outputs to state with key `validated_input`:

```python
{
    "task": "Write a Python function for prime numbers",
    "confidence": 0.95,  # How confident the extraction was
    "source": "user_input"  # "user_input", "context", or "clarified"
}
```

The developer's agent can access this via ADK's shared state if needed.

### Key Files

| File | Purpose |
|------|---------|
| `agent/validation.py` | Core validation wrapper logic |
| `runtime/server.py` | Applies wrapper to root_agent |
| `agent/input_schema.py` | Define required fields with `prompt_question` |

### Benefits

| Benefit | Description |
|---------|-------------|
| **Zero developer effort** | Just define your schema, validation is automatic |
| **Consistent UX** | All SMAs validate input the same way |
| **Smart extraction** | LLM extracts fields from context, not just explicit values |
| **Graceful degradation** | Works without tap_core (just skips question tool) |
| **Opt-out available** | Skip validation if not needed |

---

## OAuth Credentials (BYO Auth)

TAP provides a secure credential injection system for agents that need access to third-party APIs (Google Workspace, Salesforce, Slack, etc.).

### How It Works

```
1. Agent declares required_credentials in input schema
2. Gateway reads from agent card at /.well-known/agent.json
3. Gateway checks if user has connected the app
4. If connected → credentials injected into oauth_credentials field
5. If not connected → Gateway returns credential_required response
6. Frontend shows modal: Connect Account OR One-Time Purchase
7. After connection, request is automatically retried
```

### Declaring Credential Requirements

```python
# agent/schemas.py
from typing import Optional, Dict, Any
from pydantic import Field
from tap_core.schemas.base import BaseInputSchema


class AgentInputSchema(BaseInputSchema):
    task: str = Field(..., description="What task should the agent perform?")

    # Platform-injected OAuth credentials (hidden from user)
    oauth_credentials: Optional[Dict[str, Any]] = Field(
        default=None,
        description="OAuth tokens provided by TAP platform",
        json_schema_extra={
            "ui_widget": "hidden",
            "platform_provided": True,
        }
    )

    # Declare which credentials your agent needs
    model_config = {
        "json_schema_extra": {
            "required_credentials": {
                "google": {
                    "scopes": [
                        "https://www.googleapis.com/auth/documents.readonly",
                        "https://www.googleapis.com/auth/drive.readonly"
                    ],
                    "reason": "Access Google Docs for document analysis"
                }
            }
        }
    }
```

### Accessing Credentials in Tools

```python
from tap_core.tools import get_oauth_credentials
from agent.exceptions import MissingCredentialsError


def fetch_google_doc(doc_url: str) -> str:
    """Fetch a Google Doc using platform-provided credentials."""

    # Get credentials from context
    google_creds = get_oauth_credentials("google")

    if not google_creds:
        # This triggers the OAuth flow in the frontend
        raise MissingCredentialsError(
            service="Google Docs",
            scopes=["https://www.googleapis.com/auth/documents.readonly"]
        )

    # Use the token
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(token=google_creds["access_token"])
    docs_service = build('docs', 'v1', credentials=credentials)

    doc_id = extract_doc_id(doc_url)
    document = docs_service.documents().get(documentId=doc_id).execute()

    return document.get('body', {}).get('content', '')
```

### Credential Structure

```python
{
    "access_token": "ya29.xxx...",
    "token_type": "Bearer",
    "expires_at": "2025-01-10T12:00:00Z",  # ISO format, may be None
    "scopes": ["scope1", "scope2"],
    "provider_email": "user@example.com"   # Email used for OAuth
}
```

### MissingCredentialsError

```python
# agent/exceptions.py
class MissingCredentialsError(Exception):
    """Raised when required OAuth credentials are not provided."""

    def __init__(self, service: str, scopes: list[str]):
        self.service = service
        self.scopes = scopes
        self.error_code = "MISSING_OAUTH_CREDENTIALS"
        super().__init__(f"Missing OAuth credentials for {service}.")

    def to_platform_response(self) -> dict:
        return {
            "error_code": self.error_code,
            "service": self.service,
            "required_scopes": self.scopes,
            "action_required": "oauth_connect",
        }
```

### Supported Providers

| Provider | Slug | Common Scopes |
|----------|------|---------------|
| Google Workspace | `google` | `documents.readonly`, `drive.readonly`, `gmail.readonly` |
| Salesforce | `salesforce` | `api`, `refresh_token` |
| Slack | `slack` | `channels:read`, `chat:write` |

### Testing Without Credentials

```python
from tap_core.tools import set_tool_context

set_tool_context(
    org_id="test-org",
    user_id="test-user",
    session_id="test-session",
    trace_id="test-trace",
    oauth_credentials={
        "google": {
            "access_token": "test-token",
            "token_type": "Bearer",
        }
    }
)
```

---

## Mesh Tools Usage

### Available Mesh Tools (12 total)

| Tool | Intent Type | Purpose | For SMAs? |
|------|-------------|---------|-----------|
| `agent_lookup` | `TOOL_CALL` | Search tiered agent registry | Yes |
| `transfer_to_agent` | `TRANSFER_TO_AGENT` | Delegate to another agent | Yes |
| `transfer_back_to_parent` | `TRANSFER_BACK` | Return results to parent agent | **Required** |
| `ask_clarifying_questions` | `CLARIFYING_QUESTIONS` | Gather user input via inline Q&A | Yes |
| `ask_user_permission` | `PERMISSION_REQUIRED` | Request permission for sensitive actions | Yes |
| `request_input` | `INPUT_REQUIRED` | Collect structured input via modal form | Yes |
| `request_agent_approval` | `APPROVAL_REQUIRED` | Request approval for tertiary agents | Yes |
| `calculate_one_time_price` | `PRICING_QUOTE` | Get guaranteed price quote | Yes |
| `log_unfulfilled_request` | `TOOL_CALL` | Log market gaps for analysis | Yes |
| `set_needs_attention` | `STATUS_UPDATE` | Signal user attention needed | Rare |
| `set_complete` | `TASK_COMPLETION` | Signal task completion to USER | **Master Agent only** |
| `notify_user` | `NOTIFICATION` | Send progress updates | Rare |

### Critical: SMA Return Flow

> **IMPORTANT:** SMAs should use `transfer_back_to_parent()` NOT `set_complete()` to return to their caller.

**Why?**
- `set_complete()` is a **UI tool** that signals completion to the **USER** (shows completion card)
- `transfer_back_to_parent()` is an **agent-to-agent** tool that returns results to the **parent agent**

**SMA Lifecycle:**
1. Master Agent (or another SMA) calls your SMA via `transfer_to_agent()`
2. Your SMA does its work
3. Your SMA calls `transfer_back_to_parent()` with results
4. Gateway returns control to the parent agent with your results
5. Parent agent continues processing (may call `set_complete()` to show USER)

**Example: Correct SMA Return**
```python
from tap_core.tools import transfer_back_to_parent

# When SMA completes its task
result = transfer_back_to_parent(
    result="Here are my research findings: [summary]",
    success=True,
    deliverables=["comparison_table", "recommendation"],
    data={"tools": [...], "recommendation": "tool_a"},
    confidence=0.92,
)
# Gateway returns this to parent agent, NOT to user directly
```

**Example: WRONG SMA Return (Don't do this!)**
```python
from tap_core.tools import set_complete

# WRONG - This signals completion to USER, not to parent agent
set_complete(summary="Task complete")  # User sees completion card, parent agent never gets results!
```

### Tool Usage Examples

#### 1. Agent Lookup

```python
from tap_core.tools import agent_lookup

# Search all tiers
results = agent_lookup(
    query="help with tax preparation",
    tier="all",           # "primary", "secondary", "tertiary", or "all"
    limit=5,
    min_similarity=0.6,
)

# Results include tier, slug, description, pricing
for agent in results:
    print(f"{agent['tier']}: {agent['slug']} - {agent['description']}")
```

#### 2. Transfer to Agent

```python
from tap_core.tools import transfer_to_agent

# Returns intent for Gateway to execute
intent = transfer_to_agent(
    target_agent_slug="tax-specialist",
    message="Help user file their 2025 tax return",
    context={
        "user_income": "75000",
        "filing_status": "single",
    }
)
# Gateway receives intent and routes to target SMA
```

#### 3. Ask Clarifying Questions

```python
from tap_core.tools import ask_clarifying_questions

intent = ask_clarifying_questions(
    questions=[
        {
            "field": "tax_year",
            "question": "Which tax year are you filing for?",
            "type": "select",
            "options": ["2024", "2025"],
        },
        {
            "field": "has_dependents",
            "question": "Do you have any dependents?",
            "type": "boolean",
        }
    ],
    reason="Need more information to proceed accurately",
)
```

#### 4. Signal Completion (Master Agent Only)

```python
from tap_core.tools import set_complete

# NOTE: Only Master Agent should use this!
# SMAs should use transfer_back_to_parent() instead
set_complete(
    summary="Successfully prepared tax filing summary",
    metadata={
        "estimated_refund": 1250,
        "forms_completed": ["1040", "W-2"],
    }
)
```

#### 5. Transfer Back to Parent (SMA Return)

```python
from tap_core.tools import transfer_back_to_parent

# When your SMA finishes its delegated task
intent = transfer_back_to_parent(
    result="Analysis complete. Found 5 AI tools matching your requirements...",
    success=True,
    deliverables=["comparison_table", "recommendation"],
    data={
        "tools": [
            {"name": "Tool A", "score": 0.95},
            {"name": "Tool B", "score": 0.88},
        ],
        "recommendation": "tool_a",
    },
    confidence=0.92,
)
# Gateway returns this to whoever called your SMA
```

**Parameters:**
- `result` (required): Summary of work completed
- `success`: Whether the work succeeded (default: True)
- `deliverables`: List of outputs produced
- `data`: Structured data for parent agent to use
- `confidence`: Certainty score (0-1)

#### 6. Ask User Permission

```python
from tap_core.tools import ask_user_permission

# For sensitive/destructive/costly actions
intent = ask_user_permission(
    action="Delete 15 temporary files from workspace",
    reason="Free up disk space before processing",
    consequences="Files cannot be recovered after deletion",
    alternatives=["Archive files instead", "Move to trash"],
)
# User sees Approve/Deny modal
```

**Use when:**
- About to perform destructive actions (delete files, etc.)
- Action involves significant cost
- Action is irreversible
- Need explicit user confirmation

#### 7. Request Structured Input

```python
from tap_core.tools import request_input

# For collecting structured data via modal form
intent = request_input(
    reason="I need more details to research AI tools for your business",
    fields=[
        {
            "name": "industry",
            "label": "Your Industry",
            "type": "select",
            "options": [
                {"value": "tech", "label": "Technology"},
                {"value": "finance", "label": "Finance"},
                {"value": "healthcare", "label": "Healthcare"},
            ],
            "required": True,
        },
        {
            "name": "budget",
            "label": "Monthly Budget (USD)",
            "type": "number",
            "min": 0,
            "max": 100000,
        },
        {
            "name": "requirements",
            "label": "Specific Requirements",
            "type": "textarea",
        },
    ],
    title="Research Parameters",
    submit_label="Start Research",
)
# User sees modal form with JSON Schema validation
```

**Field Types:**
- `text`, `textarea` - Text input
- `number`, `integer` - Numeric with min/max
- `boolean` - Checkbox
- `select`, `radio` - Single selection
- `checkbox_group` - Multiple selection
- `email`, `url`, `date` - Formatted strings
- `file` - File upload

### Intent-Based Architecture

**Important**: Mesh tools return **intents**, not results. Gateway executes them:

```python
# Agent code:
intent = transfer_to_agent(target_agent_slug="specialist", ...)

# Gateway sees intent in response and:
# 1. Validates user entitlement
# 2. Routes to target SMA
# 3. Returns result back to your agent
```

### Local Testing with Mocks

Enable mock mode for local development without Gateway:

```bash
TAP_USE_MOCK_TRANSFER=true python runtime/main.py
```

Configure mock responses in `agent/tools/transfer_mock.py`:

```python
MOCK_RESPONSES = {
    "tax-specialist": {
        "response": "Mock tax advice...",
        "status": "completed",
    },
    "__default__": {
        "response": "Mock response from specialist",
        "status": "completed",
    },
}
```

---

## ADK Callbacks Reference

### Available Callbacks

```python
# agent/callbacks.py
from google.adk.agents.callback_context import CallbackContext
from typing import Any
import time
import logging

logger = logging.getLogger(__name__)

async def on_agent_start(ctx: CallbackContext) -> None:
    """Called before agent execution."""
    logger.info(f"Agent {ctx.agent_name} starting")
    ctx.state["_start_time"] = time.time()

async def on_agent_end(ctx: CallbackContext, output: Any) -> None:
    """Called after agent execution."""
    duration = time.time() - ctx.state.get("_start_time", time.time())
    logger.info(f"Agent completed in {duration:.2f}s")

async def on_tool_start(
    ctx: CallbackContext,
    tool_name: str,
    args: dict
) -> Any:
    """Called before tool execution. Return value to skip tool."""
    logger.info(f"Tool {tool_name} called with {args}")
    # Return None to continue, or a value to skip tool execution
    return None

async def on_tool_end(
    ctx: CallbackContext,
    tool_name: str,
    result: Any
) -> None:
    """Called after tool execution."""
    logger.info(f"Tool {tool_name} returned: {result}")
```

### Registering Callbacks

```python
root_agent = LlmAgent(
    name="MyAgent",
    before_agent_callback=on_agent_start,
    after_agent_callback=on_agent_end,
    before_tool_callback=on_tool_start,
    after_tool_callback=on_tool_end,
    ...
)
```

### Callback Use Cases

| Callback | Use Cases |
|----------|-----------|
| `before_agent` | Logging, context setup, validation |
| `after_agent` | Metrics, cleanup, audit logging |
| `before_tool` | Caching, validation, mocking |
| `after_tool` | Result transformation, logging |

---

## Deployment Guide

### Local Development

```bash
cd tap_template_agent/runtime/
cp .env.example .env
# Edit .env with your GCP project

# Interactive mode (REPL)
python main.py

# Single query
python main.py "What can you help me with?"

# A2A server (for testing JSON-RPC)
python server.py
```

### A2A Server Testing

```bash
# Start server
python runtime/server.py

# Test agent card discovery
curl http://localhost:8080/.well-known/agent.json

# Test JSON-RPC endpoint (POST to root, same as Gateway sends)
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {"text": "Hello!"}
    },
    "id": 1
  }'

# Test streaming endpoint
curl -X POST http://localhost:8080/stream \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {"text": "Hello!"},
      "context": {"org_id": "test", "user_id": "test"}
    },
    "id": 1
  }'

# Health check
curl http://localhost:8080/health
```

### Vertex AI Deployment

**Prerequisites:**

```bash
# 1. Authenticate
gcloud auth application-default login

# 2. Create staging bucket
gsutil mb -l us-central1 gs://YOUR_PROJECT-tap-staging

# 3. Grant AI Platform service agent access (CRITICAL)
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT --format="value(projectNumber)")
gsutil iam ch serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com:roles/storage.objectAdmin gs://YOUR_PROJECT-tap-staging
```

**Deploy:**

```bash
cd tap_template_agent/runtime/

# Deploy new agent
python deploy_vertex.py

# Update existing
python deploy_vertex.py --update

# Validate only
python deploy_vertex.py --validate

# Check status
python deploy_vertex.py --status

# Delete
python deploy_vertex.py --delete
```

### Cloud Run Deployment

```bash
# Build container
docker build -t my-agent .

# Deploy to Cloud Run
gcloud run deploy my-agent \
  --image my-agent \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=your-project"
```

---

## Agent Registration (register_agent.py)

The `register_agent.py` script registers your SMA with the TAP Cognee Registry. **All registration fields are REQUIRED with no silent defaults** to prevent billing failures.

### Required CLI Arguments (Fail-Fast Validation)

When registering a NEW agent, these 6 fields are REQUIRED:

| Argument | Description |
|----------|-------------|
| `--owner-org-id` | Organization UUID (required for billing - maps to developer_id) |
| `--owner-user-id` | User UUID (required for audit trail) |
| `--input-cogs` | Input COGS per token in nanodollars |
| `--input-margin` | Input margin per token in nanodollars |
| `--output-cogs` | Output COGS per token in nanodollars |
| `--output-margin` | Output margin per token in nanodollars |

**Note:** For `update` action, ownership fields are optional (keeps existing values).

### Fail-Fast Behavior

```bash
# This will fail immediately with clear error message:
python register_agent.py register

# Expected output:
# ERROR: The following fields are REQUIRED for new registrations:
#   - --owner-org-id
#   - --owner-user-id
#   - --input-cogs
#   - --input-margin
#   - --output-cogs
#   - --output-margin
#
# All fields are required for billing to work correctly.
# No silent defaults - missing data should fail loudly.
```

### Registration Commands

```bash
# Test with dry-run (shows payload without sending)
python register_agent.py register \
  --owner-org-id YOUR_ORG_UUID \
  --owner-user-id YOUR_USER_UUID \
  --input-cogs 0 \
  --input-margin 10000 \
  --output-cogs 0 \
  --output-margin 12000 \
  --dry-run

# Actual registration
python register_agent.py register \
  --owner-org-id YOUR_ORG_UUID \
  --owner-user-id YOUR_USER_UUID \
  --input-cogs 0 \
  --input-margin 10000 \
  --output-cogs 0 \
  --output-margin 12000 \
  --tier tertiary

# Update existing (ownership optional)
python register_agent.py update \
  --input-margin 15000 \
  --output-margin 18000
```

### Agent Card Structure (Required Fields)

The agent card sent to Cognee MUST include these fields in this order:

```python
agent_card = {
    # Identity (A2A Protocol Standard)
    "name": "my-agent-slug",           # REQUIRED - A2A uses "name"
    "agent_slug": "my-agent-slug",     # Keep for backward compatibility
    "displayName": "My Agent",          # REQUIRED - human readable
    "display_name": "My Agent",         # Keep for backward compatibility
    "description": "What the agent does",
    "version": "1.0.0",
    "protocolVersion": "1.0",           # REQUIRED - A2A protocol version
    "agent_type": "sma",

    # Endpoint URLs (BOTH required)
    "url": "https://...",               # REQUIRED by Cognee validation
    "cloud_run_url": "https://...",     # Gateway fallback reads this

    # Provider info
    "provider": {...},

    # Capabilities (A2A feature flags)
    "capabilities": {...},

    # I/O Modes
    "defaultInputModes": ["text"],      # REQUIRED
    "defaultOutputModes": ["text"],     # REQUIRED

    # Skills (IDs MUST be kebab-case)
    "skills": [
        {"id": "my-skill", ...},        # CORRECT: kebab-case
        # {"id": "my_skill", ...},      # WRONG: snake_case fails validation
    ],

    # Input schema
    "input_schema": {...},

    # Discovery/documentation
    "discovery": {...},
    "documentationUrl": "..."
}
```

### Skill ID Format

**CRITICAL:** Skill IDs must be kebab-case to pass Cognee validation:

```
Regex: ^[a-z0-9][a-z0-9-]*[a-z0-9]$

✅ CORRECT: "software-research", "data-analysis", "code-review"
❌ WRONG:   "software_research", "dataAnalysis", "CODE_REVIEW"
```

### Registration Request Body

The full request body sent to Cognee includes:

```python
request_body = {
    "agent_slug": agent_slug,
    "agent_card": agent_card,
    "owner_org_id": owner_org_id,
    "owner_user_id": owner_user_id,
    "input_agent_cogs_per_token_nanodollars": input_cogs,
    "input_agent_margin_per_token_nanodollars": input_margin,
    "output_agent_cogs_per_token_nanodollars": output_cogs,
    "output_agent_margin_per_token_nanodollars": output_margin,
    "visibility": "public",           # "public" or "private"
    "agent_type": "sma",
    "tier": "tertiary",               # "primary", "secondary", or "tertiary"
}
```

### Why Billing Fields Matter

Without proper registration, billing silently fails:

```
Missing owner_org_id → developer_id is None → billing SKIPPED
Missing pricing fields → $0 charged → revenue lost
```

**BILLING RESILIENCE:** All pricing fields are REQUIRED with no defaults. Missing data fails loudly at registration time, not silently at billing time.

---

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | - | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Yes | us-central1 | GCP region |
| `TAP_MODEL_NAME` | No | gemini-3-flash-preview | Model override |
| `TAP_VALIDATION_MODEL` | No | gemini-3-flash-preview | Model for input validation |
| `TAP_SKIP_VALIDATION` | No | false | Skip automatic input validation |
| `TAP_USE_MOCK_TRANSFER` | No | false | Enable mock mode |
| `LOG_LEVEL` | No | INFO | Logging level |
| `STAGING_BUCKET` | Vertex | - | Vertex AI staging bucket |

### Agent Manifest (tap-agent.yaml)

```yaml
apiVersion: tap/v1
kind: AgentManifest

metadata:
  slug: my-agent                    # URL-safe unique identifier
  display_name: My Agent            # Human-readable name
  version: 1.0.0                    # Semantic version
  model: gemini-3-flash-preview     # AI model
  description: |
    Description for semantic search in Cognee Registry.

provider:
  organization: developer@example.com
  organization_name: My Organization

schemas:
  input:
    file: agent/input_schema.py
    class: AgentInputSchema
  output:
    file: agent/output_schema.py
    class: AgentOutputSchema

discovery:
  tier: tertiary                    # primary, secondary, or tertiary
  is_public: true
  is_active: true

deployment:
  runtime: vertex-ai                # vertex-ai or cloud-run
  model: gemini-3-flash-preview
  resources:
    cpu: 4
    memory: 4Gi
    timeout_seconds: 120
```

---

## Troubleshooting Guide

### Common Errors

#### Registration fails with "REQUIRED for new registrations"

**Cause:** Missing one or more of the 6 required registration fields.

**Fix:** Provide all required fields:
```bash
python register_agent.py register \
  --owner-org-id YOUR_ORG_UUID \
  --owner-user-id YOUR_USER_UUID \
  --input-cogs 0 \
  --input-margin 10000 \
  --output-cogs 0 \
  --output-margin 12000
```

#### Billing not recorded for SMA invocations

**Cause:** Agent registered without `owner_org_id` → `developer_id` is NULL → billing silently skipped.

**Fix:** Re-register the agent with proper ownership:
```bash
python register_agent.py register \
  --owner-org-id YOUR_ORG_UUID \
  --owner-user-id YOUR_USER_UUID \
  --input-cogs 0 --input-margin 10000 \
  --output-cogs 0 --output-margin 12000
```

#### Skill ID validation error in Cognee

**Cause:** Skill IDs use snake_case instead of kebab-case.

**Fix:** Change skill IDs to kebab-case:
```python
# WRONG
{"id": "software_research", ...}

# CORRECT
{"id": "software-research", ...}
```

#### 409 ABORTED during Vertex deployment

**Cause:** AI Platform service agent lacks bucket permissions.

**Fix:**
```bash
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT --format="value(projectNumber)")
gsutil iam ch serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com:roles/storage.objectAdmin gs://YOUR_BUCKET
```

#### ModuleNotFoundError: No module named 'tap_core'

**Cause:** tap_core not installed.

**Fix:**
```bash
pip install tap-core --extra-index-url https://australia-southeast1-python.pkg.dev/tailored-agents-aaas-platform/tap-python-packages/simple/
```

#### Tool context not set

**Cause:** `setup_tool_context()` not called before agent execution.

**Fix:**
```python
from agent.definition import setup_tool_context
setup_tool_context(gateway_context)
# Then run agent
```

#### Empty agent_lookup results

**Cause:** Query too specific or min_similarity too high.

**Fix:**
```python
results = agent_lookup(
    query="help with taxes",  # Broader query
    tier="all",
    min_similarity=0.4,       # Lower threshold
    limit=10,
)
```

#### SSE stream disconnects

**Cause:** Client or server timeout.

**Fix:** Increase `STREAMING_TIMEOUT` environment variable.

#### Validation asking too many questions

**Cause:** Fields detected as required when they shouldn't be.

**Fix:** Ensure optional fields have explicit defaults:
```python
# WRONG - detected as required (no default)
name: str

# RIGHT - optional with default
name: Optional[str] = None
name: str = ""
```

#### Validation not asking questions when it should

**Cause:** Field not detected as required.

**Fix:** Use `...` (ellipsis) for required fields:
```python
# Required field
task: str = Field(..., description="...")

# Also check model_json_schema() output
print(AgentInputSchema.model_json_schema())
```

### Debug Commands

```bash
# Enable debug logging
LOG_LEVEL=DEBUG python runtime/main.py

# Test agent card
curl http://localhost:8080/.well-known/agent.json | jq

# Test with verbose output
python -c "
from agent import root_agent
print('Agent:', root_agent.name)
print('Model:', root_agent.model)
print('Tools:', [t.__name__ for t in root_agent.tools])
"
```

### Log Patterns

| Prefix | Meaning |
|--------|---------|
| `AGENT_START:` | Agent execution beginning |
| `AGENT_END:` | Agent execution complete |
| `TOOL_CALL:` | Tool invocation |
| `TOKEN_COUNT:` | Token usage |
| `A2A_REQUEST:` | A2A protocol request |
| `A2A_RESPONSE:` | A2A protocol response |

---

## Key File Paths

### Template Source Code

```
tap_template_agent/
├── register_agent.py             # REQUIRED: TAP registry registration (fail-fast validation)
├── tap-agent.yaml                # REQUIRED: Agent manifest
├── agent/definition.py           # CORE: Agent definition
├── agent/validation.py           # PLATFORM: Automatic input validation wrapper
├── agent/input_schema.py         # REQUIRED: Input contract
├── agent/output_schema.py        # Output contract
├── agent/exceptions.py           # Custom exceptions (MissingCredentialsError)
├── agent/callbacks.py            # ADK lifecycle hooks
├── agent/prompts.py              # System prompts
├── agent/agent_card.py           # A2A metadata
├── agent/tools/custom_tools.py   # Custom tools
├── agent/tools/mesh_demo.py      # Mesh tools examples
├── agent/tools/transfer_mock.py  # Mock for testing
├── runtime/main.py               # Local CLI
├── runtime/server.py             # A2A server (applies validation wrapper)
└── runtime/deploy_vertex.py      # Vertex deployment
```

### tap_core Library

```
tap_core/src/tap_core/
├── tools/                        # Mesh tools
│   ├── __init__.py               # Main API (get_all_tools, set_tool_context)
│   ├── context.py                # Tool context management
│   └── mesh_tools/               # Individual tool implementations
├── schemas/
│   └── base.py                   # BaseInputSchema
└── runtime.py                    # Agent runtime utilities
```

### External Resources (Cloned)

```
.claude/skills/template-agent/
├── adk-python/                   # Google ADK Python SDK source
├── adk-docs/                     # ADK documentation
├── adk-samples/                  # Working examples
├── agent-starter-pack/           # GCP integration patterns
└── AI_Cognitive_Design_Patterns.md  # Agent cognitive patterns
```

---

## Related Documentation

### Internal

| Resource | Path | Description |
|----------|------|-------------|
| Quick Start | `tap_template_agent/README.md` | 5-step getting started |
| Dev Guide | `tap_template_agent/DEVELOPMENT.md` | Detailed documentation |
| tap_core Tools | `tap_core/docs/tools.md` | Tool API reference |
| Gateway | `.claude/skills/gateway/SKILL.md` | Gateway integration |
| Master Agent | `.claude/skills/master-agent/SKILL.md` | Orchestration |

### External (Cloned in Skill)

| Resource | Path | Description |
|----------|------|-------------|
| ADK Docs | `adk-docs/` | Official ADK documentation |
| ADK SDK | `adk-python/` | Python SDK source code |
| ADK Samples | `adk-samples/` | Working code examples |
| GCP Patterns | `agent-starter-pack/` | Production patterns |
| Cognitive Patterns | `AI_Cognitive_Design_Patterns.md` | Agent design patterns |

### Online Resources

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [Vertex AI Agent Builder](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-builder)
- [tap_core PyPI](https://pypi.org/project/tap-core/) (private registry)

---

## Framework Comparison

From `AI_Cognitive_Design_Patterns.md`:

| Feature | Google ADK | LangGraph | CrewAI |
|---------|------------|-----------|--------|
| **Best For** | Enterprise, Google Cloud | Complex Logic, Debugging | Rapid Prototyping |
| **Philosophy** | Software Engineering | State Machines | Team Management |
| **State Mgmt** | Session Services | Shared Schema | Unstructured |
| **Parallelism** | ParallelAgent | Send API | Async Tasks |
| **Infrastructure** | Serverless (Vertex) | Self-Hosted | Self-Hosted |

**When to choose Google ADK (TAP Platform):**
- Need strict security (HIPAA/SOC2)
- Require multimodal interaction
- Want distributed Agent-to-Agent mesh
- Deploying on Google Cloud

---

## Gateway ↔ SMA Bridge Architecture

This section documents the communication protocol between Gateway and SMAs - critical knowledge for debugging and advanced customization.

### Key Bridge Files

| File | Role |
|------|------|
| `tap_backend/gateway_service/agent_client.py` | Gateway's HTTP client for invoking SMAs |
| `tap_backend/gateway_service/intent_handler.py` | Streaming delegation orchestration |
| `tap_template_agent/runtime/server.py` | SMA's A2A server receiving requests |

### Request Payload (What Gateway Sends)

**For Sync Invocation (POST /):**
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {"type": "text", "text": "Task description"},
        {"type": "data", "data": {...}}
      ]
    },
    "contextId": "session-uuid",
    "context": {
      "org_id": "...",
      "user_id": "...",
      "session_id": "...",
      "trace_id": "...",
      "system_instruction": "SMA system prompt",
      "history": [...],
      "ltm": [...]
    }
  }
}
```

**For Streaming Invocation (POST /stream):**
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "context": {
      "org_id": "...",
      "user_id": "...",
      "session_id": "...",
      "trace_id": "...",
      "oauth_credentials": {...},
      "equipped_abilities": [...],
      "history": [...],
      "system_prompt": "SMA system prompt",
      "delegation_context": {
        "original_prompt": "User's original request",
        "delegated_by": "master-agent",
        "delegation_reason": "Why SMA was chosen",
        "delegation_depth": 1
      },
      "is_specialist_delegate": true
    },
    "message": {"text": "Task description"}
  }
}
```

**Note:** For streaming, context is nested under `params.context`, not flat under `params`.

### Response Payload (What Gateway Expects)

**Sync Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": "completed",
    "message": "Your response text",
    "metadata": {
      "input_tokens": 1500,
      "output_tokens": 2500
    }
  }
}
```

**Streaming Response (SSE):**
```
event: connected
data: {"agent_slug":"my-agent"}

event: working
data: {"status":"processing"}

data: {"text":"Partial response","partial":true}

event: done
data: {"input_tokens":1500,"output_tokens":2500,"text":"Full response","is_final":true}
```

### Token Counting (Required for Billing)

**IMPORTANT**: You MUST return accurate token counts in every response.

```python
# Extract from ADK events
def extract_token_counts(events: list) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for event in events:
        if hasattr(event, 'content') and hasattr(event.content, 'usage_metadata'):
            metadata = event.content.usage_metadata
            input_tokens += getattr(metadata, 'prompt_token_count', 0) or 0
            output_tokens += getattr(metadata, 'candidates_token_count', 0) or 0
    return input_tokens, output_tokens
```

### Known Limitations

1. **No Streaming Retry**: If your `/stream` endpoint hits a Cloud Run cold start, Gateway fails immediately (no retry like sync has)
2. **SMA→SMA Streaming Not Supported**: SMAs cannot delegate to other SMAs in streaming mode (recursive delegation only works in sync)
3. **Transfer Stack Not Available**: Streaming SMAs don't receive the transfer_stack for multi-hop returns
4. **Only Last 5 History Messages**: Streaming context only includes last 5 conversation turns

### Debugging Tips

**Check what Gateway sends:**
```python
# In server.py, add logging at request entry
logger.info(f"Received params: {json.dumps(params, indent=2)[:1000]}")
```

**Verify token counts are being returned:**
```bash
# Test streaming endpoint
curl -X POST http://localhost:8080/stream \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"text":"test"}}}'
```

---

## Development Workflow

### Creating a New SMA

1. **Copy template:**
   ```bash
   cp -r tap_template_agent/ my-new-agent/
   cd my-new-agent/
   ```

2. **Rename agent package:**
   ```bash
   # Update imports in all files
   sed -i 's/my_agent/my_new_agent/g' **/*.py
   ```

3. **Configure manifest:**
   ```yaml
   # tap-agent.yaml
   metadata:
     slug: my-new-agent
     display_name: My New Agent
     description: What my agent does...
   ```

4. **Implement logic:**
   - Edit `agent/definition.py` - Customize prompts, add tools
   - Edit `agent/input_schema.py` - Define input fields
   - Add tools in `agent/tools/custom_tools.py`

5. **Test locally:**
   ```bash
   cd runtime/
   python main.py
   ```

6. **Deploy:**
   ```bash
   python deploy_vertex.py
   # or for Cloud Run:
   gcloud run deploy my-agent --image my-agent --region us-central1
   ```

7. **Register with TAP (REQUIRED for billing):**
   ```bash
   # First, test with dry-run
   python register_agent.py register \
     --owner-org-id YOUR_ORG_UUID \
     --owner-user-id YOUR_USER_UUID \
     --input-cogs 0 \
     --input-margin 10000 \
     --output-cogs 0 \
     --output-margin 12000 \
     --dry-run

   # Then register for real
   python register_agent.py register \
     --owner-org-id YOUR_ORG_UUID \
     --owner-user-id YOUR_USER_UUID \
     --input-cogs 0 \
     --input-margin 10000 \
     --output-cogs 0 \
     --output-margin 12000 \
     --tier tertiary
   ```

   > **IMPORTANT:** All 6 fields are REQUIRED. Registration will fail-fast with clear error if any are missing. This prevents billing failures at runtime.

### Best Practices

1. **Keep agents focused** - One domain/capability per SMA
2. **Use mesh tools** - Delegate to specialists via transfer_to_agent
3. **Handle errors gracefully** - Use try/except and meaningful error messages
4. **Log appropriately** - Use structured logging for debugging
5. **Test with mocks** - Use TAP_USE_MOCK_TRANSFER for local testing
6. **Document your agent** - Update description in tap-agent.yaml
