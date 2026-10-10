from typing import Any

import pytest
from sqlalchemy import Engine
from tests.helpers import ScriptedChatModel, build_test_agent, text_of

from app.graph.builder import recursion_limit
from app.graph.state import initial_state

QUESTION = "¿Cuántos clientes hay?"
COUNT_SQL = "SELECT COUNT(*) AS total FROM customers"


def run(
    engine: Engine, responses: list[Any], *, max_retries: int = 3
) -> tuple[dict[str, Any], ScriptedChatModel]:
    llm = ScriptedChatModel(responses=responses)
    agent = build_test_agent(engine, llm)
    final = agent.invoke(
        initial_state(QUESTION, max_retries),
        config={"recursion_limit": recursion_limit(max_retries)},
    )
    return final, llm


def test_happy_path(ro_engine: Engine) -> None:
    final, llm = run(ro_engine, [COUNT_SQL, "Hay 50 clientes."])

    assert final["status"] == "success"
    assert final["answer"] == "Hay 50 clientes."
    assert final["retries"] == 0
    assert final["attempts"] == []
    assert final["result"].rows == [[50]]
    assert len(llm.calls) == 2  # generar + explicar


def test_markdown_fences_are_removed(ro_engine: Engine) -> None:
    final, _ = run(ro_engine, [f"```sql\n{COUNT_SQL}\n```", "Hay 50 clientes."])

    assert final["status"] == "success"
    assert final["sql"] == COUNT_SQL


def test_prompt_contains_schema_and_current_date(ro_engine: Engine) -> None:
    _, llm = run(ro_engine, [COUNT_SQL, "ok"])

    system = text_of(llm.calls[0][0])
    assert "TABLE orders" in system
    assert "-- one of: pending, paid, shipped, delivered, cancelled" in system
    assert "2026-10-07" in system
    assert QUESTION in text_of(llm.calls[0][1])


def test_explanation_prompt_receives_the_data(ro_engine: Engine) -> None:
    _, llm = run(ro_engine, [COUNT_SQL, "ok"])

    explain_prompt = text_of(llm.calls[1][1])
    assert "<data>" in explain_prompt
    assert "50" in explain_prompt


def test_guardrail_rejection_triggers_a_fix(ro_engine: Engine) -> None:
    final, llm = run(ro_engine, ["DROP TABLE customers", COUNT_SQL, "Hay 50 clientes."])

    assert final["status"] == "success"
    assert final["retries"] == 1
    assert final["attempts"][0]["sql"] == "DROP TABLE customers"
    assert "read-only" in final["attempts"][0]["error"]

    # El prompt de corrección debe incluir el SQL fallido y el motivo.
    fix_prompt = text_of(llm.calls[1][1])
    assert "DROP TABLE customers" in fix_prompt
    assert "read-only" in fix_prompt


def test_execution_error_triggers_a_fix(ro_engine: Engine) -> None:
    # `phone` no existe: el guardrail no valida columnas, el error lo da SQLite al ejecutar.
    final, llm = run(
        ro_engine, ["SELECT phone FROM customers", COUNT_SQL, "Hay 50 clientes."]
    )

    assert final["status"] == "success"
    assert final["retries"] == 1
    assert "no such column: phone" in text_of(llm.calls[1][1])


def test_multiple_failures_accumulate_in_attempts(ro_engine: Engine) -> None:
    final, llm = run(
        ro_engine,
        ["SELECT * FROM users", "SELECT phone FROM customers", COUNT_SQL, "Hay 50."],
    )

    assert final["status"] == "success"
    assert final["retries"] == 2
    assert len(final["attempts"]) == 2
    # El segundo prompt de corrección ve los dos fallos.
    last_fix_prompt = text_of(llm.calls[2][1])
    assert "Attempt 1" in last_fix_prompt
    assert "Attempt 2" in last_fix_prompt


def test_gives_up_after_max_retries(ro_engine: Engine) -> None:
    final, llm = run(ro_engine, ["DROP TABLE x"] * 3, max_retries=2)

    assert final["status"] == "failed"
    assert final["retries"] == 2
    assert final["result"] is None
    assert len(llm.calls) == 3  # 1 generación + 2 correcciones, sin explicación
    assert "3" in final["answer"]


def test_zero_retries_gives_up_immediately(ro_engine: Engine) -> None:
    final, llm = run(ro_engine, ["DROP TABLE x"], max_retries=0)

    assert final["status"] == "failed"
    assert len(llm.calls) == 1


def test_unanswerable_question_is_not_executed(ro_engine: Engine) -> None:
    final, llm = run(ro_engine, ["CANNOT_ANSWER"])

    assert final["status"] == "unanswerable"
    assert final["result"] is None
    assert final["safe_sql"] is None
    assert "No puedo responder" in final["answer"]
    assert len(llm.calls) == 1


def test_explanation_failure_keeps_the_result(ro_engine: Engine) -> None:
    final, _ = run(ro_engine, [COUNT_SQL, RuntimeError("quota exceeded")])

    assert final["status"] == "success"
    assert final["result"].rows == [[50]]
    assert "1 fila" in final["answer"]


def test_generation_failure_propagates(ro_engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="quota"):
        run(ro_engine, [RuntimeError("quota exceeded")])


def test_executed_sql_is_the_validated_one(ro_engine: Engine) -> None:
    final, _ = run(ro_engine, ["SELECT * FROM customers /* comentario */", "ok"])

    assert final["status"] == "success"
    assert "comentario" not in final["safe_sql"]
    assert "LIMIT 100" in final["safe_sql"]
    assert final["result"].row_count == 50