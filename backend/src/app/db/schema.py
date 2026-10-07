from collections.abc import Mapping
from functools import lru_cache

from pydantic import BaseModel
from sqlalchemy import Engine, inspect

from app.db.engine import get_readonly_engine
from app.db.hints import SCHEMA_HINTS


class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool = False
    hint: str | None = None


class ForeignKeyInfo(BaseModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKeyInfo]


class DatabaseSchema(BaseModel):
    tables: list[TableInfo]

    def table_names(self) -> set[str]:
        return {table.name for table in self.tables}

    def to_prompt(self) -> str:
        """Representación compacta y legible para incluir en el prompt del LLM."""
        blocks: list[str] = []
        for table in self.tables:
            fk_by_column = {
                column: f"{fk.ref_table}.{ref_column}"
                for fk in table.foreign_keys
                for column, ref_column in zip(fk.columns, fk.ref_columns, strict=True)
            }
            lines = [f"TABLE {table.name}"]
            for col in table.columns:
                parts = [f"  {col.name} {col.type}"]
                if col.primary_key:
                    parts.append("PRIMARY KEY")
                elif not col.nullable:
                    parts.append("NOT NULL")
                if col.name in fk_by_column:
                    parts.append(f"REFERENCES {fk_by_column[col.name]}")
                if col.hint:
                    parts.append(f"-- {col.hint}")
                lines.append(" ".join(parts))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


def extract_schema(engine: Engine, hints: Mapping[str, str] | None = None) -> DatabaseSchema:
    """Lee el esquema real desde la base de datos (reflexión)."""
    hint_map: Mapping[str, str] = hints if hints is not None else {}
    insp = inspect(engine)
    tables: list[TableInfo] = []

    for table_name in sorted(insp.get_table_names()):
        if table_name.startswith("sqlite_"):
            continue  # tablas internas de SQLite

        pk_columns = set(insp.get_pk_constraint(table_name).get("constrained_columns", []))
        columns = [
            ColumnInfo(
                name=col["name"],
                type=str(col["type"]),
                nullable=bool(col["nullable"]),
                primary_key=col["name"] in pk_columns,
                hint=hint_map.get(f"{table_name}.{col['name']}"),
            )
            for col in insp.get_columns(table_name)
        ]
        foreign_keys = [
            ForeignKeyInfo(
                columns=list(fk["constrained_columns"]),
                ref_table=fk["referred_table"],
                ref_columns=list(fk["referred_columns"]),
            )
            for fk in insp.get_foreign_keys(table_name)
        ]
        tables.append(TableInfo(name=table_name, columns=columns, foreign_keys=foreign_keys))

    return DatabaseSchema(tables=tables)


@lru_cache
def get_database_schema() -> DatabaseSchema:
    return extract_schema(get_readonly_engine(), hints=SCHEMA_HINTS)