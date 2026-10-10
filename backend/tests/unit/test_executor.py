import pytest
from sqlalchemy import Engine

from app.db.executor import QueryExecutionError, execute_query


def test_returns_columns_and_rows(ro_engine: Engine) -> None:
    result = execute_query(
        ro_engine, "SELECT COUNT(*) AS total FROM customers", max_rows=10, timeout_seconds=5
    )
    assert result.columns == ["total"]
    assert result.rows == [[50]]
    assert result.row_count == 1
    assert not result.truncated


def test_truncates_when_there_are_more_rows_than_the_limit(ro_engine: Engine) -> None:
    result = execute_query(
        ro_engine, "SELECT id FROM order_items", max_rows=5, timeout_seconds=5
    )
    assert result.row_count == 5
    assert len(result.rows) == 5
    assert result.truncated


def test_unknown_column_raises_readable_error(ro_engine: Engine) -> None:
    with pytest.raises(QueryExecutionError, match="no such column"):
        execute_query(ro_engine, "SELECT phone FROM customers", max_rows=5, timeout_seconds=5)


def test_slow_query_is_interrupted(ro_engine: Engine) -> None:
    infinite = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
        "SELECT COUNT(*) FROM c"
    )
    with pytest.raises(QueryExecutionError, match="longer than"):
        execute_query(ro_engine, infinite, max_rows=5, timeout_seconds=0.3)


def test_engine_is_reusable_after_a_timeout(ro_engine: Engine) -> None:
    infinite = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
        "SELECT COUNT(*) FROM c"
    )
    with pytest.raises(QueryExecutionError):
        execute_query(ro_engine, infinite, max_rows=5, timeout_seconds=0.3)

    # El handler del timeout no debe "contaminar" la siguiente consulta del pool.
    result = execute_query(ro_engine, "SELECT COUNT(*) FROM orders", max_rows=5, timeout_seconds=5)
    assert result.rows == [[300]]


def test_colon_in_literal_is_not_treated_as_bind_parameter(ro_engine: Engine) -> None:
    result = execute_query(ro_engine, "SELECT ' :abc' AS x", max_rows=5, timeout_seconds=5)
    assert result.rows == [[" :abc"]]