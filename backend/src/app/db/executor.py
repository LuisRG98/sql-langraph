import sqlite3
import time
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError


class QueryExecutionError(Exception):
    """El motor rechazó o interrumpió la consulta."""


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, int | float | str):
        return value
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    return str(value)


def execute_query(
    engine: Engine,
    sql: str,
    *,
    max_rows: int,
    timeout_seconds: float,
) -> QueryResult:
    """Ejecuta SQL ya validado, con límite de tiempo y de filas."""
    deadline = time.monotonic() + timeout_seconds

    def _past_deadline() -> int:
        # SQLite aborta la consulta si este callback devuelve un valor distinto de 0.
        return 1 if time.monotonic() > deadline else 0

    try:
        with engine.connect() as conn:
            raw = cast(sqlite3.Connection, conn.connection.driver_connection)
            raw.set_progress_handler(_past_deadline, 10_000)
            try:
                cursor = conn.exec_driver_sql(sql)
                columns = list(cursor.keys())
                fetched = cursor.fetchmany(max_rows + 1)
            finally:
                raw.set_progress_handler(None, 0)
    except SQLAlchemyError as exc:
        message = str(getattr(exc, "orig", exc))
        if "interrupted" in message.lower():
            message = f"The query took longer than {timeout_seconds:g} seconds. Simplify it."
        raise QueryExecutionError(message) from exc

    return QueryResult(
        columns=columns,
        rows=[[_jsonable(value) for value in row] for row in fetched[:max_rows]],
        row_count=min(len(fetched), max_rows),
        truncated=len(fetched) > max_rows,
    )