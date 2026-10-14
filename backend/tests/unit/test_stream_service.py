import threading
from typing import Any

import pytest
from sqlalchemy import Engine
from tests.helpers import RecordingTracer, ScriptedChatModel, build_test_agent

from app.services.query_service import InvalidQuestionError, QueryService
from app.services.stream_events import StreamEvent

QUESTION = "¿Cuántos clientes hay?"
COUNT_SQL = "SELECT COUNT(*) AS total FROM customers"


def make_service(
    engine: Engine, responses: list[Any], tracer: RecordingTracer | None = None
) -> QueryService:
    llm = ScriptedChatModel(responses=responses)
    return QueryService(
        build_test_agent(engine, llm),
        max_retries=3,
        tracer=tracer if tracer is not None else RecordingTracer(),
    )


def nodes(events: list[StreamEvent]) -> list[str]:
    return [e.data["node"] for e in events if e.event == "step"]


def test_happy_path_emits_one_step_per_node_and_then_the_result(ro_engine: Engine) -> None:
    events = list(make_service(ro_engine, [COUNT_SQL, "Hay 50 clientes."]).stream(QUESTION))

    assert nodes(events) == ["generate_sql", "validate_sql", "execute_sql", "explain_result"]
    assert all(e.event == "step" for e in events[:-1])
    assert events[-1].event == "result"
    assert events[-1].data["status"] == "success"
    assert events[-1].data["rows"] == [[50]]
    assert events[-1].data["answer"] == "Hay 50 clientes."


def test_guardrail_rejection_is_visible_as_a_failed_step_followed_by_a_fix(
    ro_engine: Engine,
) -> None:
    service = make_service(ro_engine, ["DROP TABLE customers", COUNT_SQL, "Hay 50."])
    events = list(service.stream(QUESTION))

    assert nodes(events) == [
        "generate_sql",
        "validate_sql",
        "fix_sql",
        "validate_sql",
        "execute_sql",
        "explain_result",
    ]
    rejected = events[1].data
    assert rejected["ok"] is False
    assert "read-only" in rejected["detail"]
    assert events[2].data["label"] == "SQL corregido (intento 1)"
    assert events[-1].data["retries"] == 1


def test_giving_up_still_ends_with_a_result_event(ro_engine: Engine) -> None:
    events = list(make_service(ro_engine, ["DROP TABLE x"] * 4).stream(QUESTION))

    assert nodes(events)[-1] == "give_up"
    assert events[-1].event == "result"
    assert events[-1].data["status"] == "failed"


def test_unanswerable_question_stops_after_rejection(ro_engine: Engine) -> None:
    events = list(make_service(ro_engine, ["CANNOT_ANSWER"]).stream("¿Capital de Francia?"))

    assert nodes(events) == ["generate_sql", "reject_question"]
    assert events[-1].data["status"] == "unanswerable"


def test_final_result_matches_the_non_streaming_response(ro_engine: Engine) -> None:
    """Con un reintento de por medio, para ejercitar el reducer de `attempts`."""
    responses = ["SELECT phone FROM customers", COUNT_SQL, "Hay 50 clientes."]
    asked = make_service(ro_engine, list(responses)).ask(QUESTION)
    streamed = list(make_service(ro_engine, list(responses)).stream(QUESTION))[-1].data

    assert streamed["status"] == asked.status
    assert streamed["sql"] == asked.sql
    assert streamed["rows"] == asked.rows
    assert streamed["answer"] == asked.answer
    assert streamed["retries"] == asked.retries
    assert streamed["attempts"] == [a.model_dump() for a in asked.attempts]


def test_invalid_question_fails_before_opening_a_trace(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_service(ro_engine, [], tracer)

    with pytest.raises(InvalidQuestionError):
        list(service.stream("   "))
    assert tracer.opened == []


def test_provider_failure_propagates_to_the_caller(ro_engine: Engine) -> None:
    service = make_service(ro_engine, [RuntimeError("quota exceeded")])
    with pytest.raises(RuntimeError, match="quota"):
        list(service.stream(QUESTION))


def test_cancel_stops_between_nodes_and_avoids_further_llm_calls(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    # Solo 1 respuesta: si el grafo siguiera, el LLM falso fallaría en la segunda llamada.
    service = make_service(ro_engine, [COUNT_SQL], tracer)
    cancel = threading.Event()
    cancel.set()

    events = list(service.stream(QUESTION, cancel=cancel))

    assert nodes(events) == ["generate_sql"]
    assert not any(e.event == "result" for e in events)
    assert tracer.callback.llm_calls == 1

    recorded = tracer.handles[0].recorded
    assert recorded is not None
    scores = {s.name: s.value for s in recorded["scores"]}
    assert scores == {"status": "cancelled"}


def test_streaming_records_the_trace_like_the_normal_path(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    list(make_service(ro_engine, [COUNT_SQL, "Hay 50."], tracer).stream(QUESTION, session_id="s1"))

    assert tracer.opened[0]["session_id"] == "s1"
    assert tracer.callback.llm_calls == 2
    recorded = tracer.handles[0].recorded
    assert recorded is not None
    scores = {s.name: s.value for s in recorded["scores"]}
    assert scores == {"answered": 1.0, "status": "success", "retries": 0.0}