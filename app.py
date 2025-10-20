# ============================================================
# PALUTO POS SYSTEM — CLEANED & COMMENTED VERSION
# ============================================================

from flask import Flask, make_response, render_template, request, redirect, url_for, jsonify, Response
import sqlite3, random, string, io, csv

app = Flask(__name__)
DB = "paluto.db"


# ============================================================
# 🔹 DATABASE CONNECTION UTILITY
# ============================================================
def get_db():
    """Establishes and returns an SQLite database connection."""
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn


# ============================================================
# 🔹 MAIN TABLE SELECTION (HOME PAGE)
# ============================================================
@app.route("/")
def tables():
    """Displays all tables (1–50 + 101–107) and their current order status."""
    conn = get_db()
    cur = conn.cursor()

    # Get all active or served tables
    cur.execute("""
        SELECT DISTINCT table_id, transaction_id, status, order_mode
        FROM sales
        WHERE status IN ('ACTIVE', 'READY', 'SERVED')
    """)
    sales = cur.fetchall()

    all_tables = []
    # Regular tables 1–50
    for i in range(1, 51):
        match = next((s for s in sales if s["table_id"] == i), None)
        all_tables.append({
            "table_id": i,
            "status": "ACTIVE" if match else "AVAILABLE",
            "transaction_id": match["transaction_id"] if match else None,
            "order_mode": match["order_mode"] if match else None
        })

    # Kubo huts 101–107
    for i in range(101, 107):
        match = next((s for s in sales if s["table_id"] == i), None)
        all_tables.append({
            "table_id": i,
            "status": "ACTIVE" if match else "AVAILABLE",
            "transaction_id": match["transaction_id"] if match else None,
            "order_mode": match["order_mode"] if match else None
        })

    conn.close()
    return render_template("tables.html", tables=all_tables)


# ============================================================
# 🔹 START NEW ORDER
# ============================================================
@app.route("/start_order", methods=["POST"])
def start_order():
    """Creates a new transaction and redirects to POS screen."""
    table_id = request.form.get("table_id")
    order_type = request.form.get("order_type", "regular")
    txn_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return redirect(url_for("pos", table_id=table_id, txn_id=txn_id, order_type=order_type))


# ============================================================
# 🔹 POS INTERFACE
# ============================================================
@app.route("/pos")
def pos():
    """Renders the POS page for a specific table and transaction."""
    table_id = request.args.get("table_id")
    txn_id = request.args.get("txn_id")
    order_type = request.args.get("order_type", "regular")

    # Generate new txn_id if missing
    if not txn_id or txn_id == 'None':
        new_txn_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return redirect(url_for('pos', table_id=table_id, txn_id=new_txn_id, order_type=order_type))

    # Render page with no caching
    html = render_template("pos.html", table_id=table_id, txn_id=txn_id, order_type=order_type)
    response = make_response(html)
    response.headers.update({
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    })
    return response


# ============================================================
# 🔹 ADD ITEM TO ORDER
# ============================================================
@app.route("/add_item", methods=["POST"])
def add_item():
    """Adds or updates an item in the active sales list."""
    data = request.get_json()
    txn_id = data["transaction_id"]
    table_id = data["table_id"]
    product_id = data["product_id"]
    uom = data["uom"]
    price = float(data["price"])
    qty = int(data["qty"])
    grams = float(data.get("grams") or 0)
    order_type = data.get("order_type", "regular")

    subtotal = price * qty if uom.upper() == "SERVE" else price * (grams / 1000)
    conn = get_db()
    cur = conn.cursor()

    # Check if item already exists in ACTIVE order
    cur.execute("""
        SELECT id, quantity, weight_in_kg, subtotal 
        FROM sales 
        WHERE transaction_id = ? AND product_id = ? AND status = 'ACTIVE'
    """, (txn_id, product_id))
    existing = cur.fetchone()

    if existing:
        # Update existing item
        new_qty = existing["quantity"] + qty
        new_weight = (existing["weight_in_kg"] or 0) + (grams / 1000)
        new_subtotal = price * new_qty if uom.upper() == "SERVE" else price * new_weight
        cur.execute("""
            UPDATE sales
            SET quantity = ?, weight_in_kg = ?, subtotal = ?, total = ?
            WHERE id = ?
        """, (new_qty, new_weight, new_subtotal, new_subtotal, existing["id"]))
    else:
        # Insert new item
        cur.execute("""
            INSERT INTO sales (
                transaction_id, table_id, product_id, weight_in_kg, quantity, subtotal, discount, total, datetime, status, order_mode
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, datetime('now'), 'ACTIVE', ?)
        """, (txn_id, table_id, product_id, grams / 1000, qty, subtotal, subtotal, order_type))

    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ============================================================
