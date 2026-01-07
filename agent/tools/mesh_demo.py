"""
TAP Template Agent - Mesh Tools Demo

This file demonstrates how to use TAP mesh tools in your agent.
Mesh tools enable platform-wide capabilities like:

- agent_lookup: Search for specialist agents
- transfer_to_agent: Delegate to another agent
- ask_clarifying_questions: Gather user input
- request_agent_approval: Request approval for non-entitled agents
- set_needs_attention: Signal user attention needed
- set_complete: Signal task completion
- notify_user: Send progress updates

IMPORTANT: Mesh tools return INTENTS, not actual results.
The intent is returned to Gateway which handles execution.

This file is for DOCUMENTATION and EXAMPLES only.
The actual mesh tools are imported from tap_core.tools.
"""

# =============================================================================
# IMPORTING MESH TOOLS
# =============================================================================

# To use mesh tools in your agent, import from tap_core:
#
# from tap_core.tools import (
#     get_all_tools,        # Get all registered tools
#     set_tool_context,     # Set context before execution
#     MESH_TOOLS,           # List of mesh tool functions
#
#     # Individual tools
#     agent_lookup,
#     transfer_to_agent,
#     ask_clarifying_questions,
#     request_agent_approval,
#     set_needs_attention,
#     set_complete,
#     notify_user,
# )


# =============================================================================
# EXAMPLE: AGENT LOOKUP
# =============================================================================

def demo_agent_lookup():
    """
    Search for specialist agents that can help with a task.

    The agent_lookup tool searches the TAP registry using semantic search
    to find agents with relevant capabilities.

    Example usage in your agent:
    ```python
    from tap_core.tools import agent_lookup

    # Search for agents
    result = agent_lookup(
        query="help with tax returns",
        tier="all",        # "primary", "secondary", "tertiary", or "all"
        limit=5,
        min_similarity=0.3
    )

    # Result contains matching agents with their capabilities
    # Gateway will handle executing this and returning results
    ```

    Tiers:
    - primary: Equipped abilities (pre-authorized, fastest)
    - secondary: Org's private agents (auto-entitled)
    - tertiary: Public marketplace (requires purchase)
    - all: Search all tiers in order
    """
    pass


# =============================================================================
# EXAMPLE: TRANSFER TO AGENT
# =============================================================================

def demo_transfer_to_agent():
    """
    Delegate work to a specialist agent.

    After finding an agent with agent_lookup, use transfer_to_agent
    to delegate the task. Gateway handles routing and authorization.

    Example usage:
    ```python
    from tap_core.tools import transfer_to_agent

    # Delegate to specialist
    intent = transfer_to_agent(
        target_agent_slug="tax-specialist",
        message="Help the user with their tax return",
        context={"user_data": {...}}  # Optional context
    )

    # Return intent - Gateway handles the actual transfer
    return intent
    ```

    Important:
    - For tertiary agents, use request_agent_approval first
    - Gateway checks entitlements before allowing transfer
    """
    pass


# =============================================================================
# EXAMPLE: ASK CLARIFYING QUESTIONS
# =============================================================================

def demo_ask_clarifying_questions():
    """
    Gather additional information from the user.

    Use this when you need more information to complete a task.
    Gateway presents a form to the user and returns their responses.

    Example usage:
    ```python
    from tap_core.tools import ask_clarifying_questions

    # Ask for more information
    intent = ask_clarifying_questions(
        questions=[
            {
                "field": "tax_year",
                "question": "Which tax year are you filing for?",
                "type": "select",
                "options": ["2024", "2025", "2026"]
            },
            {
                "field": "income_type",
                "question": "What type of income do you have?",
                "type": "multiselect",
                "options": ["Salary", "Business", "Investment", "Other"]
            }
        ],
        reason="I need more details to help with your tax return"
    )

    return intent  # Gateway shows form and returns responses
    ```
    """
    pass


# =============================================================================
# EXAMPLE: REQUEST AGENT APPROVAL
# =============================================================================

def demo_request_agent_approval():
    """
    Request approval before using a non-entitled tertiary agent.

    For agents from the public marketplace that the user hasn't purchased,
    use this to show a pricing proposal and get approval.

    Example usage:
    ```python
    from tap_core.tools import request_agent_approval

    # Request approval for marketplace agent
    intent = request_agent_approval(
        agent_slug="premium-tax-advisor",
        reason="This specialist can provide detailed tax optimization",
        estimated_cost=5.00  # Optional
    )

    return intent  # Gateway shows pricing and approval UI
    ```

    After approval:
    - One-time purchase token is generated
    - You can then use transfer_to_agent
    """
    pass


# =============================================================================
# EXAMPLE: STATUS CONTROL TOOLS
# =============================================================================

def demo_status_tools():
    """
    Control task status and user notifications.

    set_needs_attention:
        Signal that the agent needs user attention (pauses execution).

    set_complete:
        Signal that the task is complete.

    notify_user:
        Send a progress notification without changing status.

    Example usage:
    ```python
    from tap_core.tools import set_complete, notify_user, set_needs_attention

    # Send progress update
    notify_user(
        message="Processing your documents...",
        progress=0.5  # Optional: 0.0 to 1.0
    )

    # Signal attention needed
    set_needs_attention(
        reason="I found an issue that requires your review",
        details={"issue": "Missing signature on page 3"}
    )

    # Signal completion
    set_complete(
        summary="Tax return prepared successfully",
        artifacts=["gs://bucket/tax-return.pdf"]
    )
    ```
    """
    pass


# =============================================================================
# FULL WORKFLOW EXAMPLE
# =============================================================================

def demo_full_workflow():
    """
    Complete workflow showing mesh tools in action.

    This demonstrates a typical flow:
    1. Receive task
    2. Search for specialist if needed
    3. Request approval for non-entitled agent
    4. Transfer to specialist
    5. Signal completion

    ```python
    from tap_core.tools import (
        agent_lookup,
        transfer_to_agent,
        request_agent_approval,
        ask_clarifying_questions,
        set_complete,
    )

    async def handle_tax_request(user_message: str):
        # 1. Check if we need clarification
        if "tax" in user_message.lower() and "year" not in user_message:
            return ask_clarifying_questions(
                questions=[{"field": "year", "question": "Which tax year?"}]
            )

        # 2. Search for specialist
        agents = agent_lookup(query="tax preparation specialist", tier="all")

        if not agents.get("data", {}).get("agents"):
            # No specialist found - handle ourselves
            return set_complete(summary="Completed basic tax guidance")

        agent = agents["data"]["agents"][0]

        # 3. Check if entitled
        if agent.get("tier") == "tertiary":
            # Need approval for marketplace agent
            return request_agent_approval(
                agent_slug=agent["slug"],
                reason="This tax specialist can help"
            )

        # 4. Transfer to specialist
        return transfer_to_agent(
            target_agent_slug=agent["slug"],
            message=user_message
        )
    ```
    """
    pass


__all__ = [
    "demo_agent_lookup",
    "demo_transfer_to_agent",
    "demo_ask_clarifying_questions",
    "demo_request_agent_approval",
    "demo_status_tools",
    "demo_full_workflow",
]
