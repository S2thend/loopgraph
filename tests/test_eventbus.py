"""Tests for EventBus error handling."""

from __future__ import annotations

import pytest

from eventflow.bus.eventbus import Event, EventBus
from eventflow.core.types import EventType


def _make_event(event_id: str = "evt-1") -> Event:
    return Event(
        id=event_id,
        graph_id="g1",
        node_id="n1",
        type=EventType.NODE_COMPLETED,
    )


@pytest.mark.asyncio
async def test_emit_without_on_error_swallows_exceptions() -> None:
    """Without on_error, exceptions are captured in results but not raised."""
    bus = EventBus()

    async def failing_listener(event: Event) -> None:
        raise ValueError("listener failed")

    bus.subscribe(None, failing_listener)
    results = await bus.emit(_make_event())

    assert len(results) == 1
    assert isinstance(results[0], ValueError)
    assert str(results[0]) == "listener failed"


@pytest.mark.asyncio
async def test_emit_with_on_error_invokes_handler() -> None:
    """With on_error, handler is invoked for each exception."""
    errors_received: list[tuple[Exception, Event]] = []

    async def error_handler(exc: Exception, event: Event) -> None:
        errors_received.append((exc, event))

    bus = EventBus(on_error=error_handler)

    async def failing_listener(event: Event) -> None:
        raise ValueError("listener failed")

    bus.subscribe(None, failing_listener)
    event = _make_event()
    await bus.emit(event)

    assert len(errors_received) == 1
    exc, received_event = errors_received[0]
    assert isinstance(exc, ValueError)
    assert str(exc) == "listener failed"
    assert received_event is event


@pytest.mark.asyncio
async def test_emit_on_error_can_raise() -> None:
    """If on_error raises, the exception propagates to caller."""
    async def raising_error_handler(exc: Exception, event: Event) -> None:
        raise RuntimeError(f"critical error handling {exc}")

    bus = EventBus(on_error=raising_error_handler)

    async def failing_listener(event: Event) -> None:
        raise ValueError("original error")

    bus.subscribe(None, failing_listener)

    with pytest.raises(RuntimeError) as exc_info:
        await bus.emit(_make_event())

    assert "critical error handling" in str(exc_info.value)


@pytest.mark.asyncio
async def test_emit_multiple_listeners_multiple_errors() -> None:
    """on_error is called for each failing listener."""
    errors_received: list[str] = []

    async def error_handler(exc: Exception, event: Event) -> None:
        errors_received.append(str(exc))

    bus = EventBus(on_error=error_handler)

    async def failing_listener_1(event: Event) -> None:
        raise ValueError("error 1")

    async def failing_listener_2(event: Event) -> None:
        raise ValueError("error 2")

    async def success_listener(event: Event) -> None:
        pass

    bus.subscribe(None, failing_listener_1)
    bus.subscribe(None, success_listener)
    bus.subscribe(None, failing_listener_2)

    results = await bus.emit(_make_event())

    assert len(results) == 3
    assert len(errors_received) == 2
    assert "error 1" in errors_received
    assert "error 2" in errors_received


@pytest.mark.asyncio
async def test_emit_on_error_stops_at_first_raise() -> None:
    """If on_error raises on first error, subsequent errors aren't processed."""
    errors_processed: list[str] = []

    async def raising_on_first_error(exc: Exception, event: Event) -> None:
        errors_processed.append(str(exc))
        if "error 1" in str(exc):
            raise RuntimeError("stopping on first error")

    bus = EventBus(on_error=raising_on_first_error)

    async def failing_listener_1(event: Event) -> None:
        raise ValueError("error 1")

    async def failing_listener_2(event: Event) -> None:
        raise ValueError("error 2")

    bus.subscribe(None, failing_listener_1)
    bus.subscribe(None, failing_listener_2)

    with pytest.raises(RuntimeError):
        await bus.emit(_make_event())

    # Only the first error was processed before on_error raised
    assert len(errors_processed) == 1
    assert "error 1" in errors_processed[0]


@pytest.mark.asyncio
async def test_emit_success_does_not_invoke_on_error() -> None:
    """on_error is not invoked when all listeners succeed."""
    errors_received: list[Exception] = []

    async def error_handler(exc: Exception, event: Event) -> None:
        errors_received.append(exc)

    bus = EventBus(on_error=error_handler)

    received_events: list[str] = []

    async def success_listener(event: Event) -> None:
        received_events.append(event.id)

    bus.subscribe(None, success_listener)
    await bus.emit(_make_event("evt-success"))

    assert len(received_events) == 1
    assert received_events[0] == "evt-success"
    assert len(errors_received) == 0
