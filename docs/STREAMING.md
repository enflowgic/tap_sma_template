# SMA Streaming Implementation Guide

> **Version**: 1.0.0 | **Updated**: January 2026

This guide covers the SSE streaming implementation for TAP SMAs, including the `SMAStreamingHandler` class and best practices for Gateway-compatible streaming.

---

## Overview

TAP uses a **streaming-only architecture** for SMA invocation. The Gateway calls `POST /stream` and expects Server-Sent Events (SSE) with specific event types and structured payloads.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `SMAStreamingHandler` | `runtime/streaming.py` | Structured event emission |
| `SMAEventType` | `runtime/streaming.py` | Event type enum |
| `SMAErrorCode` | `runtime/streaming.py` | Structured error codes |
| `SMAStreamEvent` | `runtime/streaming.py` | Pydantic event model |
| Stream endpoint | `runtime/server.py` | `/stream` handler |

---

## Event Types Reference

### Lifecycle Events

| Event | When | Required |
|-------|------|----------|
| `connected` | Stream established | Yes |
| `working` | Processing started | Yes |
| `synthesizing` | Finalizing response | Yes |
| `done` | Task complete | Yes |
| `error` | Task failed | On error |

### Content Events

| Event | When | Required |
|-------|------|----------|
| `content` | Text chunk generated | Yes (on text) |
| `thinking` | LLM reasoning | Optional |

### Tool Events

| Event | When | Required |
|-------|------|----------|
| `tool_call` | Tool invoked | On tool use |
| `tool_result` | Tool completed | On tool use |

### Agent Events

| Event | When | Required |
|-------|------|----------|
| `agent_step` | Sub-agent transition | On multi-agent |
| `token_update` | Token count change | Recommended |

### Flow Events

| Event | When | Required |
|-------|------|----------|
| `input_required` | Need user input | On input flow |

---

## Event Structure

All events share a common structure:

```json
{
  "task_id": "task-abc123def456",
  "sequence": 1,
  "elapsed_ms": 0,
  "timestamp": "2026-01-22T10:30:45.123456+00:00",
  "message": "Connected to SMA",
  ...event-specific fields...
}
```

### Common Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique identifier for this streaming session |
| `sequence` | int | Monotonically increasing event number |
| `elapsed_ms` | int | Milliseconds since handler creation |
| `timestamp` | string | ISO 8601 UTC timestamp |
| `message` | string | Human-readable description (optional) |

### SSE Wire Format

```
id: task-abc123-1
event: connected
data: {"task_id":"task-abc123","sequence":1,"elapsed_ms":0,"timestamp":"...","message":"Connected to SMA","agent_slug":"my-agent","trace_id":"trace-xyz"}

```

Note: Double newline terminates each event.

---

## Using SMAStreamingHandler

### Basic Usage

```python
from runtime.streaming import SMAStreamingHandler, SMAErrorCode

async def generate():
    # Create handler at stream start
    handler = SMAStreamingHandler(
        task_id=f"task-{uuid4().hex[:16]}",
        trace_id=trace_id,
        agent_slug="my-agent",
        org_id=org_id,
        user_id=user_id,
    )

    # Emit connection events
    yield handler.emit_connected()
    yield handler.emit_working("Processing your request")

    # ... execute agent logic ...

    # Emit completion sequence
    yield handler.emit_synthesizing()
    yield handler.emit_done(
        accumulated_text="Response text here",
        input_tokens=150,
        output_tokens=50,
    )
```

### Content Streaming

```python
# Stream text content
chunk_index = 0
for text_chunk in text_chunks:
    yield handler.emit_content(text_chunk, chunk_index)
    chunk_index += 1
```

### Tool Events

```python
# Tool invocation
yield handler.emit_tool_call("web_search", {"query": "TAP platform"})

# Tool completion
yield handler.emit_tool_result("web_search", success=True, result_preview="Found 10 results...")
```

### Agent Steps (Multi-Agent Patterns)

```python
# Agent started
yield handler.emit_agent_step(1, "ResearchAgent", "started")

# ... agent executes ...

# Agent completed
yield handler.emit_agent_step(1, "ResearchAgent", "completed")

# Next agent
yield handler.emit_agent_step(2, "AnalysisAgent", "started")
```

### Token Updates

```python
# Emit cumulative token counts
yield handler.emit_token_update(input_tokens=100, output_tokens=25)
```

### Error Handling

```python
from runtime.streaming import SMAErrorCode

try:
    # ... agent logic ...
except MissingCredentialsError as e:
    yield handler.emit_error(
        str(e),
        SMAErrorCode.MISSING_CREDENTIALS,
        {"service": e.service}
    )
except Exception as e:
    yield handler.emit_error(str(e), SMAErrorCode.EXECUTION_ERROR)
```

---

## Critical: Partial Flag Check

### The Problem

ADK sends **two types** of text events:

1. `partial=True` events: **NEW** text chunks (emit these)
2. `partial=False` events: **COMPLETE** accumulated text (already included in partials)

