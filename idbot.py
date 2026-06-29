import os, time, json, telebot, logging, re, requests, sys, sqlite3
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

# -------------------- DATABASE CONFIG --------------------
DB_TYPE = os.getenv("DB_TYPE", "mysql")
if DB_TYPE == "mysql":
    import pymysql
    DB_HOST = os.getenv("DB_HOST", "139.99.63.204")
    DB_NAME = os.getenv("DB_NAME", "keybotcp_Idbot")
    DB_USER = os.getenv("DB_USER", "keybotcp_Idbot")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "keybotcp_Idbot")
else:
    pass

ENABLE_CHANNEL_CHECK = True
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- SESSIONS ----------
broadcast_sessions = {}
admin_cmd_sessions = {}
settings_sessions = {}

def clear_user_sessions(user_id):
    for s in (broadcast_sessions, admin_cmd_sessions, settings_sessions):
        if user_id in s:
            del s[user_id]

# ---------- DATABASE MANAGER ----------
class UserData:
    def __init__(self):
        self.db_type = DB_TYPE
        if self.db_type == "mysql":
            self._connect_mysql()
            if self.db_type == "mysql":
                self._mysql_init()
                self._ensure_defaults()
            else:
                self._sqlite_init()
                self._ensure_defaults()
        else:
            self.db_path = "bot_data.db"
            self.sqlite_conn = sqlite3.connect(self.db_path)
            self._sqlite_init()
            self._ensure_defaults()

    def _connect_mysql(self):
        try:
            self.conn = pymysql.connect(
                host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
                database=DB_NAME, charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            logger.info(f"✅ MySQL connected to {DB_HOST}/{DB_NAME}")
        except Exception as e:
            logger.error(f"❌ MySQL connection error: {e}")
            logger.info("🔄 Falling back to SQLite...")
            self.db_type = "sqlite"
            self.db_path = "bot_data.db"
            self.sqlite_conn = sqlite3.connect(self.db_path)
            self.conn = None

    def _mysql_init(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS config (`key` VARCHAR(255) PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs (id INT AUTO_INCREMENT PRIMARY KEY, log_type VARCHAR(50), entry TEXT, timestamp INT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, verified TINYINT DEFAULT 0, blocked TINYINT DEFAULT 0, ai_mode TINYINT DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_channels (user_id BIGINT, channel_id BIGINT, channel_name VARCHAR(255), PRIMARY KEY (user_id, channel_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_groups (user_id BIGINT, group_id BIGINT, group_name VARCHAR(255), PRIMARY KEY (user_id, group_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS channel_owners (channel_id BIGINT PRIMARY KEY, owner_id BIGINT)''')
        self.conn.commit()
        c.close()

    def _sqlite_init(self):
        c = self.sqlite_conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, log_type TEXT, entry TEXT, timestamp INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, verified INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0, ai_mode INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_channels (user_id INTEGER, channel_id INTEGER, channel_name TEXT, PRIMARY KEY (user_id, channel_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_groups (user_id INTEGER, group_id INTEGER, group_name TEXT, PRIMARY KEY (user_id, group_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS channel_owners (channel_id INTEGER PRIMARY KEY, owner_id INTEGER)''')
        self.sqlite_conn.commit()
        c.close()

    def _ensure_defaults(self):
        # Insert default config only if table is empty
        if self._get_config_raw('bot_token') is None:
            defaults = {
                "admin_ids": '[8417161342]',
                "channel_link": 'https://t.me/+fkKWsFmum3BhNTE1',
                "channel_id": '-1002387714877',
                "bot_token": '8978422983:AAH-nbghHYz-IMbXPwiOqCYYEiffNbe20As',
                "ai_api_key": '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'
            }
            for k, v in defaults.items():
                self._set_config_raw(k, v)
            logger.info("✅ Default config inserted (table was empty)")

    def _get_config_raw(self, key):
        if self.db_type == "mysql":
            c = self.conn.cursor()
            c.execute("SELECT value FROM config WHERE `key`=%s", (key,))
            row = c.fetchone()
            c.close()
            return row['value'] if row else None
        else:
            c = self.sqlite_conn.cursor()
            c.execute("SELECT value FROM config WHERE key=?", (key,))
            row = c.fetchone()
            c.close()
            return row[0] if row else None

    def _set_config_raw(self, key, value):
        if self.db_type == "mysql":
            c = self.conn.cursor()
            c.execute("INSERT INTO config (`key`, value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE value=%s", (key, value, value))
            self.conn.commit()
            c.close()
        else:
            c = self.sqlite_conn.cursor()
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
            self.sqlite_conn.commit()
            c.close()

    def _execute(self, query, params=(), fetch=False, commit=False):
        if self.db_type == "mysql":
            c = self.conn.cursor()
            c.execute(query, params)
            if commit:
                self.conn.commit()
            if fetch:
                result = c.fetchall()
                c.close()
                return result
            c.close()
        else:
            c = self.sqlite_conn.cursor()
            c.execute(query, params)
            if commit:
                self.sqlite_conn.commit()
            if fetch:
                result = c.fetchall()
                c.close()
                return result
            c.close()

    def _ensure_user(self, user_id):
        if self.db_type == "mysql":
            self._execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,), commit=True)
        else:
            self._execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,), commit=True)

    def get_user_data(self, user_id):
        self._ensure_user(user_id)
        row = self._execute("SELECT verified, blocked, ai_mode FROM users WHERE user_id=%s" if self.db_type=="mysql" else "SELECT verified, blocked, ai_mode FROM users WHERE user_id=?", (user_id,), fetch=True)
        if row:
            if self.db_type == "mysql":
                verified, blocked, ai_mode = bool(row[0]['verified']), bool(row[0]['blocked']), bool(row[0]['ai_mode'])
            else:
                verified, blocked, ai_mode = bool(row[0][0]), bool(row[0][1]), bool(row[0][2])
        else:
            verified = blocked = ai_mode = False
        return {'verified': verified, 'blocked': blocked, 'ai_mode': ai_mode,
                'channels': self.get_channels(user_id), 'groups': self.get_groups(user_id)}

    def is_verified(self, user_id):
        row = self._execute("SELECT verified FROM users WHERE user_id=%s" if self.db_type=="mysql" else "SELECT verified FROM users WHERE user_id=?", (user_id,), fetch=True)
        if row:
            return bool(row[0]['verified']) if self.db_type == "mysql" else bool(row[0][0])
        return False

    def set_verified(self, user_id, status=True):
        self._ensure_user(user_id)
        self._execute("UPDATE users SET verified=%s WHERE user_id=%s" if self.db_type=="mysql" else "UPDATE users SET verified=? WHERE user_id=?", (1 if status else 0, user_id), commit=True)

    def is_blocked(self, user_id):
        row = self._execute("SELECT blocked FROM users WHERE user_id=%s" if self.db_type=="mysql" else "SELECT blocked FROM users WHERE user_id=?", (user_id,), fetch=True)
        if row:
            return bool(row[0]['blocked']) if self.db_type == "mysql" else bool(row[0][0])
        return False

    def block_user(self, user_id):
        self._ensure_user(user_id)
        self._execute("UPDATE users SET blocked=1 WHERE user_id=%s" if self.db_type=="mysql" else "UPDATE users SET blocked=1 WHERE user_id=?", (user_id,), commit=True)

    def unblock_user(self, user_id):
        self._ensure_user(user_id)
        self._execute("UPDATE users SET blocked=0 WHERE user_id=%s" if self.db_type=="mysql" else "UPDATE users SET blocked=0 WHERE user_id=?", (user_id,), commit=True)

    def set_ai_mode(self, user_id, status):
        self._ensure_user(user_id)
        self._execute("UPDATE users SET ai_mode=%s WHERE user_id=%s" if self.db_type=="mysql" else "UPDATE users SET ai_mode=? WHERE user_id=?", (1 if status else 0, user_id), commit=True)

    def get_ai_mode(self, user_id):
        row = self._execute("SELECT ai_mode FROM users WHERE user_id=%s" if self.db_type=="mysql" else "SELECT ai_mode FROM users WHERE user_id=?", (user_id,), fetch=True)
        if row:
            return bool(row[0]['ai_mode']) if self.db_type == "mysql" else bool(row[0][0])
        return False

    def get_all_users(self):
        rows = self._execute("SELECT user_id FROM users", fetch=True)
        if self.db_type == "mysql":
            return [str(r['user_id']) for r in rows]
        else:
            return [str(r[0]) for r in rows]

    def get_admins(self):
        raw = self._get_config_raw('admin_ids')
        if raw:
            try:
                return json.loads(raw)
            except:
                return []
        return []

    def add_admin(self, user_id):
        admins = self.get_admins()
        if user_id not in admins:
            admins.append(user_id)
            self._set_config_raw('admin_ids', json.dumps(admins))
            return True
        return False

    def remove_admin(self, user_id):
        admins = self.get_admins()
        if user_id in admins:
            admins.remove(user_id)
            self._set_config_raw('admin_ids', json.dumps(admins))
            return True
        return False

    def is_admin(self, user_id):
        return user_id in self.get_admins()

    def get_channels(self, user_id):
        rows = self._execute("SELECT channel_id, channel_name FROM user_channels WHERE user_id=%s" if self.db_type=="mysql" else "SELECT channel_id, channel_name FROM user_channels WHERE user_id=?", (user_id,), fetch=True)
        if self.db_type == "mysql":
            return [{'id': r['channel_id'], 'name': r['channel_name']} for r in rows]
        else:
            return [{'id': r[0], 'name': r[1]} for r in rows]

    def add_channel(self, user_id, channel_id, channel_name):
        if self.db_type == "mysql":
            self._execute("INSERT INTO user_channels (user_id, channel_id, channel_name) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE channel_name=%s", (user_id, channel_id, channel_name, channel_name), commit=True)
        else:
            self._execute("INSERT OR REPLACE INTO user_channels (user_id, channel_id, channel_name) VALUES (?, ?, ?)", (user_id, channel_id, channel_name), commit=True)
        return True

    def remove_channel(self, user_id, channel_id):
        self._execute("DELETE FROM user_channels WHERE user_id=%s AND channel_id=%s" if self.db_type=="mysql" else "DELETE FROM user_channels WHERE user_id=? AND channel_id=?", (user_id, channel_id), commit=True)
        return True

    def get_groups(self, user_id):
        rows = self._execute("SELECT group_id, group_name FROM user_groups WHERE user_id=%s" if self.db_type=="mysql" else "SELECT group_id, group_name FROM user_groups WHERE user_id=?", (user_id,), fetch=True)
        if self.db_type == "mysql":
            return [{'id': r['group_id'], 'name': r['group_name']} for r in rows]
        else:
            return [{'id': r[0], 'name': r[1]} for r in rows]

    def add_group(self, user_id, group_id, group_name):
        if self.db_type == "mysql":
            self._execute("INSERT INTO user_groups (user_id, group_id, group_name) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE group_name=%s", (user_id, group_id, group_name, group_name), commit=True)
        else:
            self._execute("INSERT OR REPLACE INTO user_groups (user_id, group_id, group_name) VALUES (?, ?, ?)", (user_id, group_id, group_name), commit=True)
        return True

    def remove_group(self, user_id, group_id):
        self._execute("DELETE FROM user_groups WHERE user_id=%s AND group_id=%s" if self.db_type=="mysql" else "DELETE FROM user_groups WHERE user_id=? AND group_id=?", (user_id, group_id), commit=True)
        return True

    def get_channel_owner(self, channel_id):
        row = self._execute("SELECT owner_id FROM channel_owners WHERE channel_id=%s" if self.db_type=="mysql" else "SELECT owner_id FROM channel_owners WHERE channel_id=?", (channel_id,), fetch=True)
        if row:
            return row[0]['owner_id'] if self.db_type == "mysql" else row[0][0]
        return None

    def set_channel_owner(self, channel_id, user_id):
        if self.db_type == "mysql":
            self._execute("INSERT INTO channel_owners (channel_id, owner_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE owner_id=%s", (channel_id, user_id, user_id), commit=True)
        else:
            self._execute("INSERT OR REPLACE INTO channel_owners (channel_id, owner_id) VALUES (?, ?)", (channel_id, user_id), commit=True)

    def add_log(self, log_type, entry):
        self._execute("INSERT INTO logs (log_type, entry, timestamp) VALUES (%s, %s, %s)" if self.db_type=="mysql" else "INSERT INTO logs (log_type, entry, timestamp) VALUES (?, ?, ?)", (log_type, entry, int(time.time())), commit=True)

    def get_logs(self, log_type, limit=50):
        rows = self._execute("SELECT entry, timestamp FROM logs WHERE log_type=%s ORDER BY timestamp DESC LIMIT %s" if self.db_type=="mysql" else "SELECT entry, timestamp FROM logs WHERE log_type=? ORDER BY timestamp DESC LIMIT ?", (log_type, limit), fetch=True)
        logs = []
        for row in rows:
            if self.db_type == "mysql":
                entry, ts = row['entry'], row['timestamp']
            else:
                entry, ts = row[0], row[1]
            logs.append(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))} - {entry}")
        return logs

    def clear_logs(self, log_type):
        self._execute("DELETE FROM logs WHERE log_type=%s" if self.db_type=="mysql" else "DELETE FROM logs WHERE log_type=?", (log_type,), commit=True)

    def get_config(self, key=None):
        if key:
            raw = self._get_config_raw(key)
            if raw is not None:
                try:
                    return json.loads(raw)
                except:
                    return raw
            return None
        else:
            if self.db_type == "mysql":
                c = self.conn.cursor()
                c.execute("SELECT `key`, value FROM config")
                rows = c.fetchall()
                c.close()
            else:
                c = self.sqlite_conn.cursor()
                c.execute("SELECT key, value FROM config")
                rows = c.fetchall()
                c.close()
            config = {}
            for row in rows:
                if self.db_type == "mysql":
                    k, v = row['key'], row['value']
                else:
                    k, v = row[0], row[1]
                try:
                    config[k] = json.loads(v)
                except:
                    config[k] = v
            return config

    def set_config(self, key, value):
        if isinstance(value, (list, dict)):
            val_str = json.dumps(value)
        else:
            val_str = str(value)
        self._set_config_raw(key, val_str)

db = UserData()

# ---------- Bot Init ----------
def get_bot():
    token = db.get_config('bot_token')
    if token is None:
        logger.error("❌ BOT_TOKEN not found in database! Please insert config first.")
        sys.exit(1)
    return telebot.TeleBot(token, parse_mode="Markdown")

bot = get_bot()

def is_admin(user_id):
    return db.is_admin(user_id)

def check_membership(user_id):
    if not ENABLE_CHANNEL_CHECK or is_admin(user_id) or db.is_verified(user_id):
        return True
    cid = db.get_config('channel_id')
    if not cid:
        return True
    try:
        member = bot.get_chat_member(cid, user_id)
        return member.status not in ('left', 'kicked', 'banned')
    except:
        return False

def send_join_prompt(chat_id):
    link = db.get_config('channel_link')
    if not link:
        bot.send_message(chat_id, "⚠️ Channel link not configured. Contact admin.")
        return
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📢 Join Channel", url=link))
    kb.row(InlineKeyboardButton("✅ I have joined", callback_data="check_join"))
    bot.send_message(chat_id, "⚠️ **You must join our official channel to use this bot!**\n\n1. Click the button below to join.\n2. After joining, click 'I have joined'.", reply_markup=kb, parse_mode='Markdown')

def restart_bot():
    logger.info("Restarting bot...")
    time.sleep(1)
    os.execv(sys.executable, ['python'] + sys.argv)

def deactivate_ai_mode(user_id):
    db.set_ai_mode(user_id, False)

def show_loading(chat_id):
    msg = bot.send_message(chat_id, "🌺 Loading: [▱▱▱▱▱▱▱▱▱▱] 0%")
    steps = [
        ("🌼 [▰▱▱▱▱▱▱▱▱▱] 10%", 0.1),
        ("🌻 [▰▰▱▱▱▱▱▱▱▱] 20%", 0.1),
        ("🌸 [▰▰▰▱▱▱▱▱▱▱] 30%", 0.1),
        ("🌹 [▰▰▰▰▱▱▱▱▱▱] 40%", 0.1),
        ("🍁 [▰▰▰▰▰▱▱▱▱▱] 50%", 0.1),
        ("🌿 [▰▰▰▰▰▰▱▱▱▱] 60%", 0.1),
        ("🌳 [▰▰▰▰▰▰▰▱▱▱] 70%", 0.1),
        ("🌲 [▰▰▰▰▰▰▰▰▱▱] 80%", 0.1),
        ("🪷 [▰▰▰▰▰▰▰▰▰▱] 90%", 0.1),
        ("✅ [▰▰▰▰▰▰▰▰▰▰] 100%", 0.1)
    ]
    for t, d in steps:
        time.sleep(d)
        try:
            bot.edit_message_text(f"🌺 Loading: {t}", chat_id, msg.message_id)
        except:
            pass
    return msg

def delete_loading(chat_id, msg_obj):
    try:
        bot.delete_message(chat_id, msg_obj.message_id)
    except:
        pass

def get_user_display_name(uid):
    try:
        chat = bot.get_chat(uid)
        name = chat.first_name or "Unknown"
        uname = f"@{chat.username}" if chat.username else ""
        return f"{name} {uname}".strip()
    except:
        return f"User {uid}"

# ---------- KEYBOARDS ----------
def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🚀GET MY ID", "📢 GET CHANNEL ID")
    kb.row("👥 GET GROUP ID", "🎃USER HELP")
    return kb

def admin_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🚀GET MY ID", "📢 GET CHANNEL ID")
    kb.row("👥 GET GROUP ID", "🎃USER HELP")
    kb.row("🎭 START ADMIN ACCESS")
    return kb

def help_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🚀GET MY ID", "📢 GET CHANNEL ID")
    kb.row("👥 GET GROUP ID", "🪄 AI ASSISTANT")
    kb.row("🏠 MAIN MENU")
    return kb

def ai_mode_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔙 Exit AI Mode")
    return kb

def admin_main_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🐦‍🔥managebot", "👥manageusers")
    kb.row("💬broadcast", "📖 Admin Help")
    kb.row("🏠 MAIN MENU")
    return kb

def manage_bot_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💠ChannelLink", "🍶botApi")
    kb.row("🦞Aiapi", "🍃back")
    return kb

def manage_users_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🛸totalusers", "🚫blocksdusers")
    kb.row("🎃activeusers", "🛸addadmin")
    kb.row("🍃back")
    return kb

def broadcast_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🧳broadcastlog", "🍃back")
    return kb

def add_admin_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🎀admins", "🍃back")
    return kb

def admin_help_reply_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.row("💨ChannelLink", "🍶BotToken")
    kb.row("🦞AIKey", "🔍SearchUser", "🗑️DeleteAdmin")
    kb.row("➕AddAdmin", "🚫BlockUser", "✅UnblockUser")
    kb.row("🧹ClearLogs", "📢Broadcast")
    kb.row("🍃back")
    return kb

def wizard_input_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.row("❌ Cancel", "🍃back")
    return kb

def wizard_confirm_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.row("✅ Confirm", "❌ Cancel")
    return kb

def wizard_search_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.row("🍃back")
    return kb

def settings_confirm_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("✅ Done", "❌ Cancel", "🍃back")
    return kb

def broadcast_confirm_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.row("✅ Send Now", "❌ Cancel")
    return kb

# ---------- USER LIST ----------
def build_user_list_keyboard(users, page, menu_type, per_page=10):
    start = (page - 1) * per_page
    end = start + per_page
    list_users = users[start:end]
    if not list_users:
        return "No users found.", None
    total = (len(users) + per_page - 1) // per_page
    kb = InlineKeyboardMarkup(row_width=2)
    for uid in list_users:
        uid_int = int(uid)
        display = get_user_display_name(uid_int)
        kb.add(InlineKeyboardButton(f"ℹ️ {display}", callback_data=f"user_info_{uid_int}"))
        if menu_type in ('total', 'active'):
            if not db.is_blocked(uid_int):
                kb.add(InlineKeyboardButton("🚫 Block", callback_data=f"block_from_list_{uid_int}_{menu_type}_{page}"))
            else:
                kb.add(InlineKeyboardButton("🔓 Unblock", callback_data=f"unblock_from_list_{uid_int}_{menu_type}_{page}"))
        elif menu_type == 'blocked':
            kb.add(InlineKeyboardButton("✅ Unblock", callback_data=f"unblock_from_list_{uid_int}_{menu_type}_{page}"))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"admin_{menu_type}_page_{page-1}"))
    if page < total:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"admin_{menu_type}_page_{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton("🍃back", callback_data="admin_pagination_back"))
    text = f"📋 *User List (Page {page}/{total})*\n━━━━━━━━━━━━━━━━━━\n"
    for idx, uid in enumerate(list_users, start=start + 1):
        uid_int = int(uid)
        display = get_user_display_name(uid_int)
        status = "🔒 Blocked" if db.is_blocked(uid_int) else "✅ Active"
        text += f"{idx}. `{uid}` {display}\n   {status}\n"
    return text, kb

