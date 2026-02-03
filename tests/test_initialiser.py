"""
TAP Template Agent - TapInitialiserAgent Tests

Tests for manifest loading, instruction generation, and state distribution.
Updated for the new state_schema.per_agent_preferences structure.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml


# =============================================================================
# MANIFEST TESTS
# =============================================================================

class TestManifestLoading:
    """Test system manifest loading and validation."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear manifest cache before each test for isolation."""
        from tap_wrapper.manifest import clear_manifest_cache
        clear_manifest_cache()
        yield
        clear_manifest_cache()

    def test_load_manifest_from_file(self, tmp_path):
        """Test loading a valid manifest file with new schema."""
        from tap_wrapper.manifest import load_system_manifest, SystemManifest

        # Create a test manifest with new schema
        manifest_content = {
            "apiVersion": "tap/v1",
            "kind": "SystemManifest",
            "system": {
                "name": "Test Agent",
                "version": "1.0.0",
                "purpose": "Testing",
            },
            "state_schema": {
                "per_agent_preferences": {
                    "test_agent_user_preferences": {
                        "domain": "Testing",
                        "description": "Test preferences",
                        "wrapper_guidance": "Extract test preferences",
                    }
                }
            },
            "personalization": {
                "enabled": True,
                "user_preferences_key": "user_preferences",
                "fallback_snippet": "Default behavior.",
            },
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        # Load manifest
        manifest = load_system_manifest(manifest_path=manifest_path)

        assert isinstance(manifest, SystemManifest)
        assert manifest.system.name == "Test Agent"
        assert "test_agent_user_preferences" in manifest.state_schema.per_agent_preferences
        assert manifest.personalization.enabled is True

    def test_load_manifest_not_found(self, tmp_path):
        """Test loading when manifest file doesn't exist."""
        from tap_wrapper.manifest import load_system_manifest, SystemManifest

        manifest = load_system_manifest(manifest_path=tmp_path / "nonexistent.yaml")

        # Should return empty manifest, not raise error
        assert isinstance(manifest, SystemManifest)
        assert manifest.system.name == ""

    def test_load_manifest_invalid_yaml(self, tmp_path):
        """Test loading an invalid YAML file."""
        from tap_wrapper.manifest import load_system_manifest, SystemManifest

        manifest_path = tmp_path / "invalid.yaml"
        with open(manifest_path, "w") as f:
            f.write("{ invalid yaml: [")

        manifest = load_system_manifest(manifest_path=manifest_path)

        # Should return empty manifest, not raise error
        assert isinstance(manifest, SystemManifest)
        assert manifest.system.name == ""

    def test_load_manifest_invalid_schema(self, tmp_path):
        """Test loading YAML with invalid schema."""
        from tap_wrapper.manifest import load_system_manifest, SystemManifest

        manifest_content = {
            "apiVersion": "tap/v1",
            "state_schema": "invalid_type",  # Should be object
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        manifest = load_system_manifest(manifest_path=manifest_path)

        # Should return empty/partial manifest, not raise error
        assert isinstance(manifest, SystemManifest)

    def test_get_preference_keys(self, tmp_path):
        """Test getting preference keys from state_schema."""
        from tap_wrapper.manifest import load_system_manifest

        manifest_content = {
            "apiVersion": "tap/v1",
            "kind": "SystemManifest",
            "state_schema": {
                "per_agent_preferences": {
                    "agent_a_user_preferences": {
                        "domain": "Agent A",
                    },
                    "agent_b_user_preferences": {
                        "domain": "Agent B",
                    },
                }
            },
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        manifest = load_system_manifest(manifest_path=manifest_path)
        pref_keys = list(manifest.state_schema.per_agent_preferences.keys())

        assert len(pref_keys) == 2
        assert "agent_a_user_preferences" in pref_keys
        assert "agent_b_user_preferences" in pref_keys

    def test_manifest_caching(self, tmp_path):
        """Test that manifest is cached after first load."""
        from tap_wrapper.manifest import load_system_manifest, _manifest_cache

        manifest_content = {
            "apiVersion": "tap/v1",
            "system": {"name": "Cached Agent"},
            "state_schema": {
                "per_agent_preferences": {
                    "test_user_preferences": {"domain": "Test"},
                }
            },
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        # First load - should read from disk
        manifest1 = load_system_manifest(manifest_path=manifest_path)
        assert manifest1.system.name == "Cached Agent"

        # Verify it was cached
        resolved_path = manifest_path.resolve()
        assert resolved_path in _manifest_cache

        # Second load - should return cached version
        manifest2 = load_system_manifest(manifest_path=manifest_path)
        assert manifest2.system.name == "Cached Agent"
        assert manifest1 is manifest2  # Should be the exact same object

    def test_manifest_cache_bypass(self, tmp_path):
        """Test that use_cache=False bypasses the cache."""
        from tap_wrapper.manifest import load_system_manifest, _manifest_cache

        manifest_content = {
            "apiVersion": "tap/v1",
            "system": {"name": "Test Agent"},
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        # Load without cache
        manifest = load_system_manifest(manifest_path=manifest_path, use_cache=False)
        assert manifest.system.name == "Test Agent"

        # Should NOT be in cache
        resolved_path = manifest_path.resolve()
        assert resolved_path not in _manifest_cache


# =============================================================================
# INSTRUCTION GENERATION TESTS
# =============================================================================

class TestInstructionGeneration:
    """Test TapInitialiserAgent instruction generation."""

    def test_create_initialiser_instruction(self):
        """Test instruction generation from manifest."""
        from tap_wrapper.manifest import (
            SystemManifest, SystemInfo, StateSchema, AgentPreference, Personalization
        )
        from tap_wrapper.initialiser import create_initialiser_instruction

        manifest = SystemManifest(
            system=SystemInfo(
                name="Test Pipeline",
                purpose="Test purpose",
            ),
            state_schema=StateSchema(
                per_agent_preferences={
                    "researcher_user_preferences": AgentPreference(
                        domain="Research",
                        description="Does research",
                        wrapper_guidance="Extract depth and source preferences",
                    ),
                    "writer_user_preferences": AgentPreference(
                        domain="Writing",
                        description="Writes output",
                        wrapper_guidance="Extract tone and verbosity preferences",
                    ),
                }
            ),
            personalization=Personalization(
                enabled=True,
                user_preferences_key="user_prefs",
            ),
        )

        instruction = create_initialiser_instruction(manifest)

        # Check that key elements are present
        assert "Test Pipeline" in instruction
        assert "Test purpose" in instruction
        assert "Researcher" in instruction
        assert "researcher_user_preferences" in instruction
        assert "Writer" in instruction
        assert "writer_user_preferences" in instruction
        assert "user_prefs" in instruction

    def test_instruction_with_empty_preferences(self):
        """Test instruction generation with no preferences defined."""
        from tap_wrapper.manifest import SystemManifest
        from tap_wrapper.initialiser import create_initialiser_instruction

        manifest = SystemManifest()  # Empty manifest

        instruction = create_initialiser_instruction(manifest)

        assert "No agents defined for personalization" in instruction


# =============================================================================
# AGENT FACTORY TESTS
# =============================================================================

class TestTapInitialiserAgentFactory:
    """Test TapInitialiserAgent creation."""

    def test_create_agent_with_valid_manifest(self, tmp_path):
        """Test creating TapInitialiserAgent with valid manifest."""
        from tap_wrapper.manifest import load_system_manifest
        from tap_wrapper.initialiser import create_tap_initialiser_agent

        manifest_content = {
            "state_schema": {
                "per_agent_preferences": {
                    "test_agent_user_preferences": {
                        "domain": "Testing",
                        "description": "Test agent preferences",
                    }
                }
            },
            "personalization": {
                "enabled": True,
            },
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        manifest = load_system_manifest(manifest_path=manifest_path)
        agent = create_tap_initialiser_agent(manifest)

        assert agent is not None
        assert agent.name == "TapInitialiserAgent"
        assert agent.output_key == "personalization_result"

    def test_create_agent_returns_none_when_disabled(self, tmp_path):
        """Test that None is returned when personalization is disabled."""
        from tap_wrapper.manifest import load_system_manifest
        from tap_wrapper.initialiser import create_tap_initialiser_agent

        manifest_content = {
            "personalization": {
                "enabled": False,
            },
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        manifest = load_system_manifest(manifest_path=manifest_path)
        agent = create_tap_initialiser_agent(manifest)

        assert agent is None

    def test_create_agent_returns_none_when_no_preferences(self, tmp_path):
        """Test that None is returned when no per_agent_preferences defined."""
        from tap_wrapper.manifest import load_system_manifest
        from tap_wrapper.initialiser import create_tap_initialiser_agent

        manifest_content = {
            "state_schema": {
                "per_agent_preferences": {}  # Empty
            },
            "personalization": {
                "enabled": True,
            },
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        manifest = load_system_manifest(manifest_path=manifest_path)
        agent = create_tap_initialiser_agent(manifest)

        assert agent is None


# =============================================================================
# STATE DISTRIBUTION TESTS
# =============================================================================

class TestStateDistribution:
    """Test distributing personalization snippets to state."""

    @pytest.mark.asyncio
    async def test_distribute_snippets_success(self, tmp_path):
        """Test successful snippet distribution."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        # Create mock callback context
        mock_state = {
            "personalization_result": json.dumps({
                "snippets": {
                    "agent_a_user_preferences": "Be friendly and concise.",
                    "agent_b_user_preferences": "Focus on technical details.",
                },
                "ltm_summary": "User works in healthcare.",
                "reasoning": "User prefers casual tone.",
            }),
        }

        callback_context = MagicMock()
        callback_context.state = mock_state

        # Mock manifest to match the test's expected keys
        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "agent_a_user_preferences": AgentPreference(domain="Agent A"),
                        "agent_b_user_preferences": AgentPreference(domain="Agent B"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Default behavior.",
                ),
            )

            # Call the callback
            await distribute_snippets_to_state(callback_context)

        # Verify snippets were distributed
        assert mock_state["agent_a_user_preferences"] == "Be friendly and concise."
        assert mock_state["agent_b_user_preferences"] == "Focus on technical details."
        assert mock_state["ltm_summary"] == "User works in healthcare."
        assert mock_state["tap_init_complete"] is True
        assert mock_state["tap_init_reasoning"] == "User prefers casual tone."
        assert mock_state["tap_init_snippet_count"] == 2

    @pytest.mark.asyncio
    async def test_distribute_snippets_handles_code_blocks(self, tmp_path):
        """Test handling of JSON wrapped in code blocks."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        # LLMs sometimes wrap JSON in code blocks
        result_with_codeblock = '''```json
{
  "snippets": {
    "test_user_preferences": "Test snippet."
  },
  "ltm_summary": "",
  "reasoning": "Test reason."
}
```'''

        mock_state = {"personalization_result": result_with_codeblock}
        callback_context = MagicMock()
        callback_context.state = mock_state

        # Mock manifest to match the test's expected keys
        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "test_user_preferences": AgentPreference(domain="Test"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Default behavior.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        assert mock_state["test_user_preferences"] == "Test snippet."
        assert mock_state["tap_init_complete"] is True

    @pytest.mark.asyncio
    async def test_distribute_snippets_handles_empty_output(self, tmp_path):
        """Test fallback when output is empty."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        mock_state = {"personalization_result": ""}
        callback_context = MagicMock()
        callback_context.state = mock_state

        # Mock manifest loading for fallback
        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "test_user_preferences": AgentPreference(domain="Test"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Default behavior.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        assert mock_state["tap_init_complete"] is False
        assert "test_user_preferences" in mock_state
        assert mock_state["test_user_preferences"] == "Default behavior."

    @pytest.mark.asyncio
    async def test_distribute_snippets_handles_invalid_json(self, tmp_path):
        """Test fallback when output is invalid JSON."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        mock_state = {"personalization_result": "not valid json"}
        callback_context = MagicMock()
        callback_context.state = mock_state

        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "test_user_preferences": AgentPreference(domain="Test"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Fallback text.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        assert mock_state["tap_init_complete"] is False
        assert mock_state["test_user_preferences"] == "Fallback text."

    @pytest.mark.asyncio
    async def test_distribute_snippets_validates_against_manifest(self, tmp_path):
        """Test that unexpected keys from LLM are rejected and expected keys get fallback."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        # LLM returns unexpected keys that don't match manifest
        mock_state = {
            "personalization_result": json.dumps({
                "snippets": {
                    "wrong_key_a": "Snippet for wrong key A",
                    "wrong_key_b": "Snippet for wrong key B",
                },
                "ltm_summary": "",
                "reasoning": "Test",
            }),
        }

        callback_context = MagicMock()
        callback_context.state = mock_state

        # Manifest expects different keys
        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "expected_key_a": AgentPreference(domain="A"),
                        "expected_key_b": AgentPreference(domain="B"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Fallback for missing keys.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        # Unexpected keys should NOT be set
        assert "wrong_key_a" not in mock_state
        assert "wrong_key_b" not in mock_state

        # Expected keys should get fallback
        assert mock_state["expected_key_a"] == "Fallback for missing keys."
        assert mock_state["expected_key_b"] == "Fallback for missing keys."

        # Metadata should track what happened
        assert mock_state["tap_init_complete"] is True
        assert mock_state["tap_init_snippet_count"] == 0
        assert set(mock_state["tap_init_missing_keys"]) == {"expected_key_a", "expected_key_b"}
        assert set(mock_state["tap_init_unexpected_keys"]) == {"wrong_key_a", "wrong_key_b"}

    @pytest.mark.asyncio
    async def test_distribute_snippets_partial_match(self, tmp_path):
        """Test when LLM returns some correct keys and some wrong keys."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        # LLM returns one correct key and one wrong key
        mock_state = {
            "personalization_result": json.dumps({
                "snippets": {
                    "valid_key": "Valid snippet content",
                    "wrong_key": "Wrong key content",
                },
                "ltm_summary": "",
                "reasoning": "Test",
            }),
        }

        callback_context = MagicMock()
        callback_context.state = mock_state

        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "valid_key": AgentPreference(domain="Valid"),
                        "missing_key": AgentPreference(domain="Missing"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Fallback.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        # Valid key should be set with its snippet
        assert mock_state["valid_key"] == "Valid snippet content"

        # Wrong key should NOT be set
        assert "wrong_key" not in mock_state

        # Missing key should get fallback
        assert mock_state["missing_key"] == "Fallback."

        # Metadata
        assert mock_state["tap_init_snippet_count"] == 1

    @pytest.mark.asyncio
    async def test_distribute_snippets_handles_non_string_values(self, tmp_path):
        """Test that non-string snippet values are replaced with fallback."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        # LLM returns a dict instead of string (malformed output)
        mock_state = {
            "personalization_result": json.dumps({
                "snippets": {
                    "string_key": "Valid string snippet",
                    "dict_key": {"nested": "object"},  # Non-string
                    "list_key": ["a", "b"],  # Non-string
                    "null_key": None,  # None
                },
                "reasoning": "Test",
            }),
        }

        callback_context = MagicMock()
        callback_context.state = mock_state

        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "string_key": AgentPreference(domain="String"),
                        "dict_key": AgentPreference(domain="Dict"),
                        "list_key": AgentPreference(domain="List"),
                        "null_key": AgentPreference(domain="Null"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Fallback for invalid.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        # String key should be set normally
        assert mock_state["string_key"] == "Valid string snippet"

        # Non-string keys should get fallback
        assert mock_state["dict_key"] == "Fallback for invalid."
        assert mock_state["list_key"] == "Fallback for invalid."
        assert mock_state["null_key"] == "Fallback for invalid."

    @pytest.mark.asyncio
    async def test_distribute_snippets_handles_empty_strings(self, tmp_path):
        """Test that empty string snippets are replaced with fallback."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        mock_state = {
            "personalization_result": json.dumps({
                "snippets": {
                    "valid_key": "Valid content",
                    "empty_key": "",
                    "whitespace_key": "   ",  # Only whitespace
                },
                "reasoning": "Test",
            }),
        }

        callback_context = MagicMock()
        callback_context.state = mock_state

        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "valid_key": AgentPreference(domain="Valid"),
                        "empty_key": AgentPreference(domain="Empty"),
                        "whitespace_key": AgentPreference(domain="Whitespace"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="Fallback for empty.",
                ),
            )

            await distribute_snippets_to_state(callback_context)

        # Valid key should be set normally
        assert mock_state["valid_key"] == "Valid content"

        # Empty/whitespace keys should get fallback
        assert mock_state["empty_key"] == "Fallback for empty."
        assert mock_state["whitespace_key"] == "Fallback for empty."


# =============================================================================
# SHOULD USE INITIALISER TESTS
# =============================================================================

class TestShouldUseInitialiser:
    """Test the should_use_initialiser helper function."""

    def test_returns_false_when_skip_flag_set(self, tmp_path):
        """Test that skip flag overrides everything."""
        from tap_wrapper.initialiser import should_use_initialiser

        result = should_use_initialiser(skip_initialiser=True)
        assert result is False

    def test_returns_false_when_env_var_set(self, tmp_path, monkeypatch):
        """Test that environment variable works."""
        from tap_wrapper.initialiser import should_use_initialiser

        monkeypatch.setenv("TAP_SKIP_INITIALISER", "true")

        result = should_use_initialiser()
        assert result is False

    def test_returns_false_when_personalization_disabled(self, tmp_path):
        """Test returns False when personalization is disabled in manifest."""
        from tap_wrapper.manifest import SystemManifest, Personalization
        from tap_wrapper.initialiser import should_use_initialiser

        manifest = SystemManifest(
            personalization=Personalization(enabled=False),
        )

        result = should_use_initialiser(manifest=manifest)
        assert result is False

    def test_returns_true_when_enabled_with_preferences(self, tmp_path):
        """Test returns True when properly configured."""
        from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
        from tap_wrapper.initialiser import should_use_initialiser

        manifest = SystemManifest(
            state_schema=StateSchema(
                per_agent_preferences={
                    "test_user_preferences": AgentPreference(domain="Test"),
                }
            ),
            personalization=Personalization(enabled=True),
        )

        result = should_use_initialiser(manifest=manifest)
        assert result is True


# =============================================================================
# PIPELINE INTEGRATION TESTS
# =============================================================================

class TestFullPipeline:
    """Test wrap_with_full_pipeline integration."""

    def test_wrap_with_full_pipeline_creates_sequential_agent(self, tmp_path):
        """Test that full pipeline creates SequentialAgent with all stages."""
        from tap_wrapper.validation import wrap_with_full_pipeline
        from tap_wrapper.manifest import load_system_manifest
        from google.adk.agents import LlmAgent, SequentialAgent
        from pydantic import BaseModel, Field

        # Create manifest with new schema
        manifest_content = {
            "state_schema": {
                "per_agent_preferences": {
                    "test_user_preferences": {
                        "domain": "Testing",
                    }
                }
            },
            "personalization": {"enabled": True},
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        # Create test input schema
        class TestInputSchema(BaseModel):
            query: str = Field(..., description="User query")

        # Create test agent
        test_agent = LlmAgent(
            name="TestDeveloperAgent",
            model="gemini-3-flash-preview",
            instruction="Test instruction",
        )

        # Patch manifest loading to use our test manifest
        with patch("tap_wrapper.manifest.load_system_manifest") as mock_load:
            mock_load.return_value = load_system_manifest(manifest_path=manifest_path)

            wrapped = wrap_with_full_pipeline(
                test_agent,
                TestInputSchema,
                skip_validation=False,
                skip_initialiser=False,
            )

        # Should be a SequentialAgent with multiple stages
        assert isinstance(wrapped, SequentialAgent)
        assert "Pipeline" in wrapped.name

    def test_initialiser_runs_before_validator(self, tmp_path):
        """Test that TapInitialiserAgent runs BEFORE InputValidator."""
        from tap_wrapper.validation import wrap_with_full_pipeline
        from tap_wrapper.manifest import load_system_manifest
        from google.adk.agents import LlmAgent, SequentialAgent
        from pydantic import BaseModel, Field

        # Create manifest with preferences for both agents
        manifest_content = {
            "state_schema": {
                "per_agent_preferences": {
                    "input_validator_user_preferences": {
                        "domain": "Validation",
                    },
                    "main_agent_user_preferences": {
                        "domain": "Main",
                    },
                }
            },
            "personalization": {"enabled": True},
        }

        manifest_path = tmp_path / "system-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_content, f)

        # Create test input schema with required field
        class TestInputSchema(BaseModel):
            query: str = Field(..., description="User query")

        # Create test agent
        test_agent = LlmAgent(
            name="TestAgent",
            model="gemini-3-flash-preview",
            instruction="Test instruction",
        )

        with patch("tap_wrapper.manifest.load_system_manifest") as mock_load:
            mock_load.return_value = load_system_manifest(manifest_path=manifest_path)

            wrapped = wrap_with_full_pipeline(
                test_agent,
                TestInputSchema,
                skip_validation=False,
                skip_initialiser=False,
            )

        # Should be a SequentialAgent
        assert isinstance(wrapped, SequentialAgent)

        # Get sub-agent names
        sub_agent_names = [sa.name for sa in wrapped.sub_agents]

        # Verify order: Initialiser -> Validator -> DeveloperAgent
        assert sub_agent_names[0] == "TapInitialiserAgent", "Initialiser should be first"
        assert sub_agent_names[1] == "InputValidator", "Validator should be second"
        assert sub_agent_names[2] == "TestAgent", "Developer agent should be third"

    def test_wrap_with_full_pipeline_skips_when_no_manifest(self):
        """Test that pipeline skips initialiser when no manifest exists."""
        from tap_wrapper.validation import wrap_with_full_pipeline
        from tap_wrapper.manifest import SystemManifest
        from google.adk.agents import LlmAgent
        from pydantic import BaseModel

        class EmptySchema(BaseModel):
            pass

        test_agent = LlmAgent(
            name="TestAgent",
            model="gemini-3-flash-preview",
            instruction="Test",
        )

        # No manifest = no personalization, no required fields = no validation
        with patch("tap_wrapper.manifest.load_system_manifest") as mock_load:
            mock_load.return_value = SystemManifest()  # Empty manifest

            wrapped = wrap_with_full_pipeline(
                test_agent,
                EmptySchema,
                skip_validation=True,
                skip_initialiser=True,
            )

        # Should return original agent when all stages skipped
        assert wrapped is test_agent


# =============================================================================
# JSON EXTRACTION TESTS
# =============================================================================

class TestJsonExtraction:
    """Test the _extract_json_from_codeblock helper function."""

    def test_extract_from_json_codeblock(self):
        """Test extraction from ```json ... ``` block."""
        from tap_wrapper.initialiser import _extract_json_from_codeblock

        text = '''Here is the result:
```json
{"key": "value"}
```
That's all.'''

        result = _extract_json_from_codeblock(text)
        assert result == '{"key": "value"}'

    def test_extract_from_generic_codeblock(self):
        """Test extraction from ``` ... ``` block (no json marker)."""
        from tap_wrapper.initialiser import _extract_json_from_codeblock

        text = '''```
{"key": "value"}
```'''

        result = _extract_json_from_codeblock(text)
        assert result == '{"key": "value"}'

    def test_extract_raw_json(self):
        """Test that raw JSON without code blocks is returned as-is."""
        from tap_wrapper.initialiser import _extract_json_from_codeblock

        text = '{"key": "value"}'
        result = _extract_json_from_codeblock(text)
        assert result == '{"key": "value"}'

    def test_extract_malformed_no_closing(self):
        """Test extraction when closing ``` is missing."""
        from tap_wrapper.initialiser import _extract_json_from_codeblock

        text = '''```json
{"key": "value"}
some trailing text'''

        result = _extract_json_from_codeblock(text)
        # Should extract the content after the opening marker
        assert '{"key": "value"}' in result

    def test_extract_handles_empty_content(self):
        """Test extraction with empty content between markers."""
        from tap_wrapper.initialiser import _extract_json_from_codeblock

        text = '''```json
```'''

        result = _extract_json_from_codeblock(text)
        assert result == ""

    def test_extract_handles_whitespace_only(self):
        """Test extraction with whitespace only."""
        from tap_wrapper.initialiser import _extract_json_from_codeblock

        text = "   "
        result = _extract_json_from_codeblock(text)
        assert result == ""


# =============================================================================
# FALLBACK RESILIENCE TESTS
# =============================================================================

class TestFallbackResilience:
    """Test that fallback handling is resilient to errors."""

    @pytest.mark.asyncio
    async def test_fallback_survives_manifest_load_failure(self):
        """Test that fallback still sets metadata even if manifest fails to load."""
        from tap_wrapper.initialiser import _apply_fallback_snippets

        mock_state = {}
        callback_context = MagicMock()
        callback_context.state = mock_state

        # Make manifest loading fail
        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            mock_load.side_effect = Exception("Manifest file corrupted")

            # Should not raise, should set minimal state
            await _apply_fallback_snippets(callback_context, "Test error")

        # Metadata should still be set
        assert mock_state["tap_init_complete"] is False
        assert mock_state["tap_init_error"] == "Test error"

    @pytest.mark.asyncio
    async def test_fallback_uses_default_when_manifest_has_none(self):
        """Test that fallback uses default text when manifest has no fallback_snippet."""
        from tap_wrapper.initialiser import _apply_fallback_snippets

        mock_state = {}
        callback_context = MagicMock()
        callback_context.state = mock_state

        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest, StateSchema, AgentPreference, Personalization
            # Manifest with None/empty fallback_snippet
            mock_load.return_value = SystemManifest(
                state_schema=StateSchema(
                    per_agent_preferences={
                        "test_key": AgentPreference(domain="Test"),
                    }
                ),
                personalization=Personalization(
                    fallback_snippet="",  # Empty string
                ),
            )

            await _apply_fallback_snippets(callback_context, "Test error")

        # Should use the DEFAULT_FALLBACK constant
        assert mock_state["test_key"] == "Proceed with default professional behavior."

    @pytest.mark.asyncio
    async def test_distribute_snippets_tracks_error_message(self):
        """Test that error message is captured in state on JSON parse failure."""
        from tap_wrapper.initialiser import distribute_snippets_to_state

        mock_state = {
            "personalization_result": "this is not valid json {{{",
        }

        callback_context = MagicMock()
        callback_context.state = mock_state

        with patch("tap_wrapper.initialiser.load_system_manifest") as mock_load:
            from tap_wrapper.manifest import SystemManifest
            mock_load.return_value = SystemManifest()

            await distribute_snippets_to_state(callback_context)

        # Error should be captured
        assert "tap_init_error" in mock_state
        assert "Invalid JSON output" in mock_state["tap_init_error"]
