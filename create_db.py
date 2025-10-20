import sqlite3

conn = sqlite3.connect("paluto.db")
cur = conn.cursor()

# Create products table
cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    type TEXT,
    variety_1 TEXT,
    variety_2 TEXT,
    state_1 TEXT,
    state_2 TEXT,
    luto TEXT,
    uom TEXT,
    price REAL
)
""")

# ✅ Create sales table
cur.execute("""
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT,
    table_id INTEGER,
    product_id TEXT,
    weight_in_kg REAL,
    quantity INTEGER,
    subtotal REAL,
    discount REAL,
    total REAL,
    datetime TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'ACTIVE'
)
""")

conn.commit()
conn.close()

print("✅ Database and tables created successfully!")