Without checking the `partial` flag, you'll emit duplicate text.

### Wrong (Causes Duplication)

```python
# BAD - emits ALL text events, causing duplication
if hasattr(part, 'text') and part.text:
    accumulated_text += part.text
    yield handler.emit_content(part.text, chunk_index)
```

### Correct (Only New Chunks)

```python
# GOOD - only emits NEW text chunks
is_partial = getattr(event, 'partial', None)
if is_partial and hasattr(part, 'text') and part.text:
    accumulated_text += part.text
    yield handler.emit_content(part.text, chunk_index)
    chunk_index += 1
```

---

## Error Codes Reference

```python
class SMAErrorCode(str, Enum):
    EXECUTION_ERROR = "EXECUTION_ERROR"         # General agent execution failure
    MISSING_CREDENTIALS = "MISSING_CREDENTIALS" # OAuth/API key needed
    VALIDATION_ERROR = "VALIDATION_ERROR"       # Input validation failed
    TIMEOUT_ERROR = "TIMEOUT_ERROR"             # Operation timed out
    CONTEXT_ERROR = "CONTEXT_ERROR"             # Context assembly failed
    TOOL_ERROR = "TOOL_ERROR"                   # Tool execution failed
    UNKNOWN_ERROR = "UNKNOWN_ERROR"             # Catch-all
```

Gateway and Frontend can use these codes for:
- Retry logic (some errors are retryable)
- User-friendly error messages
- Metrics and alerting

---

## Heartbeat Implementation

During long operations (tool calls, LLM thinking), emit heartbeats to prevent Gateway timeout:

```python
async def iter_with_heartbeats(async_iter, heartbeat_interval=15.0):
    """Wrap ADK event stream to inject heartbeats."""
    async_it = aiter(async_iter)
    while True:
        try:
            async with asyncio.timeout(heartbeat_interval):
                event = await anext(async_it)
                yield ("event", event)
        except TimeoutError:
            yield ("heartbeat", handler.emit_heartbeat())
        except StopAsyncIteration:
            break

# In your stream handler:
async for event_type, event_or_hb in iter_with_heartbeats(adk_stream):
    if event_type == "heartbeat":
        yield event_or_hb  # Raw SSE comment
        continue
    # Process ADK event...
```

Heartbeat format (SSE comment, ignored by EventSource):
```
: heartbeat 2026-01-22T10:30:45.123456+00:00

```

---

## SSE Event IDs for Reconnection

Events include SSE `id:` lines for client reconnection support:

```
id: task-abc123-5
event: content
data: {"task_id":"task-abc123","sequence":5,...}

```

If a client disconnects and reconnects with:
```
Last-Event-ID: task-abc123-5
```

The server could (optionally) replay events after sequence 5.

---

## Response Headers

The `/stream` endpoint must return these headers:

```python
return StreamingResponse(
    generate(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",      # Prevent caching
        "X-Accel-Buffering": "no",        # Disable nginx buffering
        "Connection": "keep-alive",        # Keep connection open
        "X-Request-ID": trace_id,          # Tracing correlation
    },
)
```

---

## Event History (Debugging)

`SMAStreamingHandler` keeps a record of all emitted events:

```python
# Get all events (for debugging/testing)
events = handler.get_events()

# Get event count
count = handler.get_event_count()

# Log on completion
logger.info(f"Stream completed: events={handler.get_event_count()}")
```

---

## Gateway Compatibility

Gateway's `invoke_sma_streaming()` in `agent_client.py` expects:

1. **SSE format**: `event: type\ndata: json\n\n`
2. **Event types**: `connected`, `working`, `content`, `tool_call`, `tool_result`, `thinking`, `agent_step`, `token_update`, `synthesizing`, `done`, `error`
3. **Token tracking**: `token_update` events with cumulative counts
4. **Final event**: `done` with `is_final: true` and final token counts

---

## Testing Streaming

### Local Testing with curl

```bash
curl -N -X POST http://localhost:8080/stream \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "task/sendSubscribe",
    "params": {
      "message": {"parts": [{"type": "text", "text": "Hello"}]},
      "context": {}
    },
    "id": "1"
  }'
```

### Verify Output

Look for:
- `id:` lines for reconnection support
- `sequence` incrementing in each event
- `task_id` same across all events
- `synthesizing` event before `done`
- No duplicate text content

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Duplicate text in response | Not checking `partial` flag | Add `is_partial = getattr(event, 'partial', None)` check |
| Gateway timeout | No heartbeats during long ops | Use `iter_with_heartbeats()` wrapper |
| Events arrive in bursts | Proxy buffering | Check `X-Accel-Buffering: no` header |
| Missing synthesizing event | Not emitting before done | Add `handler.emit_synthesizing()` |
| Events can't be correlated | No task_id | Use SMAStreamingHandler (auto-includes) |
| Can't detect dropped events | No sequence numbers | Use SMAStreamingHandler (auto-includes) |
