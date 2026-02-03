"""
Unit tests for SMAStreamingHandler.

Tests the structured SSE event emission for TAP SMAs.
"""

import json
import pytest
import sys
import os

# Add runtime directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'runtime'))

from streaming import (
    SMAStreamingHandler,
    SMAEventType,
    SMAErrorCode,
    SMAStreamEvent,
)


class TestSMAStreamEvent:
    """Tests for SMAStreamEvent model."""

    def test_to_dict_includes_required_fields(self):
        """Event dict should include task_id, sequence, elapsed_ms, timestamp."""
        event = SMAStreamEvent(
            task_id="test-task",
            event_type=SMAEventType.CONNECTED,
            sequence=1,
            elapsed_ms=100,
        )

        result = event.to_dict()

        assert result["task_id"] == "test-task"
        assert result["sequence"] == 1
        assert result["elapsed_ms"] == 100
        assert "timestamp" in result

    def test_to_dict_includes_message_when_present(self):
        """Event dict should include message if provided."""
        event = SMAStreamEvent(
            task_id="test-task",
            event_type=SMAEventType.WORKING,
            message="Processing request",
            sequence=1,
            elapsed_ms=0,
        )

        result = event.to_dict()

        assert result["message"] == "Processing request"

    def test_to_dict_merges_data_fields(self):
        """Event dict should merge data fields at top level."""
        event = SMAStreamEvent(
            task_id="test-task",
            event_type=SMAEventType.CONTENT,
            data={"text": "Hello", "partial": True, "index": 0},
            sequence=1,
            elapsed_ms=0,
        )

        result = event.to_dict()

        assert result["text"] == "Hello"
        assert result["partial"] is True
        assert result["index"] == 0

    def test_to_sse_format(self):
        """SSE output should have correct format."""
        event = SMAStreamEvent(
            task_id="test-task",
            event_type=SMAEventType.CONNECTED,
            sequence=1,
            elapsed_ms=0,
        )

        sse = event.to_sse()

        # Should have event type line
        assert "event: connected\n" in sse
        # Should have data line with JSON
        assert "data: " in sse
        # Should end with double newline
        assert sse.endswith("\n\n")

    def test_to_sse_with_event_id(self):
        """SSE output should include id line when event_id provided."""
        event = SMAStreamEvent(
            task_id="test-task",
            event_type=SMAEventType.CONTENT,
            sequence=5,
            elapsed_ms=100,
        )

        sse = event.to_sse(event_id="test-task-5")

        assert sse.startswith("id: test-task-5\n")


