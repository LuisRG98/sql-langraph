SCHEMA_HINTS: dict[str, str] = {
    "customers.country": "country name in English, e.g. Bolivia, Spain, Mexico",
    "customers.created_at": "registration date, format YYYY-MM-DD",
    "products.price": "current list price in USD",
    "products.stock": "units currently in inventory",
    "orders.order_date": "date the order was placed, format YYYY-MM-DD",
    "orders.status": "one of: pending, paid, shipped, delivered, cancelled",
    "order_items.quantity": "units of the product in this order line",
    "order_items.unit_price": "USD price per unit at purchase time; line total = quantity * unit_price",
}