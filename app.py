import telebot
import random
import threading
import time
import os
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from threading import Thread, Lock
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

ADMIN_ID = 5671366303
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://mybingobot.onrender.com')
DB_PATH = 'bingo_data.db'

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
db_lock = Lock()

# ================= 💾 DATABASE =================

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            balance INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER DEFAULT 0,
            daily_last TEXT,
            total_wins INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            created_at TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount INTEGER,
            status TEXT,
            note TEXT,
            date TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            winner_id INTEGER,
            winner_name TEXT,
            card_num INTEGER,
            room_id INTEGER,
            called_count INTEGER,
            prize INTEGER,
            date TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS jackpot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            amount INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS scheduled_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hour INTEGER,
            minute INTEGER,
            chat_id INTEGER,
            enabled INTEGER DEFAULT 1
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            message TEXT,
            date TEXT
        )''')
        # Defaults
        c.execute("INSERT OR IGNORE INTO jackpot (id, amount) VALUES (1, 0)")
        defaults = {
            'price': '50 ብር',
            'account': 'CBE 1000123456789',
            'call_interval': '5',
            'commission': '15',
            'jackpot_percent': '10',
            'min_withdraw': '100',
            'daily_bonus': '10',
            'max_cards_per_player': '1',
            'game_name': 'ዘና ቢንጎ ከድጎ',
            'theme': 'purple',
            'win_pattern': 'single',
            'game_time_limit': '30'
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
        conn.close()

def db_get_setting(key, default=''):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default

def db_set_setting(key, value):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()

def db_get_user(uid):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, name, balance, banned, referral_code, referred_by, daily_last, total_wins, total_games FROM users WHERE user_id=?", (uid,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                'user_id': row[0], 'name': row[1], 'balance': row[2],
                'banned': bool(row[3]), 'referral_code': row[4],
                'referred_by': row[5], 'daily_last': row[6],
                'total_wins': row[7], 'total_games': row[8]
            }
        return None

def db_create_user(uid, name, referred_by=0):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        code = f"REF{uid % 100000}{random.randint(100,999)}"
        c.execute("INSERT OR IGNORE INTO users (user_id, name, balance, referral_code, referred_by, created_at) VALUES (?, ?, 0, ?, ?, ?)",
                  (uid, name, code, referred_by, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    return db_get_user(uid)

def db_update_name(uid, name):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET name=? WHERE user_id=?", (name, uid))
        conn.commit()
        conn.close()

def db_update_balance(uid, delta):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, uid))
        conn.commit()
        c.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0

def db_set_banned(uid, banned):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, uid))
        conn.commit()
        conn.close()

def db_add_transaction(uid, typ, amount, status='pending', note=''):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO transactions (user_id, type, amount, status, note, date) VALUES (?, ?, ?, ?, ?, ?)",
                  (uid, typ, amount, status, note, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def db_get_pending_transactions():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, user_id, type, amount, note, date FROM transactions WHERE status='pending' ORDER BY id DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        return rows

def db_update_transaction(tid, status):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE transactions SET status=? WHERE id=?", (status, tid))
        conn.commit()
        conn.close()

def db_add_game(winner_id, winner_name, card_num, room_id, called_count, prize):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO game_history (winner_id, winner_name, card_num, room_id, called_count, prize, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (winner_id, winner_name, card_num, room_id, called_count, prize, datetime.now().isoformat()))
        c.execute("UPDATE users SET total_wins = total_wins + 1 WHERE user_id=?", (winner_id,))
        c.execute("UPDATE users SET total_games = total_games + 1 WHERE user_id != ?", (winner_id,))
        c.execute("UPDATE users SET total_games = total_games + 1 WHERE user_id=?", (winner_id,))
        conn.commit()
        conn.close()

def db_get_history(limit=20):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT winner_name, card_num, room_id, called_count, prize, date FROM game_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

def db_get_leaderboard(limit=10):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, name, total_wins, total_games, balance FROM users ORDER BY total_wins DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

def db_get_jackpot():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT amount FROM jackpot WHERE id=1")
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0

def db_add_jackpot(amount):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE jackpot SET amount = amount + ? WHERE id=1", (amount,))
        conn.commit()
        c.execute("SELECT amount FROM jackpot WHERE id=1")
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0

def db_reset_jackpot():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE jackpot SET amount=0 WHERE id=1")
        conn.commit()
        conn.close()

def db_save_feedback(uid, name, msg):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO feedback (user_id, name, message, date) VALUES (?, ?, ?, ?)",
                  (uid, name, msg, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def db_get_feedback(limit=20):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, message, date FROM feedback ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

def db_get_scheduled():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, hour, minute, chat_id, enabled FROM scheduled_games WHERE enabled=1")
        rows = c.fetchall()
        conn.close()
        return rows

def db_add_scheduled(hour, minute, chat_id):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO scheduled_games (hour, minute, chat_id, enabled) VALUES (?, ?, ?, 1)", (hour, minute, chat_id))
        conn.commit()
        conn.close()

def db_clear_scheduled():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM scheduled_games")
        conn.commit()
        conn.close()

# ================= 📦 የጨዋታ ክፍል =================

class BingoGame:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}
        self.player_card_numbers = {}
        self.called_numbers = []
        self.available_numbers = list(range(1, 91))
        random.shuffle(self.available_numbers)
        self.is_active = False
        self.join_open = False
        self.game_state = 'idle'
        self.winners = []
        self.card_pool = self.generate_card_pool(200)
        self.taken_cards = set()
        self.approved_players = set()
        self.used_receipts = set()
        self.chat_id = None
        self.join_deadline = None
        self.game_name = db_get_setting('game_name', 'ዘና ቢንጎ ከድጎ')
        self.last_called = None
        self.paused = False
        self.winner_name = None
        self.winner_card = None
        self.started_at = None

    def generate_single_card(self):
        card = []
        cols = [list(range(1, 19)), list(range(19, 37)), list(range(37, 55)),
                list(range(55, 73)), list(range(73, 91))]
        for col in cols:
            card.append(random.sample(col, 5))
        matrix = [[card[c][r] for c in range(5)] for r in range(5)]
        matrix[2][2] = "⭐"
        return matrix

    def generate_card_pool(self, count):
        pool, seen = [], set()
        while len(pool) < count:
            c = self.generate_single_card()
            if str(c) not in seen:
                seen.add(str(c))
                pool.append(c)
        return pool

    def check_bingo(self, card, called):
        called_set = set(called)
        pattern = db_get_setting('win_pattern', 'single')
        for row in card:
            if all(str(n) == "⭐" or n in called_set for n in row):
                return True
        for c in range(5):
            if all(str(card[r][c]) == "⭐" or card[r][c] in called_set for r in range(5)):
                return True
        if all(str(card[i][i]) == "⭐" or card[i][i] in called_set for i in range(5)):
            return True
        if all(str(card[i][4-i]) == "⭐" or card[i][4-i] in called_set for i in range(5)):
            return True
        if pattern == 'fullhouse':
            if all(str(card[r][c]) == "⭐" or card[r][c] in called_set for r in range(5) for c in range(5)):
                return True
        if pattern == 'corners':
            corners = [card[0][0], card[0][4], card[4][0], card[4][4]]
            l = ["B","I","N","G","O"]
            if all(f"{l[i]}-{corners[i]}" in called_set for i in range(4)):
                return True
        return False

rooms = {}
room_counter = 1
user_names_cache = {}
rate_limit = {}

def get_user_name(uid):
    if uid in user_names_cache:
        return user_names_cache[uid]
    u = db_get_user(uid)
    if u and u['name']:
        user_names_cache[uid] = u['name']
        return u['name']
    try:
        info = bot.get_chat(uid)
        name = f"@{info.username}" if info.username else info.first_name
    except:
        name = "ተጫዋች"
    user_names_cache[uid] = name
    return name

def get_price_int():
    try:
        return int(''.join(filter(str.isdigit, db_get_setting('price', '50 ብር'))))
    except:
        return 50

def check_rate_limit(uid, seconds=1):
    now = time.time()
    if uid in rate_limit and now - rate_limit[uid] < seconds:
        return False
    rate_limit[uid] = now
    return True

# ================= 🌐 API =================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return "OK", 200

@app.route('/api/room/<int:room_id>')
def api_room_info(room_id):
    if room_id not in rooms:
        return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    now = time.time()
    time_left = 0
    if r.join_deadline and r.join_open:
        time_left = max(0, int(r.join_deadline - now))
        if time_left == 0 and r.game_state == 'joining':
            r.join_open = False
    return jsonify({
        'room_id': room_id, 'game_name': r.game_name, 'game_state': r.game_state,
        'is_active': r.is_active, 'join_open': r.join_open, 'time_left': time_left,
        'players': len(r.approved_players), 'pending': 0,
        'called': r.called_numbers, 'called_count': len(r.called_numbers),
        'remaining': len(r.available_numbers), 'price': db_get_setting('price', '50 ብር'),
        'winners': r.winners, 'winner_name': r.winner_name, 'winner_card': r.winner_card,
        'taken_cards': list(r.taken_cards), 'total_cards': len(r.card_pool),
        'last_called': r.last_called, 'paused': r.paused,
        'jackpot': db_get_jackpot(),
        'theme': db_get_setting('theme', 'purple'),
        'max_cards': int(db_get_setting('max_cards_per_player', '1')),
    })

@app.route('/api/user_info', methods=['POST'])
def api_user_info():
    data = request.json
    uid = data.get('user_id')
    name = data.get('name', 'ተጫዋች')
    referred_by = data.get('referred_by', 0)
    u = db_get_user(uid)
    if not u:
        u = db_create_user(uid, name, referred_by)
        if referred_by and referred_by != uid:
            referrer = db_get_user(referred_by)
            if referrer:
                db_update_balance(referred_by, 20)
                db_add_transaction(referred_by, 'referral', 20, 'completed', f'ጓደኛ ጋበዘ')
                try:
                    bot.send_message(referred_by, "🎉 ውድ ተጫዋች! ጓደኛዎን በመጋበዝዎ +20 ብር አግኝተዋል! 💚")
                except: pass
    else:
        if u['name'] != name:
            db_update_name(uid, name)
            u['name'] = name
    return jsonify({
        'user_id': uid, 'name': u['name'], 'balance': u['balance'],
        'is_admin': uid == ADMIN_ID, 'banned': u['banned'],
        'referral_code': u['referral_code'],
        'total_wins': u['total_wins'], 'total_games': u['total_games'],
        'account': db_get_setting('account', ''),
        'price': db_get_setting('price', '50 ብር'),
        'price_int': get_price_int(),
    })

@app.route('/api/daily_bonus', methods=['POST'])
def api_daily_bonus():
    data = request.json
    uid = data.get('user_id')
    u = db_get_user(uid)
    if not u: return jsonify({'ok': False, 'msg': '🙏 ይቅርታ፣ መጀመሪያ ገጹን ክፈት።'})
    today = datetime.now().strftime('%Y-%m-%d')
    if u['daily_last'] == today:
        return jsonify({'ok': False, 'msg': '🙏 ውድ ተጫዋች፣ የዛሬ ስጦታዎን ተቀብለዋል። ነገ ይምጡ! 💚'})
    bonus = int(db_get_setting('daily_bonus', '10'))
    db_update_balance(uid, bonus)
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET daily_last=? WHERE user_id=?", (today, uid))
        conn.commit()
        conn.close()
    db_add_transaction(uid, 'daily_bonus', bonus, 'completed', 'የቀን ስጦታ')
    return jsonify({'ok': True, 'msg': f'🎁 ውድ ተጫዋች! +{bonus} ብር የቀን ስጦታ አግኝተዋል። መልካም ቀን! 💚', 'bonus': bonus})

@app.route('/api/join', methods=['POST'])
def api_join():
    data = request.json
    uid = data.get('user_id')
    room_id = data.get('room_id')
    card_num = data.get('card_num')
    u = db_get_user(uid)
    if not u: return jsonify({'ok': False, 'msg': '🙏 ይቅርታ፣ መጀመሪያ ገጹን ክፈት።'})
    if u['banned']: return jsonify({'ok': False, 'msg': '🙏 ይቅርታ፣ አገልግሎቱን ለመጠቀም ፈቃድ የለህም።'})
    if not check_rate_limit(uid, 0.5): return jsonify({'ok': False, 'msg': '🙏 እባክህ ትንሽ ታገስ።'})
    if room_id not in rooms: return jsonify({'ok': False, 'msg': '🙏 ክፍሉ አልተገኘም።'})
    r = rooms[room_id]
    if r.game_state in ('playing', 'finished'):
        return jsonify({'ok': False, 'msg': '🙏 ጨዋታው ተጀምሯል። በትዕግስት ተጠብቅ።'})
    if not r.join_open:
        return jsonify({'ok': False, 'msg': '⏰ የመግቢያ ጊዜ አልፏል። በትዕግስት ተጠብቅ።'})
    max_cards = int(db_get_setting('max_cards_per_player', '1'))
    if uid in r.players and len(r.players[uid]) >= max_cards:
        return jsonify({'ok': False, 'msg': f'🙏 ከፍተኛው {max_cards} ካርድ ብቻ ነው።'})

    ci = card_num - 1
    if ci < 0 or ci >= len(r.card_pool):
        return jsonify({'ok': False, 'msg': '🙏 ካርድ አልተገኘም።'})
    if ci in r.taken_cards:
        return jsonify({'ok': False, 'msg': f'🙏 ካርድ {card_num} ቀድሞ ተመርጧል። ሌላ ምረጥ።'})

    price = get_price_int()
    if u['balance'] < price:
        return jsonify({
            'ok': False,
            'msg': f'🙏 በቂ ባላንስ የለህም።\n\n💰 ያለህ: {u["balance"]} ብር\n💵 የሚያስፈልግ: {price} ብር\n\n🏦 {db_get_setting("account", "")}\n\n💚 እባክህ {price} ብር ላክና ስክሪንሾት ወደ ቦቱ ላክ።',
            'need_payment': True, 'balance': u['balance'], 'price': price,
            'account': db_get_setting('account', '')
        })

    new_bal = db_update_balance(uid, -price)
    db_add_transaction(uid, 'buy_card', -price, 'completed', f'ካርድ #{card_num}')
    r.taken_cards.add(ci)
    if uid not in r.players: r.players[uid] = []
    r.players[uid].append(r.card_pool[ci])
    if uid not in r.player_card_numbers: r.player_card_numbers[uid] = []
    r.player_card_numbers[uid].append(card_num)
    r.approved_players.add(uid)
    db_update_name(uid, get_user_name(uid))

    # Jackpot
    jp_pct = int(db_get_setting('jackpot_percent', '10'))
    jp_add = int(price * jp_pct / 100)
    db_add_jackpot(jp_add)

    try:
        bot.send_message(ADMIN_ID,
            f"🎫 <b>አዲስ ካርድ ተመረጠ</b>\n👤 {get_user_name(uid)}\n🎫 ካርድ #{card_num}\n💰 +{jp_add} ብር ጃክፖት",
            parse_mode='HTML')
    except: pass

    return jsonify({'ok': True, 'card': r.card_pool[ci], 'card_num': card_num,
                    'called': r.called_numbers, 'new_balance': new_bal})

@app.route('/api/mycard', methods=['POST'])
def api_mycard():
    data = request.json
    uid = data.get('user_id')
    room_id = data.get('room_id')
    if room_id not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if uid not in r.players: return jsonify({'error': 'no card'}), 404
    cards = r.players[uid]
    called_set = set(r.called_numbers)
    marked_list = []
    for card in cards:
        marked = []
        for row in card:
            new_row = []
            for num in row:
                if num == "⭐": new_row.append("⭐")
                elif num in called_set: new_row.append(f"✅{num}")
                else: new_row.append(str(num))
            marked.append(new_row)
        marked_list.append(marked)
    return jsonify({
        'cards': marked_list,
        'card_nums': r.player_card_numbers.get(uid, []),
        'called': r.called_numbers,
        'balance': db_get_user(uid)['balance'],
    })

@app.route('/api/bingo', methods=['POST'])
def api_bingo():
    data = request.json
    uid = data.get('user_id')
    room_id = data.get('room_id')
    if room_id not in rooms: return jsonify({'ok': False, 'msg': '🙏 ክፍሉ አልተገኘም።'})
    r = rooms[room_id]
    if uid not in r.approved_players: return jsonify({'ok': False, 'msg': '🙏 ገና አልተጸደቅህም።'})
    if uid in r.winners: return jsonify({'ok': False, 'msg': '🌟 ቀድመህ አሸንፈሃል!'})
    if not r.is_active: return jsonify({'ok': False, 'msg': '🙏 ጨዋታው አልተጀመረም።'})
    cards = r.players.get(uid, [])
    for card in cards:
        if r.check_bingo(card, r.called_numbers):
            r.winners.append(uid)
            card_nums = r.player_card_numbers.get(uid, [])
            card_num = card_nums[0] if card_nums else "?"
            name = get_user_name(uid)
            r.winner_name = name
            r.winner_card = card_num

            # የሽልማት ስሌት
            total_pool = len(r.approved_players) * get_price_int()
            jp = db_get_jackpot()
            commission_pct = int(db_get_setting('commission', '15'))
            commission = int(total_pool * commission_pct / 100)
            prize = total_pool - commission + jp
            db_update_balance(uid, prize)
            db_add_transaction(uid, 'win', prize, 'completed', f'የካርድ #{card_num} ድል')
            db_add_game(uid, name, card_num, room_id, len(r.called_numbers), prize)
            db_reset_jackpot()

            msg = (
                f"🌟🌟🌟 <b>ቢንጎ!</b> 🌟🌟🌟\n━━━━━━━━━━━━━━━━━━━━\n"
                f"🎊 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🎊\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>ውድ አሸናፊ:</b> {name}\n"
                f"🎫 <b>ያሸነፍክበት ካርድ:</b> #{card_num}\n"
                f"🎯 <b>ጠቅላላ ጥሪዎች:</b> {len(r.called_numbers)}\n"
                f"💰 <b>ያገኙት ሽልማት:</b> {prize} ብር\n"
                f"🎰 <b>ጃክፖት:</b> {jp} ብር\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🙏 <i>ስለ ተሳትፎህ/ሽ ከልብ እናመሰግናለን!</i>"
            )
            if r.chat_id:
                try: bot.send_message(r.chat_id, msg, parse_mode='HTML')
                except: pass
            try: bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
            except: pass
            try:
                bot.send_message(uid,
                    f"🌟 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🌟\n\n"
                    f"🏆 ውድ አሸናፊ!\n💰 ሽልማት: <b>{prize} ብር</b>\n"
                    f"🎫 ካርድ: <b>#{card_num}</b>\n\n"
                    f"🙏 ስለ ተሳትፎህ/ሽ እናመሰግናለን!",
                    parse_mode='HTML')
            except: pass
            r.is_active = False
            r.game_state = 'finished'
            return jsonify({'ok': True, 'winner': name, 'card_num': card_num, 'prize': prize})
    return jsonify({'ok': False, 'msg': '🙏 ገና አልተሸነፍክም። ካርድህን በጥንቃቄ ተመልከት።'})

@app.route('/api/leaderboard', methods=['GET'])
def api_leaderboard():
    rows = db_get_leaderboard(10)
    return jsonify({'leaders': [{'name': r[1], 'wins': r[2], 'games': r[3], 'balance': r[4]} for r in rows]})

@app.route('/api/history', methods=['GET'])
def api_history():
    rows = db_get_history(20)
    return jsonify({'history': [{'winner': r[0], 'card': r[1], 'room': r[2], 'called': r[3], 'prize': r[4], 'date': r[5]} for r in rows]})

@app.route('/api/withdraw', methods=['POST'])
def api_withdraw():
    data = request.json
    uid = data.get('user_id')
    amount = int(data.get('amount', 0))
    account = data.get('account', '').strip()
    u = db_get_user(uid)
    if not u: return jsonify({'ok': False, 'msg': '🙏 ይቅርታ።'})
    min_w = int(db_get_setting('min_withdraw', '100'))
    if amount < min_w: return jsonify({'ok': False, 'msg': f'🙏 አነስተኛው ማውጣት {min_w} ብር ነው።'})
    if u['balance'] < amount: return jsonify({'ok': False, 'msg': f'🙏 በቂ ባላንስ የለህም። ({u["balance"]} ብር)'})
    if not account: return jsonify({'ok': False, 'msg': '🙏 የባንክ አካውንትህን አስገባ።'})
    db_update_balance(uid, -amount)
    db_add_transaction(uid, 'withdraw', -amount, 'pending', account)
    try:
        bot.send_message(ADMIN_ID,
            f"💸 <b>የገንዘብ ማውጣት ጥያቄ</b>\n\n"
            f"👤 {u['name']}\n🆔 {uid}\n💰 {amount} ብር\n🏦 {account}",
            parse_mode='HTML')
    except: pass
    return jsonify({'ok': True, 'msg': f'🙏 ጥያቄህ ለአስተዳዳሪው ተልኳል። {amount} ብር ወደ {account} ይላካል።'})

@app.route('/api/feedback', methods=['POST'])
def api_feedback():
    data = request.json
    uid = data.get('user_id')
    msg = data.get('message', '').strip()
    if not msg: return jsonify({'ok': False, 'msg': '🙏 መልእክት አስገባ።'})
    name = get_user_name(uid)
    db_save_feedback(uid, name, msg)
    try:
        bot.send_message(ADMIN_ID, f"💬 <b>አስተያየት</b>\n👤 {name}\n📝 {msg}", parse_mode='HTML')
    except: pass
    return jsonify({'ok': True, 'msg': '🙏 አስተያየትህ ደርሶናል! ስለ ተሳትፎህ እናመሰግናለን! 💚'})

# ================= 🔐 ADMIN API =================

def is_admin(d): return d.get('user_id') == ADMIN_ID

@app.route('/api/admin/create_room', methods=['POST'])
def api_admin_create_room():
    global room_counter
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    chat_id = d.get('chat_id')
    rid = room_counter
    room_counter += 1
    rooms[rid] = BingoGame(rid)
    rooms[rid].is_active = True
    rooms[rid].join_open = True
    rooms[rid].game_state = 'joining'
    rooms[rid].chat_id = chat_id
    rooms[rid].join_deadline = time.time() + 120
    if chat_id:
        try:
            bot.send_message(chat_id,
                f"🌟 <b>እንኳን ደህና መጡ ውድ ተጫዋቾች!</b> 🌟\n"
                f"🎮 <b>{rooms[rid].game_name} - ክፍል {rid}</b> ተከፍቷል!\n"
                f"💰 {db_get_setting('price')}\n⏱️ 2 ደቂቃ\n\n"
                f"🙏 የቢንጎ ገጹን ክፈቱ!",
                reply_markup=get_main_panel(rid), parse_mode='HTML')
        except: pass
    return jsonify({'ok': True, 'room_id': rid})

@app.route('/api/admin/start_game', methods=['POST'])
def api_admin_start_game():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if len(r.approved_players) == 0:
        return jsonify({'ok': False, 'msg': '🙏 ተጫዋች የለም።'})
    r.join_open = False
    r.game_state = 'playing'
    r.started_at = time.time()
    threading.Thread(target=auto_call_loop, args=(rid,), daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/admin/toggle_pause', methods=['POST'])
def api_admin_toggle_pause():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    rooms[rid].paused = not rooms[rid].paused
    return jsonify({'paused': rooms[rid].paused})

@app.route('/api/admin/call_number', methods=['POST'])
def api_admin_call_number():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    num = d.get('number')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if num in r.called_numbers:
        return jsonify({'ok': False, 'msg': '🙏 ቁጥሩ ቀድሞ ተጠርቷል።'})
    if num in r.available_numbers: r.available_numbers.remove(num)
    r.called_numbers.append(num)
    r.last_called = num
    return jsonify({'ok': True})

@app.route('/api/admin/force_win', methods=['POST'])
def api_admin_force_win():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    target = d.get('target_user_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if target in r.players:
        r.winners.append(target)
        card_nums = r.player_card_numbers.get(target, [])
        card_num = card_nums[0] if card_nums else "?"
        name = get_user_name(target)
        r.winner_name = name
        r.winner_card = card_num
        total_pool = len(r.approved_players) * get_price_int()
        commission = int(total_pool * int(db_get_setting('commission', '15')) / 100)
        prize = total_pool - commission
        db_update_balance(target, prize)
        db_add_game(target, name, card_num, rid, len(r.called_numbers), prize)
        if r.chat_id:
            try: bot.send_message(r.chat_id, f"🌟 አስተዳዳሪው {name} አሸናፊ አድርጎታል! (ካርድ #{card_num})")
            except: pass
        r.is_active = False
        r.game_state = 'finished'
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/reset', methods=['POST'])
def api_admin_reset():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid in rooms: del rooms[rid]
    return jsonify({'ok': True})

@app.route('/api/admin/set_name', methods=['POST'])
def api_admin_set_name():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    name = d.get('name', '').strip()
    if name:
        db_set_setting('game_name', name)
        rid = d.get('room_id')
        if rid in rooms: rooms[rid].game_name = name
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_price', methods=['POST'])
def api_admin_set_price():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    p = d.get('price', '').strip()
    if p:
        db_set_setting('price', p)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_account', methods=['POST'])
def api_admin_set_account():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    a = d.get('account', '').strip()
    if a:
        db_set_setting('account', a)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_interval', methods=['POST'])
def api_admin_set_interval():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    iv = d.get('interval')
    if iv and 1 <= iv <= 60:
        db_set_setting('call_interval', iv)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_commission', methods=['POST'])
def api_admin_set_commission():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    c = d.get('commission')
    if c is not None and 0 <= c <= 50:
        db_set_setting('commission', c)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_theme', methods=['POST'])
def api_admin_set_theme():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    t = d.get('theme')
    if t in ('purple', 'green', 'blue', 'red'):
        db_set_setting('theme', t)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_pattern', methods=['POST'])
def api_admin_set_pattern():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    p = d.get('pattern')
    if p in ('single', 'fullhouse', 'corners'):
        db_set_setting('win_pattern', p)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_max_cards', methods=['POST'])
def api_admin_set_max_cards():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    m = d.get('max_cards')
    if m and 1 <= m <= 5:
        db_set_setting('max_cards_per_player', m)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_jackpot_pct', methods=['POST'])
def api_admin_set_jackpot_pct():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    p = d.get('percent')
    if p is not None and 0 <= p <= 30:
        db_set_setting('jackpot_percent', p)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_daily_bonus', methods=['POST'])
def api_admin_set_daily_bonus():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    a = d.get('amount')
    if a is not None and 0 <= a <= 100:
        db_set_setting('daily_bonus', a)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_min_withdraw', methods=['POST'])
def api_admin_set_min_withdraw():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    a = d.get('amount')
    if a is not None and a >= 0:
        db_set_setting('min_withdraw', a)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_game_time', methods=['POST'])
def api_admin_set_game_time():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    m = d.get('minutes')
    if m and 1 <= m <= 120:
        db_set_setting('game_time_limit', m)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/ban', methods=['POST'])
def api_admin_ban():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id')
    if uid:
        db_set_banned(uid, True)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/unban', methods=['POST'])
def api_admin_unban():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id')
    if uid:
        db_set_banned(uid, False)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/add_balance', methods=['POST'])
def api_admin_add_balance():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id')
    amt = d.get('amount')
    if uid and amt:
        new_bal = db_update_balance(uid, int(amt))
        db_add_transaction(uid, 'admin_add', int(amt), 'completed', 'በአስተዳዳሪ')
        try:
            bot.send_message(uid, f"🙏 ውድ ተጫዋች! +{amt} ብር ተጨምሯል።\n💵 አሁን: {new_bal} ብር")
        except: pass
        return jsonify({'ok': True, 'balance': new_bal})
    return jsonify({'ok': False})

@app.route('/api/admin/set_balance', methods=['POST'])
def api_admin_set_balance():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id')
    amt = d.get('amount')
    if uid and amt is not None:
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE users SET balance=? WHERE user_id=?", (int(amt), uid))
            conn.commit()
            conn.close()
        return jsonify({'ok': True, 'balance': int(amt)})
    return jsonify({'ok': False})

@app.route('/api/admin/broadcast', methods=['POST'])
def api_admin_broadcast():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    msg = d.get('message', '').strip()
    if not msg: return jsonify({'ok': False})
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        uids = [r[0] for r in c.fetchall()]
        conn.close()
    count = 0
    for uid in uids:
        try:
            bot.send_message(uid, f"🙏 <b>ከአስተዳዳሪው መልእክት</b>\n\n{msg}\n\n💚", parse_mode='HTML')
            count += 1
            time.sleep(0.05)
        except: pass
    return jsonify({'ok': True, 'count': count})

@app.route('/api/admin/send_dm', methods=['POST'])
def api_admin_send_dm():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id')
    msg = d.get('message', '').strip()
    if uid and msg:
        try:
            bot.send_message(uid, f"📩 <b>የግል መልእክት</b>\n\n{msg}\n\n🙏", parse_mode='HTML')
            return jsonify({'ok': True})
        except: return jsonify({'ok': False, 'msg': '🙏 መላክ አልተቻለም።'})
    return jsonify({'ok': False})

@app.route('/api/admin/allcards', methods=['POST'])
def api_admin_allcards():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    result = []
    for uid in r.players.keys():
        u = db_get_user(uid)
        result.append({
            'user_id': uid, 'name': get_user_name(uid),
            'card_nums': r.player_card_numbers.get(uid, []),
            'balance': u['balance'] if u else 0,
            'winner': uid in r.winners
        })
    return jsonify({'players': result})

@app.route('/api/admin/remove_card', methods=['POST'])
def api_admin_remove_card():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    cn = d.get('card_num')
    if rid in rooms and cn:
        r = rooms[rid]
        idx = cn - 1
        r.taken_cards.discard(idx)
        for uid in list(r.players.keys()):
            nums = r.player_card_numbers.get(uid, [])
            if cn in nums:
                pos = nums.index(cn)
                r.players[uid].pop(pos)
                nums.pop(pos)
                if not nums:
                    r.players.pop(uid, None)
                    r.player_card_numbers.pop(uid, None)
                    r.approved_players.discard(uid)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/stats', methods=['POST'])
def api_admin_stats():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(balance) FROM users")
        total_users, total_balance = c.fetchone()
        c.execute("SELECT COUNT(*) FROM game_history")
        total_games = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE banned=1")
        banned_count = c.fetchone()[0]
        conn.close()
    return jsonify({
        'total_users': total_users or 0,
        'total_balance': total_balance or 0,
        'total_games': total_games,
        'banned': banned_count,
        'jackpot': db_get_jackpot(),
        'history': [{'winner': r[0], 'card': r[1], 'prize': r[4], 'date': r[5]} for r in db_get_history(10)]
    })

@app.route('/api/admin/pending_withdrawals', methods=['POST'])
def api_admin_pending_withdrawals():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rows = db_get_pending_transactions()
    return jsonify({'pending': [{'id': r[0], 'user_id': r[1], 'type': r[2], 'amount': r[3], 'note': r[4], 'date': r[5]} for r in rows]})

@app.route('/api/admin/approve_withdraw', methods=['POST'])
def api_admin_approve_withdraw():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    tid = d.get('transaction_id')
    action = d.get('action')  # approve / reject
    if tid:
        db_update_transaction(tid, 'completed' if action == 'approve' else 'rejected')
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/add_scheduled', methods=['POST'])
def api_admin_add_scheduled():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    h = d.get('hour')
    m = d.get('minute')
    cid = d.get('chat_id')
    if h is not None and m is not None and cid:
        db_add_scheduled(h, m, cid)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/clear_scheduled', methods=['POST'])
def api_admin_clear_scheduled():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    db_clear_scheduled()
    return jsonify({'ok': True})

# ================= 🤖 የቦት =================

def get_main_panel(room_id=None):
    markup = InlineKeyboardMarkup()
    if room_id and room_id in rooms:
        markup.row(InlineKeyboardButton("🌐 የቢንጎ ገጽ ክፈት",
                     web_app=WebAppInfo(url=f"{WEBAPP_URL}/?room={room_id}")))
        markup.row(
            InlineKeyboardButton("▶️ ቁጥር ጥራ", callback_data=f"adm_begin_{room_id}"),
            InlineKeyboardButton("🛑 ጨዋታ አቁም", callback_data=f"adm_stop_{room_id}")
        )
        markup.row(
            InlineKeyboardButton("📊 ዳሽቦርድ", callback_data=f"adm_dash_{room_id}"),
            InlineKeyboardButton("⚙️ ቅንብሮች", callback_data="adm_settings")
        )
    else:
        markup.row(InlineKeyboardButton("🎮 አዲስ ክፍል ክፈት", callback_data="adm_new_room"))
        markup.row(InlineKeyboardButton("📋 የክፍት ክፍሎች", callback_data="adm_list_rooms"))
        markup.row(InlineKeyboardButton("⚙️ ቅንብሮች", callback_data="adm_settings"))
    return markup

@bot.message_handler(commands=['panel'])
def show_panel(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id,
        "🎛️ <b>እንኳን ደህና መጡ ውድ አስተዳዳሪ!</b>\n\n"
        "🙏 ይህ የእርስዎ የግል ማዕከል ነው።\n"
        "እባክህ የሚፈልጉትን ይምረጡ፦",
        reply_markup=get_main_panel(), parse_mode='HTML')

@bot.message_handler(commands=['balance'])
def show_balance(message):
    uid = message.from_user.id
    u = db_get_user(uid)
    if not u:
        u = db_create_user(uid, message.from_user.first_name)
    bot.reply_to(message,
        f"🙏 ውድ ተጫዋች {u['name']}!\n\n"
        f"💰 ባላንስ: <b>{u['balance']} ብር</b>\n"
        f"🏆 ድሎች: {u['total_wins']}\n"
        f"🎮 ጨዋታዎች: {u['total_games']}\n"
        f"🔗 የእርስዎ ኮድ: <code>{u['referral_code']}</code>\n\n"
        f"💚 ስለ ተሳትፎዎ እናመሰግናለን!",
        parse_mode='HTML')

@bot.message_handler(commands=['rules'])
def show_rules(message):
    rules = (
        "📜 <b>የጨዋታ ህጎች</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ ካርድ ዋጋ: " + db_get_setting('price') + "\n"
        "2️⃣ ጨዋታ ሲጀመር አዲስ መግባት አይቻልም\n"
        "3️⃣ አንድ ሰው " + db_get_setting('max_cards_per_player', '1') + " ካርድ ብቻ\n"
        "4️⃣ የማሸነፍ ዓይነት: " + db_get_setting('win_pattern', 'single') + "\n"
        "5️⃣ አነስተኛ ማውጣት: " + db_get_setting('min_withdraw', '100') + " ብር\n"
        "6️⃣ የቀን ስጦታ: " + db_get_setting('daily_bonus', '10') + " ብር\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🙏 መልካም ጨዋታ! 💚"
    )
    bot.send_message(message.chat.id, rules, parse_mode='HTML')

@bot.message_handler(commands=['daily'])
def daily_bonus_cmd(message):
    uid = message.from_user.id
    u = db_get_user(uid)
    if not u:
        u = db_create_user(uid, message.from_user.first_name)
    today = datetime.now().strftime('%Y-%m-%d')
    if u['daily_last'] == today:
        bot.reply_to(message, "🙏 ውድ ተጫዋች፣ የዛሬ ስጦታዎን ተቀብለዋል። ነገ ይምጡ! 💚")
        return
    bonus = int(db_get_setting('daily_bonus', '10'))
    db_update_balance(uid, bonus)
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET daily_last=? WHERE user_id=?", (today, uid))
        conn.commit()
        conn.close()
    bot.reply_to(message, f"🎁 ውድ ተጫዋች! +{bonus} ብር የቀን ስጦታ አግኝተዋል።\n💚 መልካም ቀን!")

@bot.message_handler(commands=['feedback'])
def feedback_cmd(message):
    msg = message.text.replace('/feedback', '').strip()
    if not msg:
        bot.reply_to(message, "🙏 እባክህ እንዲህ ጻፍ: /feedback አስተያየትህ")
        return
    uid = message.from_user.id
    u = db_get_user(uid) or db_create_user(uid, message.from_user.first_name)
    db_save_feedback(uid, u['name'], msg)
    try:
        bot.send_message(ADMIN_ID, f"💬 <b>አስተያየት</b>\n👤 {u['name']}\n📝 {msg}", parse_mode='HTML')
    except: pass
    bot.reply_to(message, "🙏 አስተያየትህ ደርሶናል! ስለ ተሳትፎህ እናመሰግናለን! 💚")

@bot.message_handler(commands=['withdraw'])
def withdraw_cmd(message):
    try:
        parts = message.text.split()
        amount = int(parts[1])
        account = ' '.join(parts[2:]) if len(parts) > 2 else ''
    except:
        bot.reply_to(message, "🙏 እባክህ እንዲህ ጻፍ: /withdraw 100 CBE1000123456")
        return
    uid = message.from_user.id
    u = db_get_user(uid) or db_create_user(uid, message.from_user.first_name)
    min_w = int(db_get_setting('min_withdraw', '100'))
    if amount < min_w:
        bot.reply_to(message, f"🙏 አነስተኛው ማውጣት {min_w} ብር ነው።")
        return
    if u['balance'] < amount:
        bot.reply_to(message, f"🙏 በቂ ባላንስ የለህም። ({u['balance']} ብር)")
        return
    if not account:
        bot.reply_to(message, "🙏 የባንክ አካውንትህን አስገባ።")
        return
    db_update_balance(uid, -amount)
    db_add_transaction(uid, 'withdraw', -amount, 'pending', account)
    try:
        bot.send_message(ADMIN_ID,
            f"💸 <b>የገንዘብ ማውጣት ጥያቄ</b>\n👤 {u['name']}\n🆔 {uid}\n💰 {amount} ብር\n🏦 {account}",
            parse_mode='HTML')
    except: pass
    bot.reply_to(message, f"🙏 ጥያቄህ ለአስተዳዳሪው ተልኳል። {amount} ብር ወደ {account} ይላካል።")

@bot.message_handler(commands=['addbalance'])
def add_balance_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        amt = int(parts[2])
        new_bal = db_update_balance(uid, amt)
        db_add_transaction(uid, 'admin_add', amt, 'completed', 'በአስተዳዳሪ')
        bot.reply_to(message, f"✅ በአክብሮት ተጨምሯል። ባላንስ: {new_bal} ብር")
        try:
            bot.send_message(uid, f"🙏 ውድ ተጫዋች!\n💰 ባላንስዎ +{amt} ብር ተጨምሯል!\n💵 አሁን: {new_bal} ብር\n\n💚 እናመሰግናለን!")
        except: pass
    except:
        bot.reply_to(message, "🙏 እባክህ እንዲህ ጻፍ: /addbalance USER_ID AMOUNT")

@bot.message_handler(commands=['jackpot'])
def jackpot_cmd(message):
    jp = db_get_jackpot()
    bot.reply_to(message, f"🎰 የአሁን ጃክፖት: <b>{jp} ብር</b>\n\n🌟 ሁሉንም ካርድ ሞልቶ ይውሰዱት!", parse_mode='HTML')

@bot.message_handler(commands=['leaderboard'])
def leaderboard_cmd(message):
    rows = db_get_leaderboard(10)
    text = "🏆 <b>የአሸናፊዎች ሰንጠረዥ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {r[1]} — {r[2]} ድሎች\n"
    if not rows: text += "🙏 እስካሁን አሸናፊ የለም።"
    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
def handle_admin(call):
    global room_counter
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🙏 ይቅርታ፣ ይህ ለአስተዳዳሪ ብቻ ነው።")
        return
    data = call.data
    chat_id = call.message.chat.id

    if data == "adm_new_room":
        rid = room_counter
        room_counter += 1
        rooms[rid] = BingoGame(rid)
        rooms[rid].is_active = True
        rooms[rid].join_open = True
        rooms[rid].game_state = 'joining'
        rooms[rid].chat_id = chat_id
        rooms[rid].join_deadline = time.time() + 120
        bot.send_message(chat_id,
            f"🌟 <b>እንኳን ደህና መጡ ውድ ተጫዋቾች!</b> 🌟\n"
            f"🎮 <b>{rooms[rid].game_name} - ክፍል {rid}</b> ተከፍቷል!\n"
            f"💰 {db_get_setting('price')}\n⏱️ 2 ደቂቃ\n\n"
            f"🙏 የቢንጎ ገጹን ክፈቱ!",
            reply_markup=get_main_panel(rid), parse_mode='HTML')

    elif data == "adm_list_rooms":
        text = "📋 <b>የክፍት ክፍሎች</b>\n\n"
        for rid, r in rooms.items():
            text += f"{'🟢' if r.is_active else '🔴'} ክፍል {rid}: {len(r.approved_players)} ተጫዋቾች\n"
        if not rooms: text = "🙏 እስካሁን ክፍል የለም።"
        bot.send_message(chat_id, text, parse_mode='HTML')

    elif data.startswith("adm_begin_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        if len(r.approved_players) == 0:
            bot.answer_callback_query(call.id, "🙏 ተጫዋች የለም።")
            return
        r.join_open = False
        r.game_state = 'playing'
        r.started_at = time.time()
        threading.Thread(target=auto_call_loop, args=(rid,), daemon=True).start()
        bot.answer_callback_query(call.id, "▶️ ተጀምሯል")
        bot.send_message(chat_id, f"▶️ ክፍል {rid} ተጀምሯል! መልካም እድል! 🍀")

    elif data.startswith("adm_stop_"):
        rid = int(data.split('_')[2])
        if rid in rooms:
            rooms[rid].is_active = False
            rooms[rid].game_state = 'finished'
        bot.answer_callback_query(call.id, "🛑 ቆሟል")
        bot.send_message(chat_id, f"🛑 ክፍል {rid} ቆሟል።")

    elif data.startswith("adm_dash_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        text = f"📊 <b>ዳሽቦርድ - ክፍል {rid}</b>\n\n"
        text += f"🎮 {r.game_state}\n👥 {len(r.approved_players)}\n"
        text += f"📢 የተጠሩ: {len(r.called_numbers)}\n📦 የቀሩ: {len(r.available_numbers)}\n"
        text += f"🎰 ጃክፖት: {db_get_jackpot()} ብር"
        bot.send_message(chat_id, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "📊")

    elif data == "adm_settings":
        bot.send_message(chat_id,
            "⚙️ <b>ቅንብሮች</b>\n\n"
            f"💰 ዋጋ: {db_get_setting('price')}\n"
            f"🏦 {db_get_setting('account')}\n"
            f"⏱️ ፍጥነት: {db_get_setting('call_interval')}s\n"
            f"💹 ኮሚሽን: {db_get_setting('commission')}%\n"
            f"🎁 የቀን ስጦታ: {db_get_setting('daily_bonus')} ብር\n"
            f"🎫 ከፍተኛ ካርድ: {db_get_setting('max_cards_per_player')}\n"
            f"🏆 ማሸነፍ: {db_get_setting('win_pattern')}\n"
            f"🎨 ገጽታ: {db_get_setting('theme')}\n\n"
            "🙏 ለመቀየር ትዕዛዞቹን ተጠቀም።",
            parse_mode='HTML')

def auto_call_loop(room_id):
    r = rooms.get(room_id)
    if not r: return
    interval = int(db_get_setting('call_interval', '5'))
    time_limit = int(db_get_setting('game_time_limit', '30')) * 60
    start = time.time()
    while r.is_active:
        time.sleep(interval)
        if not r.is_active: break
        if r.paused: continue
        if time.time() - start > time_limit:
            if r.chat_id:
                try: bot.send_message(r.chat_id, "⏰ ጊዜው አልቋል። ጨዋታው አብቅቷል።")
                except: pass
            r.is_active = False
            r.game_state = 'finished'
            break
        if not r.available_numbers:
            if r.chat_id:
                try: bot.send_message(r.chat_id, "🙏 ሁሉም ቁጥሮች ተጠርተዋል። ጨዋታው አብቅቷል።")
                except: pass
            r.is_active = False
            r.game_state = 'finished'
            break
        num = r.available_numbers.pop()
        r.called_numbers.append(num)
        r.last_called = num
        if r.chat_id:
            try:
                bot.send_message(r.chat_id,
                    f"🎯 <b>የተጠራ ቁጥር:</b> {num}\n"
                    f"📜 <i>የመጨረሻ 5:</i> {', '.join(map(str, r.called_numbers[-5:]))}",
                    parse_mode='HTML')
            except: pass

        new_winners = []
        for uid, cards in r.players.items():
            if uid in r.approved_players and uid not in r.winners:
                for card in cards:
                    if r.check_bingo(card, r.called_numbers):
                        r.winners.append(uid)
                        new_winners.append(uid)
                        break
        if new_winners:
            for uid in new_winners:
                name = get_user_name(uid)
                card_nums = r.player_card_numbers.get(uid, [])
                card_num = card_nums[0] if card_nums else "?"
                r.winner_name = name
                r.winner_card = card_num
                total_pool = len(r.approved_players) * get_price_int()
                jp = db_get_jackpot()
                commission = int(total_pool * int(db_get_setting('commission', '15')) / 100)
                prize = total_pool - commission + jp
                db_update_balance(uid, prize)
                db_add_transaction(uid, 'win', prize, 'completed', f'ካርድ #{card_num}')
                db_add_game(uid, name, card_num, room_id, len(r.called_numbers), prize)
                db_reset_jackpot()
                msg = (
                    f"🌟🌟🌟 <b>ቢንጎ!</b> 🌟🌟🌟\n"
                    f"🎊 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🎊\n"
                    f"👤 <b>አሸናፊ:</b> {name}\n"
                    f"🎫 <b>ካርድ:</b> #{card_num}\n"
                    f"🎯 <b>ጥሪዎች:</b> {len(r.called_numbers)}\n"
                    f"💰 <b>ሽልማት:</b> {prize} ብር\n"
                    f"🎰 <b>ጃክፖት:</b> {jp} ብር\n\n"
                    f"🙏 <i>ስለ ተሳትፎህ/ሽ እናመሰግናለን!</i>"
                )
                if r.chat_id:
                    try: bot.send_message(r.chat_id, msg, parse_mode='HTML')
                    except: pass
                try: bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
                except: pass
                try:
                    bot.send_message(uid,
                        f"🌟 <b>እንኳን ደስ አለህ/ሽ!</b> 🌟\n\n"
                        f"💰 ሽልማት: <b>{prize} ብር</b>\n🎫 ካርድ: <b>#{card_num}</b>\n\n"
                        f"🙏 እናመሰግናለን!",
                        parse_mode='HTML')
                except: pass
            r.is_active = False
            r.game_state = 'finished'
            break

# ================= 📥 የክፍያ ስክሪንሾት =================

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = message.from_user.id
    u = db_get_user(uid) or db_create_user(uid, message.from_user.first_name)
    if u['banned']: return
    price = get_price_int()
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ አጽድቅ", callback_data=f"bal_approve_{uid}"),
        InlineKeyboardButton("❌ ውድቅ", callback_data=f"bal_reject_{uid}")
    )
    bot.send_message(ADMIN_ID,
        f"🔔 <b>ውድ አስተዳዳሪ፣ አዲስ የክፍያ ስክሪንሾት</b>\n"
        f"👤 {u['name']}\n🆔 {uid}\n"
        f"💰 ባላንስ: {u['balance']} ብር\n"
        f"💵 ሊጨመር: +{price} ብር",
        reply_markup=markup, parse_mode='HTML')
    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    bot.reply_to(message,
        f"🙏 ውድ ተጫዋች {u['name']}!\n\n"
        f"✅ ስክሪንሾትዎ በአክብሮት ለአስተዳዳሪው ተልኳል።\n"
        f"💰 የአሁን ባላንስ: {u['balance']} ብር\n\n"
        f"💚 ስለ ትዕግስትዎ እናመሰግናለን!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('bal_'))
def handle_bal_approve(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🙏 ለአስተዳዳሪ ብቻ።")
        return
    parts = call.data.split('_')
    action = parts[1]
    uid = int(parts[2])
    price = get_price_int()
    if action == 'approve':
        new_bal = db_update_balance(uid, price)
        db_add_transaction(uid, 'deposit', price, 'completed', 'ክፍያ ተረጋግጧል')
        bot.answer_callback_query(call.id, "✅")
        try:
            bot.send_message(uid,
                f"🌟 <b>ውድ ተጫዋች! ክፍያዎ ተረጋግጧል!</b>\n\n"
                f"💰 +{price} ብር\n💵 አሁን: <b>{new_bal} ብር</b>\n\n"
                f"🎫 ካርድ መምረጥ ይችላሉ!\n🍀 መልካም እድል!",
                parse_mode='HTML')
        except: pass
    else:
        bot.answer_callback_query(call.id, "❌")
        try:
            bot.send_message(uid, "🙏 ውድ ተጫዋች፣ ክፍያዎ ውድቅ ሆኗል። እባክህ እንደገና ሞክር።")
        except: pass

# ================= ⏰ SCHEDULED GAMES =================

def scheduler_loop():
    while True:
        try:
            now = datetime.now()
            for s in db_get_scheduled():
                if s[1] == now.hour and s[2] == now.minute:
                    global room_counter
                    rid = room_counter
                    room_counter += 1
                    rooms[rid] = BingoGame(rid)
                    rooms[rid].is_active = True
                    rooms[rid].join_open = True
                    rooms[rid].game_state = 'joining'
                    rooms[rid].chat_id = s[3]
                    rooms[rid].join_deadline = time.time() + 120
                    try:
                        bot.send_message(s[3],
                            f"🌟 <b>ጊዜው ደርሷል!</b> 🌟\n🎮 {rooms[rid].game_name} - ክፍል {rid}\n🙏 ገጹን ክፈቱ!",
                            reply_markup=get_main_panel(rid), parse_mode='HTML')
                    except: pass
        except: pass
        time.sleep(60)

# ================= 🚀 =================

def run_flask():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    init_db()
    Thread(target=run_flask, daemon=True).start()
    Thread(target=scheduler_loop, daemon=True).start()
    print("🌟 ሰርቨሩ ተጀምሯል...")
    bot.polling(none_stop=True)
