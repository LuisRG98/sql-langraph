"""Muestra el esquema y comprueba que la conexión es de solo lectura."""
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.engine import get_readonly_engine
from app.db.hints import SCHEMA_HINTS
from app.db.schema import extract_schema

REVENUE_BY_CATEGORY = """
SELECT c.name AS category,
       ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN categories c ON c.id = p.category_id
JOIN orders o ON o.id = oi.order_id
WHERE o.status = 'delivered'
GROUP BY c.name
ORDER BY revenue DESC
"""


def main() -> None:
    engine = get_readonly_engine()

    print("=== ESQUEMA PARA EL PROMPT ===\n")
    print(extract_schema(engine, hints=SCHEMA_HINTS).to_prompt())

    print("\n=== INGRESOS POR CATEGORIA (pedidos entregados) ===")
    with engine.connect() as conn:
        for row in conn.execute(text(REVENUE_BY_CATEGORY)):
            print(f"  {row.category:<12} {row.revenue:>10}")

    print("\n=== PRUEBA DE SOLO LECTURA ===")
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM customers"))
        print("PELIGRO: la escritura NO fue bloqueada")
    except OperationalError as exc:
        print(f"Escritura bloqueada correctamente: {exc.orig}")


if __name__ == "__main__":
    main()