from datetime import date
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sqlalchemy import Engine

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