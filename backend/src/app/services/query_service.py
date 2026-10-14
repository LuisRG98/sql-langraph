import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.llm import get_llm
from app.core.observability import ScoreSpec, TraceHandle, Tracer, noop_trace, trace_query
from app.db.engine import get_readonly_engine
from app.db.guardrail import get_sql_validator
from app.db.schema import get_database_schema
from app.graph.builder import SqlAgent, build_graph, recursion_limit
from app.graph.nodes import GraphDeps
from app.graph.prompts import PROMPT_VERSION
from app.graph.state import GraphState, initial_state
from app.services.stream_events import StreamEvent, result_event, step_event

MAX_QUESTION_LENGTH = 500
TRACE_NAME = "text2sql-query"


class InvalidQuestionError(ValueError):
    """La pregunta no cumple las reglas de entrada."""


class AttemptRecord(BaseModel):
    sql: str
    error: str


class QueryResponse(BaseModel):
    question: str
    status: Literal["success", "failed", "unanswerable"]
    answer: str
    sql: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    retries: int
    attempts: list[AttemptRecord]
    prompt_version: str


def build_scores(response: QueryResponse) -> list[ScoreSpec]:
    """Métricas que se adjuntan a cada traza para filtrar y analizar en Langfuse."""
    return [
        ScoreSpec("answered", 1.0 if response.status == "success" else 0.0),
        ScoreSpec("status", response.status, data_type="CATEGORICAL"),
        ScoreSpec("retries", float(response.retries)),
    ]


class QueryService:
    def __init__(
        self,
        agent: SqlAgent,
        max_retries: int,
        *,
        tracer: Tracer = noop_trace,
        environment: str = "development",
    ) -> None:
        self._agent = agent
        self._max_retries = max_retries
        self._tracer = tracer
        self._environment = environment

    # ---- API pública --------------------------------------------------

    @staticmethod
    def validate_question(question: str) -> str:
        """Devuelve la pregunta limpia o lanza InvalidQuestionError."""
        question = question.strip()
        if not question:
            raise InvalidQuestionError("La pregunta no puede estar vacía.")
        if len(question) > MAX_QUESTION_LENGTH:
            raise InvalidQuestionError(f"La pregunta supera los {MAX_QUESTION_LENGTH} caracteres.")
        return question

    def ask(
        self,
        question: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> QueryResponse:
        question = self.validate_question(question)
        with self._open_trace(session_id, user_id) as trace:
            final = self._agent.invoke(
                initial_state(question, self._max_retries),
                config=self._run_config(trace),
            )
            return self._finish(trace, question, final)

    def stream(
        self,
        question: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        cancel: threading.Event | None = None,
    ) -> Iterator[StreamEvent]:
        """Ejecuta el grafo emitiendo un evento por cada nodo terminado.

        Si `cancel` se activa, se detiene entre nodos (no se hacen más llamadas al LLM).
        Importante: este generador debe consumirse completo desde UN solo hilo, porque la
        traza de Langfuse vive en variables de contexto de ese hilo.
        """
        question = self.validate_question(question)
        with self._open_trace(session_id, user_id) as trace:
            final: GraphState = {}
            for mode, chunk in self._agent.stream(
                initial_state(question, self._max_retries),
                config=self._run_config(trace),
                stream_mode=["updates", "values"],
            ):
                if mode == "values":
                    final = chunk  # estado completo tras cada paso; el último es el final
                    continue
                for node, update in chunk.items():
                    yield step_event(node, update)
                if cancel is not None and cancel.is_set():
                    trace.record(
                        inputs={"question": question},
                        outputs={"status": "cancelled"},
                        scores=[ScoreSpec("status", "cancelled", data_type="CATEGORICAL")],
                    )
                    return
            response = self._finish(trace, question, final)
        yield result_event(response.model_dump(mode="json"))

    # ---- piezas compartidas -------------------------------------------

    def _open_trace(
        self, session_id: str | None, user_id: str | None
    ) -> AbstractContextManager[TraceHandle]:
        return self._tracer(
            TRACE_NAME,
            session_id=session_id,
            user_id=user_id,
            tags=[f"prompt:{PROMPT_VERSION}", f"env:{self._environment}"],
            metadata={
                "prompt_version": PROMPT_VERSION,
                "max_retries": str(self._max_retries),
            },
        )

    def _run_config(self, trace: TraceHandle) -> dict[str, Any]:
        return {
            "recursion_limit": recursion_limit(self._max_retries),
            "callbacks": trace.callbacks,
            "run_name": "text2sql-graph",
        }

    def _finish(self, trace: TraceHandle, question: str, final: GraphState) -> QueryResponse:
        response = self._to_response(question, final)
        trace.record(
            inputs={"question": question},
            outputs={
                "status": response.status,
                "sql": response.sql,
                "answer": response.answer,
                "retries": response.retries,
            },
            scores=build_scores(response),
        )
        return response

    @staticmethod
    def _to_response(question: str, final: GraphState) -> QueryResponse:
        result = final.get("result")
        status = final.get("status", "failed")
        if status == "running":  # no debería ocurrir; mejor fallar explícitamente
            status = "failed"

        return QueryResponse(
            question=question,
            status=status,
            answer=final.get("answer") or "",
            sql=final.get("safe_sql") or final.get("sql"),
            columns=result.columns if result else [],
            rows=result.rows if result else [],
            row_count=result.row_count if result else 0,
            truncated=result.truncated if result else False,
            retries=final.get("retries", 0),
            attempts=[AttemptRecord(**a) for a in final.get("attempts", [])],
            prompt_version=PROMPT_VERSION,
        )


@lru_cache
def get_query_service() -> QueryService:
    s = get_settings()
    deps = GraphDeps(
        llm=get_llm(),
        validator=get_sql_validator(),
        engine=get_readonly_engine(),
        schema_prompt=get_database_schema().to_prompt(),
        max_rows=s.max_rows,
        query_timeout=s.sql_timeout_seconds,
    )
    return QueryService(
        build_graph(deps),
        max_retries=s.max_sql_retries,
        tracer=trace_query,
        environment=s.app_env,
    )