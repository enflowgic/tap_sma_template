"""
TAP Template Agent - Tools Tests

Tests for custom tools and mesh tool integration.

Run with:
    pytest tests/test_tools.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestCustomTools:
    """Tests for custom tools defined in agent/tools/."""

    def test_custom_tools_importable(self):
        """Verify custom tools can be imported."""
        from agent.tools import custom_tools

        assert custom_tools is not None
        assert isinstance(custom_tools, (list, tuple))

    def test_custom_tools_are_callable(self):
        """Verify each custom tool is callable."""
        from agent.tools import custom_tools

        for tool in custom_tools:
            assert callable(tool), f"Tool {tool} is not callable"

    def test_example_tool_exists(self):
        """Verify example_tool is defined (template ships with this)."""
        try:
            from agent.tools.example import example_tool

            assert callable(example_tool)
        except ImportError:
            pytest.skip("example_tool not found (may have been removed)")

    def test_example_tool_works(self):
        """Verify example_tool returns expected structure."""
        try:
            from agent.tools.example import example_tool

            result = example_tool("test query", limit=3)
            assert isinstance(result, dict)
            assert "status" in result
            assert "results" in result
            assert result["status"] == "success"
            assert len(result["results"]) == 3
        except ImportError:
            pytest.skip("example_tool not found")


class TestMeshToolsIntegration:
    """Tests for mesh tools integration via tap_wrapper."""

    def test_mesh_tools_available(self):
        """Verify mesh tools can be loaded via tap_wrapper."""
        from tap_wrapper.mesh_integration import get_mesh_tools

        tools = get_mesh_tools()
        # Should return list (empty if tap_core not installed)
        assert isinstance(tools, list)

    def test_setup_tool_context_available(self):
        """Verify setup_tool_context is available via tap_wrapper."""
        from tap_wrapper import setup_tool_context

        assert callable(setup_tool_context)


class TestMeshToolPatterns:
    """Tests verifying correct mesh tool usage patterns."""

    def test_transfer_back_intent_structure(self, mock_transfer_back_intent):
        """Verify transfer_back_to_parent intent structure."""
        intent = mock_transfer_back_intent

        # Required fields
        assert intent["intent"] == "TRANSFER_BACK"
        assert "result" in intent
        assert "success" in intent

        # Optional but recommended fields
        assert "confidence" in intent
        assert "data" in intent

    def test_transfer_back_result_is_string(self, mock_transfer_back_intent):
        """Verify result field is a string summary."""
        result = mock_transfer_back_intent["result"]
        assert isinstance(result, str)
        assert len(result) > 0

    def test_transfer_back_confidence_valid_range(self, mock_transfer_back_intent):
        """Verify confidence is between 0 and 1."""
        confidence = mock_transfer_back_intent["confidence"]
        assert 0.0 <= confidence <= 1.0


class TestToolsDirectory:
    """Tests for tools directory structure."""

    def test_tools_package_exists(self):
        """Verify agent/tools/ is a valid package."""
        import agent.tools

        assert agent.tools is not None

    def test_tools_init_exports_custom_tools(self):
        """Verify __init__.py exports custom_tools."""
        from agent.tools import custom_tools

        assert custom_tools is not None
        assert isinstance(custom_tools, list)

    def test_can_add_tools_from_submodules(self):
        """Verify tools can be imported from submodules."""
        # This pattern should work for adding new tool files
        from agent.tools.example import example_tool

        assert callable(example_tool)


class TestToolContext:
    """Tests for tool context setup via tap_wrapper."""

    def test_setup_tool_context_accepts_dict(self, mock_tool_context):
        """Verify setup_tool_context accepts context dict."""
        from tap_wrapper import setup_tool_context

        # Should not raise (tap_core may or may not be installed)
        try:
            setup_tool_context(mock_tool_context)
        except ImportError:
            pytest.skip("tap_core not installed")

    def test_setup_tool_context_handles_minimal_context(self):
        """Verify setup_tool_context handles minimal context."""
        from tap_wrapper import setup_tool_context

        minimal_context = {
            "org_id": "test-org",
            "user_id": "test-user",
        }

        # Should not raise even with minimal context
        try:
            setup_tool_context(minimal_context)
        except ImportError:
            pytest.skip("tap_core not installed")
