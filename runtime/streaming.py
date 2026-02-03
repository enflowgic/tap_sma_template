"""
SMA Streaming Handler - SSE Streaming Utilities for TAP Template Agent

Implements A2A task/sendSubscribe compliant Server-Sent Events (SSE) streaming.
Matches Gateway's expected event format for proper integration.

This module provides structured streaming events with:
- Sequence numbering for dropped event detection
- Task ID correlation across events
- Elapsed time tracking for observability
- Error codes for structured error handling
- SSE event IDs for client reconnection support

Event Types:
- connected: Initial connection established
- working: Task execution started
- thinking: LLM reasoning tokens (if model supports)
- content: Response text chunks (PARTIAL ONLY - critical!)
- tool_call: Tool invocation
- tool_result: Tool completion
- agent_step: Sub-agent transitions (for SequentialAgent)
- token_update: Real-time token counts
- synthesizing: Creating final response
- done: Task completed successfully
- error: Task failed
- input_required: Need structured input from user

Usage:
    handler = SMAStreamingHandler(task_id, trace_id, agent_slug)
    yield handler.emit_connected()
    yield handler.emit_working()
    # ... stream content, tools, etc. ...
    yield handler.emit_synthesizing()
    yield handler.emit_done(text, input_tokens, output_tokens)
"""

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# EVENT TYPES
# =============================================================================

class SMAEventType(str, Enum):
    """A2A task event types for SMA SSE streaming.

    These event types match Gateway's expected format in agent_client.py.
    """

    # Connection lifecycle
    CONNECTED = "connected"

    # Execution states
    WORKING = "working"
    THINKING = "thinking"
    CONTENT = "content"

    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Agent hierarchy events (for SequentialAgent, ParallelAgent, etc.)
    AGENT_STEP = "agent_step"

    # Token tracking for billing
    TOKEN_UPDATE = "token_update"

    # Completion events
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    ERROR = "error"

    # Input flow
    INPUT_REQUIRED = "input_required"


# =============================================================================
# ERROR CODES
# =============================================================================

class SMAErrorCode(str, Enum):
    """Standard error codes for SMA streaming errors.

    These codes enable programmatic error handling in Gateway and Frontend.
    """

    EXECUTION_ERROR = "EXECUTION_ERROR"         # General agent execution failure
    MISSING_CREDENTIALS = "MISSING_CREDENTIALS" # OAuth/API key needed
    VALIDATION_ERROR = "VALIDATION_ERROR"       # Input validation failed
    TIMEOUT_ERROR = "TIMEOUT_ERROR"             # Operation timed out
    CONTEXT_ERROR = "CONTEXT_ERROR"             # Context assembly failed
    TOOL_ERROR = "TOOL_ERROR"                   # Tool execution failed
    UNKNOWN_ERROR = "UNKNOWN_ERROR"             # Catch-all for unexpected errors


# =============================================================================
# EVENT MODELS
# =============================================================================

