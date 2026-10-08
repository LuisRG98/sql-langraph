import pytest

from app.db.guardrail import SQLValidator, ViolationCode

ALLOWED_TABLES = {"categories", "products", "customers", "orders", "order_items"}


@pytest.fixture
def validator() -> SQLValidator:
    return SQLValidator(ALLOWED_TABLES, max_rows=100)


# ---------------------------------------------------------------- consultas válidas

VALID_QUERIES = [
    "SELECT * FROM customers",
    "SELECT * FROM CUSTOMERS",
    "SELECT 1",
    "SELECT * FROM customers;",
    "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders)",
    "WITH t AS (SELECT * FROM orders) SELECT COUNT(*) FROM t",
    "SELECT id FROM orders UNION SELECT id FROM customers",
    "SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM orders",
    "SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) FROM orders GROUP BY month",
    "SELECT * FROM products WHERE name = 'DROP TABLE x'",
    """
    SELECT c.name, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
    FROM order_items oi
    JOIN products p ON p.id = oi.product_id
    JOIN categories c ON c.id = p.category_id
    GROUP BY c.name
    ORDER BY revenue DESC
    """,
]


@pytest.mark.parametrize("sql", VALID_QUERIES)
def test_valid_queries_are_accepted(validator: SQLValidator, sql: str) -> None:
    result = validator.validate(sql)
    assert result.valid, result.error
    assert result.sql is not None
    assert result.error is None
    assert result.code is None


def test_reports_used_tables(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id")
    assert result.tables == ["customers", "orders"]


def test_cte_names_are_not_reported_as_tables(validator: SQLValidator) -> None:
    result = validator.validate("WITH t AS (SELECT * FROM orders) SELECT * FROM t")
    assert result.tables == ["orders"]


# ---------------------------------------------------------------- ataques con código exacto

REJECTED_WITH_CODE = [
    ("", ViolationCode.EMPTY),
    ("   ", ViolationCode.EMPTY),
    (";", ViolationCode.EMPTY),
    ("DROP TABLE customers", ViolationCode.NOT_READ_ONLY),
    ("DELETE FROM customers", ViolationCode.NOT_READ_ONLY),
    ("UPDATE products SET price = 0", ViolationCode.NOT_READ_ONLY),
    ("INSERT INTO categories (id, name) VALUES (99, 'x')", ViolationCode.NOT_READ_ONLY),
    ("CREATE TABLE x (id INTEGER)", ViolationCode.NOT_READ_ONLY),
    ("SELECT 1; DROP TABLE customers", ViolationCode.MULTIPLE_STATEMENTS),
    ("SELECT * FROM customers; SELECT * FROM orders", ViolationCode.MULTIPLE_STATEMENTS),
    (
        "SELECT * FROM customers WHERE name = 'x'; DROP TABLE customers; --",
        ViolationCode.MULTIPLE_STATEMENTS,
    ),
    ("SELECT * FROM sqlite_master", ViolationCode.UNKNOWN_TABLE),
    ("SELECT * FROM users", ViolationCode.UNKNOWN_TABLE),
    (
        "WITH x AS (SELECT * FROM sqlite_master) SELECT * FROM x",
        ViolationCode.UNKNOWN_TABLE,
    ),
    (
        "SELECT * FROM customers WHERE id IN (SELECT id FROM secrets)",
        ViolationCode.UNKNOWN_TABLE,
    ),
    ("SELECT * FROM main.customers", ViolationCode.QUALIFIED_TABLE),
    ("SELECT load_extension('evil.dll')", ViolationCode.FORBIDDEN_FUNCTION),
    ("SELECT readfile('/etc/passwd')", ViolationCode.FORBIDDEN_FUNCTION),
    ("SELECT randomblob(1000000000)", ViolationCode.FORBIDDEN_FUNCTION),
    ("SELECT * FROM customers WHERE (id = 1", ViolationCode.SYNTAX),
]


@pytest.mark.parametrize(("sql", "code"), REJECTED_WITH_CODE)
def test_attacks_are_rejected_with_expected_code(
    validator: SQLValidator, sql: str, code: ViolationCode
) -> None:
    result = validator.validate(sql)
    assert not result.valid
    assert result.code == code
    assert result.error
    assert result.sql is None


# ---------------------------------------------------------------- ataques (basta con rechazo)

REJECTED_ANY_REASON = [
    "PRAGMA table_info(customers)",
    "ATTACH DATABASE 'other.db' AS other",
    "VACUUM",
    "SELECT * FROM pragma_table_info('customers')",
    "Dame los clientes de Bolivia",
]


@pytest.mark.parametrize("sql", REJECTED_ANY_REASON)
def test_other_dangerous_or_invalid_input_is_rejected(validator: SQLValidator, sql: str) -> None:
    assert not validator.validate(sql).valid


def test_rejects_too_long_query(validator: SQLValidator) -> None:
    sql = "SELECT " + ", ".join(["1"] * 5000)
    result = validator.validate(sql)
    assert result.code == ViolationCode.TOO_LONG


def test_error_for_unknown_table_lists_available_tables(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM users")
    assert result.error is not None
    assert "customers" in result.error
    assert "orders" in result.error


# ---------------------------------------------------------------- comentarios y regeneración


def test_comments_are_stripped_from_final_sql(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM customers /* ; DROP TABLE customers */ -- otra")
    assert result.valid
    assert result.sql is not None
    assert "DROP" not in result.sql.upper()
    assert "/*" not in result.sql
    assert "--" not in result.sql


def test_trailing_comment_after_semicolon_is_harmless(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM customers; -- DROP TABLE customers")
    assert result.valid
    assert result.sql is not None
    assert "DROP" not in result.sql.upper()


def test_string_literal_content_is_preserved(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM products WHERE name = 'DROP TABLE x'")
    assert result.sql is not None
    assert "'DROP TABLE x'" in result.sql


# ---------------------------------------------------------------- límite de filas


def test_adds_limit_when_missing(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM customers")
    assert result.sql is not None
    assert "LIMIT 100" in result.sql


def test_caps_limit_above_maximum(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM orders LIMIT 10000")
    assert result.sql is not None
    assert "LIMIT 100" in result.sql
    assert "10000" not in result.sql


def test_keeps_smaller_limit(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM orders LIMIT 5")
    assert result.sql is not None
    assert "LIMIT 5" in result.sql
    assert "LIMIT 100" not in result.sql


def test_negative_limit_does_not_mean_unlimited(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM orders LIMIT -1")
    assert result.sql is not None
    assert "LIMIT 100" in result.sql


def test_union_is_wrapped_with_limit(validator: SQLValidator) -> None:
    result = validator.validate("SELECT id FROM orders UNION SELECT id FROM customers")
    assert result.sql is not None
    assert result.sql.upper().startswith("SELECT * FROM (")
    assert result.sql.upper().endswith("LIMIT 100")


def test_custom_max_rows_is_respected() -> None:
    small = SQLValidator(ALLOWED_TABLES, max_rows=7)
    result = small.validate("SELECT * FROM orders")
    assert result.sql is not None
    assert "LIMIT 7" in result.sql