# 🔹 CANCEL ORDER
# ============================================================
@app.route("/cancel_order/<txn_id>", methods=["POST"])
def cancel_order(txn_id):
    """Deletes all PENDING items for a transaction."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM sales WHERE transaction_id=? AND status='PENDING'", (txn_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ============================================================
# 🔹 LIVE RECEIPT FETCHER
# ============================================================
@app.route('/get_receipt/<txn_id>')
def get_receipt(txn_id):
    """Returns all items in a transaction for the POS live receipt."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.*, p.type, p.variety_1, p.variety_2, p.state_1, p.state_2, p.luto, p.uom, p.price
        FROM sales s JOIN products p ON s.product_id = p.id
        WHERE s.transaction_id = ? AND s.status IN ('PENDING', 'ACTIVE', 'READY', 'SERVED')
    """, (txn_id,))
    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(items)


# ============================================================
# 🔹 CHECKOUT — SAVE ORDER
# ============================================================
@app.route("/checkout/<txn_id>", methods=["POST"])
def checkout(txn_id):
    """Save all items for the transaction and mark it ACTIVE."""
    try:
        data = request.get_json()
        orders = data.get("orders", [])
        table_id = data.get("table_id")
        order_type = data.get("order_type")

        if not orders:
            return jsonify({"error": "No orders received"}), 400

        conn = get_db()
        cur = conn.cursor()

        for item in orders:
            cur.execute("""
                INSERT INTO sales (transaction_id, table_id, product_id, quantity, weight_in_kg, subtotal, total, status, order_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (
                txn_id,
                table_id,
                item.get("product_id"),
                item.get("qty"),
                (item.get("grams", 0) / 1000.0),
                (item.get("price") * (item.get("grams", 0) / 1000.0) if item.get("uom").upper() == "KG" else item.get("qty") * item.get("price")),
                (item.get("price") * (item.get("grams", 0) / 1000.0) if item.get("uom").upper() == "KG" else item.get("qty") * item.get("price")),
                order_type
            ))

        # Mark transaction ACTIVE
        cur.execute("UPDATE sales SET status='ACTIVE' WHERE transaction_id=?", (txn_id,))
        conn.commit()
        conn.close()

        return jsonify({"message": "Order saved successfully!"})
    
    except Exception as e:
        print("❌ Checkout error:", str(e))
        return jsonify({"error": str(e)})



