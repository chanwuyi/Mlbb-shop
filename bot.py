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

# =========================================================
# LOAD ENV
# =========================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing")

if not ADMIN_ID_RAW:
    raise ValueError("ADMIN_ID is missing")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise ValueError("ADMIN_ID must be numeric Telegram ID")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing")

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =========================================================
# BOT
# =========================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
user_data = {}

# =========================================================
# DATABASE TABLE NAMES (NEW NAMES)
# =========================================================
TABLE_SETTINGS = "app_settings_v2"
TABLE_ADMINS = "app_admins_v2"
TABLE_CATEGORIES = "shop_categories_v2"
TABLE_PACKAGES = "shop_packages_v2"
TABLE_ORDERS = "shop_orders_v2"

# =========================================================
# DEFAULT SETTINGS
# =========================================================
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

# =========================================================
# EASY COLUMN EXTENSION
# နောက်ပိုင်း column အသစ်တိုးချင်ရင် ဒီ dict ထဲထည့်
# ဥပမာ:
# "customer_note": "TEXT DEFAULT ''"
# "payment_method": "TEXT DEFAULT ''"
# =========================================================
ORDER_EXTRA_COLUMNS = {
    # "customer_note": "TEXT DEFAULT ''",
    # "payment_method": "TEXT DEFAULT ''",
}

PACKAGE_EXTRA_COLUMNS = {
    # "image_url": "TEXT DEFAULT ''",
}

CATEGORY_EXTRA_COLUMNS = {
    # "icon_emoji": "TEXT DEFAULT ''",
}

# =========================================================
# HELPERS
# =========================================================
def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_text(value):
    return (value or "").strip()


def normalize_username(username: str) -> str:
    username = safe_text(username)
    if username.startswith("@"):
        username = username[1:]
    return username.lower()


def format_order_no(order_id: int) -> str:
    return f"ORD-{1000 + int(order_id)}"


def is_valid_number(text):
    text = safe_text(text)
    return text.isdigit() and 3 <= len(text) <= 25


def is_valid_name(text, min_len=2):
    return len(safe_text(text)) >= min_len


def reset_user(chat_id):
    user_data.pop(chat_id, None)


def actor_name(obj):
    username = getattr(obj.from_user, "username", None)
    return f"@{username}" if username else str(obj.from_user.id)


# =========================================================
# DATABASE CORE
# =========================================================
def get_connection():
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=RealDictCursor,
            sslmode="require"
        )
        return conn
    except Exception as e:
        logging.exception("Database connection failed: %s", e)
        raise


def execute_query(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(query, params or ())
        result = None

        if fetchone:
            result = cur.fetchone()
        elif fetchall:
            result = cur.fetchall()

        if commit:
            conn.commit()

        return result
    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception("DB query failed: %s", e)
        raise
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ensure_column(table_name, column_name, column_def):
    query = f"""
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = %s AND column_name = %s
    """
    row = execute_query(query, (table_name, column_name), fetchone=True)
    if not row:
        alter_sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_def}'
        execute_query(alter_sql, commit=True)
        logging.info("Added column %s.%s", table_name, column_name)


def ensure_setting(key, value):
    execute_query(
        f"""
        INSERT INTO "{TABLE_SETTINGS}"(key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO NOTHING
        """,
        (key, value),
        commit=True
    )


