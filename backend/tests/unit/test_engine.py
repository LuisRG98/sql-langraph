from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.db.engine import BACKEND_DIR, resolve_sqlite_path


def test_relative_path_resolves_inside_backend() -> None:
    path = resolve_sqlite_path("sqlite:///./data/shop.db")
    assert path == (BACKEND_DIR / "data" / "shop.db").resolve()


def test_absolute_path_is_kept(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/x.db"
    assert resolve_sqlite_path(url) == (tmp_path / "x.db").resolve()


def test_rejects_non_sqlite_url() -> None:
    with pytest.raises(ValueError, match="SQLite"):
        resolve_sqlite_path("postgresql://user:pass@localhost/db")


def test_rejects_in_memory_database() -> None:
    with pytest.raises(ValueError, match="archivo"):
        resolve_sqlite_path("sqlite:///:memory:")


def test_readonly_engine_can_select(ro_engine: Engine) -> None:
    with ro_engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar_one()
    assert total == 50


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM customers",
        "UPDATE products SET price = 0",
        "INSERT INTO categories (id, name) VALUES (99, 'Hack')",
        "DROP TABLE orders",
    ],
)
def test_readonly_engine_blocks_writes(ro_engine: Engine, statement: str) -> None:
    with pytest.raises(OperationalError), ro_engine.begin() as conn:
        conn.execute(text(statement))