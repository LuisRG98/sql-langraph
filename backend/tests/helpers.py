from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sqlalchemy import Engine

from app.core.observability import ScoreSpec, TraceHandle
from app.db.guardrail import SQLValidator
from app.db.hints import SCHEMA_HINTS
from app.db.schema import extract_schema
from app.graph.builder import build_graph
from app.graph.nodes import GraphDeps


class ScriptedChatModel(BaseChatModel):
    """LLM falso: responde con una lista de respuestas predefinidas, en orden.

    - Si un elemento es una excepción, la lanza (para simular fallos del proveedor).
    - Si el grafo pide más llamadas de las previstas, falla el test.
    - `calls` guarda los mensajes recibidos para poder inspeccionar los prompts.
    """

    responses: list[Any]
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        index = len(self.calls)
        self.calls.append(messages)
        if index >= len(self.responses):
            raise AssertionError(f"Llamada inesperada #{index + 1} al LLM falso")
        item = self.responses[index]
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=item))])


def text_of(message: BaseMessage) -> str:
    return str(message.content)


def build_test_agent(engine: Engine, llm: BaseChatModel, *, max_rows: int = 100) -> Any:
    schema = extract_schema(engine, hints=SCHEMA_HINTS)
    deps = GraphDeps(
        llm=llm,
        validator=SQLValidator(schema.table_names(), max_rows=max_rows),
        engine=engine,
        schema_prompt=schema.to_prompt(),
        max_rows=max_rows,
        query_timeout=5.0,
        today_fn=lambda: date(2026, 10, 7),
    )
    return build_graph(deps)

class CountingCallback(BaseCallbackHandler):
    """Cuenta cuántas veces se llamó a un modelo de chat."""

    def __init__(self) -> None:
        self.llm_calls = 0

    def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any
    ) -> Any:
        self.llm_calls += 1


class RecordingHandle(TraceHandle):
    def __init__(self, callback: CountingCallback) -> None:
        super().__init__(callbacks=[callback])
        self.recorded: dict[str, Any] | None = None

    def record(self, *, inputs: Any, outputs: Any, scores: Sequence[ScoreSpec]) -> None:
        self.recorded = {"inputs": inputs, "outputs": outputs, "scores": list(scores)}


class RecordingTracer:
    """Tracer falso: guarda cómo se abrió cada traza y qué se registró."""

    def __init__(self) -> None:
        self.opened: list[dict[str, Any]] = []
        self.handles: list[RecordingHandle] = []
        self.callback = CountingCallback()

    @contextmanager
    def __call__(
        self,
        name: str,
        *,
        session_id: str | None,
        user_id: str | None,
        tags: Sequence[str],
        metadata: dict[str, str] | None,
    ) -> Iterator[TraceHandle]:
        self.opened.append(
            {
                "name": name,
                "session_id": session_id,
                "user_id": user_id,
                "tags": list(tags),
                "metadata": metadata,
            }
        )
        handle = RecordingHandle(self.callback)
        self.handles.append(handle)
        yield handle