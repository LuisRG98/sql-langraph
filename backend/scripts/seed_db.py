"""Crea (o recrea) la base de datos de ejemplo."""
from app.core.config import get_settings
from app.db.engine import create_rw_engine, resolve_sqlite_path
from app.db.seed import seed_database


def main() -> None:
    path = resolve_sqlite_path(get_settings().database_url)
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_rw_engine(path)
    counts = seed_database(engine)
    engine.dispose()

    print(f"Base de datos creada en: {path}")
    for table, total in counts.items():
        print(f"  {table:<12} {total:>5} filas")


if __name__ == "__main__":
    main()