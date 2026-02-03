"""
TAP Wrapper - Mesh Tools Integration

Handles automatic injection of TAP mesh tools and context setup.
Developers don't need to manage this - TAP handles it automatically.

Mesh Tools (12 total):
- agent_lookup: Search for specialist agents
- transfer_to_agent: Delegate to another agent
- transfer_back_to_parent: Return to parent agent
- ask_clarifying_questions: Gather user input
- ask_user_permission: Request permission for actions
- request_input: Collect structured input
- request_agent_approval: Request tertiary agent approval
- calculate_one_time_price: Get price quote
- log_unfulfilled_request: Log capability gaps
- set_needs_attention: Signal need for user direction
- set_complete: Signal task completion
- notify_user: Send notifications
"""

import logging
from typing import Callable, Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def get_mesh_tools() -> List[Callable]:
    """
    Get all TAP mesh tools.

    These tools enable agent-to-agent communication and platform integration.
    They are automatically injected into every SMA by the TAP wrapper.

    Returns:
        List of mesh tool functions, or empty list if tap_core unavailable
    """
    try:
        from tap_core.tools import get_all_tools
        tools = get_all_tools()
        logger.debug(f"Loaded {len(tools)} mesh tools from tap_core")
        return tools
    except ImportError:
        logger.warning(
            "tap_core not available - mesh tools disabled. "
            "Install tap_core for production deployment."
        )
        return []


def setup_tool_context(gateway_context: Dict[str, Any]) -> None:
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
            - equipped_abilities: List of equipped ability slugs
            - oauth_credentials: Dict of OAuth tokens by app_slug
    """
    try:
        from tap_core.tools import set_tool_context

        set_tool_context(
            org_id=gateway_context.get("org_id", ""),
            user_id=gateway_context.get("user_id", ""),
            session_id=gateway_context.get("session_id", ""),
            trace_id=gateway_context.get("trace_id", ""),
            equipped_slugs=gateway_context.get("equipped_abilities", []),
            oauth_credentials=gateway_context.get("oauth_credentials", {}),
        )
        logger.debug(
            "Tool context configured",
            extra={
                "org_id": gateway_context.get("org_id"),
                "session_id": gateway_context.get("session_id"),
                "trace_id": gateway_context.get("trace_id"),
            }
        )
    except ImportError:
        logger.warning(
            "tap_core not available - tool context not set. "
            "Mesh tools will not work correctly."
        )


def get_oauth_credentials(app_slug: str) -> Optional[Dict[str, Any]]:
    """
    Get OAuth credentials for a specific app from tool context.

    This is a convenience wrapper for accessing credentials injected
    by Gateway.

    Args:
        app_slug: The app slug (e.g., "google", "salesforce")

    Returns:
        Credentials dict with access_token, or None if not available
    """
    try:
        from tap_core.tools import get_tool_context
        ctx = get_tool_context()
        oauth_creds = ctx.get("oauth_credentials", {})
        return oauth_creds.get(app_slug)
    except ImportError:
        logger.warning("tap_core not available - cannot access OAuth credentials")
        return None
    except Exception as e:
        logger.warning(f"Failed to get OAuth credentials for {app_slug}: {e}")
        return None


def inject_mesh_tools(developer_tools: List[Callable]) -> List[Callable]:
    """
    Combine mesh tools with developer's custom tools.

    Mesh tools are prepended so they're available alongside developer tools.

    Args:
        developer_tools: List of developer's custom tool functions

    Returns:
        Combined list: [mesh_tools...] + [developer_tools...]
    """
    mesh_tools = get_mesh_tools()
    return [*mesh_tools, *developer_tools]


__all__ = [
    "get_mesh_tools",
    "setup_tool_context",
    "get_oauth_credentials",
    "inject_mesh_tools",
]
