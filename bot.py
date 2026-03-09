import os
import re
import time
import logging
from datetime import datetime

from dotenv import load_dotenv
import telebot
from telebot import types
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID is missing")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
user_data = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_PAYMENT_INFO = """💳 <b>Payment Information</b>

💵 <b>HHW</b>
Wave - 09123456789
KPay - 09123456789

💴 <b>NNo</b>
Wave - 09123456789
KPay - 09123456789

⚠️ ငွေလွှဲပြီး 5 မိနစ်အတွင်း screenshot ပို့ပေးပါ။
⚠️ Screenshot မပို့ရင် order မသိမ်းပါ။"""

DEFAULT_PUBLIC_ADMIN = "@si198"

DEFAULT_CATEGORIES = [
    "MLBB DIAMOND",
    "PASS / BUNDLE",
    "BONUS PACKAGE",
]

DEFAULT_PACKAGES = [
    ("MLBB DIAMOND", "86 Diamond", "4800 ks", "Fast delivery", 1, True),
    ("MLBB DIAMOND", "172 Diamond", "9550 ks", "Fast delivery", 2, True),
    ("MLBB DIAMOND", "257 Diamond", "13900 ks", "Fast delivery", 3, True),
    ("MLBB DIAMOND", "343 Diamond", "18900 ks", "Fast delivery", 4, True),
    ("MLBB DIAMOND", "429 Diamond", "23700 ks", "Fast delivery", 5, True),
    ("PASS / BUNDLE", "Weekely Pass", "5800 ks", "1 weekly pass", 1, True),
    ("PASS / BUNDLE", "Twilight Pass", "31600 ks", "Twilight pass", 2, True),
    ("BONUS PACKAGE", "11 Diamond", "750 ks", "Bonus package", 1, True),
    ("BONUS PACKAGE", "22 Diamond", "1500 ks", "Bonus package", 2, True),
    ("BONUS PACKAGE", "56 Diamond", "3750 ks", "Bonus package", 3, True),
]


