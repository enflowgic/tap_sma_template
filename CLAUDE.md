# TAP SMA Template - AI Assistant Instructions

## Session Startup (REQUIRED)

**On EVERY session start, load these skills for context:**

```
/google-adk
/template-agent
```

These skills provide the Google ADK documentation and TAP platform integration patterns you need.

---

## What You're Building

You are helping a developer build a **Stateless Mesh Agent (SMA)** - a single-purpose AI agent that:

- Runs on **Cloud Run** (serverless container)
- Exposes **A2A protocol** endpoints (JSON-RPC 2.0 + SSE streaming)
- Uses **Google ADK** (Agent Development Kit) for LLM orchestration
- Integrates with **TAP platform** via mesh tools (transfer_to_agent, ask_clarifying_questions, etc.)
- Is **stateless** - all state comes from Gateway, no local persistence

**Architecture:**
```
User Request → Gateway → Your SMA (Cloud Run) → Gemini LLM
                ↑            ↓
           Response ← SSE Stream
```

---

## Repository Structure

```
tap_template_agent/
├── tap-agent.yaml          # Agent manifest - START HERE
├── main.py                 # Cloud Run entry point
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container build
├── cloudbuild.yaml         # CI/CD deployment
│
├── agent/                  # YOUR CODE - Customize these
│   ├── agent.py            # LlmAgent definition (model, tools, config)
│   ├── schemas.py          # Input/output Pydantic schemas
│   ├── prompts.py          # System prompt components
│   ├── callbacks.py        # ADK lifecycle hooks (optional)
│   └── tools/              # Custom tool implementations
│       └── example.py      # Delete when adding real tools
│
├── tap_wrapper/            # PLATFORM CODE - Don't modify
│   ├── __init__.py         # build_tap_agent(), setup_tool_context()
│   ├── config.py           # Parses tap-agent.yaml
│   ├── mesh_integration.py # Injects 14 TAP mesh tools
│   ├── validation.py       # Auto input validation
│   └── prompts.py          # Combines developer + platform prompts
│
├── runtime/                # Server infrastructure
│   ├── server.py           # FastAPI A2A server
│   ├── cli.py              # Local testing CLI
│   └── streaming.py        # SSE event handling
│
├── scripts/                # Utilities
│   └── register_agent.py   # Register with TAP platform
│
├── deploy/                 # Deployment config
│   └── .env.example        # Environment template
│
└── tests/                  # pytest test suite
```

---

## Key Files to Understand

### 1. tap-agent.yaml (Agent Manifest)
Single source of truth for agent metadata, model, schemas, capabilities:

```yaml
metadata:
  slug: my-agent              # URL-safe unique ID
  display_name: My Agent      # Human-readable name
  description: "What I do"

deployment:
  model: gemini-3-flash-preview
  region: us-central1         # ALWAYS us-central1
  runtime: cloud-run
```

### 2. agent/schemas.py (Input/Output Contracts)
Pydantic models that define what your agent accepts and returns:

```python
from tap_core.schemas.base import BaseInputSchema
from pydantic import Field

class AgentInputSchema(BaseInputSchema):
    task: str = Field(
        ...,  # Required field
        description="What to do",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "What would you like help with?",
        }
    )

    def to_prompt(self) -> str:
        return f"Task: {self.task}"
```

### 3. agent/agent.py (LlmAgent Definition)
Where you define the agent using Google ADK:

```python
from google.adk.agents import LlmAgent
from google.genai import types
from tap_wrapper.prompts import compose_system_prompt
from .tools import custom_tools

agent = LlmAgent(
    name="MyAgent",
    model=os.environ.get("TAP_MODEL_NAME", "gemini-3-flash-preview"),
    instruction=compose_system_prompt(),  # Auto-combines with platform prompts
    tools=custom_tools,  # Mesh tools added automatically by tap_wrapper
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=4096,
    ),
)
```

### 4. agent/prompts.py (System Prompt Components)
Define your agent's identity and behavior:

```python
AGENT_DESCRIPTION = """
You are a specialist in X. Your role is to help users accomplish Y.
"""

AGENT_CAPABILITIES = """
- Capability A
- Capability B
"""

AGENT_INSTRUCTIONS = """
1. First, understand the user's request
2. If unclear, use ask_clarifying_questions
3. When done, use transfer_back_to_parent to return results
"""
```

---

## Development Workflow

### Local Testing
```bash
# Configure environment
cp deploy/.env.example deploy/.env
# Edit deploy/.env with your GCP project

# Interactive mode
python runtime/cli.py

# Single query
python runtime/cli.py "Your task here"

# A2A server (for testing with Gateway)
python runtime/server.py
```

