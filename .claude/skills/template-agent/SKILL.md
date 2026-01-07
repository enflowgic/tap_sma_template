---
name: template-agent
description: TAP Template Agent comprehensive guide. Use when building TAP-compatible Stateless Mesh Agents (SMAs), working with Google ADK, implementing mesh tools, or debugging agent deployment issues. Covers agent definition patterns, input schemas, A2A protocol, and deployment to Vertex AI or Cloud Run.
globs:
  - tap_template_agent/**
  - SMAs/**/agent/**
---

# TAP Template Agent

> **Version**: 1.0.0 | **Framework**: Google ADK + FastAPI | **Updated**: January 2026

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

### What Template Agent DOES NOT Do:

1. **Does NOT implement business logic** - That's your job as the developer
2. **Does NOT connect to production backends** - Uses mocks for local testing
3. **Does NOT handle authentication** - Gateway handles auth before calling SMAs
4. **Does NOT implement billing directly** - tap_core intents + Gateway handle billing
5. **Does NOT persist state** - Stateless design; Session Service stores state
6. **Does NOT call LLMs directly in platform** - Gateway routes to SMAs that call LLMs

> **Key Principle:** The template provides structure and patterns. You add the domain-specific logic.

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
├── README.md                   # Quick start guide
├── DEVELOPMENT.md              # Detailed development documentation
├── Dockerfile                  # Cloud Run container build
├── register_agent.py           # TAP registry registration script
│
├── agent/                      # Your agent code
│   ├── __init__.py             # Package exports
│   ├── definition.py           # LlmAgent definition (CORE)
│   ├── input_schema.py         # Input contract with UI widgets (REQUIRED)
│   ├── output_schema.py        # Output contract (recommended)
│   ├── agent_card.py           # A2A Agent Card metadata
│   ├── prompts.py              # System prompts
│   ├── callbacks.py            # ADK lifecycle hooks
│   └── tools/                  # Custom tools directory
│       ├── __init__.py
│       ├── custom_tools.py     # Your business tools
│       ├── mesh_demo.py        # Mesh tools documentation/examples
│       └── transfer_mock.py    # Mock for local testing
│
├── runtime/                    # Runtime infrastructure
│   ├── __init__.py
│   ├── main.py                 # Local development CLI
│   ├── server.py               # FastAPI A2A server
│   ├── deploy_vertex.py        # Vertex AI deployment script
│   ├── requirements.txt        # Python dependencies
│   ├── pip.conf                # Artifact Registry config
│   └── .env.example            # Environment template
│
└── .github/workflows/
    └── tap-onboarding.yaml     # CI/CD workflow
```

---

## Agent Definition Patterns

### Core Pattern: LlmAgent with Mesh Tools

```python
# agent/definition.py
from google.adk.agents import LlmAgent
from google.genai import types
from tap_core.tools import get_all_tools, set_tool_context

from .prompts import SYSTEM_PROMPT
from .callbacks import on_agent_start, on_agent_end
from .tools import custom_tools

MODEL_NAME = os.environ.get("TAP_MODEL_NAME", "gemini-3-flash-preview")

def get_mesh_tools():
    """Get TAP mesh tools."""
    try:
        return get_all_tools()
    except ImportError:
        return []

root_agent = LlmAgent(
    name="MyAgent",
    model=MODEL_NAME,
    instruction=SYSTEM_PROMPT["content"],
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
from agent.definition import setup_tool_context

# In main.py or server.py, before running agent:
setup_tool_context({
    "org_id": gateway_context.get("org_id"),
    "user_id": gateway_context.get("user_id"),
    "session_id": gateway_context.get("session_id"),
    "trace_id": gateway_context.get("trace_id"),
    "equipped_abilities": gateway_context.get("equipped_abilities", []),
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
# agent/input_schema.py
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

## Mesh Tools Usage

### Available Mesh Tools (9 total)

| Tool | Intent Type | Purpose |
|------|-------------|---------|
| `agent_lookup` | TOOL_CALL | Search tiered agent registry |
| `transfer_to_agent` | TRANSFER_TO_AGENT | Delegate to specialist agent |
| `ask_clarifying_questions` | INPUT_REQUIRED | Gather additional user input |
| `request_agent_approval` | APPROVAL_REQUIRED | Request approval for tertiary agents |
| `log_unfulfilled_request` | TOOL_CALL | Log market gaps for analysis |
| `set_needs_attention` | STATUS_UPDATE | Signal user attention needed |
| `set_complete` | TASK_COMPLETION | Signal task completion |
| `notify_user` | NOTIFICATION | Send progress updates |
| `request_pricing_quote` | PRICING_REQUIRED | Get pricing before execution |

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

#### 4. Signal Completion

```python
from tap_core.tools import set_complete

set_complete(
    summary="Successfully prepared tax filing summary",
    metadata={
        "estimated_refund": 1250,
        "forms_completed": ["1040", "W-2"],
    }
)
```

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

# Test JSON-RPC endpoint
curl -X POST http://localhost:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {"text": "Hello!"}
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

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | - | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Yes | us-central1 | GCP region |
| `TAP_MODEL_NAME` | No | gemini-3-flash-preview | Model override |
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
├── agent/definition.py           # CORE: Agent definition
├── agent/input_schema.py         # REQUIRED: Input contract
├── agent/output_schema.py        # Output contract
├── agent/callbacks.py            # ADK lifecycle hooks
├── agent/prompts.py              # System prompts
├── agent/agent_card.py           # A2A metadata
├── agent/tools/custom_tools.py   # Custom tools
├── agent/tools/mesh_demo.py      # Mesh tools examples
├── agent/tools/transfer_mock.py  # Mock for testing
├── runtime/main.py               # Local CLI
├── runtime/server.py             # A2A server
├── runtime/deploy_vertex.py      # Vertex deployment
└── tap-agent.yaml                # REQUIRED: Manifest
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
   ```

### Best Practices

1. **Keep agents focused** - One domain/capability per SMA
2. **Use mesh tools** - Delegate to specialists via transfer_to_agent
3. **Handle errors gracefully** - Use try/except and meaningful error messages
4. **Log appropriately** - Use structured logging for debugging
5. **Test with mocks** - Use TAP_USE_MOCK_TRANSFER for local testing
6. **Document your agent** - Update description in tap-agent.yaml
