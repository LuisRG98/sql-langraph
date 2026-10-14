import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator

from app.api.errors import classify_error
from app.services.stream_events import StreamEvent, error_event

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0
KEEP_ALIVE = ": keep-alive\n\n"


def format_sse(event: StreamEvent) -> str:
    """Formato SSE: `json.dumps` escapa los saltos de línea, así `data:` ocupa una sola línea."""
    payload = json.dumps(event.data, ensure_ascii=False, default=str)
    return f"event: {event.event}\ndata: {payload}\n\n"


async def sse_stream(
    make_events: Callable[[threading.Event], Iterator[StreamEvent]],
    *,
    request_id: str,
    heartbeat: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """Ejecuta `make_events` en un hilo y entrega sus eventos como texto SSE.

    - Todo el generador corre en UN hilo (la traza de Langfuse depende de eso).
    - Si el cliente se desconecta, se activa `cancel` y el trabajo se detiene entre nodos.
    - Cualquier excepción del hilo se convierte en un evento `error`.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
    cancel = threading.Event()

    def push(item: StreamEvent | None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # el bucle de eventos ya se cerró (apagado del servidor)
            cancel.set()

    def produce() -> None:
        try:
            for event in make_events(cancel):
                push(event)
        except Exception as exc:
            status, detail = classify_error(exc, request_id)
            push(error_event(status, detail))
        finally:
            push(None)  # señal de "terminé"

    threading.Thread(target=produce, name="sse-producer", daemon=True).start()

    finished = False
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield KEEP_ALIVE
                continue
            if item is None:
                finished = True
                return
            yield format_sse(item)
    finally:
        if not finished:
            logger.info("Cliente desconectado; se cancela la consulta (request_id=%s)", request_id)
        cancel.set()