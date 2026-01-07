# TAP Template Agent

A canonical template for building TAP-compatible Stateless Mesh Agents (SMAs).

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
| `agent/definition.py` | Agent definition (LlmAgent) |
| `agent/input_schema.py` | Input contract |
| `agent/prompts.py` | System prompts |
| `agent/tools/custom_tools.py` | Custom tools |

### 4. Test Locally

```bash
cd runtime/
cp .env.example .env
# Edit .env with your GCP project

python main.py              # Interactive mode
python main.py "Hello!"     # Single query
python server.py            # A2A server
```

### 5. Deploy

Contact Jamie at jamie@tailoredagents.ai with a link to your public repo and he will deploy it on the mesh and register it with your account.


## Directory Structure

```
tap_template_agent/
├── tap-agent.yaml          # Agent manifest
├── agent/                  # Your agent code
│   ├── definition.py       # Agent definition
│   ├── input_schema.py     # Input contract
│   ├── output_schema.py    # Output contract
│   ├── agent_card.py       # A2A metadata
│   ├── prompts.py          # System prompts
│   ├── callbacks.py        # ADK callbacks
│   └── tools/              # Custom tools
└── runtime/                # Runtime infrastructure
    ├── main.py             # Local dev CLI
    ├── server.py           # FastAPI A2A server
    ├── deploy_vertex.py    # Vertex AI deployment
    └── requirements.txt    # Dependencies
```

## Key Features

- **Simple LlmAgent pattern** - Easy to understand and customize
- **TAP mesh tools** - agent_lookup, transfer_to_agent, ask_clarifying_questions
- **A2A protocol** - Standard agent-to-agent communication
- **Billing integration** - Automatic token counting
- **Mock testing** - Local testing without Gateway

## Documentation

See `DEVELOPMENT.md` for detailed documentation:
- Platform architecture
- Mesh tools usage
- Input schema patterns
- Deployment troubleshooting

## TAP Platform

This template integrates with:
- **Gateway** - Request routing and authorization
- **Master Agent** - Agent orchestration
- **Cognee Registry** - Agent discovery
- **Billing Service** - Usage tracking
- **Prompt Library** - Prompt management
