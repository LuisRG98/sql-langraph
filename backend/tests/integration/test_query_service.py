import pytest
from sqlalchemy import Engine
from tests.helpers import ScriptedChatModel, build_test_agent

from app.graph.prompts import PROMPT_VERSION
from app.services.query_service import MAX_QUESTION_LENGTH, QueryService


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