"""
TAP Template Agent - Agent Definition

This file defines your agent using Google ADK. The template uses a simple
LlmAgent pattern that works for most use cases.

For more complex workflows, see the ADK documentation:
- SequentialAgent: Multi-step pipelines
- ParallelAgent: Concurrent sub-agents
- LoopAgent: Iterative processing

TODO: Customize the agent for your use case.
"""

import os
from typing import List, Callable

from google.adk.agents import LlmAgent
from google.genai import types

# TAP Core imports for mesh tools
from tap_core.tools import get_all_tools, set_tool_context, MESH_TOOLS

# Local imports
from .prompts import SYSTEM_PROMPT
from .input_schema import AgentInputSchema
from .callbacks import on_agent_start, on_agent_end

# Import custom tools
from .tools import custom_tools


# =============================================================================
# CONFIGURATION
# =============================================================================

# Agent name - used for registration and routing (URL-safe, lowercase)
AGENT_NAME = "my-agent"  # TODO: Change to your agent's unique slug

# Model - can be overridden via environment variable
# Available models: gemini-3-flash-preview (fast), gemini-3-pro-preview (reasoning)
MODEL_NAME = os.environ.get("TAP_MODEL_NAME", "gemini-3-flash-preview")

# Agent description for discovery
BASE_DESCRIPTION = """
A TAP-compatible template agent that demonstrates platform integration.

TODO: Replace this with your agent's actual description. This text is used
for semantic search when other agents look for capabilities to delegate to.
"""


# =============================================================================
# MESH TOOLS SETUP
# =============================================================================

def get_mesh_tools() -> List[Callable]:
    """
    Get TAP mesh tools for platform integration.

    Mesh tools enable your agent to:
    - agent_lookup: Search for specialist agents
    - transfer_to_agent: Delegate to another agent
    - ask_clarifying_questions: Gather user input
    - set_complete: Signal task completion
    - notify_user: Send progress updates

    Returns:
        List of mesh tool functions
    """
    try:
        # Returns all registered mesh tools
        return get_all_tools()
    except ImportError:
        # tap_core not available (local development without package)
        return []


# =============================================================================
# AGENT DEFINITION
# =============================================================================

# Combine mesh tools with custom tools
all_tools = [
    *get_mesh_tools(),  # Platform-wide mesh tools
    *custom_tools,       # Your agent-specific tools
]

# Create the agent
root_agent = LlmAgent(
    name="MyAgent",  # Internal name (can differ from AGENT_NAME slug)
    model=MODEL_NAME,
    description=BASE_DESCRIPTION.strip(),
    instruction=SYSTEM_PROMPT["content"],
    tools=all_tools,

    # Generation configuration
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,  # Adjust for your use case (0.0-1.0)
        # max_output_tokens=1000,  # Uncomment to limit output length
    ),

    # ADK callbacks for lifecycle hooks
    before_agent_callback=on_agent_start,
    after_agent_callback=on_agent_end,

    # Disable transfers for simple agents (enable for multi-agent systems)
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)


# =============================================================================
# TAP PLATFORM EXPORTS
# =============================================================================

# Required export for TAP runtime
AGENT_RUNNABLE = root_agent

# Metadata for TAP registration
AGENT_METADATA = {
    "name": AGENT_NAME,
    "description": BASE_DESCRIPTION.strip(),
    "model": MODEL_NAME,
    "input_schema": AgentInputSchema.model_json_schema(),
    "version": "1.0.0",
}


# =============================================================================
# CONTEXT SETUP (Call before execution)
# =============================================================================

def setup_tool_context(gateway_context: dict) -> None:
    """
    Set up tool context from Gateway-provided context.

    This MUST be called before agent execution to enable mesh tools
    to access org/user/session information.

    Args:
        gateway_context: Context dict from Gateway containing:
            - org_id: Organization ID
            - user_id: User ID
            - session_id: Session ID
            - trace_id: Distributed trace ID
    """
    set_tool_context(
        org_id=gateway_context.get("org_id", ""),
        user_id=gateway_context.get("user_id", ""),
        session_id=gateway_context.get("session_id", ""),
        trace_id=gateway_context.get("trace_id", ""),
        equipped_slugs=gateway_context.get("equipped_abilities", []),
    )


__all__ = [
    # Agent
    "root_agent",
    "AGENT_RUNNABLE",
    "AGENT_NAME",
    "AGENT_METADATA",
    "BASE_DESCRIPTION",
    "MODEL_NAME",
    # Setup
    "setup_tool_context",
    "get_mesh_tools",
]