# ==================================
# DB
# ==================================
def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins(
        id SERIAL PRIMARY KEY,
        tg_id BIGINT UNIQUE,
        username TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS categories(
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS packages(
        id SERIAL PRIMARY KEY,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        category_name TEXT NOT NULL,
        name TEXT UNIQUE NOT NULL,
        price TEXT NOT NULL,
        description TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 9999,
        is_active BOOLEAN DEFAULT TRUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id SERIAL PRIMARY KEY,
        user_name TEXT,
        user_id BIGINT NOT NULL,
        category_id INTEGER,
        category_name TEXT NOT NULL,
        package_id INTEGER,
        package_name TEXT NOT NULL,
        package_price TEXT NOT NULL,
        package_description TEXT DEFAULT '',
        game_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        screenshot_file_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        admin_note TEXT DEFAULT '',
        admin_action_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    INSERT INTO settings(key, value)
    VALUES (%s, %s)
    ON CONFLICT (key) DO NOTHING
    """, ("payment_info", DEFAULT_PAYMENT_INFO))

    cur.execute("""
    INSERT INTO settings(key, value)
    VALUES (%s, %s)
    ON CONFLICT (key) DO NOTHING
    """, ("public_admin_username", DEFAULT_PUBLIC_ADMIN))

    for category_name in DEFAULT_CATEGORIES:
        cur.execute("""
        INSERT INTO categories(name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        """, (category_name,))

    conn.commit()

    for category_name, package_name, price, desc, sort_order, active in DEFAULT_PACKAGES:
        cur.execute("SELECT id FROM categories WHERE name = %s", (category_name,))
        cat = cur.fetchone()
        if cat:
            cur.execute("""
            INSERT INTO packages(category_id, category_name, name, price, description, sort_order, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO NOTHING
            """, (cat["id"], category_name, package_name, price, desc, sort_order, active))

    conn.commit()
    cur.close()
    conn.close()


# ==================================
# HELPERS
# ==================================
def normalize_username(username: str) -> str:
    username = (username or "").strip()
    if username.startswith("@"):
        username = username[1:]
    return username.lower()


def safe_text(value):
    return (value or "").strip()


def is_valid_number(text):
    text = safe_text(text)
    return text.isdigit() and 3 <= len(text) <= 25


def is_valid_name(text, min_len=2):
    return len(safe_text(text)) >= min_len


def reset_user(chat_id):
    user_data.pop(chat_id, None)


def format_order_no(order_id: int) -> str:
    return f"ORD-{1000 + int(order_id)}"


def actor_name(obj):
    username = obj.from_user.username
    return f"@{username}" if username else str(obj.from_user.id)


def is_owner(obj):
    return obj.from_user.id == ADMIN_ID


def is_admin_user(obj):
    if obj.from_user.id == ADMIN_ID:
        return True

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM admins WHERE tg_id = %s", (obj.from_user.id,))
    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return True

    if obj.from_user.username:
        cur.execute("SELECT id FROM admins WHERE username = %s", (normalize_username(obj.from_user.username),))
        row = cur.fetchone()

    cur.close()
    conn.close()
    return row is not None if 'row' in locals() else False


def get_setting(key, fallback=""):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["value"] if row else fallback


def set_setting(key, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO settings(key, value)
    VALUES (%s, %s)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (key, value))
    conn.commit()
    cur.close()
    conn.close()


# ==================================
# MENUS
# ==================================
def step_back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🔙 Back", "❌ Cancel")
    return markup


def client_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🛒 Order", "📄 My Orders")
    markup.add("📞 Contact Admin")
    markup.add("❌ Cancel")
    return markup


def owner_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📊 Dashboard", "📦 All Orders")
    markup.add("⏳ Pending Orders", "✅ Done Orders")
    markup.add("❌ Cancelled Orders", "🔍 Search Order")
    markup.add("🗂 Manage Categories", "💎 Manage Packages")
    markup.add("👥 Manage Admins", "📢 Broadcast")
    markup.add("📱 Change Payment Info", "👤 Change Admin Username")
    markup.add("👀 Client Panel", "🏠 Admin Panel")
    markup.add("❌ Cancel")
    return markup


def admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📊 Dashboard", "📦 All Orders")
    markup.add("⏳ Pending Orders", "✅ Done Orders")
    markup.add("❌ Cancelled Orders", "🔍 Search Order")
    markup.add("📢 Broadcast", "👀 Client Panel")
    markup.add("🏠 Admin Panel", "❌ Cancel")
    return markup


def admin_home_markup(obj):
    return owner_menu() if is_owner(obj) else admin_menu()


def manage_category_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 List Categories", "➕ Add Category")
    markup.add("✏️ Rename Category", "🗑 Delete Category")
    markup.add("🔙 Back", "❌ Cancel")
    return markup


def manage_package_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 List Packages", "➕ Add Package")
    markup.add("✏️ Edit Package", "🗑 Delete Package")
    markup.add("🔁 Toggle Active", "🔙 Back")
    markup.add("❌ Cancel")
    return markup


def manage_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 List Admins", "➕ Add Admin")
    markup.add("🗑 Remove Admin", "🔙 Back")
    markup.add("❌ Cancel")
    return markup


def confirm_order_inline_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_order_submit")
    )
    return markup


def admin_order_buttons(order_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Done", callback_data=f"done_{order_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{order_id}")
    )
    markup.add(types.InlineKeyboardButton("🖼 View Screenshot", callback_data=f"viewss_{order_id}"))
    return markup


# ==================================
# CATEGORY / PACKAGE QUERIES
# ==================================
def get_non_empty_active_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT DISTINCT c.id, c.name
    FROM categories c
    JOIN packages p ON p.category_id = c.id
    WHERE p.is_active = TRUE
    ORDER BY c.id ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_category_names():
    return [row["name"] for row in get_non_empty_active_categories()]


def category_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for row in get_non_empty_active_categories():
        markup.add(row["name"])
    markup.add("🔙 Back", "❌ Cancel")
    return markup


def get_all_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM categories ORDER BY id ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_category_by_id(category_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM categories WHERE id = %s", (category_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_category_by_name(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM categories WHERE name = %s", (safe_text(name),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def add_category(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO categories(name) VALUES (%s)", (safe_text(name),))
    conn.commit()
    cur.close()
    conn.close()


def rename_category(old_name, new_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE categories SET name = %s WHERE name = %s", (safe_text(new_name), safe_text(old_name)))
    changed = cur.rowcount
    if changed:
        cur.execute("UPDATE packages SET category_name = %s WHERE category_name = %s", (safe_text(new_name), safe_text(old_name)))
        cur.execute("UPDATE orders SET category_name = %s WHERE category_name = %s", (safe_text(new_name), safe_text(old_name)))
    conn.commit()
    cur.close()
    conn.close()
    return changed


def delete_category(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM packages WHERE category_name = %s", (safe_text(name),))
    total = cur.fetchone()["total"]
    if total > 0:
        cur.close()
        conn.close()
        return -1
    cur.execute("DELETE FROM categories WHERE name = %s", (safe_text(name),))
    changed = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return changed


def count_packages_by_category(category_name, only_active=True):
    conn = get_connection()
    cur = conn.cursor()
    if only_active:
        cur.execute("SELECT COUNT(*) AS total FROM packages WHERE category_name = %s AND is_active = TRUE", (category_name,))
    else:
        cur.execute("SELECT COUNT(*) AS total FROM packages WHERE category_name = %s", (category_name,))
    total = cur.fetchone()["total"]
    cur.close()
    conn.close()
    return total


def get_all_packages():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, category_id, category_name, name, price, description, sort_order, is_active
    FROM packages
    ORDER BY category_id ASC, sort_order ASC, id ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_packages_by_category_name(category_name, only_active=False):
    conn = get_connection()
    cur = conn.cursor()
    if only_active:
        cur.execute("""
        SELECT id, category_id, category_name, name, price, description, sort_order, is_active
        FROM packages
        WHERE category_name = %s AND is_active = TRUE
        ORDER BY sort_order ASC, id ASC
        """, (category_name,))
    else:
        cur.execute("""
        SELECT id, category_id, category_name, name, price, description, sort_order, is_active
        FROM packages
        WHERE category_name = %s
        ORDER BY sort_order ASC, id ASC
        """, (category_name,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_package_by_id(package_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, category_id, category_name, name, price, description, sort_order, is_active
    FROM packages
    WHERE id = %s
    """, (package_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_package_by_name(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, category_id, category_name, name, price, description, sort_order, is_active
    FROM packages
    WHERE LOWER(name) = LOWER(%s)
    """, (safe_text(name),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def next_sort_order(category_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order), 0) AS mx FROM packages WHERE category_name = %s", (category_name,))
    mx = cur.fetchone()["mx"]
    cur.close()
    conn.close()
    return mx + 1


def add_package(category_name, name, price, description):
    category = get_category_by_name(category_name)
    if not category:
        raise ValueError("Category not found")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO packages(category_id, category_name, name, price, description, sort_order, is_active)
    VALUES (%s, %s, %s, %s, %s, %s, TRUE)
    """, (category["id"], category["name"], safe_text(name), safe_text(price), safe_text(description), next_sort_order(category_name)))
    conn.commit()
    cur.close()
    conn.close()


def update_package_by_id(package_id, new_name, new_price, new_description):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE packages
    SET name = %s, price = %s, description = %s
    WHERE id = %s
    """, (safe_text(new_name), safe_text(new_price), safe_text(new_description), package_id))
    changed = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return changed


def delete_package_by_id(package_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM packages WHERE id = %s", (package_id,))
    changed = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return changed


def toggle_package_active(package_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_active FROM packages WHERE id = %s", (package_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None
    new_value = not row["is_active"]
    cur.execute("UPDATE packages SET is_active = %s WHERE id = %s", (new_value, package_id))
    conn.commit()
    cur.execute("SELECT * FROM packages WHERE id = %s", (package_id,))
    updated = cur.fetchone()
    cur.close()
    conn.close()
    return updated


def package_inline_markup(category_name):
    markup = types.InlineKeyboardMarkup(row_width=1)
    rows = get_packages_by_category_name(category_name, only_active=True)
    for row in rows:
        markup.add(
            types.InlineKeyboardButton(
                f"💎 {row['name']}  •  {row['price']}",
                callback_data=f"buy_{row['id']}"
            )
        )
    return markup


# ==================================
# ORDER QUERIES
# ==================================
def create_order(user_name, user_id, category_id, category_name, package_id, package_name, package_price, package_description, game_id, server_id, screenshot_file_id):
    conn = get_connection()
    cur = conn.cursor()
    current = now_text()
    cur.execute("""
    INSERT INTO orders(
        user_name, user_id, category_id, category_name, package_id, package_name, package_price,
        package_description, game_id, server_id, screenshot_file_id, status, admin_note,
        admin_action_by, created_at, updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING *
    """, (
        user_name, user_id, category_id, category_name, package_id, package_name, package_price,
        package_description, game_id, server_id, screenshot_file_id, "Pending", "", "",
        current, current
    ))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row


def get_user_orders(user_id, limit=5):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_orders(limit=10):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_orders_by_status(status, limit=10):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE status = %s ORDER BY id DESC LIMIT %s", (status, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_order_by_id(order_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def update_order_status(order_id, new_status, admin_note="", admin_action_by=""):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE orders
    SET status = %s, admin_note = %s, admin_action_by = %s, updated_at = %s
    WHERE id = %s
    RETURNING *
    """, (new_status, safe_text(admin_note), safe_text(admin_action_by), now_text(), order_id))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row


def count_today_orders():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM orders WHERE created_at LIKE %s", (f"{today}%",))
    total = cur.fetchone()["total"]
    cur.close()
    conn.close()
    return total


def get_dashboard_text():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM orders")
    total = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS total FROM orders WHERE status = %s", ("Pending",))
    pending = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS total FROM orders WHERE status = %s", ("Completed",))
    completed = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS total FROM orders WHERE status = %s", ("Cancelled",))
    cancelled = cur.fetchone()["total"]

    cur.close()
    conn.close()

    return (
        "📊 <b>Dashboard Summary</b>\n\n"
        f"📦 <b>Total Orders:</b> {total}\n"
        f"📅 <b>Today Orders:</b> {count_today_orders()}\n"
        f"⏳ <b>Pending:</b> {pending}\n"
        f"✅ <b>Done:</b> {completed}\n"
        f"❌ <b>Cancelled:</b> {cancelled}"
    )


# ==================================
# DISPLAY
# ==================================
def format_order(row):
    note = f"\n📝 <b>Admin Note:</b> {row['admin_note']}" if safe_text(row["admin_note"]) else ""
    actor = f"\n👤 <b>Action By:</b> {row['admin_action_by']}" if safe_text(row["admin_action_by"]) else ""
    desc = f"\n📄 <b>Description:</b> {row['package_description']}" if safe_text(row["package_description"]) else ""

    return (
        f"🧾 <b>Order No:</b> {format_order_no(row['id'])}\n"
        f"🔢 <b>DB ID:</b> {row['id']}\n"
        f"👤 <b>Name:</b> {row['user_name']}\n"
        f"🗂 <b>Category:</b> {row['category_name']}\n"
        f"💎 <b>Package:</b> {row['package_name']}\n"
        f"💰 <b>Price:</b> {row['package_price']}"
        f"{desc}\n"
        f"🎮 <b>Game ID:</b> {row['game_id']}\n"
        f"🖥 <b>Server ID:</b> {row['server_id']}\n"
        f"📌 <b>Status:</b> {row['status']}"
        f"{note}"
        f"{actor}\n"
        f"🕒 <b>Created:</b> {row['created_at']}\n"
        f"🛠 <b>Updated:</b> {row['updated_at']}"
    )


def update_caption_status(caption, new_status, note="", actor=""):
    if not caption:
        return caption
    lines = caption.split("\n")
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("📌 <b>Status:</b>"):
            lines[i] = f"📌 <b>Status:</b> {new_status}"
            replaced = True
    if not replaced:
        lines.append(f"📌 <b>Status:</b> {new_status}")

    filtered = []
    for line in lines:
        if not line.startswith("📝 <b>Admin Note:</b>") and not line.startswith("👤 <b>Action By:</b>"):
            filtered.append(line)

    if safe_text(note):
        filtered.append(f"📝 <b>Admin Note:</b> {note}")
    if safe_text(actor):
        filtered.append(f"👤 <b>Action By:</b> {actor}")

    return "\n".join(filtered)


def notify_user(order_id, user_id, status, note=""):
    base = {
        "Completed": f"✅ Your order <b>{format_order_no(order_id)}</b> is done.",
        "Cancelled": f"❌ Your order <b>{format_order_no(order_id)}</b> has been cancelled.",
        "Pending": f"⏳ Your order <b>{format_order_no(order_id)}</b> is pending."
    }.get(status, f"📌 Order {format_order_no(order_id)} status: {status}")

    if safe_text(note):
        base += f"\n📝 Note: {note}"

    try:
        bot.send_message(user_id, base)
    except Exception as e:
        logging.warning("Notify user failed: %s", e)


# ==================================
# START / PANELS
# ==================================
@bot.message_handler(commands=["start"])
def start(message):
    reset_user(message.chat.id)
    if is_owner(message):
        bot.send_message(message.chat.id, "👑 <b>Owner Panel</b>", reply_markup=owner_menu())
    elif is_admin_user(message):
        bot.send_message(message.chat.id, "🛠 <b>Admin Panel</b>", reply_markup=admin_menu())
    else:
        bot.send_message(message.chat.id, "👋 <b>Welcome</b>\n\nChoose game/service to order.", reply_markup=client_menu())


@bot.message_handler(func=lambda m: m.text == "👀 Client Panel")
def client_panel_preview(message):
    if not is_admin_user(message):
        return
    reset_user(message.chat.id)
    bot.send_message(message.chat.id, "👀 <b>Client Panel Preview</b>", reply_markup=client_menu())


@bot.message_handler(func=lambda m: m.text == "🏠 Admin Panel")
def go_admin_panel(message):
    if not is_admin_user(message):
        return
    reset_user(message.chat.id)
    bot.send_message(message.chat.id, "🏠 <b>Admin Panel</b>", reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "❌ Cancel")
def cancel(message):
    reset_user(message.chat.id)
    if is_admin_user(message):
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=admin_home_markup(message))
    else:
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=client_menu())


@bot.message_handler(func=lambda m: m.text == "🔙 Back")
def go_back(message):
    chat_id = message.chat.id
    state = user_data.get(chat_id, {}).get("step")

    if is_admin_user(message):
        prev = user_data.get(chat_id, {}).get("prev")
        if prev == "categories":
            reset_user(chat_id)
            bot.send_message(chat_id, "🔙 Back to Category Manager", reply_markup=manage_category_menu())
            return
        if prev == "packages":
            reset_user(chat_id)
            bot.send_message(chat_id, "🔙 Back to Package Manager", reply_markup=manage_package_menu())
            return
        if prev == "admins":
            reset_user(chat_id)
            bot.send_message(chat_id, "🔙 Back to Admin Manager", reply_markup=manage_admin_menu())
            return
        if prev == "admin_panel":
            reset_user(chat_id)
            bot.send_message(chat_id, "🔙 Back to Admin Panel", reply_markup=admin_home_markup(message))
            return

    if state == "choose_category":
        reset_user(chat_id)
        bot.send_message(chat_id, "🔙 Back to main menu", reply_markup=client_menu())
    elif state == "game_id":
        user_data[chat_id] = {"step": "choose_category"}
        bot.send_message(chat_id, "🔙 Back to category list", reply_markup=category_menu())
    elif state == "server_id":
        user_data[chat_id]["step"] = "game_id"
        bot.send_message(chat_id, "🔙 Send your <b>Game ID</b> again", reply_markup=step_back_menu())
    elif state == "screenshot":
        user_data[chat_id]["step"] = "server_id"
        bot.send_message(chat_id, "🔙 Send your <b>Server ID</b> again", reply_markup=step_back_menu())
    elif state == "confirm_order":
        user_data[chat_id]["step"] = "screenshot"
        bot.send_message(chat_id, "🔙 Send payment screenshot again", reply_markup=step_back_menu())
    else:
        reset_user(chat_id)
        if is_admin_user(message):
            bot.send_message(chat_id, "🔙 Back to Admin Panel", reply_markup=admin_home_markup(message))
        else:
            bot.send_message(chat_id, "🔙 Back to main menu", reply_markup=client_menu())


# ==================================
# CLIENT FLOW
# ==================================
@bot.message_handler(func=lambda m: m.text == "📞 Contact Admin")
def contact_admin(message):
    public_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)
    bot.send_message(message.chat.id, f"📞 <b>Admin Contact</b>\n\nTelegram Username: {public_username}")


@bot.message_handler(func=lambda m: m.text == "🛒 Order")
def order_start(message):
    if message.chat.id in user_data:
        bot.send_message(message.chat.id, "⚠️ You already have an active order step. Finish it or cancel first.", reply_markup=step_back_menu())
        return
    categories = get_non_empty_active_categories()
    if not categories:
        bot.send_message(message.chat.id, "⚠️ No active categories available now.", reply_markup=client_menu())
        return
    user_data[message.chat.id] = {"step": "choose_category"}
    bot.send_message(message.chat.id, "🛒 <b>Choose game/service</b>\n\nအောက်က category တစ်ခုရွေးပါ။", reply_markup=category_menu())


@bot.message_handler(func=lambda m: m.text in get_category_names())
def category_selected(message):
    category_name = message.text
    count = count_packages_by_category(category_name, only_active=True)
    user_data[message.chat.id] = {"step": "choose_category", "selected_category": category_name}
    rows = get_packages_by_category_name(category_name, only_active=True)
    if not rows:
        bot.send_message(message.chat.id, f"🗂 <b>{category_name}</b>\n\nဒီ category အောက်မှာ active package မရှိသေးပါ။", reply_markup=step_back_menu())
        return
    bot.send_message(
        message.chat.id,
        f"🗂 <b>{category_name}</b>\n📦 <b>Total Packages:</b> {count}\n\nလိုချင်တဲ့ package ကို အောက်က button ကနေရွေးပါ 👇",
        reply_markup=package_inline_markup(category_name)
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def buy_package(call):
    try:
        package_id = int(call.data.split("_")[1])
    except Exception:
        bot.answer_callback_query(call.id, "Invalid package.")
        return

    package = get_package_by_id(package_id)
    if not package or not package["is_active"]:
        bot.answer_callback_query(call.id, "Package not available.")
        return

    user_data[call.message.chat.id] = {
        "step": "game_id",
        "category_id": package["category_id"],
        "category_name": package["category_name"],
        "package_id": package["id"],
        "package_name": package["name"],
        "package_price": package["price"],
        "package_description": package["description"]
    }

    bot.answer_callback_query(call.id, f"Selected {package['name']}")
    bot.send_message(
        call.message.chat.id,
        f"✅ <b>Selected Package</b>\n\n"
        f"🗂 <b>Category:</b> {package['category_name']}\n"
        f"💎 <b>Package:</b> {package['name']}\n"
        f"💰 <b>Price:</b> {package['price']}\n"
        f"📄 <b>Description:</b> {package['description']}\n\n"
        f"🎮 Now send your <b>Game ID</b>",
        reply_markup=step_back_menu()
    )


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "game_id", content_types=["text"])
def get_game_id(message):
    game_id = safe_text(message.text)
    if not is_valid_number(game_id):
        bot.send_message(message.chat.id, "⚠️ Game ID must be number only.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["game_id"] = game_id
    user_data[message.chat.id]["step"] = "server_id"
    bot.send_message(message.chat.id, "🖥 <b>Send your Server ID</b>", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "server_id", content_types=["text"])
def get_server_id(message):
    server_id = safe_text(message.text)
    if not is_valid_number(server_id):
        bot.send_message(message.chat.id, "⚠️ Server ID must be number only.", reply_markup=step_back_menu())
        return

    user_data[message.chat.id]["server_id"] = server_id
    user_data[message.chat.id]["step"] = "screenshot"

    payment_info = get_setting("payment_info", DEFAULT_PAYMENT_INFO)
    public_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)

    bot.send_message(
        message.chat.id,
        f"📦 <b>Order Summary</b>\n\n"
        f"🗂 <b>Category:</b> {user_data[message.chat.id]['category_name']}\n"
        f"💎 <b>Package:</b> {user_data[message.chat.id]['package_name']}\n"
        f"💰 <b>Price:</b> {user_data[message.chat.id]['package_price']}\n"
        f"📄 <b>Description:</b> {user_data[message.chat.id]['package_description']}\n"
        f"🎮 <b>Game ID:</b> {user_data[message.chat.id]['game_id']}\n"
        f"🖥 <b>Server ID:</b> {user_data[message.chat.id]['server_id']}\n\n"
        f"{payment_info}\n\n"
        
        f"📸 <b>Payment screenshot ကို photo နဲ့ပို့ပေးပါ။</b>",
        reply_markup=step_back_menu()
    )


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "screenshot", content_types=["photo", "text", "document", "video", "audio", "sticker"])
def receive_screenshot(message):
    if message.content_type != "photo":
        bot.send_message(message.chat.id, "⚠️ Payment screenshot ကို <b>photo</b> နဲ့ပဲ ပို့ရမယ်။", reply_markup=step_back_menu())
        return

    data = user_data.get(message.chat.id)
    if not data:
        bot.send_message(message.chat.id, "⚠️ Session expired. Please /start again.")
        return

    data["screenshot_file_id"] = message.photo[-1].file_id
    data["step"] = "confirm_order"

    bot.send_message(
        message.chat.id,
        f"📝 <b>Confirm Order</b>\n\n"
        f"🗂 <b>Category:</b> {data['category_name']}\n"
        f"💎 <b>Package:</b> {data['package_name']}\n"
        f"💰 <b>Price:</b> {data['package_price']}\n"
        f"📄 <b>Description:</b> {data['package_description']}\n"
        f"🎮 <b>Game ID:</b> {data['game_id']}\n"
        f"🖥 <b>Server ID:</b> {data['server_id']}\n\n"
        f"မှန်ရင် confirm လုပ်ပါ။",
        reply_markup=confirm_order_inline_markup()
    )


@bot.callback_query_handler(func=lambda c: c.data == "confirm_order")
def confirm_order_submit(call):
    data = user_data.get(call.message.chat.id)
    if not data or data.get("step") != "confirm_order":
        bot.answer_callback_query(call.id, "Order session expired.")
        return

    order = create_order(
        user_name=call.from_user.first_name or "Unknown",
        user_id=call.message.chat.id,
        category_id=data["category_id"],
        category_name=data["category_name"],
        package_id=data["package_id"],
        package_name=data["package_name"],
        package_price=data["package_price"],
        package_description=data["package_description"],
        game_id=data["game_id"],
        server_id=data["server_id"],
        screenshot_file_id=data["screenshot_file_id"]
    )

    public_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)

    bot.answer_callback_query(call.id, "Order confirmed.")
    bot.send_message(
        call.message.chat.id,
        f"✅ <b>Order Submitted Successfully</b>\n\n"
        f"🧾 <b>Order No:</b> {format_order_no(order['id'])}\n"
        f"🔢 <b>DB ID:</b> {order['id']}\n"
        f"🗂 <b>Category:</b> {order['category_name']}\n"
        f"💎 <b>Package:</b> {order['package_name']}\n"
        f"💰 <b>Price:</b> {order['package_price']}\n"
        f"📄 <b>Description:</b> {order['package_description']}\n"
        f"🎮 <b>Game ID:</b> {order['game_id']}\n"
        f"🖥 <b>Server ID:</b> {order['server_id']}\n"
        f"📌 <b>Status:</b> {order['status']}\n\n"
        f"📞 <b>Admin Contact:</b> {public_username}",
        reply_markup=client_menu()
    )

    admin_caption = (
        f"📥 <b>New Order Received</b>\n\n"
        f"🧾 <b>Order No:</b> {format_order_no(order['id'])}\n"
        f"🔢 <b>DB ID:</b> {order['id']}\n"
        f"👤 <b>Name:</b> {order['user_name']}\n"
        f"🆔 <b>User ID:</b> {order['user_id']}\n"
        f"🗂 <b>Category:</b> {order['category_name']}\n"
        f"💎 <b>Package:</b> {order['package_name']}\n"
        f"💰 <b>Price:</b> {order['package_price']}\n"
        f"📄 <b>Description:</b> {order['package_description']}\n"
        f"🎮 <b>Game ID:</b> {order['game_id']}\n"
        f"🖥 <b>Server ID:</b> {order['server_id']}\n"
        f"📌 <b>Status:</b> {order['status']}\n"
        f"🕒 <b>Date:</b> {order['created_at']}"
    )

    bot.send_photo(
        ADMIN_ID,
        data["screenshot_file_id"],
        caption=admin_caption,
        reply_markup=admin_order_buttons(order["id"])
    )

    reset_user(call.message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data == "cancel_order_submit")
def cancel_order_submit(call):
    reset_user(call.message.chat.id)
    bot.answer_callback_query(call.id, "Order cancelled.")
    bot.send_message(call.message.chat.id, "❌ Order cancelled.", reply_markup=client_menu())


@bot.message_handler(func=lambda m: m.text == "📄 My Orders")
def my_orders(message):
    rows = get_user_orders(message.chat.id, 5)
    if not rows:
        bot.send_message(message.chat.id, "📭 No orders yet.")
        return

    text = "📄 <b>Your Recent Orders</b>\n\n"
    for row in rows:
        emoji = "⏳"
        if row["status"] == "Completed":
            emoji = "✅"
        elif row["status"] == "Cancelled":
            emoji = "❌"

        text += (
            f"🧾 <b>{format_order_no(row['id'])}</b>\n"
            f"💎 <b>{row['package_name']}</b>\n"
            f"💰 <b>{row['package_price']}</b>\n"
            f"{emoji} <b>{row['status']}</b>\n"
            f"🕒 {row['created_at']}\n\n"
        )
    bot.send_message(message.chat.id, text)


# ==================================
# ADMIN ORDERS
# ==================================
@bot.message_handler(func=lambda m: m.text == "📊 Dashboard")
def dashboard(message):
    if not is_admin_user(message):
        return
    bot.send_message(message.chat.id, get_dashboard_text(), reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "📦 All Orders")
def all_orders(message):
    if not is_admin_user(message):
        return
    rows = get_orders(10)
    if not rows:
        bot.send_message(message.chat.id, "📭 No orders found.")
        return
    text = "📦 <b>Last 10 Orders</b>\n\n"
    for row in rows:
        text += format_order(row) + "\n\n"
    bot.send_message(message.chat.id, text, reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "⏳ Pending Orders")
def pending_orders(message):
    if not is_admin_user(message):
        return
    rows = get_orders_by_status("Pending", 10)
    if not rows:
        bot.send_message(message.chat.id, "📭 No pending orders.")
        return
    text = "⏳ <b>Pending Orders</b>\n\n"
    for row in rows:
        text += format_order(row) + "\n\n"
    bot.send_message(message.chat.id, text, reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "✅ Done Orders")
def done_orders(message):
    if not is_admin_user(message):
        return
    rows = get_orders_by_status("Completed", 10)
    if not rows:
        bot.send_message(message.chat.id, "📭 No done orders.")
        return
    text = "✅ <b>Done Orders</b>\n\n"
    for row in rows:
        text += format_order(row) + "\n\n"
    bot.send_message(message.chat.id, text, reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "❌ Cancelled Orders")
def cancelled_orders(message):
    if not is_admin_user(message):
        return
    rows = get_orders_by_status("Cancelled", 10)
    if not rows:
        bot.send_message(message.chat.id, "📭 No cancelled orders.")
        return
    text = "❌ <b>Cancelled Orders</b>\n\n"
    for row in rows:
        text += format_order(row) + "\n\n"
    bot.send_message(message.chat.id, text, reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "🔍 Search Order")
def search_order_prompt(message):
    if not is_admin_user(message):
        return
    user_data[message.chat.id] = {"step": "search_order", "prev": "admin_panel"}
    bot.send_message(message.chat.id, "🔍 Send <b>Order DB ID</b> to search", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "search_order", content_types=["text"])
def search_order_result(message):
    if not is_admin_user(message):
        return
    try:
        order_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Please send valid order ID.", reply_markup=step_back_menu())
        return
    row = get_order_by_id(order_id)
    if not row:
        bot.send_message(message.chat.id, "❌ Order not found.", reply_markup=step_back_menu())
        return
    bot.send_message(message.chat.id, format_order(row), reply_markup=admin_home_markup(message))
    try:
        bot.send_photo(message.chat.id, row["screenshot_file_id"], caption=f"🖼 Screenshot for {format_order_no(row['id'])}")
    except Exception:
        pass
    reset_user(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith(("done_", "cancel_")))
def ask_admin_note(call):
    if not is_admin_user(call):
        bot.answer_callback_query(call.id, "⛔ Admin only.")
        return

    action, order_id_text = call.data.split("_")
    order_id = int(order_id_text)

    user_data[call.message.chat.id] = {
        "step": "admin_note_for_status",
        "prev": "admin_panel",
        "target_order_id": order_id,
        "target_action": action
    }

    action_text = "Done" if action == "done" else "Cancel"
    bot.answer_callback_query(call.id, f"{action_text} selected")
    bot.send_message(
        call.message.chat.id,
        f"📝 Send admin note for {format_order_no(order_id)}\nဥပမာ: delivered / invalid screenshot",
        reply_markup=step_back_menu()
    )


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "admin_note_for_status", content_types=["text"])
def handle_admin_note_status(message):
    if not is_admin_user(message):
        return

    order_id = user_data[message.chat.id]["target_order_id"]
    action = user_data[message.chat.id]["target_action"]
    note = safe_text(message.text)
    new_status = "Completed" if action == "done" else "Cancelled"

    row = update_order_status(order_id, new_status, admin_note=note, admin_action_by=actor_name(message))
    if not row:
        bot.send_message(message.chat.id, "❌ Order not found.", reply_markup=admin_home_markup(message))
        reset_user(message.chat.id)
        return

    notify_user(order_id, row["user_id"], new_status, note=note)
    bot.send_message(message.chat.id, f"✅ {format_order_no(order_id)} → {new_status}", reply_markup=admin_home_markup(message))
    reset_user(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("viewss_"))
