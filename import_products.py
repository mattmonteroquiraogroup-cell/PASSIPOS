import sqlite3
import csv

# --- Connect to SQLite database ---
conn = sqlite3.connect("paluto.db")
cur = conn.cursor()

# --- CSV filename ---
csv_file = "products.csv"

def clean_price(value):
    """Remove ₱ sign, commas, and blanks; convert to float safely."""
    if not value or str(value).strip() == "":
        return 0.0
    value = str(value).replace("₱", "").replace(",", "").replace(" ", "")
    try:
        return float(value)
    except ValueError:
        print(f"⚠️ Warning: Could not convert '{value}' — set to 0.0")
        return 0.0

# --- Read and insert data ---
with open(csv_file, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = []
    for r in reader:
        rows.append((
            r.get('CATEGORY', '').strip(),
            r.get('TYPE', '').strip(),
            r.get('VARIETY_1', '').strip(),
            r.get('VARIETY_2', '').strip(),
            r.get('STATE_1', '').strip(),
            r.get('STATE_2', '').strip(),
            r.get('LUTO', '').strip(),
            r.get('UOM', '').strip(),
            clean_price(r.get('PRICE', ''))
        ))

cur.executemany("""
    INSERT INTO products (
        category, type, variety_1, variety_2, state_1, state_2, luto, uom, price
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", rows)

conn.commit()
conn.close()
print(f"✅ Imported {len(rows)} rows successfully!")