### Deployment
```bash
# Via Cloud Build (recommended)
gcloud builds submit --config cloudbuild.yaml

# Direct deploy
gcloud run deploy my-agent --source . --region us-central1
```

### Registration
```bash
python scripts/register_agent.py \
  --cloud-run-url https://my-agent-xxx.run.app \
  --input-cogs 0 --output-cogs 0 \
  --input-margin 1000 --output-margin 1200 \
  --tier tertiary
```

---

## Mesh Tools (Auto-Injected)

Your agent automatically gets these 14 TAP platform tools:

| Tool | Purpose |
|------|---------|
| `agent_lookup` | Search for other agents in registry |
| `transfer_to_agent` | Delegate work to another SMA |
| `transfer_back_to_parent` | **REQUIRED** - Return results to caller |
| `ask_clarifying_questions` | Gather more info via inline Q&A |
| `ask_user_permission` | Request approval for sensitive actions |
| `request_input` | Collect structured data via modal form |
| `request_agent_approval` | Request approval for tertiary agents |
| `calculate_one_time_price` | Get guaranteed price quote |
| `search_knowledge` | Query org knowledge base (policies, docs, memory) |
| `consult_collective_intelligence` | Search platform-wide problem-solving knowledge |
| `log_unfulfilled_request` | Log gaps for market analysis |
| `set_needs_attention` | Signal user attention needed |
| `set_complete` | Signal completion (Master Agent only!) |
| `notify_user` | Send progress updates |

**CRITICAL**: SMAs must use `transfer_back_to_parent()` to return results, NOT `set_complete()`.

---

## SSE Streaming (Production)

Gateway ONLY uses the streaming endpoint (`/stream`). Your agent must:

1. Emit `connected` event on start
2. Emit `content` events with `partial: true` for response chunks
3. Emit `done` event with final token counts
4. Include heartbeats every 15s during long operations

The `runtime/streaming.py` module handles this automatically.

---

## Important Rules

### DO:
- Use `Field(...)` for required input fields
- Include `to_prompt()` method in input schema
- Use `transfer_back_to_parent()` when done
- Test streaming locally before deploying
- Set region to `us-central1` always

### DON'T:
- Modify `tap_wrapper/` files - they handle platform integration
- Use `set_complete()` - that's for Master Agent only
- Store state locally - use Session Service via Gateway
- Use HTTP/2 for Cloud Run - breaks SSE streaming
- Deploy to regions other than `us-central1`

---

## Coding Conventions

### Python
- Type hints required for function signatures
- Pydantic models for all request/response schemas
- Use `structlog` for logging
- Async functions for I/O-bound operations

### Tool Definitions
```python
def my_tool(query: str) -> dict:
    """
    Clear description for the LLM.

    Args:
        query: What to search for

    Returns:
        dict with status and results
    """
    return {"status": "success", "data": result}
```

---

## Debugging Tips

### Check Agent Card
```bash
curl http://localhost:8080/.well-known/agent.json | jq
```

### Test Streaming
```bash
curl -N -X POST http://localhost:8080/stream \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"text":"test"}},"id":1}'
```

### Enable Debug Logging
```bash
LOG_LEVEL=DEBUG python runtime/cli.py
```

### Common Issues

| Issue | Solution |
|-------|----------|
| "ModuleNotFoundError: tap_core" | `pip install tap-core --extra-index-url https://australia-southeast1-python.pkg.dev/tailored-agents-aaas-platform/tap-python-packages/simple/` |
| Empty agent_lookup results | Lower `min_similarity` or broaden query |
| SSE disconnects | Add heartbeats, check timeout settings |
| Validation asking too many questions | Use `Field(default=None)` for optional fields |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | No | Region (default: us-central1) |
| `TAP_MODEL_NAME` | No | Model override (default: gemini-3-flash-preview) |
| `TAP_SKIP_VALIDATION` | No | Skip input validation |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

---

## Skills Reference

Load these skills for detailed documentation:

| Skill | When to Use |
|-------|-------------|
| `/google-adk` | ADK Python SDK, agent patterns, tool definitions |
| `/template-agent` | TAP integration, mesh tools, deployment |

---

## Quick Reference Links

- **ADK Docs**: `.claude/skills/google-adk/adk-docs/`
- **ADK SDK**: `.claude/skills/google-adk/adk-python/`
- **Template Guide**: `.claude/skills/template-agent/SKILL.md`
- **tap_core Tools**: `tap_wrapper/mesh_integration.py`