def view_screenshot(call):
    if not is_admin_user(call):
        bot.answer_callback_query(call.id, "⛔ Admin only.")
        return
    order_id = int(call.data.split("_")[1])
    row = get_order_by_id(order_id)
    if not row:
        bot.answer_callback_query(call.id, "Order not found.")
        return
    try:
        bot.send_photo(call.message.chat.id, row["screenshot_file_id"], caption=f"🖼 Screenshot for {format_order_no(order_id)}")
        bot.answer_callback_query(call.id, "Screenshot sent.")
    except Exception:
        bot.answer_callback_query(call.id, "Failed to open screenshot.")


# ==================================
# CATEGORY MANAGER
# ==================================
@bot.message_handler(func=lambda m: m.text == "🗂 Manage Categories")
def manage_categories(message):
    if not is_owner(message):
        return
    bot.send_message(message.chat.id, "🗂 <b>Category Manager</b>", reply_markup=manage_category_menu())


@bot.message_handler(func=lambda m: m.text == "📋 List Categories")
def list_categories(message):
    if not is_owner(message):
        return
    rows = get_all_categories()
    if not rows:
        bot.send_message(message.chat.id, "No categories found.", reply_markup=manage_category_menu())
        return
    text = "📋 <b>Category List</b>\n\n"
    for row in rows:
        text += f"🆔 <b>ID:</b> {row['id']}\n📂 <b>Name:</b> {row['name']}\n\n"
    bot.send_message(message.chat.id, text, reply_markup=manage_category_menu())


