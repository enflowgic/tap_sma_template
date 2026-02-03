"""
TAP Template Agent - Test Fixtures

Pytest fixtures for testing your SMA.
"""

import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# CONTEXT FIXTURES
# =============================================================================

@pytest.fixture
def mock_tool_context():
    """Mock tool context for mesh tool tests."""
    return {
        "org_id": "test-org-123",
        "user_id": "test-user-456",
        "session_id": "test-session-789",
        "trace_id": "trace-abc-def",
        "equipped_abilities": ["test-ability-1", "test-ability-2"],
        "oauth_credentials": {},
        "is_specialist_delegate": True,
        "delegation_context": {
            "delegated_by": "master-agent",
            "delegation_reason": "Test delegation",
            "delegation_depth": 1,
        },
    }


@pytest.fixture
def mock_gateway_context():
    """Mock context as received from Gateway."""
    return {
        "org_id": "test-org-123",
        "user_id": "test-user-456",
        "session_id": "test-session-789",
        "trace_id": "trace-abc-def",
        "system_prompt": "You are a test agent.",
        "history": [
            {"role": "user", "content": "Hello", "agent_slug": None},
            {"role": "assistant", "content": "Hi there!", "agent_slug": "master-agent"},
        ],
        "equipped_abilities": ["test-ability"],
        "delegation_context": {
            "original_prompt": "Test the agent",
            "delegated_by": "master-agent",
            "delegation_reason": "Testing SMA",
            "delegation_depth": 1,
        },
        "is_specialist_delegate": True,
    }


# =============================================================================
# MOCK FIXTURES
# =============================================================================

@pytest.fixture
def mock_tap_core():
    """Mock tap_core module for isolated testing."""
    with patch.dict("sys.modules", {
        "tap_core": MagicMock(),
        "tap_core.tools": MagicMock(),
        "tap_core.tools.mesh_tools": MagicMock(),
    }):
        yield


@pytest.fixture
def mock_adk_runner():
    """Mock ADK InMemoryRunner for agent tests."""
    with patch("google.adk.runners.InMemoryRunner") as mock:
        runner_instance = MagicMock()
        mock.return_value = runner_instance

        # Mock session service
        runner_instance.session_service.get_session.return_value = None
        runner_instance.session_service.create_session.return_value = None

        yield runner_instance


# =============================================================================
# REQUEST FIXTURES
# =============================================================================

@pytest.fixture
def a2a_request():
    """Sample A2A JSON-RPC request."""
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {"text": "Hello, agent!"},
            "org_id": "test-org",
            "user_id": "test-user",
            "session_id": "test-session",
            "trace_id": "test-trace",
        },
        "id": "req-1",
    }


@pytest.fixture
def a2a_stream_request(mock_gateway_context):
    """Sample A2A streaming request with Gateway context."""
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {"text": "Analyze this data"},
            "context": mock_gateway_context,
        },
        "id": "req-stream-1",
    }


# =============================================================================
# INPUT SCHEMA FIXTURES
# =============================================================================

@pytest.fixture
def valid_input():
    """Valid input matching AgentInputSchema."""
    return {
        "task": "Test task description",
    }


@pytest.fixture
def invalid_input():
    """Invalid input (missing required fields)."""
    return {
        # Missing "task" field
    }


# =============================================================================
# OUTPUT FIXTURES
# =============================================================================

@pytest.fixture
def expected_output():
    """Expected output structure."""
    return {
        "response": "Task completed successfully",
        "confidence": 0.95,
        "status": "completed",
    }


# =============================================================================
# MOCK RESPONSE FIXTURES
# =============================================================================

@pytest.fixture
def mock_transfer_back_intent():
    """Mock transfer_back_to_parent intent payload."""
    return {
        "intent": "TRANSFER_BACK",
        "result": "Analysis complete. Found 5 items.",
        "success": True,
        "deliverables": ["analysis_report"],
        "data": {"items": ["a", "b", "c", "d", "e"]},
        "confidence": 0.92,
    }


@pytest.fixture
def mock_agent_lookup_response():
    """Mock agent_lookup tool response."""
    return {
        "intent": "TOOL_CALL",
        "tool": "agent_lookup",
        "params": {"query": "data analysis", "tier": "all"},
        "result": {
            "agents": [
                {
                    "slug": "data-analyzer",
                    "display_name": "Data Analyzer",
                    "tier": "secondary",
                    "is_entitled": True,
                },
            ],
        },
    }
