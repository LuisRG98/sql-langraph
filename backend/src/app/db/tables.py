from sqlalchemy import Column, Date, Float, ForeignKey, Integer, MetaData, String, Table

metadata = MetaData()

categories = Table(
    "categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False, unique=True),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("category_id", Integer, ForeignKey("categories.id"), nullable=False),
    Column("price", Float, nullable=False),
    Column("stock", Integer, nullable=False),
)

customers = Table(
    "customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("email", String(120), nullable=False, unique=True),
    Column("country", String(50), nullable=False),
    Column("created_at", Date, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
    Column("order_date", Date, nullable=False),
    Column("status", String(20), nullable=False),
)

order_items = Table(
    "order_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Float, nullable=False),
)