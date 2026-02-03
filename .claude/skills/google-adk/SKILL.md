---
name: google-adk
description: Agent Development Kit from Google - Python SDK and documentation for building AI agents.
globs:
  - agent/**
  - tap_wrapper/**
  - runtime/**
---

# Google ADK (Agent Development Kit)

> **Version**: Based on ADK 1.x | **Updated**: February 2026

---

## Quick Links

| Resource | Location |
|----------|----------|
| **ADK Python SDK** | `.claude/skills/google-adk/adk-python/` |
| **ADK Documentation** | `.claude/skills/google-adk/adk-docs/` |
| **Official Docs** | https://google.github.io/adk-docs/ |
| **PyPI Package** | https://pypi.org/project/google-adk/ |

---

## Overview

Google's Agent Development Kit (ADK) is a Python framework for building AI agents with:

- **LlmAgent** - Single agent with tools
- **SequentialAgent** - Multi-step pipelines
- **ParallelAgent** - Concurrent sub-agents
- **LoopAgent** - Iterative processing

## Key Files in adk-python/

```
adk-python/
├── src/google/adk/
│   ├── agents/              # Agent base classes
│   │   ├── llm_agent.py     # LlmAgent implementation
│   │   ├── sequential_agent.py
│   │   ├── parallel_agent.py
│   │   └── loop_agent.py
│   ├── tools/               # Tool definitions
│   ├── runners/             # Agent execution runners
│   └── sessions/            # Session management
├── tests/                   # Test examples
└── examples/                # Usage examples
```

## Key Files in adk-docs/

```
adk-docs/
├── docs/
│   ├── get-started/         # Quick start guides
│   ├── agents/              # Agent patterns
│   ├── tools/               # Tool documentation
│   ├── callbacks/           # Lifecycle hooks
│   └── deployment/          # Vertex AI deployment
└── examples/
    └── python/              # Working code samples
```

## Basic Usage

```python
from google.adk.agents import LlmAgent
from google.genai import types

agent = LlmAgent(
    name="MyAgent",
    model="gemini-3-flash-preview",
    instruction="You are a helpful assistant.",
    tools=[my_tool],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=4096,
    ),
)
```

## Agent Types

| Type | Use Case |
|------|----------|
| `LlmAgent` | Single agent with tools (most common) |
| `SequentialAgent` | Multi-step pipelines |
| `ParallelAgent` | Concurrent processing |
| `LoopAgent` | Iterative refinement |

## Tool Definition

```python
from google.adk.tools import FunctionTool

def my_tool(query: str) -> str:
    """Tool description for the LLM."""
    return f"Result for {query}"

# Wrap as ADK tool
tool = FunctionTool(func=my_tool)
```

## Callbacks

```python
from google.adk.agents.callback_context import CallbackContext

async def on_agent_start(ctx: CallbackContext) -> None:
    print(f"Agent {ctx.agent_name} starting")

async def on_agent_end(ctx: CallbackContext, output) -> None:
    print(f"Agent completed")
```

## Related Resources

- **TAP Template Agent**: See `/template-agent` skill for TAP-specific integration
- **Cognitive Patterns**: See `.claude/skills/template-agent/AI_Cognitive_Design_Patterns.md`
