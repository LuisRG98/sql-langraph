from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.llm import get_llm
from app.db.engine import get_readonly_engine
from app.db.guardrail import get_sql_validator
from app.db.schema import get_database_schema
from app.graph.builder import SqlAgent, build_graph, recursion_limit
from app.graph.nodes import GraphDeps
from app.graph.prompts import PROMPT_VERSION
from app.graph.state import initial_state

MAX_QUESTION_LENGTH = 500


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


class QueryService:
    def __init__(self, agent: SqlAgent, max_retries: int) -> None:
        self._agent = agent
        self._max_retries = max_retries

    def ask(self, question: str) -> QueryResponse:
        question = question.strip()
        if not question:
            raise ValueError("La pregunta no puede estar vacía.")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"La pregunta supera los {MAX_QUESTION_LENGTH} caracteres.")

        final = self._agent.invoke(
            initial_state(question, self._max_retries),
            config={"recursion_limit": recursion_limit(self._max_retries)},
        )

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
    return QueryService(build_graph(deps), max_retries=s.max_sql_retries)