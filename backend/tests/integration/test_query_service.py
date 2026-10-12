import pytest
from sqlalchemy import Engine
from tests.helpers import RecordingTracer, ScriptedChatModel, build_test_agent

from app.core.observability import ScoreSpec
from app.graph.prompts import PROMPT_VERSION
from app.services.query_service import MAX_QUESTION_LENGTH, QueryService, build_scores


def make_service(engine: Engine, responses: list[object]) -> QueryService:
    llm = ScriptedChatModel(responses=responses)
    return QueryService(build_test_agent(engine, llm), max_retries=3)


def test_maps_final_state_to_response(ro_engine: Engine) -> None:
    service = make_service(
        ro_engine,
        ["SELECT COUNT(*) AS total FROM customers", "Hay 50 clientes."],
    )
    response = service.ask("  ¿Cuántos clientes hay?  ")

    assert response.status == "success"
    assert response.question == "¿Cuántos clientes hay?"
    assert response.answer == "Hay 50 clientes."
    assert response.columns == ["total"]
    assert response.rows == [[50]]
    assert response.row_count == 1
    assert response.retries == 0
    assert response.prompt_version == PROMPT_VERSION
    assert response.sql is not None
    assert "LIMIT" in response.sql


def test_response_exposes_attempts_when_a_fix_was_needed(ro_engine: Engine) -> None:
    service = make_service(
        ro_engine,
        ["DROP TABLE customers", "SELECT COUNT(*) AS total FROM customers", "Hay 50."],
    )
    response = service.ask("¿Cuántos clientes hay?")

    assert response.retries == 1
    assert len(response.attempts) == 1
    assert response.attempts[0].sql == "DROP TABLE customers"


def test_failed_response_has_no_rows(ro_engine: Engine) -> None:
    service = make_service(ro_engine, ["DROP TABLE x"] * 4)
    response = service.ask("borra todo")

    assert response.status == "failed"
    assert response.rows == []
    assert response.columns == []
    assert response.answer


@pytest.mark.parametrize("question", ["", "   ", "x" * (MAX_QUESTION_LENGTH + 1)])
def test_invalid_questions_are_rejected_before_calling_the_llm(
    ro_engine: Engine, question: str
) -> None:
    llm = ScriptedChatModel(responses=[])
    service = QueryService(build_test_agent(ro_engine, llm), max_retries=3)

    with pytest.raises(ValueError):
        service.ask(question)
    assert llm.calls == []

def make_traced_service(
    engine: Engine, responses: list[object], tracer: RecordingTracer
) -> QueryService:
    llm = ScriptedChatModel(responses=responses)
    return QueryService(
        build_test_agent(engine, llm), max_retries=3, tracer=tracer, environment="test"
    )


def test_opens_one_trace_per_question_with_context(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_traced_service(
        ro_engine, ["SELECT COUNT(*) AS total FROM customers", "Hay 50."], tracer
    )
    service.ask("¿Cuántos clientes hay?", session_id="sesion-1", user_id="luis")

    assert len(tracer.opened) == 1
    opened = tracer.opened[0]
    assert opened["name"] == "text2sql-query"
    assert opened["session_id"] == "sesion-1"
    assert opened["user_id"] == "luis"
    assert f"prompt:{PROMPT_VERSION}" in opened["tags"]
    assert "env:test" in opened["tags"]
    assert opened["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "max_retries": "3",
    }


def test_callbacks_reach_every_llm_call_inside_the_graph(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_traced_service(
        ro_engine,
        ["DROP TABLE customers", "SELECT COUNT(*) AS total FROM customers", "Hay 50."],
        tracer,
    )
    service.ask("¿Cuántos clientes hay?")

    # generar + corregir + explicar
    assert tracer.callback.llm_calls == 3


def test_records_input_output_and_scores_on_success(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_traced_service(
        ro_engine, ["SELECT COUNT(*) AS total FROM customers", "Hay 50."], tracer
    )
    service.ask("¿Cuántos clientes hay?")

    recorded = tracer.handles[0].recorded
    assert recorded is not None
    assert recorded["inputs"] == {"question": "¿Cuántos clientes hay?"}
    assert recorded["outputs"]["status"] == "success"
    scores = {s.name: s.value for s in recorded["scores"]}
    assert scores == {"answered": 1.0, "status": "success", "retries": 0.0}


def test_records_failure_scores(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_traced_service(ro_engine, ["DROP TABLE x"] * 4, tracer)
    service.ask("borra todo")

    recorded = tracer.handles[0].recorded
    assert recorded is not None
    scores = {s.name: s.value for s in recorded["scores"]}
    assert scores == {"answered": 0.0, "status": "failed", "retries": 3.0}


def test_invalid_question_does_not_open_a_trace(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_traced_service(ro_engine, [], tracer)

    with pytest.raises(ValueError):
        service.ask("   ")
    assert tracer.opened == []


def test_unanswerable_question_scores(ro_engine: Engine) -> None:
    tracer = RecordingTracer()
    service = make_traced_service(ro_engine, ["CANNOT_ANSWER"], tracer)
    service.ask("¿Capital de Francia?")

    recorded = tracer.handles[0].recorded
    assert recorded is not None
    scores = {s.name: s.value for s in recorded["scores"]}
    assert scores["answered"] == 0.0
    assert scores["status"] == "unanswerable"


def test_build_scores_is_pure_and_typed(ro_engine: Engine) -> None:
    service = make_service(ro_engine, ["SELECT COUNT(*) AS total FROM customers", "Hay 50."])
    response = service.ask("¿Cuántos clientes hay?")

    scores = build_scores(response)
    assert all(isinstance(s, ScoreSpec) for s in scores)
    assert {s.data_type for s in scores} == {"NUMERIC", "CATEGORICAL"}