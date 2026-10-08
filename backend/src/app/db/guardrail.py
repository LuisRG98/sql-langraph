from collections.abc import Iterable
from enum import StrEnum
from functools import lru_cache

import sqlglot
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.core.config import get_settings
from app.db.schema import get_database_schema

DIALECT = "sqlite"

# Únicos tipos de sentencia raíz permitidos: consultas de lectura.
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# Nodos que jamás deben aparecer en ninguna parte del árbol (comparados por nombre de clase
# para no depender de que cada versión de sqlglot los exponga con el mismo nombre).
FORBIDDEN_NODES = frozenset(
    {
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Drop",
        "Create",
        "Alter",
        "AlterTable",
        "TruncateTable",
        "Command",
        "Pragma",
        "Attach",
        "Detach",
        "Transaction",
        "Commit",
        "Rollback",
        "Set",
        "Into",
        "Copy",
        "Use",
        "Analyze",
    }
)

# Funciones de SQLite que leen/escriben archivos, cargan código o consumen memoria sin control.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "load_extension",
        "readfile",
        "writefile",
        "edit",
        "fts3_tokenizer",
        "randomblob",
        "zeroblob",
    }
)
FORBIDDEN_FUNCTION_PREFIXES = ("pragma_",)


class ViolationCode(StrEnum):
    EMPTY = "empty"
    TOO_LONG = "too_long"
    SYNTAX = "syntax_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_READ_ONLY = "not_read_only"
    FORBIDDEN_NODE = "forbidden_node"
    FORBIDDEN_FUNCTION = "forbidden_function"
    QUALIFIED_TABLE = "qualified_table"
    UNKNOWN_TABLE = "unknown_table"


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)
    code: ViolationCode | None = None
    error: str | None = None


def _reject(code: ViolationCode, message: str) -> ValidationResult:
    return ValidationResult(valid=False, code=code, error=message)


class SQLValidator:
    def __init__(
        self,
        allowed_tables: Iterable[str],
        *,
        max_rows: int = 100,
        max_length: int = 4000,
    ) -> None:
        self._allowed = frozenset(name.lower() for name in allowed_tables)
        self._max_rows = max_rows
        self._max_length = max_length

    def validate(self, sql: str) -> ValidationResult:
        text = sql.strip()
        if not text:
            return _reject(ViolationCode.EMPTY, "The SQL query is empty.")
        if len(text) > self._max_length:
            return _reject(
                ViolationCode.TOO_LONG,
                f"The SQL query is longer than {self._max_length} characters. Make it simpler.",
            )

        try:
            parsed = sqlglot.parse(text, read=DIALECT)
        except SqlglotError as exc:
            lines = str(exc).splitlines()
            detail = lines[0][:200] if lines else "invalid syntax"
            return _reject(ViolationCode.SYNTAX, f"SQL syntax error: {detail}")

        # Una ';' final o un comentario suelto producen entradas None: se descartan.
        statements = [
            s for s in parsed if s is not None and type(s).__name__ != "Semicolon"
        ]
        if not statements:
            return _reject(ViolationCode.EMPTY, "The SQL query is empty.")
        if len(statements) > 1:
            return _reject(
                ViolationCode.MULTIPLE_STATEMENTS,
                "Only one SQL statement is allowed. Remove the extra statements.",
            )

        tree = statements[0]
        if not isinstance(tree, ALLOWED_ROOTS):
            return _reject(
                ViolationCode.NOT_READ_ONLY,
                "Only read-only SELECT queries are allowed.",
            )

        for check in (self._check_nodes, self._check_functions, self._check_tables):
            violation = check(tree)
            if violation is not None:
                return violation

        safe_tree = self._enforce_limit(tree)
        return ValidationResult(
            valid=True,
            # Se ejecuta el SQL regenerado desde el AST, nunca el texto original.
            sql=safe_tree.sql(dialect=DIALECT, comments=False),
            tables=self._used_tables(tree),
        )

    # ---- comprobaciones -------------------------------------------------

    def _check_nodes(self, tree: exp.Expression) -> ValidationResult | None:
        for node in tree.find_all(exp.Expression):
            name = type(node).__name__
            if name in FORBIDDEN_NODES:
                return _reject(
                    ViolationCode.FORBIDDEN_NODE,
                    f"The statement contains a forbidden operation ({name}).",
                )
        return None

    def _check_functions(self, tree: exp.Expression) -> ValidationResult | None:
        for node in tree.find_all(exp.Anonymous):
            func_name = node.name.lower()
            if func_name in FORBIDDEN_FUNCTIONS or func_name.startswith(
                FORBIDDEN_FUNCTION_PREFIXES
            ):
                return _reject(
                    ViolationCode.FORBIDDEN_FUNCTION,
                    f"The function '{func_name}' is not allowed.",
                )
        return None

    def _check_tables(self, tree: exp.Expression) -> ValidationResult | None:
        cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
        available = ", ".join(sorted(self._allowed))

        for table in tree.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier):
                return _reject(
                    ViolationCode.FORBIDDEN_FUNCTION,
                    "Table-valued functions are not allowed in FROM.",
                )
            if table.db or table.catalog:
                return _reject(
                    ViolationCode.QUALIFIED_TABLE,
                    "Use plain table names without a schema or database prefix.",
                )
            name = table.name.lower()
            if name in cte_names:
                continue
            if name not in self._allowed:
                return _reject(
                    ViolationCode.UNKNOWN_TABLE,
                    f"The table '{table.name}' does not exist. Available tables: {available}.",
                )
        return None

    def _used_tables(self, tree: exp.Expression) -> list[str]:
        cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
        names = {t.name.lower() for t in tree.find_all(exp.Table)}
        return sorted(names - cte_names)

    # ---- límite de filas ------------------------------------------------

    def _enforce_limit(self, tree: exp.Expression) -> exp.Expression:
        if isinstance(tree, exp.Select):
            limit = tree.args.get("limit")
            if limit is not None:
                count = limit.expression
                if isinstance(count, exp.Literal) and count.is_int:
                    if int(count.name) <= self._max_rows:
                        return tree
            return tree.limit(self._max_rows)

        # UNION / INTERSECT / EXCEPT: se envuelve en una subconsulta con LIMIT.
        return exp.select("*").from_(tree.subquery("limited")).limit(self._max_rows)


@lru_cache
def get_sql_validator() -> SQLValidator:
    schema = get_database_schema()
    return SQLValidator(schema.table_names(), max_rows=get_settings().max_rows)