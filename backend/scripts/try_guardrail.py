"""Prueba el guardrail con consultas legítimas y ataques típicos."""
from app.db.guardrail import get_sql_validator

CASES: list[tuple[str, str]] = [
    ("OK  simple", "SELECT name, country FROM customers WHERE country = 'Bolivia'"),
    ("OK  literal sospechoso", "SELECT * FROM products WHERE name = 'DROP TABLE x'"),
    ("OK  comentario", "SELECT * FROM customers /* ; DROP TABLE customers */"),
    ("OK  limite enorme", "SELECT * FROM order_items LIMIT 100000"),
    ("OK  union", "SELECT id FROM orders UNION SELECT id FROM customers"),
    ("NO  drop", "DROP TABLE customers"),
    ("NO  delete", "DELETE FROM customers"),
    ("NO  dos sentencias", "SELECT 1; DROP TABLE customers"),
    ("NO  sqlite_master", "SELECT * FROM sqlite_master"),
    ("NO  tabla inventada", "SELECT * FROM users"),
    ("NO  prefijo", "SELECT * FROM main.customers"),
    ("NO  pragma", "SELECT * FROM pragma_table_info('customers')"),
    ("NO  load_extension", "SELECT load_extension('evil.dll')"),
    ("NO  sintaxis", "SELECT * FROM customers WHERE (id = 1"),
]


def main() -> None:
    validator = get_sql_validator()
    for label, sql in CASES:
        result = validator.validate(sql)
        status = "✅ valido  " if result.valid else "⛔ rechazado"
        print(f"{status} | {label}")
        if result.valid:
            print(f"             SQL final: {result.sql}")
        else:
            print(f"             [{result.code}] {result.error}")


if __name__ == "__main__":
    main()