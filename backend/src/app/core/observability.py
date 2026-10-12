import logging
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoreSpec:
    """Una métrica que se adjunta a la traza."""

    name: str
    value: float | str
    data_type: Literal["NUMERIC", "CATEGORICAL"] = "NUMERIC"
    comment: str | None = None


@dataclass
class TraceHandle:
    """Lo que el servicio recibe al abrir una traza. Vacío si Langfuse está desactivado."""

    callbacks: list[BaseCallbackHandler] = field(default_factory=list)
    trace_id: str | None = None
    _client: Langfuse | None = None
    _span: Any = None

    def record(self, *, inputs: Any, outputs: Any, scores: Sequence[ScoreSpec]) -> None:
        """Guarda entrada, salida y scores. Nunca lanza: observar no debe romper la app."""
        if self._client is None or self._span is None or self.trace_id is None:
            return
        try:
            self._span.update(input=inputs, output=outputs)
            for score in scores:
                self._send_score(self._client, score)
        except Exception:
            logger.exception("No se pudo registrar la información en Langfuse")

    def _send_score(self, client: Langfuse, score: ScoreSpec) -> None:
        if isinstance(score.value, str):
            client.create_score(
                trace_id=self.trace_id,
                name=score.name,
                value=score.value,
                data_type="CATEGORICAL",
                comment=score.comment,
            )
        else:
            client.create_score(
                trace_id=self.trace_id,
                name=score.name,
                value=float(score.value),
                data_type="NUMERIC",
                comment=score.comment,
            )


class Tracer(Protocol):
    def __call__(
        self,
        name: str,
        *,
        session_id: str | None,
        user_id: str | None,
        tags: Sequence[str],
        metadata: dict[str, str] | None,
    ) -> AbstractContextManager[TraceHandle]: ...


@lru_cache
def get_langfuse() -> Langfuse | None:
    """Crea el cliente una sola vez. Devuelve None si no hay claves."""
    s = get_settings()
    if not s.langfuse_enabled:
        return None
    return Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key.get_secret_value(),
        host=s.langfuse_host,
    )


@contextmanager
def noop_trace(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: Sequence[str] = (),
    metadata: dict[str, str] | None = None,
) -> Iterator[TraceHandle]:
    yield TraceHandle()


@contextmanager
def trace_query(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: Sequence[str] = (),
    metadata: dict[str, str] | None = None,
) -> Iterator[TraceHandle]:
    client = get_langfuse()
    if client is None:
        yield TraceHandle()
        return

    with client.start_as_current_observation(as_type="span", name=name) as span:
        with propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            tags=list(tags),
            metadata=metadata,
        ):
            yield TraceHandle(
                callbacks=[CallbackHandler()],
                trace_id=span.trace_id,
                _client=client,
                _span=span,
            )


def flush_observability() -> None:
    """Envía las trazas pendientes. Obligatorio en scripts que terminan rápido."""
    client = get_langfuse()
    if client is not None:
        client.flush()