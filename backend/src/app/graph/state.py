import operator
from typing import Annotated, Literal, TypedDict

from app.db.executor import QueryResult

Status = Literal["running", "success", "failed", "unanswerable"]


class Attempt(TypedDict):
    sql: str
    error: str


class GraphState(TypedDict, total=False):
    question: str
    sql: str | None                # SQL tal cual lo escribió el LLM
    safe_sql: str | None           # SQL validado y regenerado desde el AST
    tables: list[str]
    error: str | None              # error del último paso (validación o ejecución)
    retries: int                   # correcciones ya realizadas
    max_retries: int
    attempts: Annotated[list[Attempt], operator.add]   # historial de fallos (reducer)
    result: QueryResult | None
    answer: str | None
    status: Status


def initial_state(question: str, max_retries: int) -> GraphState:
    return {
        "question": question,
        "sql": None,
        "safe_sql": None,
        "tables": [],
        "error": None,
        "retries": 0,
        "max_retries": max_retries,
        "attempts": [],
        "result": None,
        "answer": None,
        "status": "running",
    }