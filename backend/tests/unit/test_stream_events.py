import json

from app.db.executor import QueryResult
from app.services.stream_events import error_event, result_event, step_event


def test_generate_sql_exposes_the_sql() -> None:
    event = step_event("generate_sql", {"sql": "SELECT 1", "error": None})
    assert event.event == "step"
    assert event.data == {
        "node": "generate_sql",
        "label": "SQL generado",
        "detail": "SELECT 1",
        "ok": True,
    }


def test_generate_sql_unanswerable_is_flagged() -> None:
    event = step_event("generate_sql", {"sql": None, "status": "unanswerable"})
    assert event.data["ok"] is False
    assert "no puede responder" in event.data["label"]


def test_validate_sql_success_shows_the_safe_sql() -> None:
    event = step_event("validate_sql", {"safe_sql": "SELECT 1 LIMIT 100", "error": None})
    assert event.data["label"] == "SQL validado"
    assert event.data["detail"] == "SELECT 1 LIMIT 100"
    assert event.data["ok"] is True


def test_validate_sql_rejection_shows_the_reason() -> None:
    event = step_event("validate_sql", {"safe_sql": None, "error": "Only read-only SELECT"})
    assert event.data["ok"] is False
    assert event.data["detail"] == "Only read-only SELECT"


def test_execute_sql_reports_the_row_count() -> None:
    result = QueryResult(columns=["t"], rows=[[1], [2]], row_count=2)
    event = step_event("execute_sql", {"result": result, "error": None})
    assert event.data["detail"] == "2 fila(s)"
    assert event.data["ok"] is True


def test_execute_sql_failure_shows_the_database_error() -> None:
    event = step_event("execute_sql", {"result": None, "error": "no such column: phone"})
    assert event.data["ok"] is False
    assert event.data["detail"] == "no such column: phone"


def test_fix_sql_shows_the_attempt_number() -> None:
    event = step_event("fix_sql", {"sql": "SELECT 2", "retries": 2})
    assert event.data["label"] == "SQL corregido (intento 2)"
    assert event.data["detail"] == "SELECT 2"


def test_terminal_nodes() -> None:
    assert step_event("explain_result", {}).data["ok"] is True
    assert step_event("reject_question", {}).data["ok"] is False
    assert step_event("give_up", {}).data["ok"] is False


def test_unknown_node_and_none_update_do_not_crash() -> None:
    event = step_event("nodo_nuevo", None)
    assert event.data["label"] == "nodo_nuevo"


def test_every_event_is_json_serializable() -> None:
    result = QueryResult(columns=["t"], rows=[[1]], row_count=1)
    events = [
        step_event("execute_sql", {"result": result}),
        result_event({"status": "success", "rows": [[1]]}),
        error_event(429, "límite"),
    ]
    for event in events:
        json.dumps(event.data)