# ============================================================
# 🔹 FETCH ALL PRODUCTS
# ============================================================
@app.route("/fetch_products")
def fetch_products():
    """Provides all products for the POS product grid."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products")
    data = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(data)


# ============================================================
# 🔹 PAYMENT FUNCTIONS
# ============================================================
@app.route("/record_payment/<txn_id>", methods=["POST"])
def record_payment(txn_id):
    """Records a partial payment (Cash / GCash / Card)."""
    data = request.get_json()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO payments (transaction_id, amount, method) VALUES (?, ?, ?)",
                (txn_id, float(data['amount']), data['method']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route("/complete_payment/<txn_id>", methods=["POST"])
def complete_payment(txn_id):
    """Marks order as PAID when fully settled."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE sales SET status='PAID' WHERE transaction_id=?", (txn_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Payment successful! Table is now available."})


# ============================================================
# 🔹 KITCHEN DISPLAY SYSTEM
# ============================================================
@app.route('/kitchen')
def kitchen_page():
    """Renders kitchen display for staff."""
    return render_template('kitchen.html')


@app.route('/view')
def view_page():
    """Displays orders ready to serve."""
    return render_template('view.html')


@app.route('/api/kitchen_orders')
def get_kitchen_orders():
    """Fetches all ACTIVE and READY orders for the kitchen display."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.transaction_id, s.table_id, s.status, p.luto, p.type,
               p.variety_1, p.variety_2, p.state_1, p.state_2, s.datetime
        FROM sales s JOIN products p ON s.product_id = p.id
        WHERE s.status IN ('ACTIVE', 'READY')
        ORDER BY s.datetime ASC
    """)
    rows = cur.fetchall()
    conn.close()

    # Group by transaction
    orders = {}
    for row in rows:
        txn_id = row['transaction_id']
        if txn_id not in orders:
            orders[txn_id] = {'table_id': row['table_id'], 'status': row['status'], 'items': []}
        state = row['state_1'] or row['state_2']
        prefix = state[0].upper() + '. ' if state and (state.upper() in ['DEAD', 'ALIVE']) else ''
        item_name = ' '.join(filter(None, [prefix, row['variety_1'], row['variety_2'], row['luto']]))
        orders[txn_id]['items'].append(item_name)
    return jsonify(orders)


