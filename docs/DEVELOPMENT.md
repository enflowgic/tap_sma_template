# TAP Agent Development Guide

Complete guide for building, deploying, and publishing agents on the Tailored Agents Platform.

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Architecture](#architecture)
4. [Building Your Agent](#building-your-agent)
5. [Input Schemas](#input-schemas)
6. [OAuth Credentials](#oauth-credentials)
7. [Mesh Tools](#mesh-tools)
8. [ADK Callbacks](#adk-callbacks)
9. [Deployment](#deployment)
10. [Registration](#registration)
11. [Marketplace Publishing](#marketplace-publishing)
12. [Pricing & Payouts](#pricing--payouts)
13. [Monitoring & Analytics](#monitoring--analytics)
14. [API Contract (A2A Protocol)](#api-contract-a2a-protocol)
15. [Security Best Practices](#security-best-practices)
16. [Troubleshooting](#troubleshooting)
17. [CLI Reference](#cli-reference)

---

## Overview

### What is TAP?

TAP (Tailored Agents Platform) is a multi-tenant agent mesh that allows businesses to deploy and monetize AI agents. The platform handles:

- **Agent Discovery & Routing**: Master agents route requests to specialized worker agents
- **Billing & Metering**: Usage-based billing per token
- **Authentication & Authorization**: Multi-tenant access control
- **Mesh Tools**: Shared tools available to all agents (tap_core)
- **User Personalization**: Per-user preferences via Cognee LTM

### What You Build vs. What TAP Provides

| You Build | TAP Provides |
|-----------|--------------|
| Agent logic (prompts, workflows) | Cloud Run hosting |
| Custom tools (your APIs/databases) | Universal mesh tools |
| Input schema (what your agent needs) | Input collection UI |
| Business logic | Billing, auth, telemetry |

### Model Verification Notice

> **AI Model Currency Notice**
>
> AI models evolve rapidly and older models are frequently deprecated. Many AI coding assistants operate on stale training data and may suggest outdated models.
>
> **Before implementing or changing Gemini model references:**
> 1. Search the web for current Google Gemini model availability
> 2. Check: https://ai.google.dev/gemini-api/docs/models
> 3. Verify model IDs are currently supported in Vertex AI
>
> **Current recommended models (December 2025):**
> - `gemini-3-flash-preview` - Fast, cost-effective
> - `gemini-3-pro-preview` - Advanced reasoning
>
> **Deprecated (DO NOT USE):** gemini-1.5-*, gemini-2.0-*, gemini-2.5-*

---

## Quick Start

### Option 1: Clone the Template

```bash
cp -r tap_template_agent/ my-agent/
cd my-agent/

# Rename packages
mv agent/ my_agent_name/
# Update imports in all files

# Configure
cp deploy/.env.example deploy/.env
# Edit deploy/.env with your GCP project
```

### Option 2: Wrap an Existing Agent

If you already have an agent:

1. **Export required symbols** from your package:
   ```python
   # your_agent/__init__.py
   from .agent import root_agent as AGENT_RUNNABLE
   from .schemas import AgentInputSchema
   ```

2. **Copy the runtime wrapper** from the template

3. **Configure and deploy**

### Local Testing

```bash
# Interactive mode
python runtime/cli.py

# Single query
python runtime/cli.py "Hello, what can you help with?"

# A2A server (for testing protocol)
python runtime/server.py
```

---

## Architecture

### TAP Platform Components

Your SMA integrates with these platform services:

| Service | Purpose |
|---------|---------|
| **Gateway** | Routes requests, assembles context, handles billing |
| **Master Agent** | Orchestrates work, delegates to SMAs |
| **Session Service** | Stores conversation history |
| **Cognee Registry** | Agent discovery, LTM, user preferences |
| **Billing Service** | Token counting and usage tracking |

### Request Flow

```
User → Frontend → BFF → Gateway → Your SMA
                         ↓
                  Context Assembly:
                  - History (Session Service)
                  - LTM & User Preferences (Cognee)
                  - Equipped abilities (Cognee Registry)
                         ↓
                  SMA executes, returns response + tokens
                         ↓
                  Gateway records billing
```

### Two-Layer Architecture

Every TAP agent follows a two-layer pattern:

```
┌─────────────────────────────────────────────────────────────────┐
│               YOUR AGENT PACKAGE (agent/)                        │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────────────┐  │
│  │ agent.py  │ │ prompts.py│ │ schemas.py│ │    tools/       │  │
│  │(LlmAgent) │ │           │ │(I/O types)│ │(custom tools)   │  │
│  └───────────┘ └───────────┘ └───────────┘ └─────────────────┘  │
│  Focus on your domain logic - TAP handles the rest.             │
└─────────────────────────────────────────────────────────────────┘
                           │
                           │ imported by
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                TAP WRAPPER (tap_wrapper/)                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ build_tap_agent()    - Injects mesh tools, wraps validation ││
│  │ generate_agent_card() - Auto-generates A2A card from config ││
│  │ setup_tool_context() - Sets up context for mesh tools       ││
│  │ get_config()          - Parses tap-agent.yaml manifest      ││
│  └─────────────────────────────────────────────────────────────┘│
│  tap_wrapper/ handles all TAP integration automatically.        │
└─────────────────────────────────────────────────────────────────┘
                           │
                           │ used by
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     RUNTIME (runtime/)                           │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ server.py - FastAPI A2A server for Cloud Run                ││
│  │ cli.py    - Local development CLI for testing               ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

**Why Two Layers?**
- **Minimal Developer Burden**: You only touch 4 files in `agent/`
- **Automatic Platform Integration**: `tap_wrapper/` handles mesh tools, validation, A2A cards
- **Testability**: Test your agent locally without TAP infrastructure
- **Clean Separation**: Your ADK code never needs TAP-specific imports

### Stateless Design

**Important**: Your agent is stateless. Each request:
1. Creates a fresh `InMemoryRunner`
2. Receives context from Gateway
3. Returns response with token counts
4. No state persists between requests

---

## Building Your Agent

### Directory Structure

```
my_agent/
├── tap-agent.yaml          # Agent manifest (REQUIRED)
├── Dockerfile              # Cloud Run container
├── cloudbuild.yaml         # Cloud Build config
├── requirements.txt        # Dependencies
├── main.py                 # A2A server entry point
│
├── agent/                  # YOUR CODE
│   ├── __init__.py         # Package exports
│   ├── agent.py            # LlmAgent definition ← Your main file
│   ├── schemas.py          # Input/output schemas
│   ├── prompts.py          # Agent description & instructions
│   ├── callbacks.py        # ADK lifecycle hooks (optional)
│   └── tools/              # Your custom tools
│       ├── __init__.py     # Exports custom_tools list
│       └── example.py      # Example tool (delete when ready)
│
├── tap_wrapper/            # TAP PLATFORM CODE (don't modify)
│   ├── __init__.py         # build_tap_agent(), setup_tool_context()
│   ├── config.py           # Parses tap-agent.yaml
│   ├── prompts.py          # Platform prompt boilerplate
│   ├── agent_card.py       # Auto-generates A2A agent card
│   ├── validation.py       # Input validation wrapper
│   ├── mesh_integration.py # Mesh tools injection
│   ├── exceptions.py       # Platform exceptions
│   └── testing/            # Testing utilities
│       ├── __init__.py
│       └── mock_transfer.py # Mock for local testing
│
├── runtime/                # Runtime infrastructure
│   ├── cli.py              # Local development CLI
│   └── server.py           # FastAPI A2A server
│
├── deploy/                 # Deployment config
│   ├── .env.example        # Environment template
│   └── pip.conf            # Artifact Registry config
│
├── scripts/                # Utility scripts
│   └── register_agent.py   # TAP registry registration
│
└── tests/                  # Test suite
```

**Key Simplification:** Developers only need to work with `agent/` (4-5 files). The `tap_wrapper/` directory handles all TAP platform integration automatically.

### Agent Definition

Simple LlmAgent pattern - just define your agent, **no TAP-specific imports needed**:

```python
# agent/agent.py
import os
from google.adk.agents import LlmAgent
from google.genai import types

from .tools import custom_tools
from tap_wrapper.prompts import compose_system_prompt

MODEL = os.environ.get("TAP_MODEL_NAME", "gemini-3-flash-preview")

# Define your agent - mesh tools are injected automatically by tap_wrapper
agent = LlmAgent(
    name="MyAgent",
    model=MODEL,
    instruction=compose_system_prompt(),  # Combines your prompts with TAP boilerplate
    tools=custom_tools,  # Your tools only! Mesh tools added by tap_wrapper
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
    ),
)

__all__ = ["agent"]
```

**Key Point:** You don't import or configure mesh tools - `tap_wrapper` handles that automatically via `build_tap_agent()`.

### Prompt Composition

Your prompts are defined in `agent/prompts.py` with just the developer-specific content:

```python
# agent/prompts.py
AGENT_DESCRIPTION = """
You are a tax specialist that helps users with their tax questions.
"""

AGENT_CAPABILITIES = """  # Optional
- Tax planning and advice
- Tax form guidance
"""

AGENT_INSTRUCTIONS = """  # Optional
1. Always verify the user's tax jurisdiction
2. Recommend professional advice for complex situations
"""
```

The `tap_wrapper.prompts.compose_system_prompt()` automatically combines your content with TAP platform boilerplate (mesh tools documentation, return behavior rules).

### How tap_wrapper Works

The `runtime/server.py` uses tap_wrapper to prepare your agent:

```python
# runtime/server.py (simplified view)
from agent import agent, AgentInputSchema
from tap_wrapper import build_tap_agent, setup_tool_context, get_config

# Load configuration from tap-agent.yaml
config = get_config()

# build_tap_agent() does three things:
# 1. Injects all 12 mesh tools into your agent
# 2. Wraps with InputValidator (collects missing fields from user)
# 3. Sets up tool context for each request
wrapped_agent = build_tap_agent(agent, AgentInputSchema)
```

### Tool Context Setup

The runtime handles context setup automatically. If you need to set it manually (e.g., in tests):

```python
from tap_wrapper import setup_tool_context

setup_tool_context({
    "org_id": "your-org-id",
    "user_id": "your-user-id",
    "session_id": "session-123",
    "trace_id": "trace-abc",
    "equipped_abilities": ["specialist-a", "specialist-b"],
    "oauth_credentials": {"google": {"access_token": "..."}},
})
```

### ADK Agent Types

| Type | Use Case |
|------|----------|
| `LlmAgent` | Single agent with tools (most common) |
| `SequentialAgent` | Multi-step pipeline |
| `ParallelAgent` | Concurrent sub-agents |
| `LoopAgent` | Iterative processing |

### Prompts

TAP supports two prompt formats:

**Simple Format (strings)**
```python
MAIN_PROMPT = """
You are a helpful assistant that...
"""
```

**TAP Format (dict with metadata)**
```python
MAIN_PROMPT = {
    "id": "main_prompt_v1",
    "optimize": True,
    "text": """
You are a helpful assistant that...
"""
}
```

The TAP format enables prompt versioning and optimization.

---

## Input Schemas

### BaseInputSchema

Always inherit from `tap_core.schemas.base.BaseInputSchema`:

```python
# agent/input_schema.py
from tap_core.schemas.base import BaseInputSchema
from pydantic import Field
from typing import Optional
from enum import Enum

class TaskMode(str, Enum):
    SIMPLE = "simple"
    DETAILED = "detailed"

class AgentInputSchema(BaseInputSchema):
    """
    Inherits platform fields:
    - session_id
    - trace_id
    - client_id
    """

    task: str = Field(
        ...,
        description="The main task to perform",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "What would you like help with?",
        }
    )

    mode: TaskMode = Field(
        default=TaskMode.SIMPLE,
        description="Processing mode",
        json_schema_extra={
            "ui_widget": "select",
        }
    )

    detail_level: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Detail level (1-10). Required when mode=detailed.",
        json_schema_extra={
            "ui_widget": "number",
            "show_if": {"mode": "detailed"},
            "required_when": {"mode": "detailed"},
        }
    )

    def to_prompt(self) -> str:
        """Convert structured input to natural language."""
        prompt = f"Task: {self.task}\n"
        prompt += f"Mode: {self.mode.value}\n"
        if self.detail_level:
            prompt += f"Detail Level: {self.detail_level}/10\n"
        return prompt
```

### UI Widget Types

| Widget | Use For |
|--------|---------|
| `text` | Short text input |
| `textarea` | Long text input |
| `number` | Numeric input |
| `select` | Dropdown selection (use with Enum) |
| `hidden` | Internal fields (trace_id, session_id) |
| `date` | Date picker |
| `checkbox` | Boolean toggle |

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

---

## OAuth Credentials

If your agent needs access to third-party APIs (Google Workspace, Salesforce, Slack, etc.), TAP provides a secure credential injection system.

### How It Works

1. **Declare requirements** in your input schema
2. **Gateway checks** if user has connected the app
3. **Credentials injected** into your agent's context
4. **Access in tools** via `get_oauth_credentials()`

### Declaring Credential Requirements

```python
# agent/input_schema.py
from typing import Optional, Dict, Any
from pydantic import Field
from tap_core.schemas.base import BaseInputSchema

class AgentInputSchema(BaseInputSchema):
    task: str = Field(..., description="What task should the agent perform?")

    oauth_credentials: Optional[Dict[str, Any]] = Field(
        default=None,
        description="OAuth tokens provided by TAP platform",
        json_schema_extra={
            "ui_widget": "hidden",
            "platform_provided": True,
        }
    )

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
    google_creds = get_oauth_credentials("google")

    if not google_creds:
        raise MissingCredentialsError(
            service="Google Docs",
            scopes=["https://www.googleapis.com/auth/documents.readonly"]
        )

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
    "expires_at": "2025-01-10T12:00:00Z",
    "scopes": ["scope1", "scope2"],
    "provider_email": "user@example.com"
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

## Mesh Tools

Mesh tools enable platform-wide capabilities. They return **intents** that Gateway executes.

### Available Tools

| Tool | Purpose |
|------|---------|
| `agent_lookup` | Search for specialist agents |
| `transfer_to_agent` | Delegate to another agent |
| `transfer_back_to_parent` | Return to parent agent |
| `ask_clarifying_questions` | Gather user input |
| `ask_user_permission` | Request permission for actions |
| `request_input` | Collect structured input |
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
intent = transfer_to_agent(...)
# Gateway sees intent and:
# 1. Validates authorization
# 2. Routes to target agent
# 3. Returns result to your agent
```

### Local Testing with Mocks

```bash
TAP_USE_MOCK_TRANSFER=true python runtime/cli.py
```

Configure mocks in `tap_wrapper/testing/mock_transfer.py`.

---

## ADK Callbacks

Callbacks hook into agent lifecycle.

### Available Callbacks

```python
# agent/callbacks.py
from google.adk.agents.callback_context import CallbackContext
from typing import Any
import logging

logger = logging.getLogger(__name__)

async def on_agent_start(ctx: CallbackContext) -> None:
    """Before agent execution"""
    logger.info(f"Agent {ctx.agent_name} starting")

async def on_agent_end(ctx: CallbackContext, output: Any) -> None:
    """After agent execution"""
    logger.info(f"Agent completed")

async def on_tool_start(ctx: CallbackContext, tool_name: str, args: dict):
    """Before tool execution - return value to skip execution"""
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
    before_tool_callback=on_tool_start,
    after_tool_callback=on_tool_end,
    ...
)
```

---

## Deployment

SMAs deploy to **Cloud Run** as web servers exposing the A2A protocol endpoints.

> **Note:** SMAs do NOT deploy to Vertex AI Reasoning Engine. Cloud Run is required because SMAs expose multiple HTTP endpoints that Reasoning Engine doesn't support.

### Prerequisites

- GCP project with Cloud Run enabled
- Google Cloud SDK installed and configured
- tap-core package access (Artifact Registry)

### Option 1: Source Deploy (Development)

```bash
gcloud run deploy my-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --timeout 300s \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=your-project,GOOGLE_GENAI_USE_VERTEXAI=true"
```

### Option 2: Cloud Build (Production)

```bash
gcloud builds submit --config cloudbuild.yaml
```

### Option 3: Docker Build + Deploy

```bash
docker build -t my-agent .
docker tag my-agent REGION-docker.pkg.dev/PROJECT/REPO/my-agent:latest
docker push REGION-docker.pkg.dev/PROJECT/REPO/my-agent:latest

gcloud run deploy my-agent \
  --image REGION-docker.pkg.dev/PROJECT/REPO/my-agent:latest \
  --region us-central1 \
  --allow-unauthenticated
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | - | GCP project ID |
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes | `true` | Use Vertex AI API for Gemini |
| `PORT` | No | `8080` | Server port (Cloud Run sets this) |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `TAP_MODEL_NAME` | No | `gemini-3-flash-preview` | Model to use |
| `TAP_SKIP_VALIDATION` | No | `false` | Skip input validation |

### Verify Deployment

```bash
CLOUD_RUN_URL=$(gcloud run services describe my-agent --region us-central1 --format "value(status.url)")

curl $CLOUD_RUN_URL/health
curl $CLOUD_RUN_URL/.well-known/agent.json
curl -X POST $CLOUD_RUN_URL/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"text":"Hello"}},"id":1}'
```

---

## Registration

After deployment, register your agent with the TAP platform.

### Prerequisites

You must be authenticated with a TAP platform account:

```bash
python scripts/register_agent.py --login
```

### Register Agent

All registration fields are **required** to ensure proper billing:

```bash
python scripts/register_agent.py register \
  --cloud-run-url "https://my-agent-xxxxx.run.app" \
  --owner-org-id "your-org-uuid" \
  --owner-user-id "your-user-uuid" \
  --input-cogs 0 \
  --input-margin 10000 \
  --output-cogs 0 \
  --output-margin 12000
```

### Registration Fields

| Field | Description |
|-------|-------------|
| `--cloud-run-url` | Your deployed Cloud Run URL |
| `--owner-org-id` | Your organization UUID |
| `--owner-user-id` | Your user UUID |
| `--input-cogs` | Input COGS per token (nanodollars) |
| `--input-margin` | Input margin per token (nanodollars) |
| `--output-cogs` | Output COGS per token (nanodollars) |
| `--output-margin` | Output margin per token (nanodollars) |
| `--tier` | Discovery tier: `primary`, `secondary`, `tertiary` |

### Test Registration (Dry Run)

```bash
python scripts/register_agent.py register \
  --owner-org-id YOUR_ORG_UUID \
  --owner-user-id YOUR_USER_UUID \
  --input-cogs 0 --input-margin 10000 \
  --output-cogs 0 --output-margin 12000 \
  --dry-run
```

---

## Marketplace Publishing

### Setting Pricing

#### Pricing Strategy Guide

| Strategy | Markup Over Cost | Best For |
|----------|------------------|----------|
| Premium | +50-100% | Specialized expertise, high-value outputs |
| Competitive | +20-50% | Market-rate positioning |
| Penetration | +5-20% | New agent, building user base |

#### Pricing Calculation

```
Your Revenue = Client Bill - Infrastructure Cost - Platform Fee (5%)

Example at $0.004/1k tokens:
- Client pays: $0.004 × tokens
- Platform cost: ~$0.001 × tokens (varies by model)
- Platform fee: 5% of client payment
- Your payout: ~$0.003 × tokens
```

### Capability Description

Write compelling descriptions for semantic discovery:

**Good Example:**
> "Expert Australian tax agent specializing in small business compliance. Handles BAS preparation, GST calculations, quarterly tax estimates, and end-of-year reporting."

**Bad Example:**
> "Tax agent. Does tax stuff."

The description is embedded for semantic search - be specific about:
- Domain expertise
- Specific tasks handled
- Target audience
- Geographic/regulatory scope

### Review Process

1. **Automated Checks**: Schema validation, basic functionality test, security scan
2. **Manual Review** (for featured placement): Quality, accuracy, pricing reasonableness
3. **Approval Timeline**: Automated < 1 hour, Manual 1-3 business days

---

## Pricing & Payouts

### Stripe Connect Integration

1. **Initial Setup**
   - Verify identity (government ID)
   - Link bank account
   - Configure payout schedule

2. **Tax Documentation**
   - Provide W-9 (US) or W-8BEN (international)
   - Set up 1099 reporting preferences

### Payout Schedule

| Balance | Payout Frequency |
|---------|------------------|
| < $50 | Accumulated until threshold |
| $50-$500 | Monthly (1st of month) |
| $500+ | On-demand available |

### Viewing Earnings

```bash
tap-cli earnings balance
tap-cli earnings history --period=30d
tap-cli earnings report --format=csv --year=2025
```

---

## Monitoring & Analytics

### Usage Dashboard

Access at: `https://developers.tailoredagents.ai/dashboard`

**Available Metrics:**
- Invocations (daily/weekly/monthly)
- Token usage
- Revenue breakdown
- User feedback scores
- Error rates

### Revenue Reports

```bash
tap-cli analytics revenue --period=monthly

# Output:
# Agent               | Invocations | Tokens    | Revenue  | Payout
# --------------------|-------------|-----------|----------|--------
# my-specialized-agent| 1,234       | 2,450,000 | $9.80    | $8.82
```

### Error Logs

```bash
tap-cli logs errors --agent=my-agent --period=7d
```

### Feedback Analysis

```bash
tap-cli feedback list --agent=my-agent
tap-cli feedback summary
```

---

## API Contract (A2A Protocol)

SMAs expose standard endpoints for the A2A (Agent-to-Agent) protocol.

### Endpoints Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/.well-known/agent.json` | GET | Agent Card discovery |
| `/` | POST | A2A JSON-RPC 2.0 (sync) |
| `/stream` | POST | A2A JSON-RPC 2.0 (SSE streaming) |
| `/health` | GET | Cloud Run health check |

### 1. Agent Card Discovery

```
GET /.well-known/agent.json
```

**Response (200 OK):**
```json
{
  "name": "my-agent",
  "displayName": "My Agent",
  "description": "Agent description for semantic search",
  "version": "1.0.0",
  "protocolVersion": "1.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "skills": [{
    "id": "main-skill",
    "name": "Main Skill",
    "description": "What this skill does"
  }],
  "inputSchema": { /* JSON Schema from AgentInputSchema */ },
  "provider": {
    "organization": "Your Organization"
  }
}
```

### 2. A2A Sync Endpoint

```
POST /
Content-Type: application/json
```

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {"text": "User message"},
    "org_id": "org-123",
    "user_id": "user-456",
    "session_id": "sess-789",
    "trace_id": "trace-abc"
  },
  "id": "request-1"
}
```

**Success Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "id": "task-abc123",
    "status": "completed",
    "message": "Agent response text",
    "metadata": {
      "input_tokens": 150,
      "output_tokens": 250,
      "agent_slug": "my-agent"
    }
  },
  "id": "request-1"
}
```

**Error Response:**
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32000,
    "message": "Error description"
  },
  "id": "request-1"
}
```

**Error Codes:**

| Code | Meaning |
|------|---------|
| `-32700` | Parse error |
| `-32602` | Invalid params |
| `-32601` | Method not found |
| `-32001` | Missing OAuth credentials |
| `-32000` | Agent execution error |

### 3. A2A Streaming Endpoint

```
POST /stream
Content-Type: application/json
Accept: text/event-stream
```

**SSE Response Stream:**
```
event: connected
data: {"agent_slug":"my-agent"}

event: working
data: {"status":"processing"}

event: tool_call
data: {"tool_name":"search","args":{},"status":"calling"}

event: tool_result
data: {"tool_name":"search","result":{},"status":"completed"}

data: {"text":"Partial response...","partial":true}

event: done
data: {"input_tokens":150,"output_tokens":250,"text":"Full response","is_final":true}
```

**SSE Event Types:**

| Event | Purpose |
|-------|---------|
| `connected` | Connection established |
| `working` | Processing started |
| `agent_step` | Sub-agent started |
| `tool_call` | Tool being invoked |
| `tool_result` | Tool completed |
| `thinking` | Model reasoning |
| `token_update` | Intermediate token counts |
| `data` (default) | Streaming text chunk |
| `done` | Final completion with totals |
| `error` | Error occurred |

### 4. Health Check

```
GET /health
```

**Response (200 OK):**
```json
{
  "status": "healthy",
  "agent": "my-agent",
  "version": "1.0.0"
}
```

### Context Injection

Gateway injects context into requests:

| Field | Source | Purpose |
|-------|--------|---------|
| `org_id` | Gateway auth | Multi-tenancy |
| `user_id` | Gateway auth | User identification |
| `session_id` | Gateway | Conversation continuity |
| `trace_id` | Gateway | Distributed tracing |
| `oauth_credentials` | Gateway | Third-party API access |
| `equipped_abilities` | Gateway | Available specialist agents |
| `delegation_context` | Gateway | If delegated from another agent |

### Token Billing

**Important:** Every response MUST include token counts:

```json
"metadata": {
  "input_tokens": 150,
  "output_tokens": 250
}
```

Missing token counts will result in billing failures.

---

## Security Best Practices

### 1. SSRF Protection

Validate URLs before fetching:

```python
from urllib.parse import urlparse

def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    blocked = ['localhost', '127.0.0.1', '169.254.169.254']
    return parsed.hostname not in blocked
```

### 2. Rate Limiting

```python
from functools import wraps
import time

def rate_limit(max_calls: int, period: int):
    calls = []
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            calls[:] = [c for c in calls if now - c < period]
            if len(calls) >= max_calls:
                raise Exception("Rate limit exceeded")
            calls.append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator
```

### 3. Input Validation

```python
def process_data(data: str, max_size: int = 1_000_000) -> str:
    if len(data) > max_size:
        raise ValueError(f"Data exceeds maximum size of {max_size}")
    # Process...
```

### 4. Error Handling

Don't expose internal details:

```python
def my_tool(input: str) -> str:
    try:
        result = risky_operation(input)
        return json.dumps({"status": "success", "data": result})
    except SpecificError as e:
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return json.dumps({"status": "error", "message": "Internal error"})
```

---

## Troubleshooting

### Common Errors

**ModuleNotFoundError: No module named 'tap_core'**
```bash
pip config set global.extra-index-url \
  "https://australia-southeast1-python.pkg.dev/tailored-agents-aaas-platform/tap-python-packages/simple/"
pip install tap-core
```

**Tool context not set**
```python
from tap_wrapper import setup_tool_context
setup_tool_context(gateway_context)
```

**Cloud Run deployment fails with permission error**
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="user:YOUR_EMAIL" \
  --role="roles/run.admin"
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="user:YOUR_EMAIL" \
  --role="roles/iam.serviceAccountUser"
```

**Registration fails with billing fields error**
```bash
# All 6 registration fields are required:
python scripts/register_agent.py register \
  --owner-org-id YOUR_ORG_UUID \
  --owner-user-id YOUR_USER_UUID \
  --input-cogs 0 --input-margin 10000 \
  --output-cogs 0 --output-margin 12000
```

**Skill ID validation error**
```python
# Skill IDs must be kebab-case
"id": "software-research"   # CORRECT
"id": "software_research"   # WRONG
```

### Debug Logging

```bash
LOG_LEVEL=DEBUG python runtime/cli.py
```

### Testing A2A Protocol

```bash
python runtime/server.py

curl http://localhost:8080/.well-known/agent.json
curl http://localhost:8080/health

curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"text":"Hello"}},"id":1}'

curl -X POST http://localhost:8080/stream \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"text":"Hello"}},"id":1}'
```

---

## CLI Reference

### Authentication

```bash
python scripts/register_agent.py --login   # Interactive login
python scripts/register_agent.py --logout  # Clear credentials
```

### Registration Commands

```bash
python scripts/register_agent.py register --help   # Show options
python scripts/register_agent.py update --help     # Update existing
python scripts/register_agent.py status            # Check registration
```

### TAP CLI (tap-cli)

```bash
# Account
tap-cli auth login
tap-cli auth status

# Agents
tap-cli agents list
tap-cli agents create --template=basic
tap-cli agents pricing update <slug> --per-1k-tokens=0.004

# Analytics
tap-cli analytics usage --period=30d
tap-cli analytics revenue --period=monthly
tap-cli feedback summary

# Earnings
tap-cli earnings balance
tap-cli earnings history
tap-cli earnings payout-request
```

### Environment Variables

```bash
export TAP_DEVELOPER_ID="dev-xxx"
export TAP_API_KEY="tap_xxx"
export GOOGLE_CLOUD_PROJECT="your-project"
export GOOGLE_CLOUD_REGION="us-central1"
```

---

## Support Resources

- **Technical Issues**: support@tailoredagents.ai
- **Payout Questions**: billing@tailoredagents.ai
- **Partnership Inquiries**: partners@tailoredagents.ai
- **Developer Discord**: discord.gg/tap-developers
- **Monthly Developer Call**: First Tuesday, 10am AEST

---

## Next Steps

1. **Clone the template**: `cp -r tap_template_agent/ my_agent/`
2. **Build your agent logic** in `agent/`
3. **Test locally** with `python runtime/cli.py`
4. **Deploy** with `gcloud run deploy my-agent --source .`
5. **Register** with TAP: `python scripts/register_agent.py register`