class SMAStreamEvent(BaseModel):
    """SSE event for SMA task status updates.

    This model matches the structure expected by Gateway's invoke_sma_streaming()
    and provides consistent event formatting across all SMA implementations.

    Attributes:
        task_id: Unique identifier for this streaming task
        event_type: Type of event (from SMAEventType enum)
        message: Human-readable message (optional)
        data: Event-specific payload data (optional)
        timestamp: ISO 8601 timestamp in UTC
        sequence: Monotonically increasing event number
        elapsed_ms: Milliseconds since handler creation
    """

    task_id: str
    event_type: SMAEventType
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence: int = 0
    elapsed_ms: int = 0

    def to_sse(self, event_id: Optional[str] = None) -> str:
        """Format as Server-Sent Event string.

        Args:
            event_id: Optional event ID for client reconnection support.
                     If provided, clients can use Last-Event-ID header to resume.

        Returns:
            SSE-formatted string ready to yield to StreamingResponse
        """
        lines = []

        # Add event ID for client reconnection support
        if event_id:
            lines.append(f"id: {event_id}")

        # Event type line
        lines.append(f"event: {self.event_type.value}")

        # Data line (JSON payload)
        lines.append(f"data: {json.dumps(self.to_dict())}")

        # Empty line to end event
        lines.append("")

        return "\n".join(lines) + "\n"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE data payload.

        The data dict is flattened: task_id, sequence, elapsed_ms, timestamp
        are included at the top level, and self.data fields are merged in.
        """
        result = {
            "task_id": self.task_id,
            "sequence": self.sequence,
            "elapsed_ms": self.elapsed_ms,
            "timestamp": self.timestamp,
        }

        if self.message:
            result["message"] = self.message

        if self.data:
            result.update(self.data)

        return result


# =============================================================================
# STREAMING HANDLER
# =============================================================================

class SMAStreamingHandler:
    """
    Handles SSE streaming for SMA A2A task/sendSubscribe.

    This class provides structured event emission with automatic:
    - Sequence numbering for dropped event detection
    - Elapsed time tracking for observability
    - Event history for debugging
    - SSE event IDs for client reconnection

    Key Features:
    - All events include task_id for request-response correlation
    - Sequence numbers allow clients to detect lost events
    - Elapsed time enables latency monitoring
    - Event history supports debugging and testing
    - Convenience methods ensure consistent event formatting

    Usage:
        handler = SMAStreamingHandler(
            task_id="task-abc123",
            trace_id="trace-xyz789",
            agent_slug="my-agent"
        )

        async def stream():
            yield handler.emit_connected()
            yield handler.emit_working("Processing request")

            # Stream content (ONLY on partial=True events!)
            yield handler.emit_content("Hello ")
            yield handler.emit_content("world!")

            # Tool usage
            yield handler.emit_tool_call("search", {"query": "..."})
            yield handler.emit_tool_result("search", True, "Found 5 results")

            # Token updates for billing
            yield handler.emit_token_update(150, 42)

            # Completion sequence
            yield handler.emit_synthesizing()
            yield handler.emit_done(
                accumulated_text="Hello world!",
                input_tokens=150,
                output_tokens=42
            )

    Critical Pattern - Partial Flag Check:
        When streaming ADK events, ONLY emit content for partial=True events:

        is_partial = getattr(event, 'partial', None)
        if is_partial and hasattr(part, 'text') and part.text:
            yield handler.emit_content(part.text, chunk_index)
            chunk_index += 1

        ADK sends both partial (new text) and non-partial (accumulated text).
        Without this check, text will be duplicated in the response.
    """

    def __init__(
        self,
        task_id: str,
        trace_id: str,
        agent_slug: str,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Initialize streaming handler.

        Args:
            task_id: Unique identifier for this streaming task
            trace_id: Distributed tracing ID for observability
            agent_slug: SMA identifier (e.g., "ai-software-researcher")
            org_id: Organization ID (optional, for context)
            user_id: User ID (optional, for context)

        Raises:
            ValueError: If required parameters are empty or invalid
        """
        # Validate required parameters
        if not task_id or not isinstance(task_id, str):
            raise ValueError("task_id must be a non-empty string")
        if not trace_id or not isinstance(trace_id, str):
            raise ValueError("trace_id must be a non-empty string")
        if not agent_slug or not isinstance(agent_slug, str):
            raise ValueError("agent_slug must be a non-empty string")

        self.task_id = task_id
        self.trace_id = trace_id
        self.agent_slug = agent_slug
        self.org_id = org_id or ""
        self.user_id = user_id or ""

        # Event tracking
        self._sequence = 0
        self._events: List[SMAStreamEvent] = []
        self._start_time = datetime.now(timezone.utc)

        # Configuration
        self._include_event_ids = True  # Enable SSE event IDs for reconnection

    def _next_sequence(self) -> int:
        """Get next sequence number (auto-increment)."""
        self._sequence += 1
        return self._sequence

    def _elapsed_ms(self) -> int:
        """Get elapsed milliseconds since handler creation."""
        return int((datetime.now(timezone.utc) - self._start_time).total_seconds() * 1000)

    def _create_event(
        self,
        event_type: SMAEventType,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create and record an SSE event.

        Args:
            event_type: Type of event from SMAEventType enum
            message: Human-readable message (optional)
            data: Event-specific payload data (optional)

        Returns:
            SSE-formatted string ready to yield
        """
        sequence = self._next_sequence()

        event = SMAStreamEvent(
            task_id=self.task_id,
            event_type=event_type,
            message=message,
            data=data,
            sequence=sequence,
            elapsed_ms=self._elapsed_ms(),
        )

        # Record for debugging/testing
        self._events.append(event)

        # Generate event ID for reconnection support
        event_id = f"{self.task_id}-{sequence}" if self._include_event_ids else None

        return event.to_sse(event_id=event_id)

    # =========================================================================
    # CONNECTION LIFECYCLE EVENTS
    # =========================================================================

    def emit_connected(self) -> str:
        """Emit connection established event.

        This should be the first event emitted when streaming begins.
        """
        return self._create_event(
            SMAEventType.CONNECTED,
            message="Connected to SMA",
            data={
                "agent_slug": self.agent_slug,
                "trace_id": self.trace_id,
            }
        )

    def emit_working(self, message: str = "Processing request") -> str:
        """Emit working status event.

        Emitted after connected, before any content is generated.
        Provides immediate feedback while ADK initializes.
        """
        return self._create_event(
            SMAEventType.WORKING,
            message=message,
            data={"status": "processing"}
        )

    # =========================================================================
    # CONTENT STREAMING EVENTS
    # =========================================================================

    def emit_content(self, text: str, chunk_index: int = 0) -> str:
        """Stream response content text.

        CRITICAL: Only call this for ADK events where partial=True!

        ADK sends two types of text events:
        - partial=True: NEW text chunks (emit these)
        - partial=False: COMPLETE accumulated text (skip these)

        Without checking partial flag, text will be duplicated.

        Args:
            text: Text chunk to stream
            chunk_index: Sequential index of this chunk
        """
        return self._create_event(
            SMAEventType.CONTENT,
            data={
                "text": text,
                "partial": True,
                "index": chunk_index,
            }
        )

    def emit_thinking(self, text: str) -> str:
        """Stream LLM reasoning tokens.

        Only emitted if the underlying model supports thinking/reasoning output
        (e.g., some Gemini models with thought parts).
        """
        return self._create_event(
            SMAEventType.THINKING,
            data={"content": text}
        )

    # =========================================================================
    # TOOL EVENTS
    # =========================================================================

    def emit_tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Emit tool invocation event.

        Args:
            tool_name: Name of the tool being called
            args: Arguments passed to the tool
        """
        return self._create_event(
            SMAEventType.TOOL_CALL,
            message=f"Calling {tool_name}",
            data={
                "tool_name": tool_name,
                "args": args,
                "status": "calling",
            }
        )

    def emit_tool_result(
        self,
        tool_name: str,
        success: bool,
        result_preview: Optional[str] = None,
    ) -> str:
        """Emit tool completion event.

        Args:
            tool_name: Name of the tool that completed
            success: Whether the tool succeeded
            result_preview: Truncated preview of result (optional)
        """
        return self._create_event(
            SMAEventType.TOOL_RESULT,
            message=f"{tool_name} {'completed' if success else 'failed'}",
            data={
                "tool_name": tool_name,
                "status": "completed" if success else "failed",
                "result": result_preview,
            }
        )

    # =========================================================================
    # AGENT STEP EVENTS
    # =========================================================================

    def emit_agent_step(
        self,
        step: int,
        agent_name: str,
        status: str = "started",
    ) -> str:
        """Emit agent step event (for multi-agent patterns).

        Used with SequentialAgent, ParallelAgent, etc. to track
        which sub-agent is currently executing.

        Args:
            step: Step number (1-indexed)
            agent_name: Name of the sub-agent
            status: "started" or "completed"
        """
        return self._create_event(
            SMAEventType.AGENT_STEP,
            data={
                "step": step,
                "agent_name": agent_name,
                "status": status,
            }
        )

    # =========================================================================
    # TOKEN TRACKING EVENTS
    # =========================================================================

    def emit_token_update(self, input_tokens: int, output_tokens: int) -> str:
        """Emit real-time token count update.

        Gateway uses these for per-turn billing calculations.
        Values should be cumulative totals, not deltas.

        Args:
            input_tokens: Cumulative input token count
            output_tokens: Cumulative output token count
        """
        return self._create_event(
            SMAEventType.TOKEN_UPDATE,
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )

    # =========================================================================
    # COMPLETION EVENTS
    # =========================================================================

    def emit_synthesizing(self) -> str:
        """Emit synthesizing status (creating final response).

        This should be emitted after all content is streamed but
        before the done event. Gateway expects this event.
        """
        return self._create_event(
            SMAEventType.SYNTHESIZING,
            message="Creating final response",
            data={"status": "creating_response"}
        )

    def emit_done(
        self,
        accumulated_text: str,
        input_tokens: int,
        output_tokens: int,
    ) -> str:
        """Emit task completion event.

        This should be the last event emitted. Includes final token
        counts for billing reconciliation.

        Args:
            accumulated_text: Complete response text
            input_tokens: Final input token count
            output_tokens: Final output token count
        """
        return self._create_event(
            SMAEventType.DONE,
            message="Execution complete",
            data={
                "text": accumulated_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "is_final": True,
                "total_events": len(self._events) + 1,
            }
        )

    def emit_error(
        self,
        error_message: str,
        error_code: SMAErrorCode = SMAErrorCode.UNKNOWN_ERROR,
        error_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Emit task failure event with structured error code.

        Args:
            error_message: Human-readable error description
            error_code: Machine-readable error code from SMAErrorCode
            error_data: Additional error context (optional)
        """
        data = {
            "error": error_message,
            "error_code": error_code.value,
        }
        if error_data:
            data.update(error_data)

        return self._create_event(
            SMAEventType.ERROR,
            message=error_message,
            data=data
        )

    # =========================================================================
    # INPUT FLOW EVENTS
    # =========================================================================

    def emit_input_required(
        self,
        schema: Dict[str, Any],
        context_message: str,
        prefilled_values: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Emit input required event (SMA needs structured input).

        Used when the SMA needs additional information from the user
        that should be collected via a form.

        Args:
            schema: JSON Schema for required input
            context_message: Explanation of what's needed
            prefilled_values: Any values already collected (optional)
        """
        return self._create_event(
            SMAEventType.INPUT_REQUIRED,
            message=context_message,
            data={
                "schema": schema,
                "agent_slug": self.agent_slug,
                "prefilled_values": prefilled_values,
            }
        )

    # =========================================================================
    # HEARTBEAT (NOT A TRACKED EVENT)
    # =========================================================================

    def emit_heartbeat(self) -> str:
        """Emit SSE heartbeat comment to keep connection alive.

        SSE comments (lines starting with ':') are ignored by EventSource
        parsers but keep the TCP connection alive and prevent proxy timeouts.

        NOT tracked in event history since it's just a keep-alive.
        Recommended interval: every 15 seconds during idle periods.

        Returns:
            Raw SSE comment string (not a full event)
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        return f": heartbeat {timestamp}\n\n"

    # =========================================================================
    # EVENT HISTORY (FOR DEBUGGING/TESTING)
    # =========================================================================

    def get_events(self) -> List[SMAStreamEvent]:
        """Get all emitted events (for debugging/testing).

        Returns a copy of the internal event list.
        """
        return self._events.copy()

    def get_event_count(self) -> int:
        """Get number of emitted events."""
        return len(self._events)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "SMAEventType",
    "SMAErrorCode",
    # Models
    "SMAStreamEvent",
    # Handler
    "SMAStreamingHandler",
]