@app.route('/api/update_order_status/<txn_id>/<new_status>', methods=['POST'])
def update_order_status(txn_id, new_status):
    """Allows kitchen to mark an order as READY or SERVED."""
    if new_status not in ['READY', 'SERVED']:
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE sales SET status = ? WHERE transaction_id = ?", (new_status, txn_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})
# ============================================================
# 🔹 RECEIPT WHEN PRESS SAVE ORDER
# ============================================================
@app.route("/payment/<txn_id>")
def payment_page(txn_id):
    """Renders the payment page, showing order details and partial payments."""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            s.id AS sale_id,
            s.transaction_id,
            s.product_id,
            s.quantity,
            s.weight_in_kg,
            s.subtotal,
            s.discount,
            s.total,
            s.order_mode,
            s.discount_type,
            p.type,
            p.variety_1,
            p.variety_2,
            p.state_1,
            p.state_2,
            p.luto,
            p.uom,
            p.price AS product_price
        FROM sales s
        LEFT JOIN products p ON s.product_id = p.id
        WHERE s.transaction_id = ? AND s.status IN ('ACTIVE', 'READY', 'SERVED')
    """, (txn_id,))
    sales = cur.fetchall()

    cur.execute("SELECT * FROM payments WHERE transaction_id = ?", (txn_id,))
    payments = cur.fetchall()
    conn.close()

    sub_total = sum(row['subtotal'] for row in sales if row['subtotal'])
    total_discount = sum(row['discount'] for row in sales if row['discount'])
    vatable_sales = sub_total / 1.12 if sub_total > 0 else 0
    vat_amount = sub_total - vatable_sales
    total = sub_total - total_discount
    paid_amount = sum(p['amount'] for p in payments if p['amount'])
    remaining = total - paid_amount

    # ✅ FIXED LINE BELOW
    order_type = sales[0]['order_mode'] if sales and sales[0]['order_mode'] else 'Regular'

    return render_template("payment.html",
        txn_id=txn_id,
        sales=sales,
        payments=payments,
        total=total,
        sub_total=sub_total,
        total_discount=total_discount,
        paid_amount=paid_amount,
        remaining=remaining,
        vatable_sales=vatable_sales,
        vat_amount=vat_amount,
        order_type=order_type
    )





# ============================================================
# 🔹 ADMIN DASHBOARD + EXPORTS
# ============================================================
@app.route("/login.html")
def login_page():
    """Admin login page."""
    return render_template("login.html")


@app.route("/dashboard.html")
def dashboard_page():
    """Admin analytics dashboard."""
    return render_template("dashboard.html")


@app.route('/export_csv')
def export_csv():
    """Exports paid sales as downloadable CSV."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.transaction_id, s.table_id, p.type, p.variety_1, p.variety_2,
               p.state_1, p.state_2, p.luto, s.quantity, s.weight_in_kg, s.subtotal, s.datetime
        FROM sales s JOIN products p ON s.product_id = p.id
        WHERE s.status = 'PAID'
        ORDER BY s.datetime DESC
    """)
    sales_data = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Transaction ID', 'Table ID', 'Item', 'Quantity', 'Weight (kg)', 'Subtotal', 'Timestamp'])
    for row in sales_data:
        full_name = ' '.join(filter(None, [row['type'], row['variety_1'], row['variety_2'], row['state_1'], row['state_2'], row['luto']]))
        writer.writerow([row['transaction_id'], row['table_id'], full_name, row['quantity'], row['weight_in_kg'], row['subtotal'], row['datetime']])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=sales_report.csv"})


# ============================================================
# 🔹 DISCOUNT LOGIC
# ============================================================
@app.route('/apply_discount/<txn_id>', methods=['POST'])
def apply_discount(txn_id):
    """Applies Senior, PWD, Employee, or Custom discount logic."""
    data = request.get_json()
    discount_type = data.get('discount_type')
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT SUM(subtotal) FROM sales WHERE transaction_id = ?", (txn_id,))
    total_subtotal = cur.fetchone()[0] or 0
    if total_subtotal == 0:
        conn.close()
        return jsonify({'error': 'Cannot apply discount to an empty order.'}), 400

    total_deduction = 0
    message = "Discount applied."
    final_discount_type_to_save = discount_type if discount_type != 'remove' else None

    try:
        # Senior / PWD logic
        if discount_type in ['senior', 'pwd']:
            total_diners = int(data.get('total_diners', 1))
            headcount = int(data.get('headcount', 0))
            if headcount <= 0:
                final_discount_type_to_save = None
                message = "Discount removed."
            elif headcount > total_diners:
                conn.close()
                return jsonify({'error': 'Senior/PWD count cannot exceed total diners.'}), 400
            else:
                vat_exclusive_bill = total_subtotal / 1.12
                eligible_share = (vat_exclusive_bill / total_diners) * headcount
                discount_amount = eligible_share * 0.20
                total_vat = total_subtotal - vat_exclusive_bill
                vat_exempt_share = (total_vat / total_diners) * headcount
                total_deduction = discount_amount + vat_exempt_share
                message = f"Applied {headcount} {discount_type.upper()} discount."

        # Employee discount (10%)
        elif discount_type == 'employee':
            total_deduction = total_subtotal * 0.10
            message = "Applied 10% Employee discount."

        # Custom discount (user-defined %)
        elif discount_type == 'custom':
            percent = float(data.get('percentage', 0))
            if not (0 <= percent <= 100):
                conn.close()
                return jsonify({'error': 'Percentage must be between 0 and 100.'}), 400
            total_deduction = total_subtotal * (percent / 100.0)
            message = f"Applied {percent}% custom discount."

        # Remove discount
        elif discount_type == 'remove':
            total_deduction = 0
            message = "Discount removed."

        else:
            conn.close()
            return jsonify({'error': 'Invalid discount type specified.'}), 400

        # Apply proportionally to all items
        discount_multiplier = total_deduction / total_subtotal if total_subtotal > 0 else 0
        cur.execute("""
            UPDATE sales SET discount = subtotal * ?, discount_type = ? WHERE transaction_id = ?
        """, (discount_multiplier, final_discount_type_to_save, txn_id))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': message})

    except (ValueError, TypeError):
        conn.close()
        return jsonify({'error': 'Invalid input provided for discount calculation.'}), 400


# ============================================================
# 🔹 MAIN ENTRY POINT
# ============================================================
if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