def init_db():
    try:
        execute_query(f"""
        CREATE TABLE IF NOT EXISTS "{TABLE_SETTINGS}"(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """, commit=True)

        execute_query(f"""
        CREATE TABLE IF NOT EXISTS "{TABLE_ADMINS}"(
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE,
            username TEXT,
            created_at TEXT NOT NULL
        )
        """, commit=True)

        execute_query(f"""
        CREATE TABLE IF NOT EXISTS "{TABLE_CATEGORIES}"(
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
        """, commit=True)

        execute_query(f"""
        CREATE TABLE IF NOT EXISTS "{TABLE_PACKAGES}"(
            id SERIAL PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES "{TABLE_CATEGORIES}"(id) ON DELETE CASCADE,
            category_name TEXT NOT NULL,
            name TEXT UNIQUE NOT NULL,
            price TEXT NOT NULL,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 9999,
            is_active BOOLEAN DEFAULT TRUE
        )
        """, commit=True)

        execute_query(f"""
        CREATE TABLE IF NOT EXISTS "{TABLE_ORDERS}"(
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
        """, commit=True)

        # Easy column extension
        for col, col_def in ORDER_EXTRA_COLUMNS.items():
            ensure_column(TABLE_ORDERS, col, col_def)

        for col, col_def in PACKAGE_EXTRA_COLUMNS.items():
            ensure_column(TABLE_PACKAGES, col, col_def)

        for col, col_def in CATEGORY_EXTRA_COLUMNS.items():
            ensure_column(TABLE_CATEGORIES, col, col_def)

        ensure_setting("payment_info", DEFAULT_PAYMENT_INFO)
        ensure_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)

        for category_name in DEFAULT_CATEGORIES:
            execute_query(
                f"""
                INSERT INTO "{TABLE_CATEGORIES}"(name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                """,
                (category_name,),
                commit=True
            )

        for category_name, package_name, price, desc, sort_order, active in DEFAULT_PACKAGES:
            cat = execute_query(
                f'SELECT id FROM "{TABLE_CATEGORIES}" WHERE name = %s',
                (category_name,),
                fetchone=True
            )
            if cat:
                execute_query(
                    f"""
                    INSERT INTO "{TABLE_PACKAGES}"(
                        category_id, category_name, name, price, description, sort_order, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (cat["id"], category_name, package_name, price, desc, sort_order, active),
                    commit=True
                )

        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.exception("init_db failed: %s", e)
        raise


# =========================================================
# SETTINGS
# =========================================================
def get_setting(key, fallback=""):
    try:
        row = execute_query(
            f'SELECT value FROM "{TABLE_SETTINGS}" WHERE key = %s',
            (key,),
            fetchone=True
        )
        return row["value"] if row else fallback
    except Exception:
        return fallback


def set_setting(key, value):
    execute_query(
        f"""
        INSERT INTO "{TABLE_SETTINGS}"(key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (key, value),
        commit=True
    )


# =========================================================
# ADMIN CHECK
# =========================================================
def is_owner(obj):
    return obj.from_user.id == ADMIN_ID


def is_admin_user(obj):
    if obj.from_user.id == ADMIN_ID:
        return True

    try:
        row = execute_query(
            f'SELECT id FROM "{TABLE_ADMINS}" WHERE tg_id = %s',
            (obj.from_user.id,),
            fetchone=True
        )
        if row:
            return True

        username = getattr(obj.from_user, "username", None)
        if username:
            row = execute_query(
                f'SELECT id FROM "{TABLE_ADMINS}" WHERE username = %s',
                (normalize_username(username),),
                fetchone=True
            )
            return row is not None
    except Exception as e:
        logging.warning("is_admin_user check failed: %s", e)

    return False


# =========================================================
# MENUS
# =========================================================
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


# =========================================================
# CATEGORY / PACKAGE QUERIES
# =========================================================
def get_non_empty_active_categories():
    try:
        return execute_query(
            f"""
            SELECT DISTINCT c.id, c.name
            FROM "{TABLE_CATEGORIES}" c
            JOIN "{TABLE_PACKAGES}" p ON p.category_id = c.id
            WHERE p.is_active = TRUE
            ORDER BY c.id ASC
            """,
            fetchall=True
        ) or []
    except Exception:
        return []


def get_category_names():
    return [row["name"] for row in get_non_empty_active_categories()]


def category_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for row in get_non_empty_active_categories():
        markup.add(row["name"])
    markup.add("🔙 Back", "❌ Cancel")
    return markup


def get_all_categories():
    return execute_query(
        f'SELECT id, name FROM "{TABLE_CATEGORIES}" ORDER BY id ASC',
        fetchall=True
    ) or []


def get_category_by_id(category_id):
    return execute_query(
        f'SELECT id, name FROM "{TABLE_CATEGORIES}" WHERE id = %s',
        (category_id,),
        fetchone=True
    )


def get_category_by_name(name):
    return execute_query(
        f'SELECT id, name FROM "{TABLE_CATEGORIES}" WHERE name = %s',
        (safe_text(name),),
        fetchone=True
    )


def add_category(name):
    execute_query(
        f'INSERT INTO "{TABLE_CATEGORIES}"(name) VALUES (%s)',
        (safe_text(name),),
        commit=True
    )


def rename_category(old_name, new_name):
    changed = execute_query(
        f'UPDATE "{TABLE_CATEGORIES}" SET name = %s WHERE name = %s RETURNING id',
        (safe_text(new_name), safe_text(old_name)),
        fetchone=True,
        commit=True
    )
    if changed:
        execute_query(
            f'UPDATE "{TABLE_PACKAGES}" SET category_name = %s WHERE category_name = %s',
            (safe_text(new_name), safe_text(old_name)),
            commit=True
        )
        execute_query(
            f'UPDATE "{TABLE_ORDERS}" SET category_name = %s WHERE category_name = %s',
            (safe_text(new_name), safe_text(old_name)),
            commit=True
        )
        return 1
    return 0


def delete_category(name):
    total = execute_query(
        f'SELECT COUNT(*) AS total FROM "{TABLE_PACKAGES}" WHERE category_name = %s',
        (safe_text(name),),
        fetchone=True
    )
    if total and total["total"] > 0:
        return -1

    row = execute_query(
        f'DELETE FROM "{TABLE_CATEGORIES}" WHERE name = %s RETURNING id',
        (safe_text(name),),
        fetchone=True,
        commit=True
    )
    return 1 if row else 0


def count_packages_by_category(category_name, only_active=True):
    if only_active:
        row = execute_query(
            f'SELECT COUNT(*) AS total FROM "{TABLE_PACKAGES}" WHERE category_name = %s AND is_active = TRUE',
            (category_name,),
            fetchone=True
        )
    else:
        row = execute_query(
            f'SELECT COUNT(*) AS total FROM "{TABLE_PACKAGES}" WHERE category_name = %s',
            (category_name,),
            fetchone=True
        )
    return row["total"] if row else 0


def get_all_packages():
    return execute_query(
        f"""
        SELECT id, category_id, category_name, name, price, description, sort_order, is_active
        FROM "{TABLE_PACKAGES}"
        ORDER BY category_id ASC, sort_order ASC, id ASC
        """,
        fetchall=True
    ) or []


def get_packages_by_category_name(category_name, only_active=False):
    if only_active:
        return execute_query(
            f"""
            SELECT id, category_id, category_name, name, price, description, sort_order, is_active
            FROM "{TABLE_PACKAGES}"
            WHERE category_name = %s AND is_active = TRUE
            ORDER BY sort_order ASC, id ASC
            """,
            (category_name,),
            fetchall=True
        ) or []
    return execute_query(
        f"""
        SELECT id, category_id, category_name, name, price, description, sort_order, is_active
        FROM "{TABLE_PACKAGES}"
        WHERE category_name = %s
        ORDER BY sort_order ASC, id ASC
        """,
        (category_name,),
        fetchall=True
    ) or []


def get_package_by_id(package_id):
    return execute_query(
        f"""
        SELECT id, category_id, category_name, name, price, description, sort_order, is_active
        FROM "{TABLE_PACKAGES}"
        WHERE id = %s
        """,
        (package_id,),
        fetchone=True
    )


def get_package_by_name(name):
    return execute_query(
        f"""
        SELECT id, category_id, category_name, name, price, description, sort_order, is_active
        FROM "{TABLE_PACKAGES}"
        WHERE LOWER(name) = LOWER(%s)
        """,
        (safe_text(name),),
        fetchone=True
    )


def next_sort_order(category_name):
    row = execute_query(
        f'SELECT COALESCE(MAX(sort_order), 0) AS mx FROM "{TABLE_PACKAGES}" WHERE category_name = %s',
        (category_name,),
        fetchone=True
    )
    return (row["mx"] if row else 0) + 1


def add_package(category_name, name, price, description):
    category = get_category_by_name(category_name)
    if not category:
        raise ValueError("Category not found")

    execute_query(
        f"""
        INSERT INTO "{TABLE_PACKAGES}"(
            category_id, category_name, name, price, description, sort_order, is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
        """,
        (category["id"], category["name"], safe_text(name), safe_text(price), safe_text(description), next_sort_order(category_name)),
        commit=True
    )


def update_package_by_id(package_id, new_name, new_price, new_description):
    row = execute_query(
        f"""
        UPDATE "{TABLE_PACKAGES}"
        SET name = %s, price = %s, description = %s
        WHERE id = %s
        RETURNING id
        """,
        (safe_text(new_name), safe_text(new_price), safe_text(new_description), package_id),
        fetchone=True,
        commit=True
    )
    return 1 if row else 0


def delete_package_by_id(package_id):
    row = execute_query(
        f'DELETE FROM "{TABLE_PACKAGES}" WHERE id = %s RETURNING id',
        (package_id,),
        fetchone=True,
        commit=True
    )
    return 1 if row else 0


def toggle_package_active(package_id):
    row = get_package_by_id(package_id)
    if not row:
        return None
    new_value = not row["is_active"]
    execute_query(
        f'UPDATE "{TABLE_PACKAGES}" SET is_active = %s WHERE id = %s',
        (new_value, package_id),
        commit=True
    )
    return get_package_by_id(package_id)


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


# =========================================================
# ORDERS
# =========================================================
def create_order(user_name, user_id, category_id, category_name, package_id, package_name, package_price, package_description, game_id, server_id, screenshot_file_id):
    current = now_text()
    row = execute_query(
        f"""
        INSERT INTO "{TABLE_ORDERS}"(
            user_name, user_id, category_id, category_name, package_id, package_name, package_price,
            package_description, game_id, server_id, screenshot_file_id, status, admin_note,
            admin_action_by, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            user_name, user_id, category_id, category_name, package_id, package_name, package_price,
            package_description, game_id, server_id, screenshot_file_id, "Pending", "", "",
            current, current
        ),
        fetchone=True,
        commit=True
    )
    return row


def get_user_orders(user_id, limit=5):
    return execute_query(
        f'SELECT * FROM "{TABLE_ORDERS}" WHERE user_id = %s ORDER BY id DESC LIMIT %s',
        (user_id, limit),
        fetchall=True
    ) or []


def get_orders(limit=10):
    return execute_query(
        f'SELECT * FROM "{TABLE_ORDERS}" ORDER BY id DESC LIMIT %s',
        (limit,),
        fetchall=True
    ) or []


def get_orders_by_status(status, limit=10):
    return execute_query(
        f'SELECT * FROM "{TABLE_ORDERS}" WHERE status = %s ORDER BY id DESC LIMIT %s',
        (status, limit),
        fetchall=True
    ) or []


def get_order_by_id(order_id):
    return execute_query(
        f'SELECT * FROM "{TABLE_ORDERS}" WHERE id = %s',
        (order_id,),
        fetchone=True
    )


def update_order_status(order_id, new_status, admin_note="", admin_action_by=""):
    return execute_query(
        f"""
        UPDATE "{TABLE_ORDERS}"
        SET status = %s, admin_note = %s, admin_action_by = %s, updated_at = %s
        WHERE id = %s
        RETURNING *
        """,
        (new_status, safe_text(admin_note), safe_text(admin_action_by), now_text(), order_id),
        fetchone=True,
        commit=True
    )


def count_today_orders():
    today = datetime.now().strftime("%Y-%m-%d")
    row = execute_query(
        f'SELECT COUNT(*) AS total FROM "{TABLE_ORDERS}" WHERE created_at LIKE %s',
        (f"{today}%",),
        fetchone=True
    )
    return row["total"] if row else 0


def get_dashboard_text():
    total = execute_query(f'SELECT COUNT(*) AS total FROM "{TABLE_ORDERS}"', fetchone=True)["total"]
    pending = execute_query(f'SELECT COUNT(*) AS total FROM "{TABLE_ORDERS}" WHERE status = %s', ("Pending",), fetchone=True)["total"]
    completed = execute_query(f'SELECT COUNT(*) AS total FROM "{TABLE_ORDERS}" WHERE status = %s', ("Completed",), fetchone=True)["total"]
    cancelled = execute_query(f'SELECT COUNT(*) AS total FROM "{TABLE_ORDERS}" WHERE status = %s', ("Cancelled",), fetchone=True)["total"]

    return (
        "📊 <b>Dashboard Summary</b>\n\n"
        f"📦 <b>Total Orders:</b> {total}\n"
        f"📅 <b>Today Orders:</b> {count_today_orders()}\n"
        f"⏳ <b>Pending:</b> {pending}\n"
        f"✅ <b>Done:</b> {completed}\n"
        f"❌ <b>Cancelled:</b> {cancelled}"
    )


# =========================================================
# DISPLAY
# =========================================================
def format_order(row):
    note = f"\n📝 <b>Admin Note:</b> {row['admin_note']}" if safe_text(row.get("admin_note")) else ""
    actor = f"\n👤 <b>Action By:</b> {row['admin_action_by']}" if safe_text(row.get("admin_action_by")) else ""
    desc = f"\n📄 <b>Description:</b> {row['package_description']}" if safe_text(row.get("package_description")) else ""

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


# =========================================================
# SAFE SEND WRAPPERS
# =========================================================
def safe_send_message(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.warning("send_message failed: %s", e)
        return None


def safe_send_photo(chat_id, photo, **kwargs):
    try:
        return bot.send_photo(chat_id, photo, **kwargs)
    except Exception as e:
        logging.warning("send_photo failed: %s", e)
        return None


def safe_answer_callback(callback_id, text=""):
    try:
        bot.answer_callback_query(callback_id, text)
    except Exception as e:
        logging.warning("answer_callback failed: %s", e)


# =========================================================
# START / PANELS
# =========================================================
@bot.message_handler(commands=["start"])
def start(message):
    try:
        reset_user(message.chat.id)
        if is_owner(message):
            safe_send_message(message.chat.id, "👑 <b>Owner Panel</b>", reply_markup=owner_menu())
        elif is_admin_user(message):
            safe_send_message(message.chat.id, "🛠 <b>Admin Panel</b>", reply_markup=admin_menu())
        else:
            safe_send_message(message.chat.id, "👋 <b>Welcome</b>\n\nChoose game/service to order.", reply_markup=client_menu())
    except Exception as e:
        logging.exception("/start failed: %s", e)
        safe_send_message(message.chat.id, "❌ Something went wrong. Please try again.")


@bot.message_handler(func=lambda m: m.text == "📞 Contact Admin")
def contact_admin(message):
    try:
        public_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)
        safe_send_message(message.chat.id, f"📞 <b>Admin Contact</b>\n\nTelegram Username: {public_username}")
    except Exception as e:
        logging.exception("contact_admin failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "🛒 Order")
def order_start(message):
    try:
        if message.chat.id in user_data:
            safe_send_message(message.chat.id, "⚠️ You already have an active order step. Finish it or cancel first.", reply_markup=step_back_menu())
            return

        categories = get_non_empty_active_categories()
        if not categories:
            safe_send_message(message.chat.id, "⚠️ No active categories available now.", reply_markup=client_menu())
            return

        user_data[message.chat.id] = {"step": "choose_category"}
        safe_send_message(message.chat.id, "🛒 <b>Choose game/service</b>\n\nအောက်က category တစ်ခုရွေးပါ။", reply_markup=category_menu())
    except Exception as e:
        logging.exception("order_start failed: %s", e)
        safe_send_message(message.chat.id, "❌ Failed to open order menu.")


@bot.message_handler(func=lambda m: m.text in get_category_names())
def category_selected(message):
    try:
        category_name = message.text
        count = count_packages_by_category(category_name, only_active=True)
        user_data[message.chat.id] = {"step": "choose_category", "selected_category": category_name}
        rows = get_packages_by_category_name(category_name, only_active=True)

        if not rows:
            safe_send_message(message.chat.id, f"🗂 <b>{category_name}</b>\n\nဒီ category အောက်မှာ active package မရှိသေးပါ။", reply_markup=step_back_menu())
            return

        safe_send_message(
            message.chat.id,
            f"🗂 <b>{category_name}</b>\n📦 <b>Total Packages:</b> {count}\n\nလိုချင်တဲ့ package ကို အောက်က button ကနေရွေးပါ 👇",
            reply_markup=package_inline_markup(category_name)
        )
    except Exception as e:
        logging.exception("category_selected failed: %s", e)
        safe_send_message(message.chat.id, "❌ Failed to load category.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def buy_package(call):
    try:
        package_id = int(call.data.split("_")[1])
        package = get_package_by_id(package_id)

        if not package or not package["is_active"]:
            safe_answer_callback(call.id, "Package not available.")
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

        safe_answer_callback(call.id, f"Selected {package['name']}")
        safe_send_message(
            call.message.chat.id,
            f"✅ <b>Selected Package</b>\n\n"
            f"🗂 <b>Category:</b> {package['category_name']}\n"
            f"💎 <b>Package:</b> {package['name']}\n"
            f"💰 <b>Price:</b> {package['price']}\n"
            f"📄 <b>Description:</b> {package['description']}\n\n"
            f"🎮 Now send your <b>Game ID</b>",
            reply_markup=step_back_menu()
        )
    except Exception as e:
        logging.exception("buy_package failed: %s", e)
        safe_answer_callback(call.id, "❌ Failed.")


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "game_id", content_types=["text"])
def get_game_id_handler(message):
    try:
        game_id = safe_text(message.text)
        if not is_valid_number(game_id):
            safe_send_message(message.chat.id, "⚠️ Game ID must be number only.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["game_id"] = game_id
        user_data[message.chat.id]["step"] = "server_id"
        safe_send_message(message.chat.id, "🖥 <b>Send your Server ID</b>", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("get_game_id_handler failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "server_id", content_types=["text"])
def get_server_id_handler(message):
    try:
        server_id = safe_text(message.text)
        if not is_valid_number(server_id):
            safe_send_message(message.chat.id, "⚠️ Server ID must be number only.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["server_id"] = server_id
        user_data[message.chat.id]["step"] = "screenshot"

        payment_info = get_setting("payment_info", DEFAULT_PAYMENT_INFO)
        public_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)

        safe_send_message(
            message.chat.id,
            f"📦 <b>Order Summary</b>\n\n"
            f"🗂 <b>Category:</b> {user_data[message.chat.id]['category_name']}\n"
            f"💎 <b>Package:</b> {user_data[message.chat.id]['package_name']}\n"
            f"💰 <b>Price:</b> {user_data[message.chat.id]['package_price']}\n"
            f"📄 <b>Description:</b> {user_data[message.chat.id]['package_description']}\n"
            f"🎮 <b>Game ID:</b> {user_data[message.chat.id]['game_id']}\n"
            f"🖥 <b>Server ID:</b> {user_data[message.chat.id]['server_id']}\n\n"
            f"{payment_info}\n\n"
            f"📞 <b>Admin Telegram:</b> {public_username}\n\n"
            f"📸 <b>Payment screenshot ကို photo နဲ့ပို့ပေးပါ။</b>",
            reply_markup=step_back_menu()
        )
    except Exception as e:
        logging.exception("get_server_id_handler failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "screenshot", content_types=["photo", "text", "document", "video", "audio", "sticker"])
def receive_screenshot(message):
    try:
        if message.content_type != "photo":
            safe_send_message(message.chat.id, "⚠️ Payment screenshot ကို <b>photo</b> နဲ့ပဲ ပို့ရမယ်။", reply_markup=step_back_menu())
            return

        data = user_data.get(message.chat.id)
        if not data:
            safe_send_message(message.chat.id, "⚠️ Session expired. Please /start again.")
            return

        data["screenshot_file_id"] = message.photo[-1].file_id
        data["step"] = "confirm_order"

        safe_send_message(
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
    except Exception as e:
        logging.exception("receive_screenshot failed: %s", e)


@bot.callback_query_handler(func=lambda c: c.data == "confirm_order")
def confirm_order_submit(call):
    try:
        data = user_data.get(call.message.chat.id)
        if not data or data.get("step") != "confirm_order":
            safe_answer_callback(call.id, "Order session expired.")
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
        safe_answer_callback(call.id, "Order confirmed.")

        safe_send_message(
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

        safe_send_photo(
            ADMIN_ID,
            data["screenshot_file_id"],
            caption=admin_caption,
            reply_markup=admin_order_buttons(order["id"])
        )

        reset_user(call.message.chat.id)

    except Exception as e:
        logging.exception("confirm_order_submit failed: %s", e)
        safe_answer_callback(call.id, "❌ Failed to save order.")


@bot.callback_query_handler(func=lambda c: c.data == "cancel_order_submit")
def cancel_order_submit(call):
    try:
        reset_user(call.message.chat.id)
        safe_answer_callback(call.id, "Order cancelled.")
        safe_send_message(call.message.chat.id, "❌ Order cancelled.", reply_markup=client_menu())
    except Exception as e:
        logging.exception("cancel_order_submit failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📄 My Orders")
def my_orders(message):
    try:
        rows = get_user_orders(message.chat.id, 5)
        if not rows:
            safe_send_message(message.chat.id, "📭 No orders yet.")
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
        safe_send_message(message.chat.id, text)
    except Exception as e:
        logging.exception("my_orders failed: %s", e)


# =========================================================
# SIMPLE ADMIN ACTIONS
# =========================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith(("done_", "cancel_", "viewss_")))
def admin_actions(call):
    try:
        if not is_admin_user(call):
            safe_answer_callback(call.id, "⛔ Admin only.")
            return

        if call.data.startswith("viewss_"):
            order_id = int(call.data.split("_")[1])
            row = get_order_by_id(order_id)
            if row:
                safe_send_photo(call.message.chat.id, row["screenshot_file_id"], caption=f"🖼 Screenshot for {format_order_no(order_id)}")
                safe_answer_callback(call.id, "Screenshot sent.")
            else:
                safe_answer_callback(call.id, "Order not found.")
            return

        action, order_id_text = call.data.split("_")
        order_id = int(order_id_text)
        new_status = "Completed" if action == "done" else "Cancelled"

        row = update_order_status(order_id, new_status, admin_note="", admin_action_by=actor_name(call))
        if not row:
            safe_answer_callback(call.id, "Order not found.")
            return

        notify_user(order_id, row["user_id"], new_status)
        safe_answer_callback(call.id, f"{format_order_no(order_id)} → {new_status}")
    except Exception as e:
        logging.exception("admin_actions failed: %s", e)
        safe_answer_callback(call.id, "❌ Failed.")


# =========================================================
# FALLBACKS
# =========================================================
@bot.message_handler(func=lambda m: m.text == "❌ Cancel")
def cancel_text(message):
    try:
        reset_user(message.chat.id)
        if is_admin_user(message):
            safe_send_message(message.chat.id, "❌ Cancelled.", reply_markup=admin_home_markup(message))
        else:
            safe_send_message(message.chat.id, "❌ Cancelled.", reply_markup=client_menu())
    except Exception as e:
        logging.exception("cancel_text failed: %s", e)


@bot.message_handler(func=lambda m: True)
def fallback(message):
    try:
        if is_admin_user(message):
            safe_send_message(message.chat.id, "🛠 Choose from admin panel.", reply_markup=admin_home_markup(message))
        else:
            safe_send_message(message.chat.id, "👤 Choose from client panel.", reply_markup=client_menu())
    except Exception as e:
        logging.exception("fallback failed: %s", e)


# =========================================================
# MAIN
# =========================================================
def run_bot():
    while True:
        try:
            logging.info("Initializing database...")
            init_db()

            logging.info("Removing webhook...")
            bot.remove_webhook()
            time.sleep(1)

            logging.info("Bot is running...")
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            logging.exception("Bot crashed: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    run_bot()
