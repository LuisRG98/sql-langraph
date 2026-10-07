import random
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, func, insert, select

from app.db.tables import (
    categories,
    customers,
    metadata,
    order_items,
    orders,
    products,
)

CATEGORIES = ["Electronics", "Home", "Books", "Sports", "Clothing"]

# (nombre, categoría, precio USD)
PRODUCTS = [
    ("Wireless Mouse", "Electronics", 24.99),
    ("Mechanical Keyboard", "Electronics", 89.90),
    ("USB-C Hub", "Electronics", 39.50),
    ("Noise Cancelling Headphones", "Electronics", 199.00),
    ("Coffee Maker", "Home", 59.90),
    ("Desk Lamp", "Home", 32.00),
    ("Air Purifier", "Home", 129.00),
    ("Cookware Set", "Home", 149.50),
    ("Python Cookbook", "Books", 45.00),
    ("Clean Architecture", "Books", 38.00),
    ("Data Science Handbook", "Books", 52.75),
    ("Sci-Fi Anthology", "Books", 18.50),
    ("Yoga Mat", "Sports", 22.00),
    ("Dumbbell Set", "Sports", 75.00),
    ("Running Shoes", "Sports", 110.00),
    ("Water Bottle", "Sports", 14.99),
    ("Denim Jacket", "Clothing", 79.00),
    ("Cotton T-Shirt", "Clothing", 15.00),
    ("Wool Sweater", "Clothing", 64.90),
    ("Rain Coat", "Clothing", 95.00),
]

FIRST_NAMES = ["Ana", "Luis", "Maria", "Carlos", "Lucia", "Jorge", "Sofia", "Diego", "Valeria", "Pablo"]
LAST_NAMES = ["Garcia", "Rojas", "Mendoza", "Lopez", "Fernandez", "Torres", "Flores", "Vargas"]
COUNTRIES = ["Bolivia", "Argentina", "Chile", "Peru", "Colombia", "Mexico", "Spain"]

STATUSES = ["delivered", "shipped", "paid", "pending", "cancelled"]
STATUS_WEIGHTS = [55, 15, 12, 8, 10]

CUSTOMERS_START = date(2024, 1, 1)
CUSTOMERS_END = date(2025, 6, 30)
ORDERS_START = date(2025, 1, 1)
ORDERS_END = date(2026, 9, 30)


def _random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def seed_database(
    engine: Engine,
    *,
    seed: int = 42,
    n_customers: int = 50,
    n_orders: int = 300,
) -> dict[str, int]:
    """Recrea todas las tablas y las llena con datos deterministas."""
    rng = random.Random(seed)

    metadata.drop_all(engine)
    metadata.create_all(engine)

    category_rows: list[dict[str, Any]] = [
        {"id": i, "name": name} for i, name in enumerate(CATEGORIES, start=1)
    ]
    category_id = {row["name"]: row["id"] for row in category_rows}

    product_rows: list[dict[str, Any]] = [
        {
            "id": i,
            "name": name,
            "category_id": category_id[category],
            "price": price,
            "stock": rng.randint(0, 200),
        }
        for i, (name, category, price) in enumerate(PRODUCTS, start=1)
    ]

    customer_rows: list[dict[str, Any]] = []
    for i in range(1, n_customers + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        customer_rows.append(
            {
                "id": i,
                "name": f"{first} {last}",
                "email": f"{first}.{last}.{i}@example.com".lower(),
                "country": rng.choice(COUNTRIES),
                "created_at": _random_date(rng, CUSTOMERS_START, CUSTOMERS_END),
            }
        )

    order_rows: list[dict[str, Any]] = []
    item_rows: list[dict[str, Any]] = []
    item_id = 1
    for order_id in range(1, n_orders + 1):
        customer = rng.choice(customer_rows)
        first_possible_day = max(customer["created_at"], ORDERS_START)
        order_rows.append(
            {
                "id": order_id,
                "customer_id": customer["id"],
                "order_date": _random_date(rng, first_possible_day, ORDERS_END),
                "status": rng.choices(STATUSES, weights=STATUS_WEIGHTS)[0],
            }
        )
        for product in rng.sample(product_rows, k=rng.randint(1, 4)):
            item_rows.append(
                {
                    "id": item_id,
                    "order_id": order_id,
                    "product_id": product["id"],
                    "quantity": rng.randint(1, 3),
                    "unit_price": product["price"],
                }
            )
            item_id += 1

    # El orden importa: primero las tablas "padre", luego las que las referencian.
    with engine.begin() as conn:
        conn.execute(insert(categories), category_rows)
        conn.execute(insert(products), product_rows)
        conn.execute(insert(customers), customer_rows)
        conn.execute(insert(orders), order_rows)
        conn.execute(insert(order_items), item_rows)

    with engine.connect() as conn:
        return {
            table.name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for table in metadata.sorted_tables
        }