@bot.message_handler(func=lambda m: m.text == "➕ Add Category")
def add_category_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "add_category_name", "prev": "categories"}
    bot.send_message(message.chat.id, "➕ Send new category name", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "✏️ Rename Category")
def rename_category_prompt(message):
    if not is_owner(message):
        return
    rows = get_all_categories()
    text = "✏️ <b>Rename Category</b>\n\nSend existing category name:\n\n"
    for row in rows:
        text += f"• {row['name']}\n"
    user_data[message.chat.id] = {"step": "rename_category_old", "prev": "categories"}
    bot.send_message(message.chat.id, text, reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "🗑 Delete Category")
def delete_category_prompt(message):
    if not is_owner(message):
        return
    rows = get_all_categories()
    text = "🗑 <b>Delete Category</b>\n\nSend category name:\n\n"
    for row in rows:
        text += f"• {row['name']}\n"
    user_data[message.chat.id] = {"step": "delete_category_name", "prev": "categories"}
    bot.send_message(message.chat.id, text, reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_category_name", content_types=["text"])
def save_category_name(message):
    if not is_owner(message):
        return
    name = safe_text(message.text)
    if not is_valid_name(name):
        bot.send_message(message.chat.id, "⚠️ Invalid category name.", reply_markup=step_back_menu())
        return
    if get_category_by_name(name):
        bot.send_message(message.chat.id, f"⚠️ Category already exists: <b>{name}</b>", reply_markup=manage_category_menu())
        reset_user(message.chat.id)
        return
    try:
        add_category(name)
        bot.send_message(message.chat.id, f"✅ <b>Category Added</b>\n\n🗂 <b>Name:</b> {name}", reply_markup=manage_category_menu())
    except Exception:
        bot.send_message(message.chat.id, "❌ Failed to add category.", reply_markup=manage_category_menu())
    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "rename_category_old", content_types=["text"])
