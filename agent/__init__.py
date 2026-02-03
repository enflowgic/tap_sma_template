"""
TAP Template Agent - Your Agent Code

This package contains your agent implementation.

Files you'll work with:
- agent.py    - Your LlmAgent definition
- tools/      - Your custom tools (directory)
- schemas.py  - Input/output contracts
- prompts.py  - Agent description & instructions

TAP platform integration (mesh tools, validation, A2A) is handled
automatically by tap_wrapper/ - you don't need to modify that code.
"""

from .agent import agent
from .schemas import AgentInputSchema, AgentOutputSchema
from .tools import custom_tools

# Developer-defined prompts
from .prompts import AGENT_DESCRIPTION, AGENT_CAPABILITIES, AGENT_INSTRUCTIONS

# Composed prompts (backward compatible) - from tap_wrapper
from tap_wrapper.prompts import get_system_prompt_dict as _get_system_prompt_dict
from tap_wrapper.prompts import get_prompts as _get_prompts

SYSTEM_PROMPT = _get_system_prompt_dict()
PROMPTS = _get_prompts()


# Main exports for tap_wrapper and runtime
__all__ = [
    # Your agent
    "agent",

    # Schemas
    "AgentInputSchema",
    "AgentOutputSchema",

    # Tools (for reference)
    "custom_tools",

    # Developer prompts (for customization)
    "AGENT_DESCRIPTION",
    "AGENT_CAPABILITIES",
    "AGENT_INSTRUCTIONS",

    # Composed prompts (backward compatible)
    "SYSTEM_PROMPT",
    "PROMPTS",
]