def send_user_list(chat_id, menu_type, page, edit_msg_id=None):
    if menu_type == 'total':
        users = db.get_all_users()
        title = "users info"
        action = "total user"
    elif menu_type == 'blocked':
        users = [u for u in db.get_all_users() if db.is_blocked(int(u))]
        title = "blocked users"
        action = "block user"
    elif menu_type == 'active':
        users = [u for u in db.get_all_users() if not db.is_blocked(int(u))]
        title = "active users"
        action = "active user"
    else:
        return
    if not users:
        text = f"No {action} found."
        if edit_msg_id:
            try:
                bot.edit_message_text(text, chat_id, edit_msg_id, reply_markup=manage_users_reply_keyboard())
            except:
                bot.send_message(chat_id, text, reply_markup=manage_users_reply_keyboard())
        else:
            bot.send_message(chat_id, text, reply_markup=manage_users_reply_keyboard())
        return
    text, kb = build_user_list_keyboard(users, page, menu_type)
    header = f"👋Hii admin welcome back.\n💠here is the {title}.\n🌶️{action}: {len(users)}\n\n"
    full = header + text
    if edit_msg_id:
        try:
            bot.edit_message_text(full, chat_id, edit_msg_id, parse_mode='Markdown', reply_markup=kb)
        except:
            bot.send_message(chat_id, full, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.send_message(chat_id, full, parse_mode='Markdown', reply_markup=kb)

# ---------- CHAT MEMBER ----------
@bot.chat_member_handler()
def handle_chat_member(update):
    chat = update.chat
    from_user = update.from_user
    new = update.new_chat_member
    if chat.type in ('channel', 'group', 'supergroup') and new.status in ('member', 'administrator'):
        if from_user and not from_user.is_bot:
            db.set_channel_owner(chat.id, from_user.id)
            logger.info(f"Bot added to {chat.type} {chat.id} by user {from_user.id}")

# ---------- COMMANDS ----------
@bot.message_handler(commands=['start'])
@bot.channel_post_handler(commands=['start'])
def start_command(m):
    uid = m.from_user.id if m.from_user else None
    if not uid:
        bot.send_message(m.chat.id, "👋 Hello! Use commands like /getmyid in a private chat with me.", parse_mode="Markdown")
        return
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    if db.is_blocked(uid):
        bot.send_message(m.chat.id, "🚫 You are blocked from using this bot. Contact @OWNERHIMANSHU.")
        return
    if not check_membership(uid):
        send_join_prompt(m.chat.id)
        return
    db.set_verified(uid, True)
    name = m.chat.title if m.chat.type == "channel" else m.from_user.first_name
    text = (f"🗽{name} welcome back to ID Bot! 👋\n\n"
            f"🔍 *Chat ID Finder Bot* 🧞\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🚀 /getmyid – get your chat ID\n"
            f"🚀 /Channelid – For channel ID\n"
            f"👥 /groupid – For Group ID\n"
            f"🚀 /help – Manual\n\n"
            f"🛸 add me on your Group/channel & ❤️‍🔥 run commands to get your IDs 🦹 !")
    if m.chat.type == "channel":
        bot.send_message(m.chat.id, text, parse_mode="Markdown")
    else:
        kb = admin_reply_keyboard() if is_admin(uid) else main_keyboard()
        bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['help'])
