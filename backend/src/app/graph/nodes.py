import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from sqlalchemy import Engine

from app.db.executor import QueryExecutionError, execute_query
from app.db.guardrail import SQLValidator
from app.graph.parsing import content_to_text, extract_sql, is_cannot_answer
from app.graph.prompts import (
    build_explain_messages,
    build_fix_messages,
    build_generate_messages,
)
from app.graph.state import Attempt, GraphState

logger = logging.getLogger(__name__)

StateUpdate = dict[str, Any]

# Filas máximas que se envían al LLM para explicar el resultado (ahorra tokens y cuota).
EXPLAIN_MAX_ROWS = 20


@dataclass(frozen=True)
class GraphDeps:
    llm: BaseChatModel
    validator: SQLValidator
    engine: Engine
    schema_prompt: str
    max_rows: int = 100
    query_timeout: float = 5.0
    today_fn: Callable[[], date] = date.today


class SqlAgentNodes:
    def __init__(self, deps: GraphDeps) -> None:
        self._deps = deps

    def _ask(self, messages: list[BaseMessage]) -> str:
        return content_to_text(self._deps.llm.invoke(messages).content)

    # ---- generar ------------------------------------------------------

    def generate_sql(self, state: GraphState) -> StateUpdate:
        deps = self._deps
        raw = self._ask(
            build_generate_messages(state["question"], deps.schema_prompt, deps.today_fn())
        )
        sql = extract_sql(raw)
        if is_cannot_answer(sql):
            return {"sql": None, "status": "unanswerable"}
        return {"sql": sql, "safe_sql": None, "error": None}

    # ---- validar ------------------------------------------------------

    def validate_sql(self, state: GraphState) -> StateUpdate:
        sql = state.get("sql") or ""
        result = self._deps.validator.validate(sql)
        if result.valid:
            return {"safe_sql": result.sql, "tables": result.tables, "error": None}

        error = result.error or "Invalid SQL."
        return {
            "safe_sql": None,
            "error": error,
            "attempts": [Attempt(sql=sql, error=error)],
        }

    # ---- ejecutar -----------------------------------------------------

    def execute_sql(self, state: GraphState) -> StateUpdate:
        safe_sql = state.get("safe_sql")
        if not safe_sql:
            error = "There is no validated SQL to execute."
            return {"result": None, "error": error, "attempts": [Attempt(sql="", error=error)]}

        try:
            result = execute_query(
                self._deps.engine,
                safe_sql,
                max_rows=self._deps.max_rows,
                timeout_seconds=self._deps.query_timeout,
            )
        except QueryExecutionError as exc:
            error = str(exc)
            return {
                "result": None,
                "error": error,
                "attempts": [Attempt(sql=safe_sql, error=error)],
            }
        return {"result": result, "error": None}

    # ---- corregir -----------------------------------------------------

    def fix_sql(self, state: GraphState) -> StateUpdate:
        deps = self._deps
        raw = self._ask(
            build_fix_messages(
                state["question"],
                deps.schema_prompt,
                deps.today_fn(),
                state.get("attempts", []),
            )
        )
        return {
            "sql": extract_sql(raw),
            "safe_sql": None,
            "error": None,
            "retries": state.get("retries", 0) + 1,
        }

    # ---- explicar -----------------------------------------------------

    def explain_result(self, state: GraphState) -> StateUpdate:
        result = state.get("result")
        if result is None:
            return {"status": "failed", "answer": "No hay resultados para explicar."}

        data_json = json.dumps(
            {
                "columns": result.columns,
                "rows": result.rows[:EXPLAIN_MAX_ROWS],
                "total_rows": result.row_count,
                "truncated": result.truncated or result.row_count > EXPLAIN_MAX_ROWS,
            },
            ensure_ascii=False,
            default=str,
        )
        try:
            answer = self._ask(build_explain_messages(state["question"], data_json)).strip()
        except Exception:
            # La consulta ya funcionó: no se pierde el resultado por fallar la explicación.
            logger.exception("No se pudo generar la explicación")
            answer = f"La consulta devolvió {result.row_count} fila(s). Revisa la tabla de resultados."
        return {"status": "success", "answer": answer}

    # ---- salidas alternativas -----------------------------------------

    def reject_question(self, state: GraphState) -> StateUpdate:
        return {
            "status": "unanswerable",
            "answer": (
                "No puedo responder esa pregunta con los datos disponibles. "
                "Prueba con preguntas sobre clientes, pedidos, productos o categorías."
            ),
        }

    def give_up(self, state: GraphState) -> StateUpdate:
        attempts = len(state.get("attempts", []))
        return {
            "status": "failed",
            "answer": (
                f"No pude generar una consulta válida después de {attempts} intento(s). "
                "Intenta reformular la pregunta con más detalle."
            ),
        }