def save_old_category_name(message):
    if not is_owner(message):
        return
    old_name = safe_text(message.text)
    if not get_category_by_name(old_name):
        bot.send_message(message.chat.id, "❌ Category not found.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id] = {"step": "rename_category_new", "prev": "categories", "old_category_name": old_name}
    bot.send_message(message.chat.id, "✏️ Send new category name", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "rename_category_new", content_types=["text"])
def save_new_category_name(message):
    if not is_owner(message):
        return
    old_name = user_data[message.chat.id]["old_category_name"]
    new_name = safe_text(message.text)
    if not is_valid_name(new_name):
        bot.send_message(message.chat.id, "⚠️ Invalid category name.", reply_markup=step_back_menu())
        return
    if get_category_by_name(new_name):
        bot.send_message(message.chat.id, "❌ New category name already exists.", reply_markup=step_back_menu())
        return
    changed = rename_category(old_name, new_name)
    if changed:
        bot.send_message(message.chat.id, f"✅ <b>Category Renamed</b>\n\nOld: {old_name}\nNew: {new_name}", reply_markup=manage_category_menu())
    else:
        bot.send_message(message.chat.id, "❌ Rename failed.", reply_markup=manage_category_menu())
    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "delete_category_name", content_types=["text"])
def save_delete_category(message):
    if not is_owner(message):
        return
    name = safe_text(message.text)
    result = delete_category(name)
    if result == -1:
        bot.send_message(message.chat.id, "❌ This category still has packages. Delete packages first.", reply_markup=manage_category_menu())
    elif result > 0:
        bot.send_message(message.chat.id, f"✅ <b>Category Deleted</b>\n\n🗂 {name}", reply_markup=manage_category_menu())
    else:
        bot.send_message(message.chat.id, "❌ Category not found.", reply_markup=manage_category_menu())
    reset_user(message.chat.id)


