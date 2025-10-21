# ============================================================
# PALUTO POS SYSTEM — CLEANED & COMMENTED VERSION
# ============================================================

from flask import Flask, make_response, render_template, request, redirect, url_for, jsonify, Response, session
import sqlite3, random, string, io, csv

app = Flask(__name__)
app.secret_key = "super_secret_paluto_key"  # any random string
DB = "paluto.db"

# ============================================================
# 🔹 RECEIPT (PDF GENERATION) MODULES
# ============================================================
from datetime import datetime
from flask import send_file
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import tempfile


# New code
import os, sys

# Detect if running as .exe or script
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS  # Temporary folder used by PyInstaller
    ROOT_DIR = os.path.dirname(sys.executable)  # Folder where EXE is located
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = BASE_DIR

DB = os.path.join(ROOT_DIR, "paluto.db")



# ============================================================
# 🔹 DATABASE CONNECTION UTILITY
# ============================================================
def get_db():
    """Establishes and returns an SQLite database connection."""
    conn = sqlite3.connect(DB, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

# ============================================================
# 🔹 UNIVERSAL LOGIN (Admin + Cashier)
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    """Logs in either Admin or Cashier depending on credentials."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_credentials WHERE username=? AND password=?", (username, password))
        user = cur.fetchone()
        conn.close()

        if user:
            # ✅ Save user info in session
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            if user["role"] == "admin":
                return redirect(url_for("dashboard_page"))
            elif user["role"] == "cashier":
                
                return redirect(url_for("tables"))  # cashier starts at tables
        else:
            return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html")

# ============================================================
# 🔹 LOGOUT
# ============================================================
@app.route("/logout")
def logout():
    """Logs out the current user."""
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def home():
    """Always start the system at the login page."""
    return redirect(url_for("login"))


# ============================================================
# 🔹 MAIN TABLE SELECTION (HOME PAGE)
# ============================================================
@app.route("/tables")
def tables():
    """Displays all tables (1–50 + 101–107) and their current order status."""

    # 🔒 Require login as cashier before accessing
    if "role" not in session or session["role"] != "cashier":
        return redirect(url_for("login"))

    # ✅ Ensure opening cash is set for today before accessing tables
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM daily_opening_cash
        WHERE username = ? AND date_opened = date('now')
    """, (session["username"],))
    opening_cash = cur.fetchone()
    if not opening_cash:
        conn.close()
        return redirect(url_for("opening_cash"))

    # 🔍 Debug (optional): Check if the session name is being stored
    print("Session name:", session.get("name"))

    # 🪑 Get all active or served tables from sales
    cur.execute("""
        SELECT DISTINCT table_id, transaction_id, status, order_mode
        FROM sales
        WHERE status IN ('ACTIVE', 'READY', 'SERVED')
    """)
    sales = cur.fetchall()

    all_tables = []

    # 🍽️ Regular tables (1–50)
    for i in range(1, 51):
        match = next((s for s in sales if s["table_id"] == i), None)
        all_tables.append({
            "table_id": i,
            "status": "ACTIVE" if match else "AVAILABLE",
            "transaction_id": match["transaction_id"] if match else None,
            "order_mode": match["order_mode"] if match else None
        })

    # 🛖 Kubo huts (101–107)
    for i in range(101, 108):  # fixed upper bound (include 107)
        match = next((s for s in sales if s["table_id"] == i), None)
        all_tables.append({
            "table_id": i,
            "status": "ACTIVE" if match else "AVAILABLE",
            "transaction_id": match["transaction_id"] if match else None,
            "order_mode": match["order_mode"] if match else None
        })

    conn.close()

    # ✅ Pass opening cash to template (optional display in tables.html)
    return render_template("tables.html", tables=all_tables, opening_cash=opening_cash)



