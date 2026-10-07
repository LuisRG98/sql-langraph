import sqlite3
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from app.core.config import get_settings

# engine.py -> db -> app -> src -> backend
BACKEND_DIR = Path(__file__).resolve().parents[3]


def resolve_sqlite_path(database_url: str) -> Path:
    """Convierte una DATABASE_URL de SQLite en una ruta absoluta de archivo."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(f"Solo se soporta SQLite en esta etapa, recibido: {url.drivername}")
    if not url.database or url.database == ":memory:":
        raise ValueError("Se requiere una base SQLite en archivo, no en memoria")

    path = Path(url.database)
    if path.is_absolute():
        return path.resolve()
    return (BACKEND_DIR / path).resolve()


def create_rw_engine(db_path: Path) -> Engine:
    """Engine de lectura/escritura. Solo lo usa el script de seed."""

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    return create_engine(f"sqlite:///{db_path.as_posix()}", creator=_connect)


def create_ro_engine(db_path: Path) -> Engine:
    """Engine de SOLO LECTURA. Es el que ejecutará el SQL generado por el LLM."""
    uri = f"{db_path.resolve().as_uri()}?mode=ro"

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
        return conn

    return create_engine(f"sqlite:///{db_path.as_posix()}", creator=_connect)


@lru_cache
def get_readonly_engine() -> Engine:
    path = resolve_sqlite_path(get_settings().database_url)
    if not path.exists():
        raise FileNotFoundError(
            f"No existe la base de datos en {path}. Ejecuta: python scripts/seed_db.py"
        )
    return create_ro_engine(path)