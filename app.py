from flask import Flask, render_template, request, jsonify
import json, re, difflib
import pymysql
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# config.py must define:
# DB = {"host": "...", "user": "...", "password": "...", "name": "..."}
# EMAIL_USER = "your@gmail.com"
# EMAIL_APP_PASSWORD = "your-app-password"
from config import DB, EMAIL_USER, EMAIL_APP_PASSWORD

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---- Menu (12 items: biryanis + drinks + juices) ----
MENU_ITEMS = [
    {"name": "Veg Biryani", "price": 150},
    {"name": "Chicken Biryani", "price": 200},
    {"name": "Fish Biryani", "price": 250},
    {"name": "Paneer Biryani", "price": 180},
    {"name": "Mutton Biryani", "price": 300},
    {"name": "Egg Biryani", "price": 170},
    {"name": "Special Mixed Biryani", "price": 360},
    {"name": "Prawn Biryani", "price": 320},
    {"name": "Coke", "price": 45},
    {"name": "Sprite", "price": 45},
    {"name": "Mango Juice", "price": 70},
    {"name": "Orange Juice", "price": 70}
]

# ---- Helpers ----
NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
}

def db_conn():
    return pymysql.connect(
        host=DB['host'],
        user=DB['user'],
        password=DB['password'],
        db=DB['name'],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def send_confirmation(email, items, total):
    """Send a simple HTML email with the order details."""
    if not email:
        return False, "No email provided"

    item_lines = "".join([
        f"<li>{i['name']} × {i['qty']} — ₹{i['price']*i['qty']}</li>"
        for i in items
    ])
    html = f"""
    <h2>Thanks for your order! 🍽️</h2>
    <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <ul>{item_lines}</ul>
    <p><strong>Total: ₹{total}</strong></p>
    """

    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Your Order Confirmation"
    msg['From'] = EMAIL_USER
    msg['To'] = email
    msg.attach(MIMEText(html, 'html'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_USER, email, msg.as_string())
        server.quit()
        return True, ""
    except Exception as e:
        return False, str(e)

def normalize_text(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def parse_order(transcript: str):
    """
    Parse quantities + items from transcript.
    Handles: 'two chicken biryani', '1 mango juice', plurals like 'juices/biryanis',
    and a couple of fuzzy fallbacks.
    """
    txt = normalize_text(transcript)
    detected = []
    total = 0

    for m in MENU_ITEMS:
        item_name = m['name'].lower()
        words = [w for w in re.split(r"\s+", item_name) if w]

        qty_words = r"(\d+|" + "|".join(NUM_WORDS.keys()) + r")"
        exact = re.escape(item_name)
        patterns = [
            rf"\b{qty_words}\s+{exact}s?\b",
            rf"\b{exact}s?\s+{qty_words}\b",
            rf"\b{exact}s?\b",
            rf"\b{qty_words}\s+{words[0]}\b.*\b{words[-1]}s?\b",
        ]

        qty_found = 0
        matched = False
        for pat in patterns:
            mobj = re.search(pat, txt)
            if mobj:
                matched = True
                if mobj.lastindex:
                    q = mobj.group(1)
                    if q:
                        qty_found = int(q) if q.isdigit() else NUM_WORDS.get(q, 1)
                if qty_found == 0:
                    qty_found = 1
                break

        if not matched and all(w in txt for w in words):
            qty_found = 1
            matched = True

        if not matched:
            ratio = difflib.SequenceMatcher(None, txt, item_name).ratio()
            if ratio >= 0.6:
                qty_found = 1

        if qty_found > 0:
            detected.append({
                "name": m['name'],
                "price": m['price'],
                "qty": qty_found
            })
            total += m['price'] * qty_found

    # Combine duplicates
    combined = {}
    for d in detected:
        key = d['name']
        if key not in combined:
            combined[key] = d.copy()
        else:
            combined[key]['qty'] += d['qty']
    detected_final = list(combined.values())

    return detected_final, total

def save_order(items, total, email, transcript):
    # Use TEXT for compatibility instead of MySQL JSON type
    conn = db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    items_json TEXT,
                    total_cost DECIMAL(10,2),
                    email VARCHAR(120),
                    transcript TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute(
                "INSERT INTO orders (items_json, total_cost, email, transcript) VALUES (%s,%s,%s,%s)",
                (json.dumps(items, ensure_ascii=False), total, email, transcript)
            )
        conn.commit()
    finally:
        conn.close()

# ---- Routes ----
@app.route("/")
def index():
    # Pass menu to template so your Jinja loop and <script> JSON both work
    return render_template("index.html", menu=MENU_ITEMS)

@app.route("/api/menu")
def api_menu():
    return jsonify(MENU_ITEMS)

@app.route("/api/order", methods=["POST"])
def api_order():
    data = request.get_json(force=True) or {}
    transcript = (data.get("transcript") or "").strip()
    email = (data.get("email") or "").strip()

    items, total = parse_order(transcript)
    if not items:
        return jsonify({
            "saved": False,
            "items": [],
            "total": 0,
            "email_sent": False,
            "error": "No menu items detected."
        })

    saved = False
    save_err = ""
    try:
        save_order(items, total, email, transcript)
        saved = True
    except Exception as e:
        saved = False
        save_err = str(e)

    email_sent = False
    email_err = ""
    if email:
        try:
            email_sent, email_err = send_confirmation(email, items, total)
        except Exception as e:
            email_sent = False
            email_err = str(e)

    # Prefer DB error if saving failed; otherwise email error (if any)
    err_msg = save_err or email_err

    return jsonify({
        "saved": saved,
        "items": items,
        "total": total,
        "email_sent": email_sent,
        "error": err_msg
    })

if __name__ == "__main__":
    # Ensure your templates/index.html and static/ files are in place
    app.run(host="0.0.0.0", port=5000, debug=True)