# ============================================================
# 🔹 OPENING CASH SETUP
# ============================================================
@app.route("/opening_cash", methods=["GET", "POST"])
def opening_cash():
    if "role" not in session or session["role"] != "cashier":
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    # Check if already set today for this user
    cur.execute("""
        SELECT * FROM daily_opening_cash
        WHERE username = ? AND date_opened = date('now')
    """, (session["username"],))
    existing = cur.fetchone()

    if request.method == "POST":
        print("🧾 FORM SUBMITTED:", request.form)  # debug

        # total from hidden field
        raw_amount = (request.form.get("opening_amount") or "").strip()
        try:
            amount = float(raw_amount) if raw_amount else 0.0
        except (ValueError, TypeError):
            amount = 0.0

        if existing:
            conn.close()
            return render_template("opening_cash.html",
                                   existing=existing,
                                   message="Opening cash already set for today.")

        # read denomination counts from form (the inputs must have name="d1000", etc.)
        denom_keys = [1000, 500, 200, 100, 50, 20, 10, 5, 1]
        denom_dict = {}
        for n in denom_keys:
            try:
                denom_dict[f"d{n}"] = int(request.form.get(f"d{n}", 0))
            except (ValueError, TypeError):
                denom_dict[f"d{n}"] = 0

        # figure out which denom columns actually exist in the DB
        cur.execute("PRAGMA table_info(daily_opening_cash)")
        cols = {row["name"] for row in cur.fetchall()}

        # base columns always saved
        col_names = ["user_id", "username", "opening_amount"]
        params = [session["user_id"], session["username"], amount]

        # add only denomination columns that exist
        for k in denom_dict.keys():
            if k in cols:
                col_names.append(k)
                params.append(denom_dict[k])

        # Build INSERT dynamically
        placeholders = ", ".join(["?"] * len(col_names))
        col_list = ", ".join(col_names)
        sql = f"INSERT INTO daily_opening_cash ({col_list}) VALUES ({placeholders})"

        try:
            cur.execute(sql, params)
            conn.commit()
        except sqlite3.OperationalError as e:
            conn.rollback()
            print("❌ SQLite error:", e)
            return render_template("opening_cash.html",
                                   existing=None,
                                   message="Database is busy or columns missing. Please try again.")
        finally:
            conn.close()

        print("✅ Opening cash saved:", amount, "| Cols:", col_list)
        return redirect(url_for("tables"))

    conn.close()
    return render_template("opening_cash.html", existing=existing)


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
    # 🔒 Require login as cashier
    if "role" not in session or session["role"] != "cashier":
        return redirect(url_for("login"))

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
    """Records a payment but only applies up to the remaining balance; computes change."""
    try:
        data = request.get_json()
        amount_given = float(data.get("amount", 0))
        method = data.get("method", "CASH")

        conn = get_db()
        cur = conn.cursor()

        # 🧮 Compute totals safely
        cur.execute("SELECT SUM(subtotal - COALESCE(discount, 0)) FROM sales WHERE transaction_id = ?", (txn_id,))
        total_bill = cur.fetchone()[0] or 0

        cur.execute("SELECT SUM(amount) FROM payments WHERE transaction_id = ?", (txn_id,))
        already_paid = cur.fetchone()[0] or 0

        remaining = total_bill - already_paid
        applied_amount = min(amount_given, remaining)
        change = max(amount_given - remaining, 0)

        # 💾 Save only the applied amount
        cur.execute(
            "INSERT INTO payments (transaction_id, amount, method) VALUES (?, ?, ?)",
            (txn_id, applied_amount, method)
        )
        conn.commit()
        conn.close()

        print(f"✅ Payment recorded: txn={txn_id}, given={amount_given}, applied={applied_amount}, change={change}")
        return jsonify({
            "success": True,
            "message": f"Payment recorded successfully. Change: ₱{change:.2f}",
            "applied_amount": applied_amount,
            "change": change
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ==========================
# COMPLETE PAYMENT FUNCTION
# ==========================
@app.route("/complete_payment/<txn_id>", methods=["POST"])
def complete_payment(txn_id):
    """Marks order as PAID when fully settled and prints receipt."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE sales SET status='PAID' WHERE transaction_id=?", (txn_id,))
    conn.commit()
    conn.close()

    # 🖨️ Print receipt and capture result message
    result_message = print_receipt(txn_id)

    return jsonify({"message": f"Payment successful! {result_message}"})


# ============================================================
# 🔹 PRINT RECEIPT FUNCTION (PERFECT CENTERED HEADER)
# ============================================================
import platform, os, textwrap
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

def generate_receipt_pdf(lines, pdf_path, char_width=38, font_name="Courier", font_size=7.0, margin_mm=10.5):
    """
    Improved version: Centers entire receipt content evenly on paper.
    - <C> still explicitly centers header text
    - Non-<C> lines (items/totals) are horizontally centered as a block
    - Works perfectly for 58mm & 80mm printers
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    import textwrap

    width_mm = 75  # near full printable width for 58mm roll
    width_pt = width_mm * mm
    line_height = font_size * 1.22
    total_lines = sum(len(textwrap.wrap(line.replace("<C>", ""), char_width)) for line in lines) + 12
    height_pt = (margin_mm * mm * 2) + (total_lines * line_height)

    c = canvas.Canvas(pdf_path, pagesize=(width_pt, height_pt))
    c.setFont(font_name, font_size)

    y = height_pt - (margin_mm * mm)

    for line in lines:
        wrapped = textwrap.wrap(line, char_width)
        for wrapped_line in wrapped:
            # Header or centered line (manual <C> tag)
            if wrapped_line.startswith("<C>"):
                text = wrapped_line.replace("<C>", "").strip()
                text_width = c.stringWidth(text, font_name, font_size)
                c.drawString((width_pt - text_width) / 2, y, text)
            else:
                # NEW: auto-center non-<C> lines (body/totals)
                text_width = c.stringWidth(wrapped_line, font_name, font_size)
                c.drawString((width_pt - text_width) / 2, y, wrapped_line)
            y -= line_height

    c.showPage()
    c.save()
    return pdf_path



def print_receipt(txn_id):
    """
    Generates PALUTO-style TEMPORARY INVOICE receipt.
    """
    try:
        conn = get_db()
        cur = conn.cursor()

        # === Fetch Data ===
        cur.execute("""
            SELECT s.quantity, s.weight_in_kg, s.subtotal, s.discount, s.total,
                   p.variety_1, p.variety_2, p.luto, p.uom, p.price
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            WHERE s.transaction_id = ?
        """, (txn_id,))
        items = cur.fetchall()

        cur.execute("SELECT SUM(amount) FROM payments WHERE transaction_id = ?", (txn_id,))
        paid = cur.fetchone()[0] or 0.0

        cur.execute("SELECT SUM(subtotal - COALESCE(discount,0)) FROM sales WHERE transaction_id = ?", (txn_id,))
        total = cur.fetchone()[0] or 0.0
        conn.close()

        change = max(paid - total, 0.0)
        vatable = total / 1.12 if total > 0 else 0.0
        vat_amt = total - vatable
        now = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")

        # === Header (Centered) ===
        lines = [
            "<C>PALUTO SEAFOOD GRILL",
            "<C>& RESTAURANT",
            "<C>- Passi Branch -",
            "<C>PIGGLY FOODS CORP.",
            "<C>TIN #: 010-748-236-00004",
            "<C>Sablogon, Passi City,",
            "<C>Iloilo",
            "",
            "<C>TEMPORARY INVOICE",
            "-" * 38,
            f"{'QTY':<5}{'DESC':<23}{'AMT':>10}",
            "-" * 38
        ]

        # === Items ===
        for r in items:
            name = " ".join(filter(None, [r["variety_1"], r["variety_2"], r["luto"]]))
            qty = f"{int(r['quantity'])}" if (r["uom"] or "").upper() == "SERVE" else f"{r['weight_in_kg']*1000:.0f}g"
            subtotal = r["subtotal"]

            wrapped = textwrap.wrap(name, 23)
            lines.append(f"{qty:<5}{wrapped[0]:<23}{format(subtotal, '.2f'):>10}")
            for w in wrapped[1:]:
                lines.append(f"{'':<5}{w:<23}{'':>10}")

        # === Footer ===
        lines += [
            "-" * 38,
            f"{'TOTAL:':<27}{format(total, '.2f'):>11}",
            "-" * 38,
            f"{'TOTAL:':<27}{format(total, '.2f'):>11}",
            f"{'AMT. TENDERED:':<27}{format(paid, '.2f'):>11}",
            f"{'CHANGE:':<27}{format(change, '.2f'):>11}",
            "-" * 38,
            f"{'CUSTOMER:':<27}",
            f"{'ADDRESS:':<27}",
            f"{'TIN:':<27}",
            f"{'B. STYLE:':<27}",
            "-" * 38,
            f"{'VATABLE SALES:':<27}{format(vatable, '.2f'):>11}",
            f"{'VAT AMOUNT:':<27}{format(vat_amt, '.2f'):>11}",
            f"{'VAT EXEMPT SALES:':<27}{'0.00':>11}",
            "-" * 38,
            f"{'NO. OF ITEM(S):':<27}{len(items):>11}",
            f"TABLE #: {session.get('table_id', '')}",
            f"CASHIER: {session.get('name', '')}",
            "-" * 38,
            "",
            "<C>THIS SERVES AS TEMPORARY",
            "<C>INVOICE",
            f"<C>{now}",
            ""
        ]

        # === Generate PDF ===
        pdf_filename = os.path.join(ROOT_DIR, f"receipt_{txn_id}.pdf")
        generate_receipt_pdf(lines, pdf_filename, char_width=38, font_size=7.0)

        # === Print / Save ===
        current_os = platform.system().lower()
        if "windows" in current_os:
            import win32print, win32api
            printer_name = win32print.GetDefaultPrinter() or ""
            if "microsoft print to pdf" in printer_name.lower():
                print(f"⚠️ No physical printer detected. PDF saved: {pdf_filename}")
                return f"⚠️ No printer detected. PDF saved as {pdf_filename}"
            else:
                try:
                    win32api.ShellExecute(0, "print", pdf_filename, f'"{printer_name}"', ".", 0)
                    return f"✅ Receipt printed on: {printer_name}"
                except Exception as e:
                    return f"❌ Print failed: {e}"
        else:
            return f"⚠️ PDF saved: {pdf_filename} (printing not implemented on this OS)."

    except Exception as ex:
        print("PRINT ERROR:", ex)
        return f"❌ Error printing: {ex}"



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
    if "role" not in session or session["role"] != "admin":
        return redirect(url_for("login"))
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
