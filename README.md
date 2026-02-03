# TAP Template Agent

A canonical template for building TAP-compatible Stateless Mesh Agents (SMAs).

## ⚠️ Streaming-Only Architecture

> **Platform Design**: TAP Gateway is designed to use **only streaming** (`POST /stream`) for SMA invocation.
>
> The sync endpoint (`POST /`) exists for local CLI testing but is not used by Gateway.
> Always verify your `/stream` endpoint works correctly before deployment.

## 🔴 CRITICAL: HTTP/1.1 Only - No HTTP/2

> **DO NOT enable HTTP/2 for SSE streaming agents!**
>
> Cloud Run's `--use-http2` flag causes "protocol error" connection resets with Uvicorn.
> SSE streaming requires HTTP/1.1 (the default).
>
> ```bash
> # WRONG - Will break streaming
> gcloud run deploy --use-http2  # ❌ NEVER use this
>
> # CORRECT - Uses HTTP/1.1 (default)
> gcloud run deploy my-agent --source .  # ✅
> ```

## Configuration Strategy

TAP Template Agent uses a **layered configuration** approach:

| Source | Priority | Purpose |
|--------|----------|---------|
| Environment variables | Highest | Runtime overrides, secrets |
| `tap-agent.yaml` | Default | Agent metadata, default settings |

**Key environment overrides:**
- `TAP_MODEL_NAME` - Override AI model
- `TAP_OWNER_ORG_ID` / `TAP_OWNER_USER_ID` - Billing ownership
- `TAP_INPUT_*_NANODOLLARS` / `TAP_OUTPUT_*_NANODOLLARS` - Token pricing

See `deploy/.env.example` for all available settings.

## Quick Start

### 1. Copy and Rename

```bash
# Copy template
cp -r tap_template_agent/ my-agent/
cd my-agent/

# Rename packages
mv agent/ my_agent_name/
# Update imports in all files
```

### 2. Configure Your Agent

Update `tap-agent.yaml`:
```yaml
metadata:
  slug: my-agent-name        # URL-safe, unique
  display_name: My Agent     # Human-readable
  model: gemini-3-flash-preview
```

### 3. Implement Your Logic

| File | Purpose |
|------|---------|
| `agent/agent.py` | Agent definition (LlmAgent) |
| `agent/schemas.py` | Input/output contracts |
| `agent/prompts.py` | System prompts |
| `agent/tools/` | Custom tools directory |

**That's it!** Just 4 locations to customize. All TAP integration is handled automatically by `tap_wrapper/`.

### 4. Test Locally

```bash
# Set up environment
cp deploy/.env.example deploy/.env
# Edit deploy/.env with your GCP project and billing settings

# Source environment and run
source deploy/.env  # Or: set -a; source deploy/.env; set +a (exports all)
python runtime/cli.py              # Interactive mode
python runtime/cli.py "Hello!"     # Single query
python runtime/server.py           # A2A server
```

### 5. Deploy

SMAs deploy to **Cloud Run** (not Vertex AI Reasoning Engine) because they expose A2A protocol endpoints.

```bash
# Quick deploy (development)
gcloud run deploy my-agent --source . --region us-central1 --allow-unauthenticated

# Production deploy (via Cloud Build)
gcloud builds submit --config cloudbuild.yaml

# Local development server
python runtime/server.py
```

### 6. Register with TAP

After deploying to Cloud Run, register your agent with the TAP platform:

```bash
# Option 1: Using environment variables (recommended)
source deploy/.env
python scripts/register_agent.py --cloud-run-url https://my-agent-xxx.run.app

# Option 2: Using CLI arguments
python scripts/register_agent.py \
  --cloud-run-url https://my-agent-xxx.run.app \
  --owner-org-id <your-org-uuid> \
  --owner-user-id <your-user-uuid> \
  --input-cogs 0 \
  --input-margin 10000 \
  --output-cogs 0 \
  --output-margin 12000 \
  --tier tertiary

# Preview without registering
python scripts/register_agent.py --cloud-run-url ... --dry-run
```

**Billing fields are required.** All pricing is in **nanodollars per token** (1B nanodollars = $1).

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for detailed deployment instructions.

## Directory Structure

```
tap_template_agent/
├── tap-agent.yaml          # Agent manifest (REQUIRED)
├── Dockerfile              # Cloud Run container
├── cloudbuild.yaml         # Cloud Build config
├── requirements.txt        # Dependencies
├── main.py                 # A2A server entry
│
├── agent/                  # YOUR CODE
│   ├── agent.py            # LlmAgent definition ← Your main file
│   ├── schemas.py          # Input/output contracts
│   ├── prompts.py          # System prompts
│   ├── callbacks.py        # ADK hooks (optional)
│   └── tools/              # Custom tools directory
│       ├── __init__.py     # Exports custom_tools list
│       └── example.py      # Example tool (delete when ready)
│
├── tap_wrapper/            # PLATFORM CODE (don't modify)
│   ├── __init__.py         # build_tap_agent(), setup_tool_context()
│   ├── config.py           # Parses tap-agent.yaml
│   ├── prompts.py          # Platform prompt boilerplate
│   ├── agent_card.py       # Auto-generates A2A agent card
│   ├── validation.py       # Input validation wrapper
│   ├── mesh_integration.py # Mesh tools injection
│   └── testing/            # Mock utilities for local testing
│
├── runtime/                # Runtime infrastructure
│   ├── cli.py              # Local development CLI
│   └── server.py           # FastAPI A2A server
│
├── deploy/                 # Deployment config
├── scripts/                # Registration scripts
├── tests/                  # Test suite
└── docs/                   # Documentation
```

**Key Insight:** You only work with `agent/` (4-5 files). The `tap_wrapper/` handles all TAP integration automatically.

## Key Features

- **Minimal developer burden** - Just 4 files to implement your agent
- **Automatic mesh tools** - 12 tools injected automatically by tap_wrapper
- **Auto-generated A2A card** - Agent card derived from tap-agent.yaml
- **Input validation** - Missing fields collected automatically from users
- **A2A protocol** - Standard agent-to-agent communication
- **Billing integration** - Automatic token counting
- **Mock testing** - Local testing without Gateway

## Documentation

See `docs/DEVELOPMENT.md` for detailed documentation:
- Platform architecture
- tap_wrapper API reference
- Mesh tools usage
- Input schema patterns
- OAuth credentials
- Deployment troubleshooting

## TAP Platform

This template integrates with:
- **Gateway** - Request routing and authorization
- **Master Agent** - Agent orchestration
- **Cognee Registry** - Agent discovery and LTM
- **Session Service** - Conversation history
- **Billing Service** - Usage tracking
