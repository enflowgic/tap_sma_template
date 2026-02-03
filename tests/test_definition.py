"""
TAP Template Agent - Definition Tests

Tests for agent definition and configuration.

Run with:
    pytest tests/test_definition.py -v
"""

import pytest


class TestAgentDefinition:
    """Tests for agent definition module."""

    def test_agent_exists(self):
        """Verify agent is defined."""
        from agent import agent

        assert agent is not None
        assert hasattr(agent, "name")

    def test_agent_name_is_set(self):
        """Verify agent has a name."""
        from agent import agent

        assert agent.name is not None
        assert len(agent.name) > 0

    def test_model_name_valid(self):
        """Verify agent model is a valid Gemini model."""
        from agent import agent

        valid_models = [
            "gemini-3-flash-preview",
            "gemini-3-pro-preview",
        ]
        assert agent.model in valid_models, f"model should be one of {valid_models}"

    def test_agent_has_tools(self):
        """Verify agent has tools configured."""
        from agent import agent

        assert hasattr(agent, "tools")
        assert agent.tools is not None

    def test_agent_has_instruction(self):
        """Verify agent has instruction (system prompt)."""
        from agent import agent

        assert hasattr(agent, "instruction")
        assert agent.instruction is not None
        assert len(agent.instruction) > 0


class TestInputSchema:
    """Tests for input schema validation."""

    def test_input_schema_exists(self):
        """Verify AgentInputSchema is defined."""
        from agent import AgentInputSchema

        assert AgentInputSchema is not None

    def test_input_schema_has_to_prompt(self):
        """Verify AgentInputSchema has to_prompt method."""
        from agent import AgentInputSchema

        assert hasattr(AgentInputSchema, "to_prompt")

    def test_valid_input_validates(self, valid_input):
        """Verify valid input passes validation."""
        from agent import AgentInputSchema

        # Should not raise
        instance = AgentInputSchema(**valid_input)
        assert instance is not None

    def test_to_prompt_returns_string(self, valid_input):
        """Verify to_prompt returns a string."""
        from agent import AgentInputSchema

        instance = AgentInputSchema(**valid_input)
        prompt = instance.to_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestOutputSchema:
    """Tests for output schema (if defined)."""

    def test_output_schema_exists(self):
        """Verify AgentOutputSchema is defined (optional)."""
        try:
            from agent import AgentOutputSchema

            assert AgentOutputSchema is not None
        except ImportError:
            pytest.skip("AgentOutputSchema not defined (optional)")


class TestPrompts:
    """Tests for prompt configuration."""

    def test_system_prompt_defined(self):
        """Verify SYSTEM_PROMPT is defined (backward compatible)."""
        from agent import SYSTEM_PROMPT

        assert SYSTEM_PROMPT is not None
        assert "content" in SYSTEM_PROMPT
        assert "prompt_type" in SYSTEM_PROMPT

    def test_developer_prompts_defined(self):
        """Verify developer prompts are defined."""
        from agent.prompts import AGENT_DESCRIPTION

        assert AGENT_DESCRIPTION is not None
        assert len(AGENT_DESCRIPTION) > 0

    def test_system_prompt_mentions_transfer_back(self):
        """Verify system prompt mentions transfer_back_to_parent (critical for SMAs)."""
        from agent import SYSTEM_PROMPT

        content = SYSTEM_PROMPT["content"].lower()
        assert "transfer_back_to_parent" in content, (
            "System prompt should mention transfer_back_to_parent - "
            "this is the CORRECT way for SMAs to return results"
        )

    def test_system_prompt_warns_against_set_complete(self):
        """Verify system prompt warns against set_complete for SMAs."""
        from agent import SYSTEM_PROMPT

        content = SYSTEM_PROMPT["content"].lower()
        # Check for warning about set_complete
        assert "set_complete" in content, (
            "System prompt should mention set_complete"
        )


class TestPromptComposition:
    """Tests for tap_wrapper prompt composition."""

    def test_compose_system_prompt_works(self):
        """Verify compose_system_prompt returns valid prompt."""
        from tap_wrapper.prompts import compose_system_prompt

        prompt = compose_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_composed_prompt_has_platform_boilerplate(self):
        """Verify composed prompt includes platform boilerplate."""
        from tap_wrapper.prompts import compose_system_prompt

        prompt = compose_system_prompt()
        assert "TAP Mesh Tools" in prompt
        assert "transfer_back_to_parent" in prompt

    def test_composed_prompt_has_developer_content(self):
        """Verify composed prompt includes developer content."""
        from tap_wrapper.prompts import compose_system_prompt
        from agent.prompts import AGENT_DESCRIPTION

        prompt = compose_system_prompt()
        # Developer description should be in the final prompt
        # (at least the first sentence or key phrase)
        assert "helpful assistant" in prompt.lower() or AGENT_DESCRIPTION[:50] in prompt

    def test_get_prompts_for_registration(self):
        """Verify get_prompts returns dict for registration."""
        from tap_wrapper.prompts import get_prompts

        prompts = get_prompts()
        assert isinstance(prompts, dict)
        assert "system" in prompts
        assert "context_injection" in prompts
