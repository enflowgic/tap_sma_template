"""
TAP Template Agent - ADK Callbacks

This file demonstrates ADK callback patterns for lifecycle hooks.
Callbacks let you run code at key points in agent execution:

- before_agent_callback: Before agent starts processing
- after_agent_callback: After agent completes
- before_model_callback: Before LLM call
- after_model_callback: After LLM response
- before_tool_callback: Before tool execution
- after_tool_callback: After tool returns

Use cases:
- Logging and monitoring
- Input/output validation
- State management
- Security guardrails
- Metrics collection

TODO: Customize callbacks for your agent's needs.
"""

import logging
import time
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext

# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# AGENT LIFECYCLE CALLBACKS
# =============================================================================

async def on_agent_start(ctx: CallbackContext) -> None:
    """
    Called before agent execution starts.

    Use for:
    - Logging invocation start
    - Setting up context
    - Validating inputs
    - Recording metrics

    Args:
        ctx: Callback context with session and state access
    """
    agent_name = getattr(ctx, 'agent_name', 'unknown')
    invocation_id = getattr(ctx, 'invocation_id', 'unknown')

    logger.info(
        f"Agent starting",
        extra={
            "agent_name": agent_name,
            "invocation_id": invocation_id,
        }
    )

    # Store start time for duration calculation
    ctx.state["_start_time"] = time.time()


async def on_agent_end(ctx: CallbackContext, output: Any) -> None:
    """
    Called after agent execution completes.

    Use for:
    - Logging completion
    - Calculating duration
    - Recording metrics
    - Cleanup

    Args:
        ctx: Callback context
        output: Agent's output
    """
    agent_name = getattr(ctx, 'agent_name', 'unknown')
    invocation_id = getattr(ctx, 'invocation_id', 'unknown')

    # Calculate duration
    start_time = ctx.state.get("_start_time")
    duration_ms = (time.time() - start_time) * 1000 if start_time else 0

    logger.info(
        f"Agent completed",
        extra={
            "agent_name": agent_name,
            "invocation_id": invocation_id,
            "duration_ms": duration_ms,
        }
    )


# =============================================================================
# TOOL CALLBACKS (Optional - for auditing/validation)
# =============================================================================

async def on_tool_start(
    ctx: CallbackContext,
    tool_name: str,
    args: dict,
) -> Optional[Any]:
    """
    Called before tool execution.

    Use for:
    - Audit logging
    - Input validation
    - Security checks
    - Caching (return cached result to skip execution)

    Args:
        ctx: Callback context
        tool_name: Name of the tool being called
        args: Arguments passed to the tool

    Returns:
        None to continue execution, or a value to skip execution
    """
    logger.debug(f"Tool call: {tool_name}", extra={"args": args})

    # Example: Block dangerous operations
    # if tool_name == "delete_file" and not ctx.state.get("deletion_approved"):
    #     return {"error": "Deletion not approved"}

    return None  # Continue with normal execution


async def on_tool_end(
    ctx: CallbackContext,
    tool_name: str,
    result: Any,
) -> None:
    """
    Called after tool execution.

    Use for:
    - Result logging
    - Caching results
    - State updates
    - Metrics

    Args:
        ctx: Callback context
        tool_name: Name of the tool that was called
        result: Result returned by the tool
    """
    logger.debug(f"Tool result: {tool_name}", extra={"result_type": type(result).__name__})


# =============================================================================
# MODEL CALLBACKS (Optional - for advanced use cases)
# =============================================================================

async def on_model_request(ctx: CallbackContext, request: Any) -> Optional[Any]:
    """
    Called before LLM request.

    Use for:
    - Request modification
    - Prompt injection
    - Guardrails

    Args:
        ctx: Callback context
        request: LLM request

    Returns:
        None to continue, or modified request
    """
    return None


async def on_model_response(ctx: CallbackContext, response: Any) -> None:
    """
    Called after LLM response.

    Use for:
    - Response validation
    - Content filtering
    - Metrics

    Args:
        ctx: Callback context
        response: LLM response
    """
    pass


__all__ = [
    "on_agent_start",
    "on_agent_end",
    "on_tool_start",
    "on_tool_end",
    "on_model_request",
    "on_model_response",
]
