"""
TAP Template Agent - Agent Definition

This is the ONLY file you need to customize for most agents.
Define your agent using Google ADK patterns - TAP handles the rest.

For complex workflows, see Google ADK documentation:
- SequentialAgent: Multi-step pipelines
- ParallelAgent: Concurrent sub-agents
- LoopAgent: Iterative processing
"""

import os

from google.adk.agents import LlmAgent
from google.genai import types

from .schemas import AgentInputSchema
from .tools import custom_tools
from tap_wrapper import get_config
from tap_wrapper.prompts import compose_system_prompt


# =============================================================================
# AGENT CONFIGURATION
# =============================================================================

# Get config from tap-agent.yaml - the single source of truth
_config = get_config()

# Model - tap-agent.yaml is the source of truth, but can be overridden via env var
MODEL = os.environ.get("TAP_MODEL_NAME", _config.model)


# =============================================================================
# AGENT DEFINITION
# =============================================================================

agent = LlmAgent(
    name="MyAgent",  # Internal name (display name comes from tap-agent.yaml)
    model=MODEL,
    instruction=compose_system_prompt(),  # Combines your prompts with TAP platform boilerplate
    tools=custom_tools,  # Your tools only - mesh tools injected by TAP wrapper

    # Adjust temperature for your use case (0.0 = deterministic, 1.0 = creative)
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
    ),

    # Enable SMA mesh patterns (leave these as True for most agents)
    disallow_transfer_to_parent=False,
    disallow_transfer_to_peers=False,
)


# =============================================================================
# EXPORTS (used by tap_wrapper)
# =============================================================================

__all__ = ["agent", "AgentInputSchema"]
