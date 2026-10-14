from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.db.executor import QueryResult


@dataclass(frozen=True)
class StreamEvent:
    """Un mensaje del flujo. `data` siempre es un diccionario serializable a JSON."""

    event: Literal["step", "result", "error"]
    data: dict[str, Any]


def step_event(node: str, update: Mapping[str, Any] | None) -> StreamEvent:
    label, detail, ok = _describe(node, update or {})
    return StreamEvent("step", {"node": node, "label": label, "detail": detail, "ok": ok})


def result_event(response: dict[str, Any]) -> StreamEvent:
    return StreamEvent("result", response)


def error_event(status: int, detail: str) -> StreamEvent:
    return StreamEvent("error", {"status": status, "detail": detail})


def _describe(node: str, update: Mapping[str, Any]) -> tuple[str, str | None, bool]:
    """Traduce la actualización de un nodo a (texto para el usuario, detalle, ¿fue bien?)."""
    error = update.get("error")

    if node == "generate_sql":
        if update.get("status") == "unanswerable":
            return "El modelo indicó que no puede responder esta pregunta", None, False
        return "SQL generado", update.get("sql"), True

    if node == "validate_sql":
        if error:
            return "El guardrail rechazó el SQL", str(error), False
        return "SQL validado", update.get("safe_sql"), True

    if node == "execute_sql":
        if error:
            return "La consulta falló al ejecutarse", str(error), False
        result = update.get("result")
        detail = f"{result.row_count} fila(s)" if isinstance(result, QueryResult) else None
        return "Consulta ejecutada", detail, True

    if node == "fix_sql":
        attempt = update.get("retries")
        label = f"SQL corregido (intento {attempt})" if attempt else "SQL corregido"
        return label, update.get("sql"), True

    if node == "explain_result":
        return "Respuesta redactada", None, True
    if node == "reject_question":
        return "Pregunta fuera de alcance", None, False
    if node == "give_up":
        return "No se pudo generar una consulta válida", None, False

    return node, None, True