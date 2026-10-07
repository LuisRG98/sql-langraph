from sqlalchemy import Engine

from app.db.hints import SCHEMA_HINTS
from app.db.schema import DatabaseSchema, extract_schema


def _schema(engine: Engine) -> DatabaseSchema:
    return extract_schema(engine, hints=SCHEMA_HINTS)


def test_schema_lists_all_tables(ro_engine: Engine) -> None:
    assert _schema(ro_engine).table_names() == {
        "categories",
        "products",
        "customers",
        "orders",
        "order_items",
    }


def test_foreign_keys_are_detected(ro_engine: Engine) -> None:
    orders = next(t for t in _schema(ro_engine).tables if t.name == "orders")
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].ref_table == "customers"
    assert orders.foreign_keys[0].ref_columns == ["id"]


def test_primary_keys_are_detected(ro_engine: Engine) -> None:
    products = next(t for t in _schema(ro_engine).tables if t.name == "products")
    pk_columns = [c.name for c in products.columns if c.primary_key]
    assert pk_columns == ["id"]


def test_hints_are_attached_to_columns(ro_engine: Engine) -> None:
    orders = next(t for t in _schema(ro_engine).tables if t.name == "orders")
    status = next(c for c in orders.columns if c.name == "status")
    assert status.hint is not None
    assert "delivered" in status.hint


def test_schema_without_hints_has_no_hints(ro_engine: Engine) -> None:
    schema = extract_schema(ro_engine)
    assert all(col.hint is None for table in schema.tables for col in table.columns)


def test_prompt_format(ro_engine: Engine) -> None:
    prompt = _schema(ro_engine).to_prompt()
    assert "TABLE orders" in prompt
    assert "id INTEGER PRIMARY KEY" in prompt
    assert "customer_id INTEGER NOT NULL REFERENCES customers.id" in prompt
    assert "-- one of: pending, paid, shipped, delivered, cancelled" in prompt


def test_prompt_is_deterministic(ro_engine: Engine) -> None:
    assert _schema(ro_engine).to_prompt() == _schema(ro_engine).to_prompt()


def test_internal_sqlite_tables_are_excluded(ro_engine: Engine) -> None:
    assert not any(name.startswith("sqlite_") for name in _schema(ro_engine).table_names())