class TestSMAStreamingHandler:
    """Tests for SMAStreamingHandler class."""

    def test_init_sets_properties(self):
        """Handler should store all provided properties."""
        handler = SMAStreamingHandler(
            task_id="task-123",
            trace_id="trace-456",
            agent_slug="test-agent",
            org_id="org-789",
            user_id="user-abc",
        )

        assert handler.task_id == "task-123"
        assert handler.trace_id == "trace-456"
        assert handler.agent_slug == "test-agent"
        assert handler.org_id == "org-789"
        assert handler.user_id == "user-abc"

    def test_sequence_numbers_increment(self):
        """Each event should have incrementing sequence number."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        handler.emit_connected()
        handler.emit_working()
        handler.emit_content("Hello", 0)

        events = handler.get_events()

        assert events[0].sequence == 1
        assert events[1].sequence == 2
        assert events[2].sequence == 3

    def test_task_id_in_all_events(self):
        """All events should have the same task_id."""
        task_id = "my-unique-task-id"
        handler = SMAStreamingHandler(
            task_id=task_id,
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        handler.emit_connected()
        handler.emit_working()
        handler.emit_content("Text", 0)
        handler.emit_done("Text", 100, 50)

        for event in handler.get_events():
            assert event.task_id == task_id

    def test_elapsed_ms_increases(self):
        """Elapsed time should increase over handler lifetime."""
        import time

        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        handler.emit_connected()
        time.sleep(0.01)  # Small delay
        handler.emit_working()

        events = handler.get_events()

        # Second event should have higher elapsed_ms
        assert events[1].elapsed_ms >= events[0].elapsed_ms

    def test_emit_connected(self):
        """Connected event should have correct structure."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="trace-123",
            agent_slug="my-agent",
        )

        sse = handler.emit_connected()
        data = _parse_sse_data(sse)

        assert data["agent_slug"] == "my-agent"
        assert data["trace_id"] == "trace-123"
        assert "event: connected\n" in sse

    def test_emit_working(self):
        """Working event should have status field."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_working("Processing")
        data = _parse_sse_data(sse)

        assert data["status"] == "processing"
        assert data["message"] == "Processing"

    def test_emit_content(self):
        """Content event should have text, partial, and index fields."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_content("Hello world", chunk_index=3)
        data = _parse_sse_data(sse)

        assert data["text"] == "Hello world"
        assert data["partial"] is True
        assert data["index"] == 3

    def test_emit_tool_call(self):
        """Tool call event should have tool_name, args, and status."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_tool_call("search", {"query": "test"})
        data = _parse_sse_data(sse)

        assert data["tool_name"] == "search"
        assert data["args"] == {"query": "test"}
        assert data["status"] == "calling"

    def test_emit_tool_result_success(self):
        """Tool result event should indicate success."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_tool_result("search", True, "Found 10 results")
        data = _parse_sse_data(sse)

        assert data["tool_name"] == "search"
        assert data["status"] == "completed"
        assert data["result"] == "Found 10 results"

    def test_emit_tool_result_failure(self):
        """Tool result event should indicate failure."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_tool_result("search", False, "Network error")
        data = _parse_sse_data(sse)

        assert data["status"] == "failed"

    def test_emit_agent_step(self):
        """Agent step event should have step, agent_name, and status."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_agent_step(1, "ResearchAgent", "started")
        data = _parse_sse_data(sse)

        assert data["step"] == 1
        assert data["agent_name"] == "ResearchAgent"
        assert data["status"] == "started"

    def test_emit_token_update(self):
        """Token update event should have input_tokens and output_tokens."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_token_update(150, 42)
        data = _parse_sse_data(sse)

        assert data["input_tokens"] == 150
        assert data["output_tokens"] == 42

    def test_emit_synthesizing(self):
        """Synthesizing event should have status field."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_synthesizing()
        data = _parse_sse_data(sse)

        assert data["status"] == "creating_response"
        assert "event: synthesizing\n" in sse

    def test_emit_done(self):
        """Done event should have text, tokens, and is_final."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        # Emit some events first
        handler.emit_connected()
        handler.emit_working()

        sse = handler.emit_done("Complete response", 200, 100)
        data = _parse_sse_data(sse)

        assert data["text"] == "Complete response"
        assert data["input_tokens"] == 200
        assert data["output_tokens"] == 100
        assert data["is_final"] is True
        assert data["total_events"] == 3  # connected + working + done

    def test_emit_error_with_code(self):
        """Error event should have error message and code."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_error("Auth failed", SMAErrorCode.MISSING_CREDENTIALS)
        data = _parse_sse_data(sse)

        assert data["error"] == "Auth failed"
        assert data["error_code"] == "MISSING_CREDENTIALS"

    def test_emit_error_with_extra_data(self):
        """Error event should merge extra error data."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        sse = handler.emit_error(
            "OAuth needed",
            SMAErrorCode.MISSING_CREDENTIALS,
            {"service": "google"}
        )
        data = _parse_sse_data(sse)

        assert data["service"] == "google"

    def test_emit_input_required(self):
        """Input required event should have schema and context."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        sse = handler.emit_input_required(schema, "Please provide your name")
        data = _parse_sse_data(sse)

        assert data["schema"] == schema
        assert data["agent_slug"] == "test-agent"
        assert data["message"] == "Please provide your name"

    def test_emit_heartbeat_is_sse_comment(self):
        """Heartbeat should be SSE comment format (starts with ':')."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        hb = handler.emit_heartbeat()

        assert hb.startswith(": heartbeat ")
        assert hb.endswith("\n\n")

    def test_heartbeat_not_in_event_history(self):
        """Heartbeat should not be recorded in event history."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        handler.emit_connected()
        handler.emit_heartbeat()  # Should not be recorded
        handler.emit_heartbeat()  # Should not be recorded
        handler.emit_working()

        assert handler.get_event_count() == 2  # Only connected and working

    def test_get_events_returns_copy(self):
        """get_events should return a copy, not the original list."""
        handler = SMAStreamingHandler(
            task_id="test-task",
            trace_id="test-trace",
            agent_slug="test-agent",
        )

        handler.emit_connected()
        events = handler.get_events()
        events.append(None)  # Modify returned list

        # Original should be unchanged
        assert len(handler.get_events()) == 1


class TestSMAEventType:
    """Tests for SMAEventType enum."""

    def test_all_event_types_exist(self):
        """All expected event types should exist."""
        expected = [
            "CONNECTED", "WORKING", "THINKING", "CONTENT",
            "TOOL_CALL", "TOOL_RESULT", "AGENT_STEP", "TOKEN_UPDATE",
            "SYNTHESIZING", "DONE", "ERROR", "INPUT_REQUIRED"
        ]

        for name in expected:
            assert hasattr(SMAEventType, name)

    def test_event_type_values_are_lowercase(self):
        """Event type values should be lowercase for SSE."""
        assert SMAEventType.CONNECTED.value == "connected"
        assert SMAEventType.WORKING.value == "working"
        assert SMAEventType.DONE.value == "done"


class TestSMAErrorCode:
    """Tests for SMAErrorCode enum."""

    def test_all_error_codes_exist(self):
        """All expected error codes should exist."""
        expected = [
            "EXECUTION_ERROR", "MISSING_CREDENTIALS", "VALIDATION_ERROR",
            "TIMEOUT_ERROR", "CONTEXT_ERROR", "TOOL_ERROR", "UNKNOWN_ERROR"
        ]

        for name in expected:
            assert hasattr(SMAErrorCode, name)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _parse_sse_data(sse_string: str) -> dict:
    """Parse JSON data from SSE event string."""
    for line in sse_string.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise ValueError(f"No data line found in SSE: {sse_string}")
