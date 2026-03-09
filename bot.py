import os
import time
import logging
from datetime import datetime

from dotenv import load_dotenv
import telebot
from telebot import types
import psycopg2
from psycopg2.extras import RealDictCursor

# =========================================================
# ENV
# =========================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing")

if not OWNER_ID_RAW:
    raise ValueError("OWNER_ID is missing")

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    raise ValueError("OWNER_ID must be numeric Telegram ID")

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
user_data = {}

# =========================================================
# TABLES
# =========================================================
TABLE_SETTINGS = "app_settings_v5"
TABLE_ADMINS = "app_admins_v5"
TABLE_CATEGORIES = "shop_categories_v5"
TABLE_PACKAGES = "shop_packages_v5"
TABLE_ORDERS = "shop_orders_v5"

# =========================================================
# DEFAULT DATA
# =========================================================
DEFAULT_PAYMENT_INFO = """💳 <b>ငွေပေးချေမှုအချက်အလက်</b>

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


def with_at(username: str) -> str:
    username = normalize_username(username)
    return f"@{username}" if username else ""


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
# DATABASE
# =========================================================
def get_connection():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )


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
    execute_query(f"""
    CREATE TABLE IF NOT EXISTS "{TABLE_SETTINGS}"(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """, commit=True)

    execute_query(f"""
    CREATE TABLE IF NOT EXISTS "{TABLE_ADMINS}"(
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
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
# ACCESS CONTROL
# =========================================================
def is_owner(obj):
    return obj.from_user.id == OWNER_ID


def is_extra_admin_username(username: str) -> bool:
    username = normalize_username(username)
    if not username:
        return False
    row = execute_query(
        f'SELECT id FROM "{TABLE_ADMINS}" WHERE username = %s',
        (username,),
        fetchone=True
    )
    return row is not None


def is_admin_user(obj):
    if obj.from_user.id == OWNER_ID:
        return True

    username = normalize_username(getattr(obj.from_user, "username", ""))
    if not username:
        return False

    return is_extra_admin_username(username)


# =========================================================
# SAFE SEND
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
# CATEGORY / PACKAGE DB
# =========================================================
def get_non_empty_active_categories():
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
# ADMIN DB
# =========================================================
def get_all_admins():
    return execute_query(
        f'SELECT id, username, created_at FROM "{TABLE_ADMINS}" ORDER BY id ASC',
        fetchall=True
    ) or []


def add_admin_username(username):
    execute_query(
        f"""
        INSERT INTO "{TABLE_ADMINS}"(username, created_at)
        VALUES (%s, %s)
        ON CONFLICT (username) DO NOTHING
        """,
        (normalize_username(username), now_text()),
        commit=True
    )


def remove_admin_username(username):
    row = execute_query(
        f'DELETE FROM "{TABLE_ADMINS}" WHERE username = %s RETURNING id',
        (normalize_username(username),),
        fetchone=True,
        commit=True
    )
    return row is not None


def admins_text():
    rows = get_all_admins()
    text = "👥 <b>Admin List</b>\n\n"
    text += f"👑 <b>Owner ID:</b> <code>{OWNER_ID}</code>\n"
    text += f"📞 <b>Public Admin:</b> {get_setting('public_admin_username', DEFAULT_PUBLIC_ADMIN)}\n\n"

    if not rows:
        text += "Extra admins မရှိသေးပါ။"
        return text

    for row in rows:
        text += f"🆔 <b>{row['id']}</b> • @{row['username']}\n"
    return text


# =========================================================
# ORDERS DB
# =========================================================
def create_order(user_name, user_id, category_id, category_name, package_id, package_name, package_price, package_description, game_id, server_id, screenshot_file_id):
    current = now_text()
    return execute_query(
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
            safe_send_message(message.chat.id, "👋 <b>Welcome</b>\n\nGame / service ကိုရွေးပြီး order လုပ်နိုင်ပါတယ်။", reply_markup=client_menu())
    except Exception as e:
        logging.exception("/start failed: %s", e)
        safe_send_message(message.chat.id, "❌ Something went wrong.")


@bot.message_handler(func=lambda m: m.text == "🏠 Admin Panel")
def open_admin_panel(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.", reply_markup=client_menu())
            return
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, "🏠 <b>Admin Panel</b>\n\nအောက်က menu ကနေရွေးပါ။", reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("open_admin_panel failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "👀 Client Panel")
def open_client_panel(message):
    try:
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, "👀 <b>Client Panel</b>", reply_markup=client_menu())
    except Exception as e:
        logging.exception("open_client_panel failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📞 Contact Admin")
def contact_admin(message):
    try:
        public_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)
        safe_send_message(message.chat.id, f"📞 <b>Admin Contact</b>\n\nTelegram Username: {public_username}")
    except Exception as e:
        logging.exception("contact_admin failed: %s", e)


# =========================================================
# CLIENT ORDER FLOW
# =========================================================
@bot.message_handler(func=lambda m: m.text == "🛒 Order")
def order_start(message):
    try:
        if message.chat.id in user_data and user_data.get(message.chat.id, {}).get("step"):
            safe_send_message(message.chat.id, "⚠️ လက်ရှိ step တစ်ခုလုပ်နေပါတယ်။ Back သို့မဟုတ် Cancel လုပ်ပါ။", reply_markup=step_back_menu())
            return

        categories = get_non_empty_active_categories()
        if not categories:
            safe_send_message(message.chat.id, "⚠️ Active category မရှိသေးပါ။", reply_markup=client_menu())
            return

        user_data[message.chat.id] = {"step": "choose_category"}
        safe_send_message(message.chat.id, "🛒 <b>Choose Game / Service</b>\n\nအောက်က category တစ်ခုရွေးပါ။", reply_markup=category_menu())
    except Exception as e:
        logging.exception("order_start failed: %s", e)
        safe_send_message(message.chat.id, "❌ Order menu ဖွင့်မရပါ။")


@bot.message_handler(func=lambda m: m.text in get_category_names())
def category_selected(message):
    try:
        category_name = message.text
        count = count_packages_by_category(category_name, only_active=True)
        user_data[message.chat.id] = {"step": "choose_category", "selected_category": category_name}

        rows = get_packages_by_category_name(category_name, only_active=True)
        if not rows:
            safe_send_message(message.chat.id, "⚠️ ဒီ category အောက်မှာ active package မရှိသေးပါ။", reply_markup=step_back_menu())
            return

        safe_send_message(
            message.chat.id,
            f"🗂 <b>{category_name}</b>\n📦 <b>Total Packages:</b> {count}\n\nလိုချင်တဲ့ package ကို အောက်က button ကနေရွေးပါ 👇",
            reply_markup=package_inline_markup(category_name)
        )
    except Exception as e:
        logging.exception("category_selected failed: %s", e)
        safe_send_message(message.chat.id, "❌ Category load မရပါ။")


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
            f"🎮 Game ID ပို့ပါ။",
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
            safe_send_message(message.chat.id, "⚠️ Game ID ကို number only ပို့ပါ။", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["game_id"] = game_id
        user_data[message.chat.id]["step"] = "server_id"
        safe_send_message(message.chat.id, "🖥 Server ID ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("get_game_id_handler failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "server_id", content_types=["text"])
def get_server_id_handler(message):
    try:
        server_id = safe_text(message.text)
        if not is_valid_number(server_id):
            safe_send_message(message.chat.id, "⚠️ Server ID ကို number only ပို့ပါ။", reply_markup=step_back_menu())
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
            f"📸 Payment screenshot ကို <b>photo</b> နဲ့ပို့ပါ။",
            reply_markup=step_back_menu()
        )
    except Exception as e:
        logging.exception("get_server_id_handler failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "screenshot", content_types=["photo", "text", "document", "video", "audio", "sticker"])
def receive_screenshot(message):
    try:
        if message.content_type != "photo":
            safe_send_message(message.chat.id, "⚠️ Screenshot ကို <b>photo</b> နဲ့ပဲ ပို့ရမယ်။", reply_markup=step_back_menu())
            return

        data = user_data.get(message.chat.id)
        if not data:
            safe_send_message(message.chat.id, "⚠️ Session expired. /start ပြန်လုပ်ပါ။")
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
            OWNER_ID,
            data["screenshot_file_id"],
            caption=admin_caption,
            reply_markup=admin_order_buttons(order["id"])
        )

        for admin in get_all_admins():
            try:
                bot.send_photo(
                    chat_id=f"@{admin['username']}",
                    photo=data["screenshot_file_id"],
                    caption=admin_caption,
                    reply_markup=admin_order_buttons(order["id"])
                )
            except Exception as e:
                logging.warning("Failed to notify admin @%s: %s", admin["username"], e)

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
# ADMIN PANEL
# =========================================================
@bot.message_handler(func=lambda m: m.text == "📊 Dashboard")
def dashboard_handler(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return
        safe_send_message(message.chat.id, get_dashboard_text(), reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("dashboard_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📦 All Orders")
def all_orders_handler(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return

        rows = get_orders(10)
        if not rows:
            safe_send_message(message.chat.id, "📭 No orders found.", reply_markup=admin_home_markup(message))
            return

        text = "📦 <b>Last 10 Orders</b>\n\n"
        for row in rows:
            text += format_order(row) + "\n\n"

        safe_send_message(message.chat.id, text, reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("all_orders_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "⏳ Pending Orders")
def pending_orders_handler(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return

        rows = get_orders_by_status("Pending", 10)
        if not rows:
            safe_send_message(message.chat.id, "📭 No pending orders.", reply_markup=admin_home_markup(message))
            return

        text = "⏳ <b>Pending Orders</b>\n\n"
        for row in rows:
            text += format_order(row) + "\n\n"

        safe_send_message(message.chat.id, text, reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("pending_orders_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "✅ Done Orders")
def done_orders_handler(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return

        rows = get_orders_by_status("Completed", 10)
        if not rows:
            safe_send_message(message.chat.id, "📭 No done orders.", reply_markup=admin_home_markup(message))
            return

        text = "✅ <b>Done Orders</b>\n\n"
        for row in rows:
            text += format_order(row) + "\n\n"

        safe_send_message(message.chat.id, text, reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("done_orders_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "❌ Cancelled Orders")
def cancelled_orders_handler(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return

        rows = get_orders_by_status("Cancelled", 10)
        if not rows:
            safe_send_message(message.chat.id, "📭 No cancelled orders.", reply_markup=admin_home_markup(message))
            return

        text = "❌ <b>Cancelled Orders</b>\n\n"
        for row in rows:
            text += format_order(row) + "\n\n"

        safe_send_message(message.chat.id, text, reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("cancelled_orders_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "🔍 Search Order")
def search_order_prompt(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return

        user_data[message.chat.id] = {"step": "search_order_wait_id"}
        safe_send_message(
            message.chat.id,
            "🔍 DB ID သို့မဟုတ် Order No ပို့ပါ\n\nဥပမာ:\n<code>1</code>\n<code>ORD-1001</code>",
            reply_markup=step_back_menu()
        )
    except Exception as e:
        logging.exception("search_order_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "search_order_wait_id", content_types=["text"])
def search_order_input(message):
    try:
        if not is_admin_user(message):
            return

        text = safe_text(message.text).upper()

        if text.startswith("ORD-"):
            text = text.replace("ORD-", "")
            try:
                db_id = int(text) - 1000
            except ValueError:
                safe_send_message(message.chat.id, "⚠️ Invalid order number.", reply_markup=step_back_menu())
                return
        else:
            try:
                db_id = int(text)
            except ValueError:
                safe_send_message(message.chat.id, "⚠️ Valid DB ID or Order No ပို့ပါ။", reply_markup=step_back_menu())
                return

        row = get_order_by_id(db_id)
        if not row:
            safe_send_message(message.chat.id, "❌ Order not found.", reply_markup=admin_home_markup(message))
            reset_user(message.chat.id)
            return

        safe_send_message(message.chat.id, format_order(row), reply_markup=admin_home_markup(message))
        reset_user(message.chat.id)
    except Exception as e:
        logging.exception("search_order_input failed: %s", e)


# =========================================================
# MANAGE CATEGORIES
# =========================================================
@bot.message_handler(func=lambda m: m.text == "🗂 Manage Categories")
def manage_categories_open(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, "🗂 <b>Category Manager</b>", reply_markup=manage_category_menu())
    except Exception as e:
        logging.exception("manage_categories_open failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📋 List Categories")
def list_categories_handler(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return

        rows = get_all_categories()
        if not rows:
            safe_send_message(message.chat.id, "📭 No categories.", reply_markup=manage_category_menu())
            return

        text = "🗂 <b>Category List</b>\n\n"
        for row in rows:
            total = count_packages_by_category(row["name"], only_active=False)
            text += f"🆔 <b>{row['id']}</b> • {row['name']}  ({total} packages)\n"

        safe_send_message(message.chat.id, text, reply_markup=manage_category_menu())
    except Exception as e:
        logging.exception("list_categories_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "➕ Add Category")
def add_category_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "manage_categories_add"}
        safe_send_message(message.chat.id, "➕ Category name ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("add_category_prompt failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "✏️ Rename Category")
def rename_category_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "manage_categories_rename_old"}
        safe_send_message(message.chat.id, "✏️ Old category name ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("rename_category_prompt failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "🗑 Delete Category")
def delete_category_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "manage_categories_delete"}
        safe_send_message(message.chat.id, "🗑 Delete လုပ်မယ့် category name ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("delete_category_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_categories_add", content_types=["text"])
def add_category_input(message):
    try:
        name = safe_text(message.text)
        if not is_valid_name(name):
            safe_send_message(message.chat.id, "⚠️ Invalid category name.", reply_markup=step_back_menu())
            return
        if get_category_by_name(name):
            safe_send_message(message.chat.id, "⚠️ Category already exists.", reply_markup=step_back_menu())
            return

        add_category(name)
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, f"✅ Category added: <b>{name}</b>", reply_markup=manage_category_menu())
    except Exception as e:
        logging.exception("add_category_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_categories_rename_old", content_types=["text"])
def rename_category_old_input(message):
    try:
        old_name = safe_text(message.text)
        if not get_category_by_name(old_name):
            safe_send_message(message.chat.id, "❌ Category not found.", reply_markup=step_back_menu())
            return
        user_data[message.chat.id] = {"step": "manage_categories_rename_new", "old_name": old_name}
        safe_send_message(message.chat.id, "✏️ New category name ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("rename_category_old_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_categories_rename_new", content_types=["text"])
def rename_category_new_input(message):
    try:
        data = user_data.get(message.chat.id, {})
        old_name = data.get("old_name", "")
        new_name = safe_text(message.text)

        if not is_valid_name(new_name):
            safe_send_message(message.chat.id, "⚠️ Invalid new category name.", reply_markup=step_back_menu())
            return

        if get_category_by_name(new_name):
            safe_send_message(message.chat.id, "⚠️ New category name already exists.", reply_markup=step_back_menu())
            return

        changed = rename_category(old_name, new_name)
        reset_user(message.chat.id)

        if changed:
            safe_send_message(message.chat.id, f"✅ Category renamed:\n<b>{old_name}</b> → <b>{new_name}</b>", reply_markup=manage_category_menu())
        else:
            safe_send_message(message.chat.id, "❌ Rename failed.", reply_markup=manage_category_menu())
    except Exception as e:
        logging.exception("rename_category_new_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_categories_delete", content_types=["text"])
def delete_category_input(message):
    try:
        name = safe_text(message.text)
        result = delete_category(name)
        reset_user(message.chat.id)

        if result == 1:
            safe_send_message(message.chat.id, f"✅ Deleted category: <b>{name}</b>", reply_markup=manage_category_menu())
        elif result == -1:
            safe_send_message(message.chat.id, "⚠️ ဒီ category အောက်မှာ package တွေရှိနေပါတယ်။ အရင် delete လုပ်ပါ။", reply_markup=manage_category_menu())
        else:
            safe_send_message(message.chat.id, "❌ Category not found.", reply_markup=manage_category_menu())
    except Exception as e:
        logging.exception("delete_category_input failed: %s", e)


# =========================================================
# MANAGE PACKAGES
# =========================================================
@bot.message_handler(func=lambda m: m.text == "💎 Manage Packages")
def manage_packages_open(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, "💎 <b>Package Manager</b>", reply_markup=manage_package_menu())
    except Exception as e:
        logging.exception("manage_packages_open failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📋 List Packages")
def list_packages_handler(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return

        rows = get_all_packages()
        if not rows:
            safe_send_message(message.chat.id, "📭 No packages found.", reply_markup=manage_package_menu())
            return

        text = "💎 <b>Package List</b>\n\n"
        for row in rows:
            status = "🟢 Active" if row["is_active"] else "⚫ Inactive"
            text += (
                f"🆔 <b>{row['id']}</b>\n"
                f"🗂 {row['category_name']}\n"
                f"💎 {row['name']}\n"
                f"💰 {row['price']}\n"
                f"📄 {row['description']}\n"
                f"{status}\n\n"
            )

        safe_send_message(message.chat.id, text, reply_markup=manage_package_menu())
    except Exception as e:
        logging.exception("list_packages_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "➕ Add Package")
def add_package_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return

        rows = get_all_categories()
        if not rows:
            safe_send_message(message.chat.id, "⚠️ Add category first.", reply_markup=manage_package_menu())
            return

        text = "➕ <b>Add Package</b>\n\nCategory name ပို့ပါ:\n\n"
        for row in rows:
            text += f"🆔 <b>{row['id']}</b> • {row['name']}\n"

        user_data[message.chat.id] = {"step": "manage_packages_add_category"}
        safe_send_message(message.chat.id, text, reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("add_package_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_add_category", content_types=["text"])
def add_package_category_input(message):
    try:
        category_name = safe_text(message.text)
        cat = get_category_by_name(category_name)
        if not cat:
            safe_send_message(message.chat.id, "❌ Category not found.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id] = {
            "step": "manage_packages_add_name",
            "category_name": cat["name"]
        }
        safe_send_message(message.chat.id, f"🗂 Category selected: <b>{cat['name']}</b>\n\nPackage name ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("add_package_category_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_add_name", content_types=["text"])
def add_package_name_input(message):
    try:
        name = safe_text(message.text)
        if not is_valid_name(name):
            safe_send_message(message.chat.id, "⚠️ Invalid package name.", reply_markup=step_back_menu())
            return
        if get_package_by_name(name):
            safe_send_message(message.chat.id, "⚠️ Package name already exists.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["name"] = name
        user_data[message.chat.id]["step"] = "manage_packages_add_price"
        safe_send_message(message.chat.id, "💰 Price ပို့ပါ။\nဥပမာ: <code>5800 ks</code>", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("add_package_name_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_add_price", content_types=["text"])
def add_package_price_input(message):
    try:
        price = safe_text(message.text)
        if not price:
            safe_send_message(message.chat.id, "⚠️ Price cannot be empty.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["price"] = price
        user_data[message.chat.id]["step"] = "manage_packages_add_description"
        safe_send_message(message.chat.id, "📄 Description ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("add_package_price_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_add_description", content_types=["text"])
def add_package_description_input(message):
    try:
        data = user_data.get(message.chat.id, {})
        description = safe_text(message.text)

        add_package(data["category_name"], data["name"], data["price"], description)

        package = get_package_by_name(data["name"])
        reset_user(message.chat.id)

        safe_send_message(
            message.chat.id,
            f"✅ <b>Package added</b>\n\n"
            f"🆔 <b>ID:</b> {package['id']}\n"
            f"🗂 <b>Category:</b> {package['category_name']}\n"
            f"💎 <b>Name:</b> {package['name']}\n"
            f"💰 <b>Price:</b> {package['price']}\n"
            f"📄 <b>Description:</b> {package['description']}",
            reply_markup=manage_package_menu()
        )

        safe_send_message(
            message.chat.id,
            f"🗂 <b>{package['category_name']}</b>\nCustomer view inline buttons 👇",
            reply_markup=package_inline_markup(package["category_name"])
        )
    except Exception as e:
        logging.exception("add_package_description_input failed: %s", e)
        safe_send_message(message.chat.id, "❌ Failed to add package.")


@bot.message_handler(func=lambda m: m.text == "✏️ Edit Package")
def edit_package_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return

        rows = get_all_packages()
        if not rows:
            safe_send_message(message.chat.id, "📭 No packages found.", reply_markup=manage_package_menu())
            return

        text = "✏️ <b>Edit Package</b>\n\nPackage <b>ID</b> ပို့ပါ။\n\n"
        for row in rows[:20]:
            text += f"🆔 <b>{row['id']}</b> • {row['name']} • {row['price']}\n"

        user_data[message.chat.id] = {"step": "manage_packages_edit_id"}
        safe_send_message(message.chat.id, text, reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("edit_package_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_edit_id", content_types=["text"])
def edit_package_id_input(message):
    try:
        package_id = int(safe_text(message.text))
        row = get_package_by_id(package_id)
        if not row:
            safe_send_message(message.chat.id, "❌ Package not found.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id] = {"step": "manage_packages_edit_name", "package_id": package_id}
        safe_send_message(
            message.chat.id,
            f"✏️ <b>Editing Package</b>\n\n"
            f"🆔 ID: {row['id']}\n"
            f"🗂 Category: {row['category_name']}\n"
            f"💎 Name: {row['name']}\n"
            f"💰 Price: {row['price']}\n"
            f"📄 Description: {row['description']}\n\n"
            f"New name ပို့ပါ။",
            reply_markup=step_back_menu()
        )
    except Exception:
        safe_send_message(message.chat.id, "⚠️ Valid package ID ပို့ပါ။", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_edit_name", content_types=["text"])
def edit_package_name_input(message):
    try:
        name = safe_text(message.text)
        if not is_valid_name(name):
            safe_send_message(message.chat.id, "⚠️ Invalid package name.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["new_name"] = name
        user_data[message.chat.id]["step"] = "manage_packages_edit_price"
        safe_send_message(message.chat.id, "💰 New price ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("edit_package_name_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_edit_price", content_types=["text"])
def edit_package_price_input(message):
    try:
        price = safe_text(message.text)
        if not price:
            safe_send_message(message.chat.id, "⚠️ Price cannot be empty.", reply_markup=step_back_menu())
            return

        user_data[message.chat.id]["new_price"] = price
        user_data[message.chat.id]["step"] = "manage_packages_edit_description"
        safe_send_message(message.chat.id, "📄 New description ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("edit_package_price_input failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_edit_description", content_types=["text"])
def edit_package_description_input(message):
    try:
        data = user_data.get(message.chat.id, {})
        package_id = data["package_id"]
        new_name = data["new_name"]
        new_price = data["new_price"]
        new_description = safe_text(message.text)

        result = update_package_by_id(package_id, new_name, new_price, new_description)
        row = get_package_by_id(package_id)
        reset_user(message.chat.id)

        if result and row:
            safe_send_message(
                message.chat.id,
                f"✅ <b>Package Updated</b>\n\n"
                f"🆔 ID: {row['id']}\n"
                f"🗂 Category: {row['category_name']}\n"
                f"💎 Name: {row['name']}\n"
                f"💰 Price: {row['price']}\n"
                f"📄 Description: {row['description']}",
                reply_markup=manage_package_menu()
            )
        else:
            safe_send_message(message.chat.id, "❌ Update failed.", reply_markup=manage_package_menu())
    except Exception as e:
        logging.exception("edit_package_description_input failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "🗑 Delete Package")
def delete_package_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "manage_packages_delete_id"}
        safe_send_message(message.chat.id, "🗑 Delete လုပ်မယ့် package ID ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("delete_package_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_delete_id", content_types=["text"])
def delete_package_id_input(message):
    try:
        package_id = int(safe_text(message.text))
        result = delete_package_by_id(package_id)
        reset_user(message.chat.id)

        if result:
            safe_send_message(message.chat.id, "✅ Package deleted.", reply_markup=manage_package_menu())
        else:
            safe_send_message(message.chat.id, "❌ Package not found.", reply_markup=manage_package_menu())
    except Exception:
        safe_send_message(message.chat.id, "⚠️ Valid package ID ပို့ပါ။", reply_markup=step_back_menu())


@bot.message_handler(func=lambda m: m.text == "🔁 Toggle Active")
def toggle_package_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "manage_packages_toggle_id"}
        safe_send_message(message.chat.id, "🔁 Toggle လုပ်မယ့် package ID ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("toggle_package_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "manage_packages_toggle_id", content_types=["text"])
def toggle_package_id_input(message):
    try:
        package_id = int(safe_text(message.text))
        row = toggle_package_active(package_id)
        reset_user(message.chat.id)

        if row:
            status = "🟢 Active" if row["is_active"] else "⚫ Inactive"
            safe_send_message(
                message.chat.id,
                f"✅ Package updated.\n\n🆔 {row['id']}\n💎 {row['name']}\n{status}",
                reply_markup=manage_package_menu()
            )
        else:
            safe_send_message(message.chat.id, "❌ Package not found.", reply_markup=manage_package_menu())
    except Exception:
        safe_send_message(message.chat.id, "⚠️ Valid package ID ပို့ပါ။", reply_markup=step_back_menu())


# =========================================================
# MANAGE ADMINS
# =========================================================
@bot.message_handler(func=lambda m: m.text == "👥 Manage Admins")
def manage_admins_open(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, admins_text(), reply_markup=manage_admin_menu())
    except Exception as e:
        logging.exception("manage_admins_open failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📋 List Admins")
def list_admins_handler(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        safe_send_message(message.chat.id, admins_text(), reply_markup=manage_admin_menu())
    except Exception as e:
        logging.exception("list_admins_handler failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "➕ Add Admin")
def add_admin_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "add_admin_username"}
        safe_send_message(message.chat.id, "➕ Add လုပ်မယ့် admin username ပို့ပါ\nဥပမာ: <code>@username</code>", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("add_admin_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "add_admin_username", content_types=["text"])
def add_admin_input(message):
    try:
        username = safe_text(message.text)
        if not username.startswith("@"):
            safe_send_message(message.chat.id, "⚠️ Username must start with @", reply_markup=step_back_menu())
            return

        username_norm = normalize_username(username)
        if not username_norm:
            safe_send_message(message.chat.id, "⚠️ Invalid username.", reply_markup=step_back_menu())
            return

        if normalize_username(get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)) == username_norm:
            safe_send_message(message.chat.id, "⚠️ ဒီ username က public admin အဖြစ်သုံးနေတာပါ။", reply_markup=step_back_menu())
            return

        add_admin_username(username_norm)
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, f"✅ Admin added: @{username_norm}", reply_markup=manage_admin_menu())
    except Exception as e:
        logging.exception("add_admin_input failed: %s", e)
        safe_send_message(message.chat.id, "❌ Failed to add admin.")


@bot.message_handler(func=lambda m: m.text == "🗑 Remove Admin")
def remove_admin_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return

        rows = get_all_admins()
        text = "🗑 Remove လုပ်မယ့် admin username ပို့ပါ\n\n"
        if rows:
            for row in rows:
                text += f"• @{row['username']}\n"
        else:
            text += "Extra admins မရှိသေးပါ။"

        user_data[message.chat.id] = {"step": "remove_admin_username"}
        safe_send_message(message.chat.id, text, reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("remove_admin_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "remove_admin_username", content_types=["text"])
def remove_admin_input(message):
    try:
        username = safe_text(message.text)
        if not username.startswith("@"):
            safe_send_message(message.chat.id, "⚠️ Username must start with @", reply_markup=step_back_menu())
            return

        username_norm = normalize_username(username)
        removed = remove_admin_username(username_norm)
        reset_user(message.chat.id)

        if removed:
            safe_send_message(message.chat.id, f"✅ Admin removed: @{username_norm}", reply_markup=manage_admin_menu())
        else:
            safe_send_message(message.chat.id, "❌ Admin not found.", reply_markup=manage_admin_menu())
    except Exception as e:
        logging.exception("remove_admin_input failed: %s", e)


# =========================================================
# BROADCAST / SETTINGS
# =========================================================
@bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def broadcast_prompt(message):
    try:
        if not is_admin_user(message):
            safe_send_message(message.chat.id, "⛔ Admin only.")
            return
        user_data[message.chat.id] = {"step": "broadcast_wait_text"}
        safe_send_message(message.chat.id, "📢 Broadcast message ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("broadcast_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "broadcast_wait_text", content_types=["text"])
def broadcast_input(message):
    try:
        if not is_admin_user(message):
            return

        text = safe_text(message.text)
        rows = execute_query(
            f'SELECT DISTINCT user_id FROM "{TABLE_ORDERS}" ORDER BY user_id ASC',
            fetchall=True
        ) or []

        sent = 0
        failed = 0
        for row in rows:
            try:
                bot.send_message(row["user_id"], f"📢 <b>Announcement</b>\n\n{text}")
                sent += 1
                time.sleep(0.03)
            except Exception:
                failed += 1

        reset_user(message.chat.id)
        safe_send_message(message.chat.id, f"✅ Broadcast finished.\n\n📤 Sent: {sent}\n❌ Failed: {failed}", reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("broadcast_input failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "📱 Change Payment Info")
def change_payment_info_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return
        user_data[message.chat.id] = {"step": "change_payment_info"}
        safe_send_message(message.chat.id, "📱 New payment info text ပို့ပါ။", reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("change_payment_info_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "change_payment_info", content_types=["text"])
def change_payment_info_input(message):
    try:
        set_setting("payment_info", message.text)
        reset_user(message.chat.id)
        safe_send_message(message.chat.id, "✅ Payment info updated.", reply_markup=admin_home_markup(message))
    except Exception as e:
        logging.exception("change_payment_info_input failed: %s", e)


@bot.message_handler(func=lambda m: m.text == "👤 Change Admin Username")
def change_admin_username_prompt(message):
    try:
        if not is_owner(message):
            safe_send_message(message.chat.id, "⛔ Owner only.")
            return

        current_public = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)
        rows = get_all_admins()

        text = "👤 <b>Change Public Admin Username</b>\n\n"
        text += f"📞 Current public admin: {current_public}\n\n"
        text += "📋 Current extra admin list:\n"
        if rows:
            for row in rows:
                text += f"• @{row['username']}\n"
        else:
            text += "Extra admins မရှိသေးပါ။\n"

        text += "\nအသစ်ပြောင်းမယ့် public admin username ပို့ပါ\nဥပမာ: <code>@newusername</code>"

        user_data[message.chat.id] = {"step": "change_admin_username"}
        safe_send_message(message.chat.id, text, reply_markup=step_back_menu())
    except Exception as e:
        logging.exception("change_admin_username_prompt failed: %s", e)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("step") == "change_admin_username", content_types=["text"])
def change_admin_username_input(message):
    try:
        username = safe_text(message.text)
        if not username.startswith("@"):
            safe_send_message(message.chat.id, "⚠️ Username must start with @", reply_markup=step_back_menu())
            return

        username_norm = normalize_username(username)
        if not username_norm:
            safe_send_message(message.chat.id, "⚠️ Invalid username.", reply_markup=step_back_menu())
            return

        old_username = get_setting("public_admin_username", DEFAULT_PUBLIC_ADMIN)
        set_setting("public_admin_username", with_at(username_norm))
        reset_user(message.chat.id)

        safe_send_message(
            message.chat.id,
            f"✅ Public admin username updated.\n\nOld: {old_username}\nNew: {with_at(username_norm)}",
            reply_markup=admin_home_markup(message)
        )
    except Exception as e:
        logging.exception("change_admin_username_input failed: %s", e)


# =========================================================
# ADMIN CALLBACKS
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
# BACK / CANCEL / FALLBACK
# =========================================================
@bot.message_handler(func=lambda m: m.text == "🔙 Back")
def back_handler(message):
    try:
        state = user_data.get(message.chat.id, {}).get("step", "")

        if is_admin_user(message):
            if state.startswith("manage_categories"):
                reset_user(message.chat.id)
                safe_send_message(message.chat.id, "🗂 Back to admin panel.", reply_markup=admin_home_markup(message))
                return

            if state.startswith("manage_packages"):
                reset_user(message.chat.id)
                safe_send_message(message.chat.id, "💎 Back to admin panel.", reply_markup=admin_home_markup(message))
                return

            if state in [
                "broadcast_wait_text",
                "change_payment_info",
                "change_admin_username",
                "search_order_wait_id",
                "add_admin_username",
                "remove_admin_username",
            ]:
                reset_user(message.chat.id)
                safe_send_message(message.chat.id, "🛠 Back to admin panel.", reply_markup=admin_home_markup(message))
                return

        if state == "choose_category":
            reset_user(message.chat.id)
            safe_send_message(message.chat.id, "🔙 Back to client panel.", reply_markup=client_menu())
        elif state == "game_id":
            user_data[message.chat.id] = {"step": "choose_category"}
            safe_send_message(message.chat.id, "🛒 Choose category again.", reply_markup=category_menu())
        elif state == "server_id":
            user_data[message.chat.id]["step"] = "game_id"
            safe_send_message(message.chat.id, "🎮 Game ID ပြန်ပို့ပါ။", reply_markup=step_back_menu())
        elif state in ["screenshot", "confirm_order"]:
            user_data[message.chat.id]["step"] = "server_id"
            safe_send_message(message.chat.id, "🖥 Server ID ပြန်ပို့ပါ။", reply_markup=step_back_menu())
        else:
            reset_user(message.chat.id)
            if is_admin_user(message):
                safe_send_message(message.chat.id, "🛠 Back to admin panel.", reply_markup=admin_home_markup(message))
            else:
                safe_send_message(message.chat.id, "👤 Back to client panel.", reply_markup=client_menu())
    except Exception as e:
        logging.exception("back_handler failed: %s", e)
        safe_send_message(message.chat.id, "❌ Back failed.")


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
        state = user_data.get(message.chat.id, {}).get("step", "")
        if state:
            safe_send_message(message.chat.id, "⚠️ လက်ရှိ step ကို finish လုပ်ပါ၊ Back သို့မဟုတ် Cancel လုပ်ပါ။", reply_markup=step_back_menu())
            return

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

            try:
                bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                pass

            try:
                bot.remove_webhook()
            except Exception:
                pass

            time.sleep(1)
            logging.info("Bot is running...")

            bot.infinity_polling(
                skip_pending=True,
                timeout=20,
                long_polling_timeout=20
            )

        except Exception as e:
            msg = str(e)
            logging.exception("Bot crashed: %s", e)

            if "409" in msg or "terminated by other getUpdates request" in msg:
                logging.warning("409 conflict detected. Retrying...")
                time.sleep(8)
            else:
                time.sleep(5)


if __name__ == "__main__":
    run_bot()