# ==================================
# PACKAGE MANAGER
# ==================================
@bot.message_handler(func=lambda m: m.text == "💎 Manage Packages")
def manage_packages(message):
    if not is_owner(message):
        return
    bot.send_message(message.chat.id, "💎 <b>Package Manager</b>", reply_markup=manage_package_menu())


@bot.message_handler(func=lambda m: m.text == "📋 List Packages")
def list_packages(message):
    if not is_owner(message):
        return
    rows = get_all_packages()
    if not rows:
        bot.send_message(message.chat.id, "No packages found.", reply_markup=manage_package_menu())
        return
    text = "📋 <b>Package List</b>\n\n"
    for row in rows:
        active_text = "Active" if row["is_active"] else "Inactive"
        text += (
            f"🆔 <b>ID:</b> {row['id']}\n"
            f"🗂 <b>Category ID:</b> {row['category_id']}\n"
            f"📂 <b>Category:</b> {row['category_name']}\n"
            f"💎 <b>Name:</b> {row['name']}\n"
            f"💰 <b>Price:</b> {row['price']}\n"
            f"📄 <b>Description:</b> {row['description']}\n"
            f"🔢 <b>Sort:</b> {row['sort_order']}\n"
            f"🔘 <b>Status:</b> {active_text}\n\n"
        )
    bot.send_message(message.chat.id, text, reply_markup=manage_package_menu())


@bot.message_handler(func=lambda m: m.text == "➕ Add Package")
def add_package_prompt(message):
    if not is_owner(message):
        return
    rows = get_all_categories()
    if not rows:
        bot.send_message(message.chat.id, "⚠️ No category found. Add category first.", reply_markup=manage_package_menu())
        return
    text = "➕ <b>Add Package</b>\n\nရွေးချယ်ချင်တဲ့ <b>Category ID</b> ကို ပို့ပါ:\n\n"
    for row in rows:
        text += f"🆔 {row['id']} - {row['name']}\n"
    user_data[message.chat.id] = {"step": "add_package_category_id", "prev": "packages"}
    bot.send_message(message.chat.id, text, reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "✏️ Edit Package")
def edit_package_prompt(message):
    if not is_owner(message):
        return
    rows = get_all_packages()
    if not rows:
        bot.send_message(message.chat.id, "No packages found.", reply_markup=manage_package_menu())
        return
    text = "✏️ <b>Edit Package</b>\n\nSend package <b>ID</b>:\n\n"
    for row in rows:
        text += f"{row['id']} - {row['name']} ({row['price']})\n"
    user_data[message.chat.id] = {"step": "edit_package_id", "prev": "packages"}
    bot.send_message(message.chat.id, text, reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "🗑 Delete Package")
def delete_package_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "delete_package_id", "prev": "packages"}
    bot.send_message(message.chat.id, "🗑 Send package <b>ID</b> to delete", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "🔁 Toggle Active")
