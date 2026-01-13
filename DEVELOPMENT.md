# TAP Template Agent - Development Guide

Detailed documentation for building TAP-compatible agents.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Agent Definition](#agent-definition)
3. [Input Schema](#input-schema)
4. [OAuth Credentials](#oauth-credentials)
5. [Mesh Tools](#mesh-tools)
6. [ADK Callbacks](#adk-callbacks)
7. [Deployment](#deployment)
8. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### TAP Platform Components

Your SMA integrates with these platform services:

| Service | Purpose |
|---------|---------|
| **Gateway** | Routes requests, assembles context, handles billing |
| **Master Agent** | Orchestrates work, delegates to SMAs |
| **Session Service** | Stores conversation history |
| **Prompt Library** | Manages system prompts |
| **Cognee Registry** | Agent discovery via semantic search |
| **Billing Service** | Token counting and usage tracking |

### Request Flow

```
User → Frontend → BFF → Gateway → Your SMA
                         ↓
                  Context Assembly:
                  - System prompt (Prompt Library)
                  - History (Session Service)
                  - LTM (Cognee)
                         ↓
                  SMA executes, returns response + tokens
                         ↓
                  Gateway records billing
```

### Stateless Design

**Important**: Your agent is stateless. Each request:
1. Creates a fresh `InMemoryRunner`
2. Receives context from Gateway
3. Returns response with token counts
4. No state persists between requests

---

## Agent Definition

### Simple LlmAgent Pattern

```python
# agent/definition.py
from google.adk.agents import LlmAgent
from tap_core.tools import get_all_tools, set_tool_context

root_agent = LlmAgent(
    name="MyAgent",
    model="gemini-3-flash-preview",
    instruction=SYSTEM_PROMPT["content"],
    tools=[*get_all_tools(), *custom_tools],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
    ),
)
```

### Tool Context Setup

**Critical**: Call `setup_tool_context()` before execution:

```python
from agent.definition import setup_tool_context

# Set context for mesh tools
setup_tool_context({
    "org_id": gateway_context.get("org_id"),
    "user_id": gateway_context.get("user_id"),
    "session_id": gateway_context.get("session_id"),
    "trace_id": gateway_context.get("trace_id"),
})
```

### ADK Agent Types

| Type | Use Case |
|------|----------|
| `LlmAgent` | Single agent with tools (most common) |
| `SequentialAgent` | Multi-step pipeline |
| `ParallelAgent` | Concurrent sub-agents |
| `LoopAgent` | Iterative processing |

---

## Input Schema

### BaseInputSchema

Inherit from `tap_core.schemas.base.BaseInputSchema`:

```python
from tap_core.schemas.base import BaseInputSchema
from pydantic import Field

class AgentInputSchema(BaseInputSchema):
    """
    Inherits platform fields:
    - session_id
    - trace_id
    - client_id
    """

    task: str = Field(
        ...,
        description="What to do",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "What would you like help with?",
        }
    )

    def to_prompt(self) -> str:
        return f"Task: {self.task}"
```

### UI Widgets

```python
json_schema_extra={
    "ui_widget": "textarea",      # Multi-line text
    "ui_widget": "select",        # Dropdown
    "ui_widget": "number",        # Number input
    "ui_widget": "hidden",        # Hidden field
    "prompt_question": "...",     # Question for clarification
    "prompt_options": [...],      # Options for select
    "show_if": {"field": "value"}, # Conditional display
    "required_when": {"field": "value"}, # Conditional requirement
}
```

---

## OAuth Credentials

If your agent needs access to third-party APIs (Google Workspace, Salesforce, Slack, etc.), TAP provides a secure credential injection system.

### How It Works

1. **Declare requirements** in your input schema
2. **Gateway checks** if user has connected the app
3. **Credentials injected** into your agent's context
4. **Access in tools** via `get_oauth_credentials()`

### Declaring Credential Requirements

In `agent/input_schema.py`:

```python
from typing import Optional, Dict, Any
from pydantic import Field
from tap_core.schemas.base import BaseInputSchema


class AgentInputSchema(BaseInputSchema):
    task: str = Field(..., description="What task should the agent perform?")

    # Platform-provided OAuth credentials (hidden from user)
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

    # Extract doc ID and fetch...
    doc_id = extract_doc_id(doc_url)
    document = docs_service.documents().get(documentId=doc_id).execute()

    return document.get('body', {}).get('content', '')
```

### Credential Structure

When credentials are available, they have this structure:

```python
{
    "access_token": "ya29.xxx...",
    "token_type": "Bearer",
    "expires_at": "2025-01-10T12:00:00Z",  # ISO format, may be None
    "scopes": ["scope1", "scope2"],
    "provider_email": "user@example.com"   # Email used for OAuth
}
```

### Supported Providers

| Provider | Slug | Common Scopes |
|----------|------|---------------|
| Google Workspace | `google` | `documents.readonly`, `drive.readonly`, `gmail.readonly` |
| Salesforce | `salesforce` | `api`, `refresh_token` |
| Slack | `slack` | `channels:read`, `chat:write` |

### User Experience

When your agent needs credentials the user hasn't connected:

1. Gateway detects missing credentials from your `required_credentials`
2. Frontend shows a modal with two options:
   - **Connect Account**: User authorizes your agent (one-time setup)
   - **One-Time Access**: User pays for single-use via affiliate credentials
3. After connection, the request is automatically retried

### Error Handling

Always handle missing credentials gracefully:

```python
from agent.exceptions import MissingCredentialsError

try:
    result = fetch_google_doc(url)
except MissingCredentialsError as e:
    # This propagates to Gateway, which triggers OAuth flow
    raise
except Exception as e:
    # Handle other errors
    return f"Error accessing document: {e}"
```

### Testing Without Credentials

For local development, you can mock credentials:

```python
# In tests or local dev
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

## Mesh Tools

Mesh tools enable platform-wide capabilities.

### Available Tools

| Tool | Purpose |
|------|---------|
| `agent_lookup` | Search for specialist agents |
| `transfer_to_agent` | Delegate to another agent |
| `ask_clarifying_questions` | Gather user input |
| `request_agent_approval` | Request approval for non-entitled agents |
| `set_needs_attention` | Signal user attention needed |
| `set_complete` | Signal task completion |
| `notify_user` | Send progress updates |

### Usage Pattern

```python
from tap_core.tools import (
    agent_lookup,
    transfer_to_agent,
    ask_clarifying_questions,
    set_complete,
)

# Search for specialist
result = agent_lookup(
    query="help with tax returns",
    tier="all",
    limit=5,
)

# Transfer to specialist
intent = transfer_to_agent(
    target_agent_slug="tax-specialist",
    message="Help user with tax return",
)

# Ask for more info
intent = ask_clarifying_questions(
    questions=[
        {"field": "year", "question": "Which tax year?", "type": "select"}
    ],
    reason="Need more details",
)

# Signal completion
set_complete(summary="Task completed successfully")
```

### Intent-Based Architecture

Mesh tools return **intents**, not results. Gateway executes:

```python
# Tool returns intent
intent = transfer_to_agent(...)

# Gateway sees intent and:
# 1. Validates authorization
# 2. Routes to target agent
# 3. Returns result to your agent
```

### Local Testing with Mocks

Enable mock mode for local testing:

```bash
TAP_USE_MOCK_TRANSFER=true python runtime/main.py
```

Configure mocks in `agent/tools/transfer_mock.py`.

---

## ADK Callbacks

Callbacks hook into agent lifecycle.

### Available Callbacks

```python
# agent/callbacks.py
async def on_agent_start(ctx: CallbackContext) -> None:
    """Before agent execution"""
    logger.info(f"Agent {ctx.agent_name} starting")

async def on_agent_end(ctx: CallbackContext, output: Any) -> None:
    """After agent execution"""
    logger.info(f"Agent completed")

async def on_tool_start(ctx: CallbackContext, tool_name: str, args: dict):
    """Before tool execution"""
    # Return value to skip execution
    return None

async def on_tool_end(ctx: CallbackContext, tool_name: str, result: Any):
    """After tool execution"""
    pass
```

### Registering Callbacks

```python
root_agent = LlmAgent(
    name="MyAgent",
    before_agent_callback=on_agent_start,
    after_agent_callback=on_agent_end,
    ...
)
```

---

## Deployment

### Local Development

```bash
cd runtime/
cp .env.example .env
# Edit .env with your GCP project

# Interactive mode
python main.py

# A2A server
python server.py
```

### Vertex AI Deployment

```bash
# Prerequisites
gcloud auth application-default login
gsutil mb -l us-central1 gs://YOUR_PROJECT-tap-staging

# Grant permissions (CRITICAL)
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT --format="value(projectNumber)")
gsutil iam ch serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com:roles/storage.objectAdmin gs://YOUR_PROJECT-tap-staging

# Deploy
python runtime/deploy_vertex.py
```

### Cloud Run Deployment

```bash
# Build container
docker build -t my-agent .

# Deploy
gcloud run deploy my-agent \
  --image my-agent \
  --region us-central1 \
  --allow-unauthenticated
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Yes | Region (us-central1) |
| `TAP_MODEL_NAME` | No | Model override |
| `TAP_USE_MOCK_TRANSFER` | No | Enable mock mode |

---

## Troubleshooting

### Common Errors

**409 ABORTED error during deployment**
```bash
# Fix: Grant service agent bucket access
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT --format="value(projectNumber)")
gsutil iam ch serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com:roles/storage.objectAdmin gs://YOUR_BUCKET
```

**ModuleNotFoundError: No module named 'tap_core'**
```bash
# Fix: Install tap-core from your TAP Artifact Registry
# Configure pip.conf with your registry URL (see runtime/pip.conf.example)
pip install tap-core
```

**Tool context not set**
```python
# Fix: Call setup_tool_context before execution
from agent.definition import setup_tool_context
setup_tool_context(gateway_context)
```

### Debug Logging

```bash
LOG_LEVEL=DEBUG python runtime/main.py
```

### Testing A2A Protocol

```bash
# Start server
python runtime/server.py

# Test agent card
curl http://localhost:8080/.well-known/agent.json

# Test message
curl -X POST http://localhost:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"text":"Hello"}},"id":1}'
```

---

## Additional Resources

- [TAP Platform Docs](../docs/)
- [Google ADK Documentation](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-builder)
- [tap_core Library](../tap_core/)
