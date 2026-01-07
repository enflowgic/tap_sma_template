"""
TAP Template Agent - Input Schema

This schema defines what input your agent needs to operate.
It inherits from BaseInputSchema which provides platform fields.

TAP uses this schema to:
1. Generate UI forms for users to provide input
2. Validate incoming requests before execution
3. Collect missing information via ask_clarifying_questions tool

TODO: Customize this schema for your agent's needs.
"""

from typing import Optional

from pydantic import Field

from tap_core.schemas.base import BaseInputSchema


class AgentInputSchema(BaseInputSchema):
    """
    TAP Input Contract for your agent.

    Inherits from BaseInputSchema which provides platform fields:
    - session_id: Conversation continuity
    - trace_id: Distributed tracing
    - client_id: Prompt optimization lookup

    Add your agent-specific fields below.
    """

    # =========================================================================
    # REQUIRED FIELDS
    # =========================================================================

    task: str = Field(
        ...,  # ... means required
        min_length=1,
        description="What task should the agent perform?",
        json_schema_extra={
            "ui_widget": "textarea",
            "placeholder": "Describe what you want the agent to do...",
            "prompt_question": "What would you like me to help you with?",
        }
    )

    # =========================================================================
    # OPTIONAL FIELDS
    # =========================================================================

    context: Optional[str] = Field(
        default=None,
        description="Additional context or background information",
        json_schema_extra={
            "ui_widget": "textarea",
            "prompt_question": "Any additional context I should know about?",
        }
    )

    # =========================================================================
    # ADD YOUR FIELDS HERE
    # =========================================================================

    # Example: Mode selection
    # mode: str = Field(
    #     default="auto",
    #     description="Processing mode: auto, detailed, or quick",
    #     json_schema_extra={
    #         "ui_widget": "select",
    #         "prompt_question": "Which mode would you prefer?",
    #         "prompt_options": [
    #             {"value": "auto", "label": "Automatic"},
    #             {"value": "detailed", "label": "Detailed analysis"},
    #             {"value": "quick", "label": "Quick summary"},
    #         ]
    #     }
    # )

    # Example: Conditional field
    # detail_level: Optional[int] = Field(
    #     default=None,
    #     ge=1, le=10,
    #     description="Detail level (1-10). Required when mode=detailed.",
    #     json_schema_extra={
    #         "show_if": {"mode": "detailed"},
    #         "required_when": {"mode": "detailed"},
    #         "prompt_question": "What detail level (1-10)?",
    #     }
    # )

    # =========================================================================
    # PROMPT CONVERSION
    # =========================================================================

    def to_prompt(self) -> str:
        """
        Convert structured input to agent prompt.

        This transforms validated input into the natural language
        prompt your agent expects.

        Returns:
            Formatted prompt string
        """
        parts = [f"Task: {self.task}"]

        if self.context:
            parts.append(f"Context: {self.context}")

        return "\n".join(parts)


__all__ = ["AgentInputSchema"]