def toggle_package_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "toggle_package_id", "prev": "packages"}
    bot.send_message(message.chat.id, "🔁 Send package <b>ID</b> to active/inactive toggle", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_package_category_id", content_types=["text"])
def add_package_category_id_step(message):
    if not is_owner(message):
        return
    try:
        category_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Please send valid Category ID.", reply_markup=step_back_menu())
        return
    category = get_category_by_id(category_id)
    if not category:
        bot.send_message(message.chat.id, "❌ Category ID not found.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["new_category_id"] = category["id"]
    user_data[message.chat.id]["new_category_name"] = category["name"]
    user_data[message.chat.id]["step"] = "add_package_name"
    bot.send_message(
        message.chat.id,
        f"🗂 <b>Selected Category</b>\n\n🆔 <b>ID:</b> {category['id']}\n📂 <b>Name:</b> {category['name']}\n\n💎 Now send <b>package name</b>",
        reply_markup=step_back_menu()
    )


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_package_name", content_types=["text"])
def add_package_name_step(message):
    if not is_owner(message):
        return
    package_name = safe_text(message.text)
    if not is_valid_name(package_name):
        bot.send_message(message.chat.id, "⚠️ Invalid package name.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["new_package_name"] = package_name
    user_data[message.chat.id]["step"] = "add_package_price"
    bot.send_message(message.chat.id, "💰 Now send <b>package price</b>", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_package_price", content_types=["text"])
def add_package_price_step(message):
    if not is_owner(message):
        return
    price = safe_text(message.text)
    if not price:
        bot.send_message(message.chat.id, "⚠️ Price cannot be empty.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["new_package_price"] = price
    user_data[message.chat.id]["step"] = "add_package_description"
    bot.send_message(message.chat.id, "📄 Now send <b>package description</b>\nဥပမာ - fast delivery / bonus info", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_package_description", content_types=["text"])
def add_package_description_step(message):
    if not is_owner(message):
        return
    category_name = user_data[message.chat.id]["new_category_name"]
    package_name = user_data[message.chat.id]["new_package_name"]
    price = user_data[message.chat.id]["new_package_price"]
    description = safe_text(message.text)

    try:
        add_package(category_name, package_name, price, description)
        bot.send_message(
            message.chat.id,
            f"✅ <b>Package Added Successfully</b>\n\n"
            f"📂 <b>Category:</b> {category_name}\n"
            f"💎 <b>Name:</b> {package_name}\n"
            f"💰 <b>Price:</b> {price}\n"
            f"📄 <b>Description:</b> {description}",
            reply_markup=manage_package_menu()
        )
        bot.send_message(
            message.chat.id,
            f"🛒 <b>Client Preview - {category_name}</b>\n📦 <b>Total Packages:</b> {count_packages_by_category(category_name)}",
            reply_markup=package_inline_markup(category_name)
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Failed to add package.\n{e}", reply_markup=manage_package_menu())

    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "edit_package_id", content_types=["text"])
def edit_package_id_step(message):
    if not is_owner(message):
        return
    try:
        package_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Please send valid package ID.", reply_markup=step_back_menu())
        return

    row = get_package_by_id(package_id)
    if not row:
        bot.send_message(message.chat.id, "❌ Package ID not found.", reply_markup=step_back_menu())
        return

    user_data[message.chat.id] = {"step": "edit_package_name", "prev": "packages", "edit_package_id": package_id}
    bot.send_message(
        message.chat.id,
        f"✏️ <b>Editing Package</b>\n\n"
        f"🆔 <b>ID:</b> {row['id']}\n"
        f"🗂 <b>Category ID:</b> {row['category_id']}\n"
        f"📂 <b>Category:</b> {row['category_name']}\n"
        f"💎 <b>Current Name:</b> {row['name']}\n"
        f"💰 <b>Current Price:</b> {row['price']}\n"
        f"📄 <b>Current Description:</b> {row['description']}\n\n"
        f"Now send <b>new package name</b>",
        reply_markup=step_back_menu()
    )


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "edit_package_name", content_types=["text"])
def edit_package_name_step(message):
    if not is_owner(message):
        return
    new_name = safe_text(message.text)
    if not is_valid_name(new_name):
        bot.send_message(message.chat.id, "⚠️ Invalid package name.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["edit_new_name"] = new_name
    user_data[message.chat.id]["step"] = "edit_package_price"
    bot.send_message(message.chat.id, "💰 Now send <b>new price</b>", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "edit_package_price", content_types=["text"])
def edit_package_price_step(message):
    if not is_owner(message):
        return
    new_price = safe_text(message.text)
    if not new_price:
        bot.send_message(message.chat.id, "⚠️ Price cannot be empty.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["edit_new_price"] = new_price
    user_data[message.chat.id]["step"] = "edit_package_description"
    bot.send_message(message.chat.id, "📄 Now send <b>new description</b>", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "edit_package_description", content_types=["text"])
def edit_package_description_step(message):
    if not is_owner(message):
        return
    package_id = user_data[message.chat.id]["edit_package_id"]
    new_name = user_data[message.chat.id]["edit_new_name"]
    new_price = user_data[message.chat.id]["edit_new_price"]
    new_description = safe_text(message.text)

    existing = get_package_by_name(new_name)
    if existing and existing["id"] != package_id:
        bot.send_message(message.chat.id, "❌ New package name already exists.", reply_markup=step_back_menu())
        return

    changed = update_package_by_id(package_id, new_name, new_price, new_description)
    if changed:
        row = get_package_by_id(package_id)
        bot.send_message(
            message.chat.id,
            f"✅ <b>Package Updated Successfully</b>\n\n"
            f"🆔 <b>ID:</b> {row['id']}\n"
            f"🗂 <b>Category ID:</b> {row['category_id']}\n"
            f"📂 <b>Category:</b> {row['category_name']}\n"
            f"💎 <b>New Name:</b> {row['name']}\n"
            f"💰 <b>New Price:</b> {row['price']}\n"
            f"📄 <b>New Description:</b> {row['description']}",
            reply_markup=manage_package_menu()
        )
        bot.send_message(
            message.chat.id,
            f"🛒 <b>Client Preview - {row['category_name']}</b>\n📦 <b>Total Packages:</b> {count_packages_by_category(row['category_name'])}",
            reply_markup=package_inline_markup(row["category_name"])
        )
    else:
        bot.send_message(message.chat.id, "❌ Update failed.", reply_markup=manage_package_menu())
    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "delete_package_id", content_types=["text"])
def delete_package_id_step(message):
    if not is_owner(message):
        return
    try:
        package_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Please send valid package ID.", reply_markup=step_back_menu())
        return
    row = get_package_by_id(package_id)
    if not row:
        bot.send_message(message.chat.id, "❌ Package ID not found.", reply_markup=step_back_menu())
        return
    changed = delete_package_by_id(package_id)
    if changed:
        bot.send_message(
            message.chat.id,
            f"✅ <b>Package Deleted</b>\n\n"
            f"🆔 <b>ID:</b> {row['id']}\n"
            f"🗂 <b>Category ID:</b> {row['category_id']}\n"
            f"📂 <b>Category:</b> {row['category_name']}\n"
            f"💎 <b>Name:</b> {row['name']}\n"
            f"💰 <b>Price:</b> {row['price']}",
            reply_markup=manage_package_menu()
        )
    else:
        bot.send_message(message.chat.id, "❌ Delete failed.", reply_markup=manage_package_menu())
    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "toggle_package_id", content_types=["text"])
def toggle_package_id_step(message):
    if not is_owner(message):
        return
    try:
        package_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Please send valid package ID.", reply_markup=step_back_menu())
        return
    row = toggle_package_active(package_id)
    if not row:
        bot.send_message(message.chat.id, "❌ Package ID not found.", reply_markup=step_back_menu())
        return
    status = "Active" if row["is_active"] else "Inactive"
    bot.send_message(
        message.chat.id,
        f"✅ <b>Package Status Changed</b>\n\n🆔 <b>ID:</b> {row['id']}\n💎 <b>Name:</b> {row['name']}\n🔘 <b>Status:</b> {status}",
        reply_markup=manage_package_menu()
    )
    reset_user(message.chat.id)


# ==================================
# ADMIN MANAGER / BROADCAST / SETTINGS
# ==================================
@bot.message_handler(func=lambda m: m.text == "👥 Manage Admins")
def manage_admins(message):
    if not is_owner(message):
        return
    bot.send_message(message.chat.id, "👥 <b>Admin Manager</b>", reply_markup=manage_admin_menu())


@bot.message_handler(func=lambda m: m.text == "📋 List Admins")
def list_admins(message):
    if not is_owner(message):
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, tg_id, username, created_at FROM admins ORDER BY id ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    text = "👥 <b>Admin List</b>\n\n"
    text += f"👑 <b>Owner ID:</b> <code>{ADMIN_ID}</code>\n\n"
    if not rows:
        text += "No extra admins."
    else:
        for row in rows:
            username_text = f"@{row['username']}" if row["username"] else "-"
            text += (
                f"🆔 <b>ID:</b> {row['id']}\n"
                f"🔢 <b>Telegram ID:</b> {row['tg_id']}\n"
                f"👤 <b>Username:</b> {username_text}\n"
                f"🕒 <b>Added:</b> {row['created_at']}\n\n"
            )
    bot.send_message(message.chat.id, text, reply_markup=manage_admin_menu())


@bot.message_handler(func=lambda m: m.text == "➕ Add Admin")
def add_admin_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "add_admin_tg_id", "prev": "admins"}
    bot.send_message(message.chat.id, "➕ Send admin <b>Telegram ID</b>", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "🗑 Remove Admin")
def remove_admin_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "remove_admin_tg_id", "prev": "admins"}
    bot.send_message(message.chat.id, "🗑 Send admin <b>Telegram ID</b> to remove", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_admin_tg_id", content_types=["text"])
def save_admin_tg_id(message):
    if not is_owner(message):
        return
    try:
        tg_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Telegram ID must be number.", reply_markup=step_back_menu())
        return
    user_data[message.chat.id]["new_admin_tg_id"] = tg_id
    user_data[message.chat.id]["step"] = "add_admin_username"
    bot.send_message(message.chat.id, "👤 Send admin username\nဥပမာ: @newadmin", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_admin_username", content_types=["text"])
def save_added_admin(message):
    if not is_owner(message):
        return
    username = safe_text(message.text)
    if not re.match(r"^@?[A-Za-z0-9_]{5,32}$", username):
        bot.send_message(message.chat.id, "⚠️ Invalid username format.", reply_markup=step_back_menu())
        return
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO admins(tg_id, username, created_at) VALUES (%s, %s, %s)",
            (user_data[message.chat.id]["new_admin_tg_id"], normalize_username(username), now_text())
        )
        conn.commit()
        cur.close()
        conn.close()

        bot.send_message(
            message.chat.id,
            f"✅ Admin added\n\nID: {user_data[message.chat.id]['new_admin_tg_id']}\nUsername: @{normalize_username(username)}",
            reply_markup=manage_admin_menu()
        )
    except Exception:
        bot.send_message(message.chat.id, "❌ Admin ID or username already exists.", reply_markup=manage_admin_menu())
    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "remove_admin_tg_id", content_types=["text"])
def save_removed_admin(message):
    if not is_owner(message):
        return
    try:
        tg_id = int(safe_text(message.text))
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Telegram ID must be number.", reply_markup=step_back_menu())
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE tg_id = %s", (tg_id,))
    changed = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if changed:
        bot.send_message(message.chat.id, f"✅ Removed admin ID: {tg_id}", reply_markup=manage_admin_menu())
    else:
        bot.send_message(message.chat.id, "❌ Admin not found.", reply_markup=manage_admin_menu())
    reset_user(message.chat.id)


@bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def broadcast_prompt(message):
    if not is_admin_user(message):
        return
    user_data[message.chat.id] = {"step": "broadcast_text", "prev": "admin_panel"}
    bot.send_message(message.chat.id, "📢 Send broadcast message text", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "broadcast_text", content_types=["text"])
def do_broadcast(message):
    if not is_admin_user(message):
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM orders ORDER BY user_id ASC")
    ids = [r["user_id"] for r in cur.fetchall()]
    cur.close()
    conn.close()

    success = 0
    fail = 0
    for uid in ids:
        try:
            bot.send_message(uid, f"📢 <b>Announcement</b>\n\n{message.text}")
            success += 1
        except Exception:
            fail += 1

    reset_user(message.chat.id)
    bot.send_message(message.chat.id, f"✅ Broadcast finished.\n\nSuccess: {success}\nFail: {fail}", reply_markup=admin_home_markup(message))


@bot.message_handler(func=lambda m: m.text == "📱 Change Payment Info")
def change_payment_info_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "change_payment_info", "prev": "admin_panel"}
    bot.send_message(message.chat.id, "📱 Send new payment information text", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "👤 Change Admin Username")
def change_admin_username_prompt(message):
    if not is_owner(message):
        return
    user_data[message.chat.id] = {"step": "change_admin_username", "prev": "admin_panel"}
    bot.send_message(message.chat.id, "👤 Send new public admin username\nဥပမာ: @si198", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "change_payment_info", content_types=["text"])
def save_payment_info(message):
    if not is_owner(message):
        return
    set_setting("payment_info", message.text)
    reset_user(message.chat.id)
    bot.send_message(message.chat.id, "✅ Payment information updated.", reply_markup=owner_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "change_admin_username", content_types=["text"])
def save_public_admin_username(message):
    if not is_owner(message):
        return
    username = safe_text(message.text)
    if not username.startswith("@"):
        bot.send_message(message.chat.id, "⚠️ Username must start with @", reply_markup=step_back_menu())
        return
    set_setting("public_admin_username", username)
    reset_user(message.chat.id)
    bot.send_message(message.chat.id, f"✅ Public admin username updated to {username}", reply_markup=owner_menu())


# ==================================
# FALLBACK
# ==================================
@bot.message_handler(func=lambda m: True)
def fallback(message):
    if is_admin_user(message):
        bot.send_message(message.chat.id, "🛠 Choose from admin panel.", reply_markup=admin_home_markup(message))
    else:
        bot.send_message(message.chat.id, "👤 Choose from client panel.", reply_markup=client_menu())


# ==================================
# MAIN
# ==================================
def run_bot():
    init_db()

    bot.remove_webhook()
    time.sleep(1)

    while True:
        try:
            logging.info("Bot is running...")
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            logging.exception("Bot crashed: %s", e)
            time.sleep(3)


if __name__ == "__main__":
    run_bot()
