import sqlite3

# Connect to your SQLite database
conn = sqlite3.connect("paluto.db")
cur = conn.cursor()

# Select first few rows from products
cur.execute("SELECT * FROM products LIMIT 10;")
rows = cur.fetchall()

print("=== Sample Data from 'products' Table ===")
for row in rows:
    print(row)

conn.close()
print("✅ Done reading database!")
