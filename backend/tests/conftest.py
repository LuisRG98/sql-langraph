from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from app.db.engine import create_ro_engine, create_rw_engine
from app.db.seed import seed_database


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Base sembrada una sola vez para toda la sesión de tests."""
    path = tmp_path_factory.mktemp("db") / "shop.db"
    engine = create_rw_engine(path)
    seed_database(engine)
    engine.dispose()
    return path


@pytest.fixture
def ro_engine(db_path: Path) -> Iterator[Engine]:
    engine = create_ro_engine(db_path)
    yield engine
    engine.dispose()