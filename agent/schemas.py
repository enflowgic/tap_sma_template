"""
TAP Template Agent - Input/Output Schemas

Define what your agent expects as input and returns as output.

The input schema is used by TAP to:
- Generate UI forms for users
- Validate incoming requests
- Auto-collect missing fields via ask_clarifying_questions

The output schema documents your response format for A2A clients.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from tap_core.schemas.base import BaseInputSchema


# =============================================================================
# INPUT SCHEMA
# =============================================================================

class AgentInputSchema(BaseInputSchema):
    """
    What your agent needs to operate.

    Inherits platform fields from BaseInputSchema:
    - session_id: Conversation continuity
    - trace_id: Distributed tracing
    - client_id: Prompt optimization lookup
    """

    # Required field - use '...' for required, 'None' for optional
    task: str = Field(
        ...,
        min_length=1,
        description="What task should the agent perform?",
        json_schema_extra={
            "ui_widget": "textarea",
            "placeholder": "Describe what you want the agent to do...",
            # This question is asked if the field is missing:
            "prompt_question": "What would you like me to help you with?",
        }
    )

    # Optional field
    context: Optional[str] = Field(
        default=None,
        description="Additional context or background information",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "Any additional context I should know about?",
        }
    )

    # Add your fields here...
    # Examples:
    #
    # mode: str = Field(
    #     default="auto",
    #     json_schema_extra={
    #         "ui_widget": "select",
    #         "prompt_options": ["auto", "detailed", "quick"],
    #     }
    # )
    #
    # limit: int = Field(default=10, ge=1, le=100)

    def to_prompt(self) -> str:
        """Convert structured input to natural language prompt."""
        parts = [f"Task: {self.task}"]
        if self.context:
            parts.append(f"Context: {self.context}")
        return "\n".join(parts)


# =============================================================================
# OUTPUT SCHEMA
# =============================================================================

class AgentOutputSchema(BaseModel):
    """
    What your agent returns.

    This documents your response format for A2A clients and can optionally
    be used for structured output enforcement (set TAP_ENFORCE_STRUCTURED_OUTPUT=true).
    """

    response: str = Field(
        ...,
        description="Primary text response from the agent",
    )

    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured data results",
    )

    findings: List[str] = Field(
        default_factory=list,
        description="Key findings or observations",
    )

    recommendations: List[str] = Field(
        default_factory=list,
        description="Actionable recommendations",
    )

    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 to 1.0)",
    )

    status: str = Field(
        default="success",
        description="Execution status: success, partial, or needs_input",
    )


__all__ = ["AgentInputSchema", "AgentOutputSchema"]