@bot.channel_post_handler(commands=['help'])
def help_command(m):
    uid = m.from_user.id if m.from_user else None
    if uid:
        clear_user_sessions(uid)
        deactivate_ai_mode(uid)
    name = m.chat.title if m.chat.type == "channel" else m.from_user.first_name
    text = (f"✨ *HELP* ✨\n"
            f"════════════════\n"
            f"👋 Hey {name}!\n\n"
            f"📌 *COMMANDS*\n"
            f"🚀 /getmyid → Your ID\n"
            f"📢 /Channelid → Channel ID\n"
            f"👥 /groupid → Group ID\n"
            f"🪄 /helpAi → AI Assistant\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🪄 *AI ASSISTANT* 🧠\n"
            f"━━━━━━━━━━━━━━\n"
            f"✅ Enable AI mode with button below\n"
            f"💬 I answer everything with a smile 😊\n"
            f"⚡ Powered by Groq\n\n"
            f"💡 Add me to group/channel 🚀\n"
            f"🔗 Dev: @OWNERHIMANSHU\n"
            f"🏠 /start for buttons\n"
            f"════════════════\n"
            f"🎉 Happy Hunting! 🎉")
    if m.chat.type == "channel":
        bot.send_message(m.chat.id, text, parse_mode="Markdown")
    else:
        bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=help_keyboard())

