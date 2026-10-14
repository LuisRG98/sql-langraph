import threading
from collections.abc import Iterator

from app.api.streaming import KEEP_ALIVE, format_sse, sse_stream
from app.services.stream_events import StreamEvent, error_event


def test_format_sse_shape() -> None:
    event = StreamEvent("step", {"label": "Validación", "n": 1})
    assert format_sse(event) == 'event: step\ndata: {"label": "Validación", "n": 1}\n\n'


def test_format_sse_keeps_newlines_inside_one_data_line() -> None:
    text = format_sse(StreamEvent("step", {"detail": "línea 1\nlínea 2"}))
    assert text.count("\n") == 3  # event, data y la línea en blanco
    assert "\\n" in text


async def test_events_are_delivered_in_order() -> None:
    def make(cancel: threading.Event) -> Iterator[StreamEvent]:
        yield StreamEvent("step", {"n": 1})
        yield StreamEvent("step", {"n": 2})
        yield StreamEvent("result", {"ok": True})

    chunks = [chunk async for chunk in sse_stream(make, request_id="r1")]
    assert chunks == [
        format_sse(StreamEvent("step", {"n": 1})),
        format_sse(StreamEvent("step", {"n": 2})),
        format_sse(StreamEvent("result", {"ok": True})),
    ]


async def test_unexpected_error_becomes_a_safe_error_event() -> None:
    def make(cancel: threading.Event) -> Iterator[StreamEvent]:
        raise RuntimeError("boom con detalles internos")

    chunks = [chunk async for chunk in sse_stream(make, request_id="abc123")]
    assert chunks == [format_sse(error_event(500, "Error interno. Referencia: abc123"))]
    assert "boom" not in "".join(chunks)


async def test_provider_quota_error_becomes_a_429_event() -> None:
    def make(cancel: threading.Event) -> Iterator[StreamEvent]:
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")

    chunks = [chunk async for chunk in sse_stream(make, request_id="r1")]
    assert len(chunks) == 1
    assert chunks[0].startswith("event: error")
    assert '"status": 429' in chunks[0]


async def test_events_before_an_error_are_still_delivered() -> None:
    def make(cancel: threading.Event) -> Iterator[StreamEvent]:
        yield StreamEvent("step", {"n": 1})
        raise RuntimeError("quota exceeded")

    chunks = [chunk async for chunk in sse_stream(make, request_id="r1")]
    assert chunks[0].startswith("event: step")
    assert chunks[1].startswith("event: error")


async def test_heartbeat_is_sent_while_waiting() -> None:
    release = threading.Event()

    def make(cancel: threading.Event) -> Iterator[StreamEvent]:
        release.wait(timeout=2)
        yield StreamEvent("result", {"ok": True})

    stream = sse_stream(make, request_id="r1", heartbeat=0.05)
    assert await anext(stream) == KEEP_ALIVE

    release.set()
    rest = [chunk async for chunk in stream]
    assert any(chunk.startswith("event: result") for chunk in rest)


async def test_closing_the_stream_sets_the_cancel_flag() -> None:
    captured: list[threading.Event] = []
    gate = threading.Event()

    def make(cancel: threading.Event) -> Iterator[StreamEvent]:
        captured.append(cancel)
        yield StreamEvent("step", {"n": 1})
        gate.wait(timeout=2)
        yield StreamEvent("step", {"n": 2})

    stream = sse_stream(make, request_id="r1")
    await anext(stream)  # el cliente recibe el primer evento...
    await stream.aclose()  # ...y se desconecta

    assert captured[0].is_set()
    gate.set()  # libera el hilo para que termine limpio