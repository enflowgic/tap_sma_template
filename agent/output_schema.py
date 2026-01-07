"""
TAP Template Agent - Output Schema

This schema defines the structured output format for your agent.
It's part of the A2A Agent Card and tells clients what data
format to expect from your agent's responses.

TODO: Customize this schema for your agent's output format.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentOutputSchema(BaseModel):
    """
    A2A Output Contract for your agent.

    This schema defines the structure of your agent's responses.
    Clients use this to understand and validate responses.
    """

    # =========================================================================
    # PRIMARY RESPONSE
    # =========================================================================

    response: str = Field(
        ...,
        description="Primary text response from the agent",
    )

    # =========================================================================
    # STRUCTURED RESULTS
    # =========================================================================

    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured data results (key-value pairs, nested objects)",
    )

    findings: List[str] = Field(
        default_factory=list,
        description="List of key findings or observations",
    )

    recommendations: List[str] = Field(
        default_factory=list,
        description="Actionable recommendations based on the analysis",
    )

    # =========================================================================
    # QUALITY INDICATORS
    # =========================================================================

    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for the response (0.0 to 1.0)",
    )

    status: str = Field(
        default="success",
        description="Execution status: success, partial, or needs_input",
    )

    # =========================================================================
    # FOLLOW-UP
    # =========================================================================

    follow_up_questions: List[str] = Field(
        default_factory=list,
        description="Suggested follow-up questions for the user",
    )

    next_steps: List[str] = Field(
        default_factory=list,
        description="Recommended next steps or actions",
    )


__all__ = ["AgentOutputSchema"]