@bot.message_handler(commands=['helpAi'])
def help_ai_command(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    if db.is_blocked(uid):
        bot.send_message(m.chat.id, "🚫 You are blocked.")
        return
    mode = db.get_ai_mode(uid)
    db.set_ai_mode(uid, not mode)
    if not mode:
        bot.send_message(m.chat.id,
                         "🪄 *AI Mode Activated!*\n\nNow I'll reply to ALL your messages with AI. 🎉\nAsk me anything – I'm here to help! 😊\nPress '🔙 Exit AI Mode' to turn off.",
                         parse_mode='Markdown', reply_markup=ai_mode_keyboard())
    else:
        bot.send_message(m.chat.id,
                         "🔙 *AI Mode Deactivated.*\nNow I'll reply only to commands. 🤖💤",
                         parse_mode='Markdown', reply_markup=help_keyboard())

# ---------- START MENU BUTTONS ----------
@bot.message_handler(func=lambda m: m.text == "🚀GET MY ID")
def get_my_id_btn(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    get_my_id(m)

@bot.message_handler(func=lambda m: m.text == "📢 GET CHANNEL ID")
def channel_id_btn(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    channel_id_command(m)

@bot.message_handler(func=lambda m: m.text == "👥 GET GROUP ID")
def group_id_btn(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    group_id_command(m)

@bot.message_handler(func=lambda m: m.text == "🎃USER HELP")
def user_help_btn(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    help_command(m)

@bot.message_handler(func=lambda m: m.text == "🏠 MAIN MENU")
def main_menu_btn(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    start_command(m)

@bot.message_handler(func=lambda m: m.text == "🎭 START ADMIN ACCESS")
def admin_access_btn(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    if not is_admin(uid):
        bot.reply_to(m, "⛔ Unauthorized.")
        return
    load = show_loading(m.chat.id)
    delete_loading(m.chat.id, load)
    bot.send_message(m.chat.id,
                     f"🥀 Hello, *{m.from_user.first_name}* welcome to admin👋\n🪎You now get admin access.\n🪎with premium features 💨💨",
                     parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "🪄 AI ASSISTANT")
def ai_toggle(m):
    uid = m.from_user.id
    clear_user_sessions(uid)
    if db.is_blocked(uid):
        bot.send_message(m.chat.id, "🚫 You are blocked.")
        return
    mode = db.get_ai_mode(uid)
    db.set_ai_mode(uid, not mode)
    if not mode:
        bot.send_message(m.chat.id,
                         "🪄 *AI Mode Activated!*\n\nNow I'll reply to ALL your messages with AI. 🎉\nAsk me anything – I'm here to help! 😊\nPress '🔙 Exit AI Mode' to turn off.",
                         parse_mode='Markdown', reply_markup=ai_mode_keyboard())
    else:
        bot.send_message(m.chat.id,
                         "🔙 *AI Mode Deactivated.*\nNow I'll reply only to commands. 🤖💤",
                         parse_mode='Markdown', reply_markup=help_keyboard())

# ---------- GET MY ID ----------
@bot.message_handler(commands=['getmyid'])
@bot.channel_post_handler(commands=['getmyid'])
def get_my_id(m):
    if m.from_user:
        uid = m.from_user.id
        clear_user_sessions(uid)
        deactivate_ai_mode(uid)
    if db.is_blocked(m.from_user.id):
        bot.send_message(m.chat.id, "🚫 You are blocked.")
        return
    if m.chat.type == "channel":
        cid = m.chat.id
        name = m.chat.title or "Channel"
    else:
        cid = m.from_user.id
        name = m.from_user.first_name
    load = show_loading(m.chat.id)
    delete_loading(m.chat.id, load)
    final = (f"🐦‍🔥 *CHAT ID FOUND* 🌹🌹\n"
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             f"👋 Hello *{name}*!\n"
             f"📌 Your Chat ID: `{cid}`\n"
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             f"🥀 *DEVELOPER:* @OWNERHIMANSHU 💨")
    if m.chat.type == "channel":
        bot.send_message(m.chat.id, final, parse_mode="Markdown")
    else:
        kb = admin_reply_keyboard() if is_admin(m.from_user.id) else main_keyboard()
        bot.send_message(m.chat.id, final, parse_mode="Markdown", reply_markup=kb)

# ---------- CHANNEL ID ----------
@bot.message_handler(commands=['Channelid'])
@bot.channel_post_handler(commands=['Channelid'])
def channel_id_command(m):
    if m.from_user:
        uid = m.from_user.id
        clear_user_sessions(uid)
        deactivate_ai_mode(uid)
    if db.is_blocked(m.from_user.id):
        bot.send_message(m.chat.id, "🚫 You are blocked.")
        return
    if m.chat.type == "channel":
        bot.send_message(m.chat.id, f"📌 This channel's ID: `{m.chat.id}`", parse_mode="Markdown")
        return
    user_name = m.from_user.first_name
    text = (f"🗽 Hello {user_name}! 👋\n"
            f"🔍 Chat ID Finder Bot 🧞\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🐦‍🔥 To get Channel ID 💨\n"
            f"🚀 add me no channel addmin\n"
            f"🛸 Use `/* or /Csave` in channel to auto-save\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🛸 Get your channel ID now! 🎭🪎🪎")
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("💠 ADD TO CHANNEL", url="https://t.me/TeligramidBot?startchannel&admin=post_messages"))
    kb.row(InlineKeyboardButton("🍂 MY CHANNELS", callback_data="find_channels"))
    bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=kb)

# ---------- GROUP ID ----------
@bot.message_handler(commands=['groupid'])
@bot.channel_post_handler(commands=['groupid'])
def group_id_command(m):
    if m.from_user:
        uid = m.from_user.id
        clear_user_sessions(uid)
        deactivate_ai_mode(uid)
    if db.is_blocked(m.from_user.id):
        bot.send_message(m.chat.id, "🚫 You are blocked.")
        return
    if m.chat.type in ("group", "supergroup"):
        gid = m.chat.id
        gname = m.chat.title or "Unknown Group"
        db.add_group(m.from_user.id, gid, gname)
        bot.send_message(m.chat.id, f"📌 This group's ID: `{gid}`\n\n✅ Group saved for you.", parse_mode="Markdown")
        return
    user_name = m.from_user.first_name
    text = (f"🗽 Hello {user_name}! 👋\n"
            f"🔍 Chat ID Finder Bot 🧞\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🐦‍🔥 To get Group ID 💨\n"
            f"🚀 add me into your group\n"
            f"🛸 Use `/** or /Gsave` in group to auto-save\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🛸 Get your group ID now! 🎭🪎🪎")
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("💠 ADD TO GROUP", url="https://t.me/TeligramidBot?startgroup&admin=post_messages"))
    kb.row(InlineKeyboardButton("🍂 MY GROUPS", callback_data="find_groups"))
    bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=kb)

# ---------- SAVE CHANNEL/GROUP ----------
@bot.message_handler(func=lambda message: message.text in ('/*', '/Csave', '/**', '/Gsave'))
@bot.channel_post_handler(func=lambda message: message.text in ('/*', '/Csave', '/**', '/Gsave'))
def save_group_or_channel(m):
    ctype = m.chat.type
    if ctype not in ("channel") and db.is_blocked(m.from_user.id):
        bot.reply_to(m, "🚫 You are blocked.")
        return
    if ctype in ("group", "supergroup"):
        gid = m.chat.id
        gname = m.chat.title or "Unknown Group"
        user_id = m.from_user.id
        db.add_group(user_id, gid, gname)
        load = show_loading(m.chat.id)
        delete_loading(m.chat.id, load)
        final = (f"🐦‍🔥 *GROUP ID FOUND* 🌹🌹\n"
                 f"━━━━━━━━━━━━━━━━━━━━━\n"
                 f"✅ *Saved successfully!*\n"
                 f"👋 Hello *{m.from_user.first_name}*!\n"
                 f"📌 GROUP ID: `{gid}`\n"
                 f"━━━━━━━━━━━━━━━━━━━━━\n"
                 f"🥀 *DEVLOPER:* @OWNERHIMANSHU 💨")
        bot.reply_to(m, final, parse_mode="Markdown")
    elif ctype == "channel":
        cid = m.chat.id
        cname = m.chat.title or "Unknown Channel"
        owner = db.get_channel_owner(cid)
        if not owner:
            owner = m.from_user.id if m.from_user else 0
            db.set_channel_owner(cid, owner)
        db.add_channel(owner, cid, cname)
        final = (f"🐦‍🔥 *CHANNEL ID FOUND* 🌹🌹\n"
                 f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                 f"✅ *Saved successfully!*\n"
                 f"👋 Hello Owner (ID: `{owner}`)!\n"
                 f"📌 CHANNEL ID: `{cid}`\n"
                 f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                 f"🥀 *DEVLOPER:* @OWNERHIMANSHU 💨")
        bot.reply_to(m, final, parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ This command only works in groups or channels.", parse_mode="Markdown")

# ---------- BROADCAST ----------
@bot.message_handler(func=lambda m: m.text == "💬broadcast")
def admin_broadcast_start(m):
    if not is_admin(m.from_user.id):
        return
    uid = m.from_user.id
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    broadcast_sessions[uid] = {'stage': 'text', 'text': None, 'media': None, 'media_type': None, 'buttons': [],
                               'prompt_msg_id': None}
    send_broadcast_step(m.chat.id, uid)

def send_broadcast_step(chat_id, uid):
    sess = broadcast_sessions.get(uid)
    if not sess:
        return
    stage = sess['stage']
    if stage == 'text':
        text = "📢 *Broadcast Wizard - Step 1/3*\n\nSend the text message you want to broadcast.\nYou can also use the buttons below."
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        kb.row("⏭️ Skip Text", "❌ Cancel")
        kb.row("🍃back")
    elif stage == 'media':
        text = "📎 *Broadcast Wizard - Step 2/3*\n\nSend a photo, video, or document (file) if you want to include media.\nYou can also skip media."
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        kb.row("⏭️ Skip Media", "❌ Cancel")
        kb.row("🍃back")
    elif stage == 'button':
        text = "🔗 *Broadcast Wizard - Step 3/3*\n\nAdd inline keyboard buttons (URL buttons).\nSend each button as:\n`label|url` (one per line).\nWhen done, click 'Done'.\nYou can also skip adding buttons."
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        kb.row("⏭️ Skip Buttons", "✅ Done", "❌ Cancel")
        kb.row("🍃back")
    else:
        return
    if sess.get('prompt_msg_id'):
        try:
            bot.delete_message(chat_id, sess['prompt_msg_id'])
        except:
            pass
    sent = bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=kb)
    sess['prompt_msg_id'] = sent.message_id

@bot.message_handler(func=lambda m: m.text in ("⏭️ Skip Text", "⏭️ Skip Media", "⏭️ Skip Buttons", "✅ Done", "❌ Cancel", "🍃back"))
def broadcast_btn_handlers(m):
    uid = m.from_user.id
    if uid not in broadcast_sessions:
        return
    sess = broadcast_sessions[uid]
    action = m.text
    if action in ("🍃back", "❌ Cancel"):
        del broadcast_sessions[uid]
        try:
            bot.delete_message(m.chat.id, sess.get('prompt_msg_id', 0))
        except:
            pass
        bot.send_message(m.chat.id,
                         f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                         parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return
    if action == "⏭️ Skip Text":
        sess['text'] = ""
        sess['stage'] = 'media'
        send_broadcast_step(m.chat.id, uid)
        return
    if action == "⏭️ Skip Media":
        sess['media'] = None
        sess['media_type'] = None
        sess['stage'] = 'button'
        send_broadcast_step(m.chat.id, uid)
        return
    if action == "⏭️ Skip Buttons":
        sess['buttons'] = []
        send_broadcast_preview(m)
        return
    if action == "✅ Done":
        if not sess['buttons']:
            bot.reply_to(m, "❌ No buttons added. Use 'Skip Buttons' or add some.")
            return
        send_broadcast_preview(m)
        return

@bot.message_handler(func=lambda m: m.from_user.id in broadcast_sessions and broadcast_sessions[m.from_user.id]['stage'] == 'text' and not m.text.startswith(('⏭️', '❌', '🍃back')))
def broadcast_text_handler(m):
    uid = m.from_user.id
    sess = broadcast_sessions[uid]
    if m.text:
        sess['text'] = m.text
        sess['stage'] = 'media'
        send_broadcast_step(m.chat.id, uid)

@bot.message_handler(content_types=['photo', 'video', 'document', 'audio'],
                     func=lambda m: m.from_user.id in broadcast_sessions and broadcast_sessions[m.from_user.id]['stage'] == 'media')
def broadcast_media_handler(m):
    uid = m.from_user.id
    sess = broadcast_sessions[uid]
    if m.photo:
        fid = m.photo[-1].file_id
        typ = 'photo'
    elif m.video:
        fid = m.video.file_id
        typ = 'video'
    elif m.document:
        fid = m.document.file_id
        typ = 'document'
    elif m.audio:
        fid = m.audio.file_id
        typ = 'audio'
    else:
        bot.reply_to(m, "Unsupported media type. Send photo/video/document or click Skip Media.")
        return
    sess['media'] = fid
    sess['media_type'] = typ
    sess['stage'] = 'button'
    send_broadcast_step(m.chat.id, uid)

@bot.message_handler(func=lambda m: m.from_user.id in broadcast_sessions and broadcast_sessions[m.from_user.id]['stage'] == 'button' and not m.text.startswith(('⏭️', '✅', '❌', '🍃back')))
def broadcast_btn_input(m):
    uid = m.from_user.id
    sess = broadcast_sessions[uid]
    lines = m.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            parts = line.split('|', 1)
            label = parts[0].strip()
            url = parts[1].strip()
            if label and url:
                sess['buttons'].append((label, url))
                added += 1
    if added:
        bot.reply_to(m, f"✅ Added {added} button(s). Send more, or click 'Done' when finished.")
    else:
        bot.reply_to(m, "❌ Invalid format. Use `label|url` per line.")

def send_broadcast_preview(m):
    uid = m.from_user.id
    sess = broadcast_sessions.get(uid)
    if not sess:
        return
    text = sess['text'] or "*(No text)*"
    media = sess['media']
    media_type = sess['media_type']
    buttons = sess['buttons']
    kb = None
    if buttons:
        kb = InlineKeyboardMarkup(row_width=2)
        for label, url in buttons:
            kb.add(InlineKeyboardButton(label, url=url))
    preview_text = f"📢 *Broadcast Preview*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n{text}"
    try:
        if media:
            if media_type == 'photo':
                bot.send_photo(m.chat.id, media, caption=preview_text, parse_mode='Markdown', reply_markup=kb)
            elif media_type == 'video':
                bot.send_video(m.chat.id, media, caption=preview_text, parse_mode='Markdown', reply_markup=kb)
            elif media_type == 'document':
                bot.send_document(m.chat.id, media, caption=preview_text, parse_mode='Markdown', reply_markup=kb)
            elif media_type == 'audio':
                bot.send_audio(m.chat.id, media, caption=preview_text, parse_mode='Markdown', reply_markup=kb)
        else:
            bot.send_message(m.chat.id, preview_text, parse_mode='Markdown', reply_markup=kb)
        bot.send_message(m.chat.id, "Do you want to send this broadcast to all users?",
                         reply_markup=broadcast_confirm_keyboard())
    except Exception as e:
        bot.reply_to(m, f"❌ Error in preview: {e}")
        del broadcast_sessions[uid]

@bot.message_handler(func=lambda m: m.text == "✅ Send Now")
def broadcast_send_now(m):
    uid = m.from_user.id
    if uid not in broadcast_sessions:
        return
    sess = broadcast_sessions[uid]
    text = sess['text']
    media = sess['media']
    media_type = sess['media_type']
    buttons = sess['buttons']
    kb = None
    if buttons:
        kb = InlineKeyboardMarkup(row_width=2)
        for label, url in buttons:
            kb.add(InlineKeyboardButton(label, url=url))
    users = db.get_all_users()
    sent = 0
    load = show_loading(m.chat.id)
    for uid_str in users:
        try:
            if media:
                if media_type == 'photo':
                    bot.send_photo(int(uid_str), media, caption=text, parse_mode='Markdown', reply_markup=kb)
                elif media_type == 'video':
                    bot.send_video(int(uid_str), media, caption=text, parse_mode='Markdown', reply_markup=kb)
                elif media_type == 'document':
                    bot.send_document(int(uid_str), media, caption=text, parse_mode='Markdown', reply_markup=kb)
                elif media_type == 'audio':
                    bot.send_audio(int(uid_str), media, caption=text, parse_mode='Markdown', reply_markup=kb)
            else:
                bot.send_message(int(uid_str), text, parse_mode='Markdown', reply_markup=kb)
            sent += 1
            time.sleep(0.05)
        except:
            pass
    delete_loading(m.chat.id, load)
    media_info = media_type if media else "None"
    button_info = f"{len(buttons)} buttons" if buttons else "No buttons"
    log_entry = f"Sent to {sent} users | Text: {text[:30]}... | Media: {media_info} | Buttons: {button_info}"
    db.add_log('broadcast', log_entry)
    bot.reply_to(m, f"✅ Broadcast sent to {sent} users.")
    del broadcast_sessions[uid]
    bot.send_message(m.chat.id,
                     f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                     parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "❌ Cancel" and m.from_user.id in broadcast_sessions)
def broadcast_cancel(m):
    uid = m.from_user.id
    if uid in broadcast_sessions:
        del broadcast_sessions[uid]
    bot.reply_to(m, "❌ Broadcast cancelled.")
    bot.send_message(m.chat.id,
                     f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                     parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())

# ---------- ADMIN MENU ----------
@bot.message_handler(func=lambda m: m.text == "🐦‍🔥managebot")
def admin_manage_bot(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    bot.send_message(m.chat.id,
                     "🧞welcome back to bot management system.\n🎭Select management button's🥀\n💬Owner Contact : @OWNERHIMANSHU",
                     parse_mode='Markdown', reply_markup=manage_bot_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "👥manageusers")
def admin_manage_users(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    bot.send_message(m.chat.id,
                     "🧞welcome back to user management system.\n🎭Select management button's🥀\n💬Owner Contact : @OWNERHIMANSHU",
                     parse_mode='Markdown', reply_markup=manage_users_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "📖 Admin Help")
def admin_help_btn(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    admin_help_command(m)

@bot.message_handler(commands=['adminhelp'])
def admin_help_command(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "⛔ Unauthorized.")
        return
    text = ("👑 *Admin Help*\n"
            "━━━━━━━━━━━━━━━\n"
            "Click a button below to run a command.")
    bot.send_message(m.chat.id, text, parse_mode='Markdown', reply_markup=admin_help_reply_keyboard())

# ---------- ADMIN HELP BUTTONS ----------
@bot.message_handler(func=lambda m: m.text in (
"💨ChannelLink", "🍶BotToken", "🦞AIKey", "🔍SearchUser", "🗑️DeleteAdmin", "➕AddAdmin", "🚫BlockUser", "✅UnblockUser",
"🧹ClearLogs", "📢Broadcast", "🍃back"))
def admin_help_click(m):
    uid = m.from_user.id
    if not is_admin(uid):
        return
    clear_user_sessions(uid)
    deactivate_ai_mode(uid)
    text = m.text
    if text == "🍃back":
        bot.send_message(m.chat.id,
                         f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                         parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return
    if text == "📢Broadcast":
        admin_broadcast_start(m)
        return
    if text == "🧹ClearLogs":
        start_admin_wizard(uid, "clearlogs", m.chat.id)
        return
    cmd_map = {"💨ChannelLink": "link", "🍶BotToken": "botapi", "🦞AIKey": "aiapi", "🔍SearchUser": "search",
               "🗑️DeleteAdmin": "delete", "➕AddAdmin": "add", "🚫BlockUser": "block", "✅UnblockUser": "unblock"}
    cmd = cmd_map.get(text)
    if cmd:
        start_admin_wizard(uid, cmd, m.chat.id)
    else:
        bot.reply_to(m, "❌ Unknown command.")

# ---------- ADMIN WIZARD ----------
def start_admin_wizard(uid, cmd, chat_id):
    clear_user_sessions(uid)
    sess = {'cmd': cmd, 'step': 1, 'data': {}, 'chat_id': chat_id}
    admin_cmd_sessions[uid] = sess
    if cmd == 'link':
        bot.send_message(chat_id,
                         "🔗 *Channel Link Update - Step 1/2*\n\nPlease send the new channel link (invite URL).\nExample: `https://t.me/+abc123`",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'botapi':
        bot.send_message(chat_id,
                         "🍶 *Bot Token Update*\n\nPlease send the new bot API token.\nExample: `123456:ABC-DEF...`",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'aiapi':
        bot.send_message(chat_id,
                         "🦞 *AI API Key Update*\n\nPlease send the new AI API key.\nExample: `sk-...`",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'search':
        bot.send_message(chat_id,
                         "🔍 *Search User*\n\nPlease send the user ID, username (with @), or name to search.",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'delete':
        bot.send_message(chat_id,
                         "🗑️ *Remove Admin*\n\nPlease send the user ID, username (with @), or name to remove from admin list.",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'add':
        bot.send_message(chat_id,
                         "➕ *Add Admin*\n\nPlease send the user ID, username (with @), or name to add as admin.",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'block':
        bot.send_message(chat_id,
                         "🚫 *Block User*\n\nPlease send the user ID, username (with @), or name to block.",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'unblock':
        bot.send_message(chat_id,
                         "✅ *Unblock User*\n\nPlease send the user ID, username (with @), or name to unblock.",
                         parse_mode='Markdown', reply_markup=wizard_input_keyboard())
    elif cmd == 'clearlogs':
        bot.send_message(chat_id,
                         "🧹 *Clear Logs*\n\nAre you sure you want to clear all broadcast logs?",
                         parse_mode='Markdown', reply_markup=wizard_confirm_keyboard())
    else:
        bot.send_message(chat_id, "❌ Unknown command.")
        del admin_cmd_sessions[uid]

@bot.message_handler(func=lambda m: m.from_user.id in admin_cmd_sessions)
def admin_wizard_handler(m):
    uid = m.from_user.id
    sess = admin_cmd_sessions[uid]
    cmd = sess['cmd']
    step = sess['step']
    text = m.text.strip()
    if text in ("❌ Cancel", "🍃back"):
        del admin_cmd_sessions[uid]
        bot.send_message(m.chat.id,
                         f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                         parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return
    if text == "✅ Confirm":
        if cmd == 'clearlogs':
            db.clear_logs('broadcast')
            bot.reply_to(m, "🧹 Broadcast logs cleared successfully!")
        elif cmd == 'link':
            link = sess['data'].get('link')
            cid = sess['data'].get('id')
            if link and cid:
                db.set_config('channel_link', link)
                db.set_config('channel_id', cid)
                db.add_log('channel_link', f"Updated to Link: {link}, ID: {cid}")
                bot.reply_to(m, "✅ Channel link & ID updated successfully!")
            else:
                bot.reply_to(m, "❌ Missing data. Please restart the wizard.")
        elif cmd == 'botapi':
            token = sess['data'].get('token')
            if token:
                db.set_config('bot_token', token)
                db.add_log('botapi', f"Updated to: {token}")
                bot.reply_to(m, "✅ Bot token updated! Bot will restart in 3 seconds...")
                del admin_cmd_sessions[uid]
                time.sleep(1)
                restart_bot()
                return
            else:
                bot.reply_to(m, "❌ Missing token.")
        elif cmd == 'aiapi':
            key = sess['data'].get('key')
            if key:
                db.set_config('ai_api_key', key)
                db.add_log('aiapi', f"Updated to: {key}")
                bot.reply_to(m, "✅ AI API key updated!")
            else:
                bot.reply_to(m, "❌ Missing key.")
        elif cmd == 'delete':
            uid_del = sess['data'].get('uid')
            if uid_del and is_admin(uid_del):
                db.remove_admin(uid_del)
                bot.reply_to(m, f"✅ User `{uid_del}` removed from admins.")
            else:
                bot.reply_to(m, "❌ Invalid user.")
        elif cmd == 'add':
            uid_add = sess['data'].get('uid')
            if uid_add:
                if db.add_admin(uid_add):
                    bot.reply_to(m, f"✅ User `{uid_add}` added as admin.")
                else:
                    bot.reply_to(m, "⚠️ User is already admin.")
            else:
                bot.reply_to(m, "❌ Invalid user.")
        elif cmd == 'block':
            uid_block = sess['data'].get('uid')
            if uid_block:
                db.block_user(uid_block)
                bot.reply_to(m, f"✅ User `{uid_block}` blocked.")
            else:
                bot.reply_to(m, "❌ Invalid user.")
        elif cmd == 'unblock':
            uid_unblock = sess['data'].get('uid')
            if uid_unblock:
                db.unblock_user(uid_unblock)
                bot.reply_to(m, f"✅ User `{uid_unblock}` unblocked.")
            else:
                bot.reply_to(m, "❌ Invalid user.")
        elif cmd == 'search':
            bot.reply_to(m, "🔍 Search completed.")
        del admin_cmd_sessions[uid]
        bot.send_message(m.chat.id,
                         f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                         parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return

    # Input handling
    if cmd == 'link':
        if step == 1:
            if not text.startswith('https://t.me/'):
                bot.reply_to(m, "❌ Invalid channel link. Must start with `https://t.me/`")
                return
            sess['data']['link'] = text
            sess['step'] = 2
            bot.send_message(m.chat.id,
                             "🔗 *Channel Link Update - Step 2/2*\n\nNow send the channel ID (numeric).\nExample: `-1001234567890`",
                             parse_mode='Markdown', reply_markup=wizard_input_keyboard())
        elif step == 2:
            try:
                cid = int(text)
                sess['data']['id'] = cid
                summary = f"📋 *Summary*\nLink: {sess['data']['link']}\nID: `{cid}`"
                bot.send_message(m.chat.id, summary + "\n\nDo you want to update?",
                                 parse_mode='Markdown', reply_markup=wizard_confirm_keyboard())
            except ValueError:
                bot.reply_to(m, "❌ Invalid channel ID. Please send a numeric ID (e.g., `-1001234567890`).")
        return
    elif cmd == 'botapi':
        if ':' not in text:
            bot.reply_to(m, "❌ Invalid bot token format. It should contain ':'.")
            return
        sess['data']['token'] = text
        bot.send_message(m.chat.id,
                         f"📋 *Summary*\nNew Bot Token: `{text}`\n\nDo you want to update?",
                         parse_mode='Markdown', reply_markup=wizard_confirm_keyboard())
        return
    elif cmd == 'aiapi':
        if not text.startswith('sk-'):
            bot.reply_to(m, "❌ Invalid AI API key format. It should start with 'sk-'.")
            return
        sess['data']['key'] = text
        bot.send_message(m.chat.id,
                         f"📋 *Summary*\nNew AI API Key: `{text}`\n\nDo you want to update?",
                         parse_mode='Markdown', reply_markup=wizard_confirm_keyboard())
        return
    elif cmd == 'search':
        uid_found = find_user_id(text)
        if not uid_found:
            bot.reply_to(m, "❌ User not found.")
            del admin_cmd_sessions[uid]
            bot.send_message(m.chat.id,
                             f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                             parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
            return
        try:
            chat = bot.get_chat(uid_found)
            name = chat.first_name or "Unknown"
            uname = f"@{chat.username}" if chat.username else "No username"
            blocked = db.is_blocked(uid_found)
            adm = is_admin(uid_found)
            def esc(t):
                return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', t)
            result = f"👤 *User Info*\n━━━━━━━━━━━━━━━━━━\nID: `{uid_found}`\nName: {esc(name)}\nUsername: {esc(uname)}\nBlocked: {'Yes' if blocked else 'No'}\nAdmin: {'Yes' if adm else 'No'}"
            bot.reply_to(m, result, parse_mode='Markdown')
        except Exception as e:
            bot.reply_to(m, f"❌ Error fetching user details: {e}")
        bot.send_message(m.chat.id, "🔍 Search completed. Click below to go back.", reply_markup=wizard_search_keyboard())
        sess['step'] = 'done'
        return
    elif cmd in ('add', 'block', 'unblock', 'delete'):
        uid_found = find_user_id(text)
        if not uid_found:
            bot.reply_to(m, "❌ User not found.")
            del admin_cmd_sessions[uid]
            bot.send_message(m.chat.id,
                             f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                             parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
            return
        sess['data']['uid'] = uid_found
        try:
            chat = bot.get_chat(uid_found)
            name = chat.first_name or "Unknown"
            uname = f"@{chat.username}" if chat.username else "No username"
            summary = f"👤 User: `{uid_found}`\nName: {name}\nUsername: {uname}"
            if cmd == 'delete':
                summary += "\n\nDo you want to remove this admin?"
            elif cmd == 'add':
                summary += "\n\nDo you want to add this user as admin?"
            elif cmd == 'block':
                summary += "\n\nDo you want to block this user?"
            elif cmd == 'unblock':
                summary += "\n\nDo you want to unblock this user?"
            bot.send_message(m.chat.id, summary, parse_mode='Markdown', reply_markup=wizard_confirm_keyboard())
        except:
            bot.send_message(m.chat.id, f"Confirm action for `{uid_found}`?",
                             parse_mode='Markdown', reply_markup=wizard_confirm_keyboard())
        return

# ---------- SETTINGS WIZARD (FIXED) ----------
# Map short setting names to actual database keys
SETTING_MAP = {
    'link': 'channel_link',
    'botapi': 'bot_token',
    'aiapi': 'ai_api_key'
}

def start_settings_wizard(uid, setting, chat_id):
    clear_user_sessions(uid)
    settings_sessions[uid] = {'setting': setting, 'step': 1, 'data': {}, 'chat_id': chat_id}
    send_settings_step1(uid)

def send_settings_step1(uid):
    sess = settings_sessions.get(uid)
    if not sess:
        return
    setting = sess['setting']
    db_key = SETTING_MAP.get(setting, setting)  # get actual key
    val = db.get_config(db_key)
    display = str(val) if val is not None else "Not set"
    if len(display) > 50:
        display = display[:47] + "..."
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if setting == 'link':
        text = f"🔗 **Current Channel Link:** `{display}`\n\nSend new channel link (invite URL):\nExample: `https://t.me/+abc123`"
        kb.row("👁️ View Full", "❌ Cancel")
    elif setting == 'botapi':
        text = f"🍶 **Current Bot Token:** `{display}`\n\nSend new bot API token:\nExample: `123456:ABC-DEF...`"
        kb.row("👁️ View Full", "❌ Cancel")
    elif setting == 'aiapi':
        text = f"🦞 **Current AI API Key:** `{display}`\n\nSend new AI API key:\nExample: `sk-...`"
        kb.row("👁️ View Full", "❌ Cancel")
    else:
        return
    kb.row("🍃back")
    bot.send_message(sess['chat_id'], text, parse_mode='Markdown', reply_markup=kb)

def send_settings_step2(uid):
    sess = settings_sessions.get(uid)
    if not sess:
        return
    setting = sess['setting']
    if setting == 'link':
        text = "🥀 Send the new channel ID (numeric).\nExample: `-1001234567890`"
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("❌ Cancel", "🍃back")
        bot.send_message(sess['chat_id'], text, parse_mode='Markdown', reply_markup=kb)
    else:
        show_settings_confirmation(uid)

def show_settings_confirmation(uid):
    sess = settings_sessions.get(uid)
    if not sess:
        return
    setting = sess['setting']
    data = sess['data']
    if setting == 'link':
        link = data.get('link')
        cid = data.get('id')
        if not link or not cid:
            bot.send_message(sess['chat_id'], "❌ Missing data. Please restart the wizard.")
            del settings_sessions[uid]
            return
        text = f"🥀 **New Link:** `{link}`\n🥀 **New Channel ID:** `{cid}`\n\nConfirm update? Click ✅ Done"
    elif setting == 'botapi':
        token = data.get('token')
        if not token:
            bot.send_message(sess['chat_id'], "❌ Missing token. Please restart the wizard.")
            del settings_sessions[uid]
            return
        text = f"🥀 **New Bot Token:** `{token}`\n\nConfirm update? Click ✅ Done"
    elif setting == 'aiapi':
        key = data.get('key')
        if not key:
            bot.send_message(sess['chat_id'], "❌ Missing key. Please restart the wizard.")
            del settings_sessions[uid]
            return
        text = f"🥀 **New AI API Key:** `{key}`\n\nConfirm update? Click ✅ Done"
    else:
        return
    sess['step'] = 3
    kb = settings_confirm_keyboard()
    bot.send_message(sess['chat_id'], text, parse_mode='Markdown', reply_markup=kb)

@bot.message_handler(func=lambda m: m.from_user.id in settings_sessions)
def settings_wizard_handler(m):
    uid = m.from_user.id
    sess = settings_sessions.get(uid)
    if not sess:
        return
    text = m.text.strip()
    setting = sess['setting']
    step = sess.get('step', 1)
    db_key = SETTING_MAP.get(setting, setting)

    # View Full
    if text == "👁️ View Full":
        val = db.get_config(db_key)
        if val is None:
            bot.reply_to(m, "❌ Not set.")
        else:
            bot.reply_to(m, f"📋 **Current {setting.replace('_',' ').title()}:**\n`{val}`")
        return

    # Cancel
    if text == "❌ Cancel":
        del settings_sessions[uid]
        bot.send_message(m.chat.id,
                         f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                         parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return

    # Back
    if text == "🍃back":
        if step == 3:
            if setting == 'link':
                sess['step'] = 2
                sess['data'].pop('id', None)
                send_settings_step2(uid)
            else:
                sess['step'] = 1
                sess['data'].pop('token', None)
                sess['data'].pop('key', None)
                send_settings_step1(uid)
        elif step == 2:
            sess['step'] = 1
            sess['data'].pop('link', None)
            send_settings_step1(uid)
        else:
            del settings_sessions[uid]
            bot.send_message(m.chat.id,
                             f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                             parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return

    # Done
    if text == "✅ Done":
        data = sess['data']
        try:
            if setting == 'link':
                link = data.get('link')
                cid = data.get('id')
                if link and cid:
                    db.set_config('channel_link', link)
                    db.set_config('channel_id', cid)
                    db.add_log('channel_link', f"Updated to Link: {link}, ID: {cid}")
                    bot.reply_to(m, "✅ Channel link and ID updated successfully!")
                else:
                    bot.reply_to(m, "❌ Missing data. Please restart the wizard.")
                    return
            elif setting == 'botapi':
                token = data.get('token')
                if token:
                    db.set_config('bot_token', token)
                    db.add_log('botapi', f"Updated to: {token}")
                    bot.reply_to(m, "✅ Bot token updated! Bot will restart in 3 seconds...")
                    del settings_sessions[uid]
                    time.sleep(1)
                    restart_bot()
                    return
                else:
                    bot.reply_to(m, "❌ Missing token.")
                    return
            elif setting == 'aiapi':
                key = data.get('key')
                if key:
                    db.set_config('ai_api_key', key)
                    db.add_log('aiapi', f"Updated to: {key}")
                    bot.reply_to(m, "✅ AI API key updated successfully!")
                else:
                    bot.reply_to(m, "❌ Missing key.")
                    return
        except Exception as e:
            bot.reply_to(m, f"❌ Error during update: {e}")
            return
        del settings_sessions[uid]
        bot.send_message(m.chat.id,
                         f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                         parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())
        return

    # Input handling
    if setting == 'link':
        if step == 1:
            if not text.startswith('https://t.me/'):
                bot.reply_to(m, "❌ Invalid channel link. Must start with `https://t.me/`")
                return
            sess['data']['link'] = text
            sess['step'] = 2
            send_settings_step2(uid)
        elif step == 2:
            try:
                cid = int(text)
                sess['data']['id'] = cid
                sess['step'] = 3
                show_settings_confirmation(uid)
            except ValueError:
                bot.reply_to(m, "❌ Invalid channel ID. Please send a numeric ID (e.g., `-1001234567890`).")
        else:
            bot.reply_to(m, "❌ Unexpected step. Please restart the wizard.")
            del settings_sessions[uid]
    elif setting in ('botapi', 'aiapi'):
        if step == 1:
            if setting == 'botapi' and ':' not in text:
                bot.reply_to(m, "❌ Invalid bot token format. It should contain ':'.")
                return
            if setting == 'aiapi' and not text.startswith('sk-'):
                bot.reply_to(m, "❌ Invalid AI API key format. It should start with 'sk-'.")
                return
            sess['data']['token' if setting == 'botapi' else 'key'] = text
            sess['step'] = 2
            show_settings_confirmation(uid)
        else:
            bot.reply_to(m, "❌ Unexpected step. Please restart the wizard.")
            del settings_sessions[uid]
    else:
        bot.reply_to(m, "❌ Unknown setting. Please restart the wizard.")
        del settings_sessions[uid]

# ---------- SETTINGS BUTTON HANDLERS ----------
@bot.message_handler(func=lambda m: m.text == "💠ChannelLink")
def settings_link_btn(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    start_settings_wizard(m.from_user.id, 'link', m.chat.id)

@bot.message_handler(func=lambda m: m.text == "🍶botApi")
def settings_botapi_btn(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    start_settings_wizard(m.from_user.id, 'botapi', m.chat.id)

@bot.message_handler(func=lambda m: m.text == "🦞Aiapi")
def settings_aiapi_btn(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    start_settings_wizard(m.from_user.id, 'aiapi', m.chat.id)

# ---------- MANAGE USERS ----------
@bot.message_handler(func=lambda m: m.text == "🛸totalusers")
def total_users(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    send_user_list(m.chat.id, 'total', 1)

@bot.message_handler(func=lambda m: m.text == "🚫blocksdusers")
def blocked_users(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    send_user_list(m.chat.id, 'blocked', 1)

@bot.message_handler(func=lambda m: m.text == "🎃activeusers")
def active_users(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    send_user_list(m.chat.id, 'active', 1)

@bot.message_handler(func=lambda m: m.text == "🛸addadmin")
def addadmin_btn(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    bot.send_message(m.chat.id,
                     "👋Hii admin welcome back\n🥀for adding new admin command:\n🍹/add {cheatid} or {username} or {name}",
                     parse_mode='Markdown', reply_markup=add_admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "🎀admins")
def list_admins(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    admins = db.get_admins()
    if not admins:
        text = "No admins found."
    else:
        text = "👥 *Admin List:*\n━━━━━━━━━━━━━━━━━━\n"
        for idx, uid in enumerate(admins, 1):
            display = get_user_display_name(uid)
            text += f"{idx}. `{uid}` {display}\n"
        text += "\n🥙 /delete {cheatid} or {username} or {name}"
    bot.send_message(m.chat.id, text, parse_mode='Markdown', reply_markup=add_admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "🧳broadcastlog")
def broadcast_logs(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    logs = db.get_logs('broadcast')
    if not logs:
        text = "No broadcast logs found."
    else:
        text = "📋 *Broadcast Logs:*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(logs[-20:]) + "\n\n🍂 /clearlogs to clear logs"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🍂clearlogs", callback_data="admin_clear_logs"))
    bot.send_message(m.chat.id, text, parse_mode='Markdown', reply_markup=broadcast_reply_keyboard())
    bot.send_message(m.chat.id, "Click below to clear logs:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "🍃back")
def back_admin(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    bot.send_message(m.chat.id,
                     f"🥀 Hello, *{m.from_user.first_name}* welcome back to admin👋",
                     parse_mode='Markdown', reply_markup=admin_main_reply_keyboard())

# ---------- USER INFO & BLOCK/UNBLOCK ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("user_info_"))
def user_info_cb(call):
    uid = int(call.data.split("_")[-1])
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Unauthorized.")
        return
    try:
        chat = bot.get_chat(uid)
        name = chat.first_name or "Unknown"
        uname = f"@{chat.username}" if chat.username else "No username"
        blocked = db.is_blocked(uid)
        adm = is_admin(uid)
        def esc(t):
            return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', t)
        text = f"👤 *User Info*\n━━━━━━━━━━━━━━━━━━\nID: `{uid}`\nName: {esc(name)}\nUsername: {esc(uname)}\nBlocked: {'Yes' if blocked else 'No'}\nAdmin: {'Yes' if adm else 'No'}"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    except:
        bot.answer_callback_query(call.id, "Could not fetch user details.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("block_from_list_"))
def block_from_list_cb(call):
    parts = call.data.split("_")
    uid = int(parts[3])
    menu = parts[4]
    page = int(parts[5])
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Unauthorized.")
        return
    db.block_user(uid)
    bot.answer_callback_query(call.id, f"✅ User {uid} blocked.", show_alert=True)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    send_user_list(call.message.chat.id, menu, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("unblock_from_list_"))
def unblock_from_list_cb(call):
    parts = call.data.split("_")
    uid = int(parts[3])
    menu = parts[4]
    page = int(parts[5])
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Unauthorized.")
        return
    db.unblock_user(uid)
    bot.answer_callback_query(call.id, f"✅ User {uid} unblocked.", show_alert=True)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    send_user_list(call.message.chat.id, menu, page)

# ---------- PAGINATION ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_total_page_"))
def total_page(call):
    page = int(call.data.split("_")[-1])
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    send_user_list(call.message.chat.id, 'total', page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_blocked_page_"))
def blocked_page(call):
    page = int(call.data.split("_")[-1])
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    send_user_list(call.message.chat.id, 'blocked', page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_active_page_"))
def active_page(call):
    page = int(call.data.split("_")[-1])
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    send_user_list(call.message.chat.id, 'active', page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_pagination_back")
def pagination_back(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id,
                     "🧞welcome back to user management system.\n🎭Select management button's🥀\n💬Owner Contact : @OWNERHIMANSHU",
                     parse_mode='Markdown', reply_markup=manage_users_reply_keyboard())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_clear_logs")
def clear_logs_cb(call):
    load = show_loading(call.message.chat.id)
    db.clear_logs('broadcast')
    delete_loading(call.message.chat.id, load)
    bot.answer_callback_query(call.id, "✅ Logs cleared!", show_alert=True)
    logs = db.get_logs('broadcast')
    text = "No broadcast logs found." if not logs else "📋 *Broadcast Logs:*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(
        logs[-10:]) + "\n\n🍂 /clearlogs to clear logs"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🍂clearlogs", callback_data="admin_clear_logs"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown',
                              reply_markup=broadcast_reply_keyboard())
    except:
        pass
    bot.send_message(call.message.chat.id, "Click below to clear logs:", reply_markup=kb)

# ---------- EXISTING CALLBACKS ----------
@bot.callback_query_handler(func=lambda call: call.data == "find_channels")
def find_channels_cb(call):
    uid = call.from_user.id
    channels = db.get_channels(uid)
    if not channels:
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("💠 ADD TO CHANNEL", url="https://t.me/TeligramidBot?startchannel&admin=post_messages"))
        bot.send_message(call.message.chat.id,
                         "🚫 No channels saved yet.\nAdd me to your channel and use `/*` in channel to save.",
                         parse_mode="Markdown", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup()
        for ch in channels:
            name = ch['name'][:18] + ".." if len(ch['name']) > 18 else ch['name']
            kb.row(InlineKeyboardButton(name, callback_data=f"chid_{ch['id']}"),
                   InlineKeyboardButton("🗑️", callback_data=f"del_ch_{ch['id']}"))
        bot.send_message(call.message.chat.id,
                         f"📋 *Your Channels*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🍻 Tap name to get ID, 🗑️ to delete.",
                         parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "find_groups")
def find_groups_cb(call):
    uid = call.from_user.id
    groups = db.get_groups(uid)
    if not groups:
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("💠 ADD TO GROUP", url="https://t.me/TeligramidBot?startgroup&admin=post_messages"))
        bot.send_message(call.message.chat.id,
                         "🚫 No groups saved yet.\nAdd me to your group and use `/**` in group to save.",
                         parse_mode="Markdown", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup()
        for gr in groups:
            name = gr['name'][:18] + ".." if len(gr['name']) > 18 else gr['name']
            kb.row(InlineKeyboardButton(name, callback_data=f"gid_{gr['id']}"),
                   InlineKeyboardButton("🗑️", callback_data=f"del_gr_{gr['id']}"))
        bot.send_message(call.message.chat.id,
                         f"📋 *Your Groups*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🍻 Tap name to get ID, 🗑️ to delete.",
                         parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('chid_'))
def show_chid(call):
    cid = call.data.replace('chid_', '')
    uid = call.from_user.id
    channels = db.get_channels(uid)
    if not any(ch['id'] == int(cid) for ch in channels):
        bot.answer_callback_query(call.id, "❌ This channel is no longer in your saved list.", show_alert=True)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        return
    load = show_loading(call.message.chat.id)
    delete_loading(call.message.chat.id, load)
    final = (f"🐦‍🔥 *CHANNEL ID FOUND* 🌹🌹\n"
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             f"👋 Hello *{call.from_user.first_name}*!\n"
             f"📌 Your CHANNEL ID: `{cid}`\n"
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             f"🥀 *Owner:* @OWNERHIMANSHU 💨")
    bot.send_message(call.message.chat.id, final, parse_mode="Markdown")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('gid_'))
def show_gid(call):
    gid = call.data.replace('gid_', '')
    uid = call.from_user.id
    groups = db.get_groups(uid)
    if not any(gr['id'] == int(gid) for gr in groups):
        bot.answer_callback_query(call.id, "❌ This group is no longer in your saved list.", show_alert=True)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        return
    load = show_loading(call.message.chat.id)
    delete_loading(call.message.chat.id, load)
    final = (f"🐦‍🔥 *GROUP ID FOUND* 🌹🌹\n"
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             f"👋 Hello *{call.from_user.first_name}*!\n"
             f"📌 Your GROUP ID: `{gid}`\n"
             f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             f"🥀 *DEVLOPER:* @OWNERHIMANSHU 💨")
    bot.send_message(call.message.chat.id, final, parse_mode="Markdown")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('del_ch_'))
def del_ch_confirm(call):
    cid = int(call.data.replace('del_ch_', ''))
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_del_ch_{cid}"),
           InlineKeyboardButton("❌ Cancel", callback_data="cancel_delete"))
    bot.send_message(call.message.chat.id, f"⚠️ Are you sure you want to delete this channel?\nID: `{cid}`",
                     parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('del_gr_'))
def del_gr_confirm(call):
    gid = int(call.data.replace('del_gr_', ''))
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_del_gr_{gid}"),
           InlineKeyboardButton("❌ Cancel", callback_data="cancel_delete"))
    bot.send_message(call.message.chat.id, f"⚠️ Are you sure you want to delete this group?\nID: `{gid}`",
                     parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_del_ch_'))
def confirm_del_ch(call):
    cid = int(call.data.replace('confirm_del_ch_', ''))
    db.remove_channel(call.from_user.id, cid)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, "✅ Channel removed from your saved list.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_del_gr_'))
def confirm_del_gr(call):
    gid = int(call.data.replace('confirm_del_gr_', ''))
    db.remove_group(call.from_user.id, gid)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, "✅ Group removed from your saved list.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_delete")
def cancel_delete_cb(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, "❌ Deletion cancelled.")
    bot.answer_callback_query(call.id)

# ---------- HELPERS ----------
def find_user_id(query):
    q = query.lower()
    for uid in db.get_all_users():
        try:
            chat = bot.get_chat(int(uid))
            name = (chat.first_name or "").lower()
            uname = (chat.username or "").lower()
            if q in name or q in uname or q == str(uid):
                return int(uid)
        except:
            pass
    return None

# ---------- AI (REAL GROQ - WORKING) ----------
def get_ai_response(msg, key):
    if not key:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content":
                    "You are a friendly, witty, and engaging assistant for a Telegram Chat ID Finder Bot. "
                    "You can answer any question the user asks – from bot-related queries to general topics. "
                    "If the user asks about this bot itself (its commands: /getmyid, /Channelid, /groupid, /help, /helpAi, /start; "
                    "how to save channels/groups using /* or /**, admin features, etc.), provide accurate and helpful information. "
                    "For any other question (sports, entertainment, general knowledge, fun facts, etc.), "
                    "give a cheerful, engaging, and concise response with lots of emojis. "
                    "Keep your replies short, crisp, and professional but with a friendly tone. "
                    "Always be positive, helpful, and add a touch of humor."},
                {"role": "user", "content": msg}
            ],
            "max_tokens": 200,
            "temperature": 0.8
        }
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data, timeout=5)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        else:
            return None
    except Exception as e:
        return None

# ---------- AI REPLY HANDLER ----------
@bot.message_handler(func=lambda message: True)
def ai_reply_all(m):
    uid = m.from_user.id if m.from_user else None
    if uid:
        if uid in broadcast_sessions or uid in admin_cmd_sessions or uid in settings_sessions:
            return
    if not m.text or m.text.startswith('/'):
        return
    ignore = ("🚀GET MY ID", "📢 GET CHANNEL ID", "👥 GET GROUP ID", "🎃USER HELP", "🏠 MAIN MENU",
              "🪄 AI ASSISTANT", "🎭 START ADMIN ACCESS", "🐦‍🔥managebot", "👥manageusers",
              "💬broadcast", "📖 Admin Help", "🍃back", "💠ChannelLink", "🍶botApi", "🦞Aiapi",
              "🛸totalusers", "🚫blocksdusers", "🎃activeusers", "🛸addadmin", "🧳broadcastlog",
              "🎀admins", "🔙 Exit AI Mode", "⏭️ Skip Text", "⏭️ Skip Media", "⏭️ Skip Buttons",
              "✅ Done", "❌ Cancel", "🍃back", "✅ Send Now", "✅ Confirm", "❌ Cancel", "🍃back",
              "💨ChannelLink", "🍶BotToken", "🦞AIKey", "🔍SearchUser", "🗑️DeleteAdmin",
              "➕AddAdmin", "🚫BlockUser", "✅UnblockUser", "🧹ClearLogs", "📢Broadcast",
              "🧭 Logs", "👁️ View Full")
    if m.text in ignore:
        return
    if db.is_blocked(uid):
        return
    if db.get_ai_mode(uid):
        bot.send_chat_action(m.chat.id, "typing")
        key = db.get_config('ai_api_key')
        reply = get_ai_response(m.text, key)
        if reply:
            bot.send_message(m.chat.id, f"🤖 {reply}", parse_mode='Markdown')
        else:
            bot.send_message(m.chat.id, "🤖 Sorry, AI is currently unavailable. Please try later.")
    else:
        bot.send_message(m.chat.id,
                         "🤖 *AI mode is off.*\nClick '🪄 AI ASSISTANT' in the help menu to enable AI replies to all your messages.\nOr use /helpAi to ask a direct question.",
                         parse_mode='Markdown')

# ---------- CHECK JOIN ----------
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_cb(call):
    uid = call.from_user.id
    if check_membership(uid):
        db.set_verified(uid, True)
        bot.edit_message_text("✅ **Verification successful!**\nYou can now use the bot.",
                              call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        name = call.from_user.first_name
        text = (f"🗽{name} welcome back to ID Bot! 👋\n\n"
                f"🔍 *Chat ID Finder Bot* 🧞\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🚀 /getmyid – get your chat ID\n"
                f"🚀 /Channelid – For channel ID\n"
                f"👥 /groupid – For Group ID\n"
                f"🚀 /help – Manual\n\n"
                f"🛸 add me on your Group/channel & ❤️‍🔥 run commands to get your IDs 🦹 !")
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown',
                         reply_markup=admin_reply_keyboard() if is_admin(uid) else main_keyboard())
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined the channel yet! Please join and click again.",
                                  show_alert=True)

# ---------- AUTO-SAVE FORWARD ----------
@bot.message_handler(content_types=['forward'])
@bot.channel_post_handler(content_types=['forward'])
def auto_save_forward(m):
    if db.is_blocked(m.from_user.id):
        return
    if m.forward_from_chat:
        chat = m.forward_from_chat
        cid = chat.id
        cname = chat.title or "Unknown"
        ctype = chat.type
        if ctype == "channel":
            if db.add_channel(m.from_user.id, cid, cname):
                bot.reply_to(m, f"✅ *Channel Saved!*\n📌 ID: `{cid}`\n📝 Name: {cname}", parse_mode="Markdown")
        elif ctype in ("group", "supergroup"):
            if db.add_group(m.from_user.id, cid, cname):
                bot.reply_to(m, f"✅ *Group Saved!*\n📌 ID: `{cid}`\n📝 Name: {cname}", parse_mode="Markdown")

# ---------- ALIASES ----------
@bot.message_handler(commands=['getcid'])
def get_cid(m):
    class Fake:
        pass
    fake = Fake()
    fake.from_user = m.from_user
    fake.message = m
    find_channels_cb(fake)

@bot.message_handler(commands=['getgid'])
def get_gid(m):
    class Fake:
        pass
    fake = Fake()
    fake.from_user = m.from_user
    fake.message = m
    find_groups_cb(fake)

@bot.message_handler(commands=['getchatid'])
@bot.channel_post_handler(commands=['getchatid'])
def get_chat_id(m):
    bot.send_message(m.chat.id, f"📌 This chat ID: `{m.chat.id}`", parse_mode="Markdown")

# ---------- ADMIN COMMANDS ----------
@bot.message_handler(commands=['Link'])
def cmd_link(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 3:
        try:
            link = parts[1]
            cid = int(parts[2])
            db.set_config('channel_link', link)
            db.set_config('channel_id', cid)
            db.add_log('channel_link', f"Updated to Link: {link}, ID: {cid}")
            bot.reply_to(m, "✅ Channel link & ID updated successfully!")
        except Exception as e:
            bot.reply_to(m, f"❌ Error: {e}")
    else:
        start_admin_wizard(m.from_user.id, 'link', m.chat.id)

@bot.message_handler(commands=['botapi'])
def cmd_botapi(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        new = parts[1]
        db.set_config('bot_token', new)
        db.add_log('botapi', f"Updated to: {new}")
        bot.reply_to(m, "✅ Bot token updated! Bot will restart in 3 seconds...")
        time.sleep(1)
        restart_bot()
    else:
        start_admin_wizard(m.from_user.id, 'botapi', m.chat.id)

@bot.message_handler(commands=['aiapi'])
def cmd_aiapi(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        new = parts[1]
        db.set_config('ai_api_key', new)
        db.add_log('aiapi', f"Updated to: {new}")
        bot.reply_to(m, "✅ AI API key updated!")
    else:
        start_admin_wizard(m.from_user.id, 'aiapi', m.chat.id)

@bot.message_handler(commands=['search'])
def cmd_search(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        q = ' '.join(parts[1:])
        uid = find_user_id(q)
        if not uid:
            bot.reply_to(m, "❌ User not found.")
            return
        try:
            chat = bot.get_chat(uid)
            name = chat.first_name or "Unknown"
            uname = f"@{chat.username}" if chat.username else "No username"
            blocked = db.is_blocked(uid)
            adm = is_admin(uid)
            def esc(t):
                return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', t)
            result = f"👤 *User Info*\n━━━━━━━━━━━━━━━━━━\nID: `{uid}`\nName: {esc(name)}\nUsername: {esc(uname)}\nBlocked: {'Yes' if blocked else 'No'}\nAdmin: {'Yes' if adm else 'No'}"
            bot.reply_to(m, result, parse_mode='Markdown')
        except Exception as e:
            bot.reply_to(m, f"❌ Error: {e}")
    else:
        start_admin_wizard(m.from_user.id, 'search', m.chat.id)

@bot.message_handler(commands=['add'])
def cmd_add(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        q = ' '.join(parts[1:])
        uid = find_user_id(q)
        if not uid:
            bot.reply_to(m, "❌ User not found.")
            return
        if db.add_admin(uid):
            bot.reply_to(m, f"✅ User `{uid}` added as admin.")
        else:
            bot.reply_to(m, "⚠️ User is already admin.")
    else:
        start_admin_wizard(m.from_user.id, 'add', m.chat.id)

@bot.message_handler(commands=['delete'])
def cmd_delete(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        q = ' '.join(parts[1:])
        uid = find_user_id(q)
        if not uid:
            bot.reply_to(m, "❌ User not found.")
            return
        if not is_admin(uid):
            bot.reply_to(m, "⚠️ This user is not an admin.")
            return
        db.remove_admin(uid)
        bot.reply_to(m, f"✅ User `{uid}` removed from admins.")
    else:
        start_admin_wizard(m.from_user.id, 'delete', m.chat.id)

@bot.message_handler(commands=['block'])
def cmd_block(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        q = ' '.join(parts[1:])
        uid = find_user_id(q)
        if not uid:
            bot.reply_to(m, "❌ User not found.")
            return
        db.block_user(uid)
        bot.reply_to(m, f"✅ User `{uid}` blocked.")
    else:
        start_admin_wizard(m.from_user.id, 'block', m.chat.id)

@bot.message_handler(commands=['unblock'])
def cmd_unblock(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    parts = m.text.split()
    if len(parts) >= 2:
        q = ' '.join(parts[1:])
        uid = find_user_id(q)
        if not uid:
            bot.reply_to(m, "❌ User not found.")
            return
        db.unblock_user(uid)
        bot.reply_to(m, f"✅ User `{uid}` unblocked.")
    else:
        start_admin_wizard(m.from_user.id, 'unblock', m.chat.id)

@bot.message_handler(commands=['clearlogs'])
def cmd_clearlogs(m):
    if not is_admin(m.from_user.id):
        return
    clear_user_sessions(m.from_user.id)
    deactivate_ai_mode(m.from_user.id)
    db.clear_logs('broadcast')
    bot.reply_to(m, "🧹 Broadcast logs cleared.")

# ---------- MAIN ----------
if __name__ == "__main__":
    if db.get_config('bot_token') is None:
        logger.error("❌ Bot token not found in database. Please insert config first.")
        sys.exit(1)
    print(f"🚀 Bot started with {DB_TYPE} database.")
    if DB_TYPE == "mysql":
        print(f"📊 Connected to MySQL: {DB_HOST}/{DB_NAME}")
    else:
        print("📁 Using SQLite: bot_data.db")
    bot.delete_webhook()
    bot.infinity_polling()