import pytest
from sqlalchemy import Engine, text

from app.db.guardrail import SQLValidator
from app.db.hints import SCHEMA_HINTS
from app.db.schema import extract_schema

MAX_ROWS = 10


@pytest.fixture
def validator(ro_engine: Engine) -> SQLValidator:
    schema = extract_schema(ro_engine, hints=SCHEMA_HINTS)
    return SQLValidator(schema.table_names(), max_rows=MAX_ROWS)


def _run(engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def test_validated_query_is_capped_at_max_rows(validator: SQLValidator, ro_engine: Engine) -> None:
    result = validator.validate("SELECT * FROM order_items")
    assert result.sql is not None
    assert len(_run(ro_engine, result.sql)) == MAX_ROWS


def test_validated_union_is_capped_at_max_rows(validator: SQLValidator, ro_engine: Engine) -> None:
    result = validator.validate("SELECT id FROM orders UNION SELECT id FROM customers")
    assert result.sql is not None
    assert len(_run(ro_engine, result.sql)) == MAX_ROWS


def test_smaller_limit_is_respected_when_executed(
    validator: SQLValidator, ro_engine: Engine
) -> None:
    result = validator.validate("SELECT * FROM orders LIMIT 3")
    assert result.sql is not None
    assert len(_run(ro_engine, result.sql)) == 3


def test_aggregate_query_returns_expected_value(
    validator: SQLValidator, ro_engine: Engine
) -> None:
    result = validator.validate("SELECT COUNT(*) AS total FROM customers")
    assert result.sql is not None
    assert _run(ro_engine, result.sql) == [(50,)]


def test_cte_query_executes(validator: SQLValidator, ro_engine: Engine) -> None:
    result = validator.validate(
        "WITH delivered AS (SELECT * FROM orders WHERE status = 'delivered') "
        "SELECT COUNT(*) FROM delivered"
    )
    assert result.sql is not None
    rows = _run(ro_engine, result.sql)
    assert len(rows) == 1
    assert int(str(rows[0][0])) > 0