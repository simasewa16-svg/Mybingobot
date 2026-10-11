import telebot
import random
import threading
import time
import os
import sqlite3
from datetime import datetime
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
            user_id INTEGER PRIMARY KEY, name TEXT, balance INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0, referral_code TEXT, referred_by INTEGER DEFAULT 0,
            daily_last TEXT, total_wins INTEGER DEFAULT 0, total_games INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT,
            amount INTEGER, status TEXT, note TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, winner_id INTEGER, winner_name TEXT,
            card_num INTEGER, room_id INTEGER, called_count INTEGER, prize INTEGER,
            pattern TEXT, marked TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS jackpot (id INTEGER PRIMARY KEY CHECK (id = 1), amount INTEGER DEFAULT 0)''')
        c.execute("INSERT OR IGNORE INTO jackpot (id, amount) VALUES (1, 0)")
        defaults = {
            'price': '50 ብር', 'account': 'CBE 1000123456789', 'call_interval': '5',
            'commission': '15', 'jackpot_percent': '10', 'min_withdraw': '100',
            'daily_bonus': '10', 'max_cards_per_player': '2',
            'game_name': 'ዘና ቢንጎ ከድጎ', 'win_pattern': 'single', 'game_time_limit': '30'
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
        conn.close()

def db_setting(key, default=''):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone(); conn.close()
        return row[0] if row else default

def db_set_setting(key, value):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit(); conn.close()

def db_user(uid):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id, name, balance, banned, referral_code, daily_last, total_wins, total_games FROM users WHERE user_id=?", (uid,))
        row = c.fetchone(); conn.close()
        if row:
            return {'user_id': row[0], 'name': row[1], 'balance': row[2], 'banned': bool(row[3]),
                    'referral_code': row[4], 'daily_last': row[5], 'total_wins': row[6], 'total_games': row[7]}
    return None

def db_new_user(uid, name, ref=0):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        code = f"REF{uid % 100000}{random.randint(100, 999)}"
        c.execute("INSERT OR IGNORE INTO users (user_id, name, referral_code, referred_by) VALUES (?, ?, ?, ?)", (uid, name, code, ref))
        conn.commit(); conn.close()
    return db_user(uid)

def db_update_name(uid, name):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET name=? WHERE user_id=?", (name, uid))
        conn.commit(); conn.close()

def db_balance_delta(uid, delta):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, uid))
        conn.commit()
        c.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        row = c.fetchone(); conn.close()
        return row[0] if row else 0

def db_set_balance(uid, amount):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, uid))
        conn.commit(); conn.close()

def db_ban(uid, banned):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, uid))
        conn.commit(); conn.close()

def db_tx(uid, typ, amount, status='pending', note=''):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO transactions (user_id, type, amount, status, note, date) VALUES (?, ?, ?, ?, ?, ?)",
                  (uid, typ, amount, status, note, datetime.now().isoformat()))
        conn.commit(); conn.close()

def db_pending_tx():
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT id, user_id, type, amount, note, date FROM transactions WHERE status='pending' ORDER BY id DESC LIMIT 50")
        rows = c.fetchall(); conn.close()
        return rows

def db_update_tx(tid, status):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE transactions SET status=? WHERE id=?", (status, tid))
        conn.commit(); conn.close()

def db_add_game(wid, name, cn, rid, cc, prize, pattern, marked):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO game_history (winner_id, winner_name, card_num, room_id, called_count, prize, pattern, marked, date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (wid, name, cn, rid, cc, prize, pattern, marked, datetime.now().isoformat()))
        c.execute("UPDATE users SET total_wins = total_wins + 1 WHERE user_id=?", (wid,))
        c.execute("UPDATE users SET total_games = total_games + 1")
        conn.commit(); conn.close()

def db_history(limit=20):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT winner_name, card_num, room_id, called_count, prize, pattern, marked, date FROM game_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall(); conn.close()
        return rows

def db_leaders(limit=10):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, total_wins, total_games FROM users ORDER BY total_wins DESC LIMIT ?", (limit,))
        rows = c.fetchall(); conn.close()
        return rows

def db_jackpot():
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT amount FROM jackpot WHERE id=1")
        row = c.fetchone(); conn.close()
        return row[0] if row else 0

def db_jackpot_add(amount):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE jackpot SET amount = amount + ? WHERE id=1", (amount,))
        conn.commit()
        c.execute("SELECT amount FROM jackpot WHERE id=1")
        row = c.fetchone(); conn.close()
        return row[0] if row else 0

def db_jackpot_reset():
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE jackpot SET amount=0 WHERE id=1")
        conn.commit(); conn.close()

def db_all_users():
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE banned=0")
        rows = [r[0] for r in c.fetchall()]; conn.close()
        return rows

# ================= 📦 የጨዋታ ክፍል =================

class BingoGame:
    def __init__(self, rid):
        self.room_id = rid
        self.players = {}
        self.player_card_numbers = {}
        self.called_numbers = []
        self.available_numbers = list(range(1, 91))
        random.shuffle(self.available_numbers)
        self.is_active = False
        self.join_open = False
        self.game_state = 'idle'
        self.winners = []
        self.card_pool = self.gen_cards(200)
        self.taken_cards = set()
        self.approved_players = set()
        self.chat_id = None
        self.join_deadline = None
        self.game_name = db_setting('game_name', 'ዘና ቢንጎ ከድጎ')
        self.last_called = None
        self.paused = False
        self.winner_name = None
        self.winner_card = None
        self.winner_prize = 0
        self.winner_pattern = None
        self.winner_marked = []

    def gen_one(self):
        cols = [list(range(1, 19)), list(range(19, 37)), list(range(37, 55)),
                list(range(55, 73)), list(range(73, 91))]
        card = [random.sample(c, 5) for c in cols]
        m = [[card[c][r] for c in range(5)] for r in range(5)]
        m[2][2] = "⭐"
        return m

    def gen_cards(self, n):
        pool, seen = [], set()
        while len(pool) < n:
            c = self.gen_one()
            if str(c) not in seen:
                seen.add(str(c)); pool.append(c)
        return pool

    def check_bingo(self, card, called):
        """የተዘጋውን መስመር ስም ይመልሳል (ወይም None)"""
        cs = set(called)
        # Rows
        for i, row in enumerate(card):
            if all(str(n) == "⭐" or n in cs for n in row):
                return f"Row {i+1} (አግድም #{i+1})"
        # Columns
        for c in range(5):
            if all(str(card[r][c]) == "⭐" or card[r][c] in cs for r in range(5)):
                L = ["B", "I", "N", "G", "O"]
                return f"Column {L[c]} (ቀጥ ያለ {L[c]})"
        # Main diagonal
        if all(str(card[i][i]) == "⭐" or card[i][i] in cs for i in range(5)):
            return "Diagonal ↘ (ሰያፍ ↘)"
        # Anti-diagonal
        if all(str(card[i][4-i]) == "⭐" or card[i][4-i] in cs for i in range(5)):
            return "Diagonal ↙ (ሰያፍ ↙)"
        pattern = db_setting('win_pattern', 'single')
        if pattern == 'fullhouse':
            if all(str(card[r][c]) == "⭐" or card[r][c] in cs for r in range(5) for c in range(5)):
                return "Full House (ሙሉ ካርድ)"
        if pattern == 'corners':
            corners = [(0,0), (0,4), (4,0), (4,4)]
            if all(str(card[r][c]) == "⭐" or card[r][c] in cs for r, c in corners):
                return "Corners (አራት ማዕዘን)"
        return None

    def get_marked_numbers(self, card, called):
        """በካርዱ ላይ የተዘጉ ቁጥሮችን ይመልሳል"""
        cs = set(called)
        L = ["B", "I", "N", "G", "O"]
        marked = []
        for r in range(5):
            for c in range(5):
                n = card[r][c]
                if n == "⭐":
                    marked.append("⭐ (ነፃ)")
                elif n in cs:
                    marked.append(f"{L[c]}-{n}")
        return marked

    def get_marked_numbers_by_line(self, card, called, pattern):
        """በተዘጋው መስመር ላይ ያሉ ቁጥሮችን ይመልሳል"""
        cs = set(called)
        L = ["B", "I", "N", "G", "O"]
        nums = []
        if pattern and pattern.startswith("Row"):
            i = int(pattern.split()[1]) - 1
            for c in range(5):
                n = card[i][c]
                nums.append("⭐" if n == "⭐" else f"{L[c]}-{n}")
        elif pattern and pattern.startswith("Column"):
            c_idx = L.index(pattern.split()[2])
            for r in range(5):
                n = card[r][c_idx]
                nums.append("⭐" if n == "⭐" else f"{L[c_idx]}-{n}")
        elif pattern and "↘" in pattern:
            for i in range(5):
                n = card[i][i]
                nums.append("⭐" if n == "⭐" else f"{L[i]}-{n}")
        elif pattern and "↙" in pattern:
            for i in range(5):
                n = card[i][4-i]
                nums.append("⭐" if n == "⭐" else f"{L[4-i]}-{n}")
        return nums

rooms = {}
room_counter = 1
name_cache = {}
rate_limit = {}

def get_name(uid):
    if uid in name_cache: return name_cache[uid]
    u = db_user(uid)
    if u and u['name']:
        name_cache[uid] = u['name']; return u['name']
    try:
        info = bot.get_chat(uid)
        n = f"@{info.username}" if info.username else info.first_name
    except: n = "ተጫዋች"
    name_cache[uid] = n; return n

def price_int():
    try: return int(''.join(filter(str.isdigit, db_setting('price', '50 ብር'))))
    except: return 50

def rate_ok(uid, sec=1):
    now = time.time()
    if uid in rate_limit and now - rate_limit[uid] < sec: return False
    rate_limit[uid] = now; return True

def process_winner(uid, r):
    """የአሸናፊ ሂደት - ጽሑፍ ይፈጥራል"""
    name = get_name(uid)
    cnums = r.player_card_numbers.get(uid, [])
    cn = cnums[0] if cnums else "?"
    r.winner_name = name
    r.winner_card = cn
    total = len(r.approved_players) * price_int()
    jp = db_jackpot()
    comm = int(total * int(db_setting('commission', '15')) / 100)
    prize = total - comm + jp
    r.winner_prize = prize
    db_balance_delta(uid, prize)
    db_tx(uid, 'win', prize, 'completed', f'ካርድ #{cn} ድል')
    db_add_game(uid, name, cn, r.room_id, len(r.called_numbers), prize, r.winner_pattern, ", ".join(r.winner_marked))
    db_jackpot_reset()
    return name, cn, prize, jp

def winner_msg(name, cn, prize, jp, pattern, line_nums, all_marked, called_count):
    line_str = " , ".join(line_nums) if line_nums else ""
    all_str = ", ".join(all_marked) if all_marked else "—"
    return (
        f"🌟🌟🌟 <b>ቢንጎ!</b> 🌟🌟🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎊 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🎊\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ውድ አሸናፊ:</b> {name}\n"
        f"🎫 <b>ያሸነፍክበት ካርድ:</b> #{cn}\n"
        f"🏆 <b>ያሸነፍክበት መስመር:</b> {pattern}\n"
        f"📌 <b>የዘጋህባቸው ቁጥሮች:</b>\n  {line_str}\n"
        f"🎯 <b>በካርድህ ላይ የተዘጉ ሁሉም:</b>\n  {all_str}\n"
        f"📊 <b>ጠቅላላ ጥሪዎች:</b> {called_count}\n"
        f"💰 <b>ያገኙት ሽልማት:</b> {prize} ብር\n"
        f"🎰 <b>ጃክፖት:</b> {jp} ብር\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🙏 <i>ስለ ተሳትፎህ/ሽ ከልብ እናመሰግናለን!</i>"
    )

# ================= 🌐 API =================

@app.route('/')
def index(): return render_template('index.html')

@app.route('/health')
def health(): return "OK", 200

@app.route('/api/auto_room')
def api_auto_room():
    global room_counter
    for rid, r in rooms.items():
        if r.is_active and r.game_state in ('joining', 'playing'):
            return jsonify({'ok': True, 'room_id': rid, 'created': False})
    rid = room_counter; room_counter += 1
    rooms[rid] = BingoGame(rid)
    rooms[rid].is_active = True; rooms[rid].join_open = True
    rooms[rid].game_state = 'joining'
    rooms[rid].join_deadline = time.time() + 120
    return jsonify({'ok': True, 'room_id': rid, 'created': True})

@app.route('/api/room/<int:rid>')
def api_room(rid):
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    now = time.time(); tl = 0
    if r.join_deadline and r.join_open:
        tl = max(0, int(r.join_deadline - now))
        if tl == 0 and r.game_state == 'joining': r.join_open = False
    return jsonify({
        'room_id': rid, 'game_name': r.game_name, 'game_state': r.game_state,
        'is_active': r.is_active, 'join_open': r.join_open, 'time_left': tl,
        'players': len(r.approved_players), 'called': r.called_numbers,
        'called_count': len(r.called_numbers), 'remaining': len(r.available_numbers),
        'price': db_setting('price', '50 ብር'), 'winners': r.winners,
        'winner_name': r.winner_name, 'winner_card': r.winner_card,
        'winner_prize': r.winner_prize,
        'winner_pattern': r.winner_pattern,
        'winner_marked': r.winner_marked,
        'taken_cards': list(r.taken_cards), 'total_cards': len(r.card_pool),
        'last_called': r.last_called, 'paused': r.paused,
        'jackpot': db_jackpot(),
        'max_cards': int(db_setting('max_cards_per_player', '2'))
    })

@app.route('/api/user_info', methods=['POST'])
def api_user_info():
    d = request.json; uid = d.get('user_id'); name = d.get('name', 'ተጫዋች')
    ref = d.get('referred_by', 0)
    u = db_user(uid)
    if not u:
        u = db_new_user(uid, name, ref)
        if ref and ref != uid and db_user(ref):
            db_balance_delta(ref, 20)
            db_tx(ref, 'referral', 20, 'completed', 'ጓደኛ ጋበዘ')
            try: bot.send_message(ref, "🎉 +20 ብር! 💚")
            except: pass
    elif u['name'] != name:
        db_update_name(uid, name); u['name'] = name
    return jsonify({
        'user_id': uid, 'name': u['name'], 'balance': u['balance'],
        'is_admin': uid == ADMIN_ID, 'banned': u['banned'],
        'referral_code': u['referral_code'], 'total_wins': u['total_wins'],
        'total_games': u['total_games'],
        'account': db_setting('account', ''), 'price': db_setting('price', '50 ብር'),
        'price_int': price_int(), 'max_cards': int(db_setting('max_cards_per_player', '2'))
    })

@app.route('/api/daily_bonus', methods=['POST'])
def api_daily():
    d = request.json; uid = d.get('user_id')
    u = db_user(uid)
    if not u: return jsonify({'ok': False, 'msg': '🙏 ይቅርታ፣ መጀመሪያ ገጹን ክፈት።'})
    today = datetime.now().strftime('%Y-%m-%d')
    if u['daily_last'] == today:
        return jsonify({'ok': False, 'msg': '🙏 የዛሬ ስጦታዎን ተቀብለዋል። ነገ ይምጡ! 💚'})
    bonus = int(db_setting('daily_bonus', '10'))
    db_balance_delta(uid, bonus)
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET daily_last=? WHERE user_id=?", (today, uid))
        conn.commit(); conn.close()
    db_tx(uid, 'daily_bonus', bonus, 'completed', 'የቀን ስጦታ')
    return jsonify({'ok': True, 'bonus': bonus, 'msg': f'🎁 +{bonus} ብር የቀን ስጦታ! 💚'})

@app.route('/api/join', methods=['POST'])
def api_join():
    d = request.json; uid = d.get('user_id'); rid = d.get('room_id'); cn = d.get('card_num')
    u = db_user(uid)
    if not u: return jsonify({'ok': False, 'msg': '🙏 መጀመሪያ ገጹን ክፈት።'})
    if u['banned']: return jsonify({'ok': False, 'msg': '🙏 ፈቃድ የለህም።'})
    if not rate_ok(uid, 0.5): return jsonify({'ok': False, 'msg': '🙏 ትንሽ ታገስ።'})
    if rid not in rooms: return jsonify({'ok': False, 'msg': '🙏 ክፍሉ አልተገኘም።'})
    r = rooms[rid]
    if r.game_state in ('playing', 'finished'):
        return jsonify({'ok': False, 'msg': '🙏 ጨዋታው ተጀምሯል። በትዕግስት ተጠብቅ።'})
    if not r.join_open: return jsonify({'ok': False, 'msg': '⏰ የመግቢያ ጊዜ አልፏል።'})
    max_c = int(db_setting('max_cards_per_player', '2'))
    if uid in r.players and len(r.players[uid]) >= max_c:
        return jsonify({'ok': False, 'msg': f'🙏 ከፍተኛው {max_c} ካርድ ብቻ።'})
    ci = cn - 1
    if ci < 0 or ci >= len(r.card_pool):
        return jsonify({'ok': False, 'msg': '🙏 ካርድ አልተገኘም።'})
    if ci in r.taken_cards:
        return jsonify({'ok': False, 'msg': f'🙏 ካርድ {cn} ተመርጧል። ሌላ ምረጥ።'})
    price = price_int()
    if u['balance'] < price:
        return jsonify({'ok': False, 'need_payment': True, 'balance': u['balance'],
                        'price': price, 'account': db_setting('account', ''),
                        'msg': f'🙏 በቂ ባላንስ የለህም።\n💰 {u["balance"]} ብር\n💵 {price} ብር\n🏦 {db_setting("account", "")}'})
    nb = db_balance_delta(uid, -price)
    db_tx(uid, 'buy_card', -price, 'completed', f'ካርድ #{cn}')
    r.taken_cards.add(ci)
    if uid not in r.players:
        r.players[uid] = []; r.player_card_numbers[uid] = []
    r.players[uid].append(r.card_pool[ci])
    r.player_card_numbers[uid].append(cn)
    r.approved_players.add(uid)
    db_update_name(uid, get_name(uid))
    db_jackpot_add(int(price * int(db_setting('jackpot_percent', '10')) / 100))
    try:
        bot.send_message(ADMIN_ID, f"🎫 <b>ካርድ ተመረጠ</b>\n👤 {get_name(uid)}\n🎫 #{cn}", parse_mode='HTML')
    except: pass
    return jsonify({'ok': True, 'card': r.card_pool[ci], 'card_num': cn, 'new_balance': nb})

@app.route('/api/mycard', methods=['POST'])
def api_mycard():
    d = request.json; uid = d.get('user_id'); rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if uid not in r.players: return jsonify({'error': 'no card'}), 404
    cards = r.players[uid]; cs = set(r.called_numbers)
    marked = []
    for card in cards:
        m = []
        for row in card:
            nr = []
            for num in row:
                if num == "⭐": nr.append("⭐")
                elif num in cs: nr.append(f"✅{num}")
                else: nr.append(str(num))
            m.append(nr)
        marked.append(m)
    u = db_user(uid)
    return jsonify({'cards': marked, 'card_nums': r.player_card_numbers.get(uid, []),
                    'called': r.called_numbers, 'balance': u['balance'] if u else 0})

@app.route('/api/bingo', methods=['POST'])
def api_bingo():
    d = request.json; uid = d.get('user_id'); rid = d.get('room_id')
    if rid not in rooms: return jsonify({'ok': False, 'msg': '🙏 ክፍሉ አልተገኘም።'})
    r = rooms[rid]
    if uid not in r.approved_players: return jsonify({'ok': False, 'msg': '🙏 ገና አልተጸደቅህም።'})
    if uid in r.winners: return jsonify({'ok': False, 'msg': '🌟 ቀድመህ አሸንፈሃል!'})
    if not r.is_active: return jsonify({'ok': False, 'msg': '🙏 ጨዋታው አልተጀመረም።'})
    cards = r.players.get(uid, [])
    for card in cards:
        pattern = r.check_bingo(card, r.called_numbers)
        if pattern:
            r.winners.append(uid)
            r.winner_pattern = pattern
            r.winner_marked = r.get_marked_numbers(card, r.called_numbers)
            line_nums = r.get_marked_numbers_by_line(card, r.called_numbers, pattern)
            name, cn, prize, jp = process_winner(uid, r)
            msg = winner_msg(name, cn, prize, jp, pattern, line_nums, r.winner_marked, len(r.called_numbers))
            if r.chat_id:
                try: bot.send_message(r.chat_id, msg, parse_mode='HTML')
                except: pass
            try: bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
            except: pass
            try:
                bot.send_message(uid,
                    f"🌟 <b>እንኳን ደስ አለህ/ሽ!</b>\n💰 {prize} ብር\n🎫 #{cn}\n🏆 {pattern}\n🙏", parse_mode='HTML')
            except: pass
            r.is_active = False; r.game_state = 'finished'
            threading.Thread(target=auto_restart_room, args=(rid,), daemon=True).start()
            return jsonify({'ok': True, 'winner': name, 'card_num': cn, 'prize': prize,
                            'pattern': pattern, 'line_nums': line_nums, 'marked': r.winner_marked})
    return jsonify({'ok': False, 'msg': '🙏 ገና አልተሸነፍክም። ካርድህን በጥንቃቄ ተመልከት።'})

@app.route('/api/leaderboard')
def api_lb():
    rows = db_leaders(10)
    return jsonify({'leaders': [{'name': r[0], 'wins': r[1], 'games': r[2]} for r in rows]})

@app.route('/api/history')
def api_hist():
    rows = db_history(20)
    return jsonify({'history': [{'winner': r[0], 'card': r[1], 'room': r[2], 'called': r[3],
                                  'prize': r[4], 'pattern': r[5], 'marked': r[6], 'date': r[7]} for r in rows]})

@app.route('/api/withdraw', methods=['POST'])
def api_withdraw():
    d = request.json; uid = d.get('user_id'); amt = int(d.get('amount', 0)); acc = d.get('account', '').strip()
    u = db_user(uid)
    if not u: return jsonify({'ok': False, 'msg': '🙏 ይቅርታ።'})
    min_w = int(db_setting('min_withdraw', '100'))
    if amt < min_w: return jsonify({'ok': False, 'msg': f'🙏 አነስተኛው {min_w} ብር ነው።'})
    if u['balance'] < amt: return jsonify({'ok': False, 'msg': f'🙏 በቂ ባላንስ የለህም። ({u["balance"]} ብር)'})
    if not acc: return jsonify({'ok': False, 'msg': '🙏 አካውንትህን አስገባ።'})
    db_balance_delta(uid, -amt)
    db_tx(uid, 'withdraw', -amt, 'pending', acc)
    try: bot.send_message(ADMIN_ID, f"💸 <b>ማውጣት</b>\n👤 {u['name']}\n💰 {amt} ብር\n🏦 {acc}", parse_mode='HTML')
    except: pass
    return jsonify({'ok': True, 'msg': f'🙏 ጥያቄህ ተልኳል። {amt} ብር ወደ {acc} ይላካል።'})

# ================= 🔐 ADMIN API =================

def is_admin(d): return d.get('user_id') == ADMIN_ID

@app.route('/api/admin/create_room', methods=['POST'])
def adm_create_room():
    global room_counter
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    cid = d.get('chat_id')
    rid = room_counter; room_counter += 1
    rooms[rid] = BingoGame(rid)
    rooms[rid].is_active = True; rooms[rid].join_open = True
    rooms[rid].game_state = 'joining'; rooms[rid].chat_id = cid
    rooms[rid].join_deadline = time.time() + 120
    if cid:
        try:
            bot.send_message(cid,
                f"🌟 <b>እንኳን ደህና መጡ!</b>\n🎮 {rooms[rid].game_name} - ክፍል {rid}\n💰 {db_setting('price')}\n🙏 ገጹን ክፈቱ!",
                reply_markup=get_panel(rid), parse_mode='HTML')
        except: pass
    return jsonify({'ok': True, 'room_id': rid})

@app.route('/api/admin/start_game', methods=['POST'])
def adm_start():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if len(r.approved_players) == 0: return jsonify({'ok': False, 'msg': '🙏 ተጫዋች የለም።'})
    r.join_open = False; r.game_state = 'playing'
    threading.Thread(target=call_loop, args=(rid,), daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/admin/toggle_pause', methods=['POST'])
def adm_pause():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    rooms[rid].paused = not rooms[rid].paused
    return jsonify({'paused': rooms[rid].paused})

@app.route('/api/admin/call_number', methods=['POST'])
def adm_call():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id'); num = d.get('number')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if num in r.called_numbers: return jsonify({'ok': False, 'msg': '🙏 ተጠርቷል።'})
    if num in r.available_numbers: r.available_numbers.remove(num)
    r.called_numbers.append(num); r.last_called = num
    return jsonify({'ok': True})

@app.route('/api/admin/force_win', methods=['POST'])
def adm_force_win():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id'); t = d.get('target_user_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]
    if t in r.players:
        r.winners.append(t)
        card = r.players[t][0]
        r.winner_pattern = "Force Win (በአስተዳዳሪ)"
        r.winner_marked = r.get_marked_numbers(card, r.called_numbers)
        name, cn, prize, jp = process_winner(t, r)
        msg = winner_msg(name, cn, prize, jp, r.winner_pattern, [], r.winner_marked, len(r.called_numbers))
        if r.chat_id:
            try: bot.send_message(r.chat_id, msg, parse_mode='HTML')
            except: pass
        r.is_active = False; r.game_state = 'finished'
        threading.Thread(target=auto_restart_room, args=(rid,), daemon=True).start()
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/reset', methods=['POST'])
def adm_reset():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid in rooms: del rooms[rid]
    return jsonify({'ok': True})

@app.route('/api/admin/set_setting', methods=['POST'])
def adm_set_setting():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    key = d.get('key'); val = d.get('value')
    if key and val is not None:
        db_set_setting(key, val); return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/ban', methods=['POST'])
def adm_ban():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    t = d.get('target_id')
    if t: db_ban(t, True); return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/unban', methods=['POST'])
def adm_unban():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    t = d.get('target_id')
    if t: db_ban(t, False); return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/add_balance', methods=['POST'])
def adm_add_bal():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id'); amt = d.get('amount')
    if uid and amt:
        nb = db_balance_delta(uid, int(amt))
        db_tx(uid, 'admin_add', int(amt), 'completed', 'በአስተዳዳሪ')
        try: bot.send_message(uid, f"🙏 +{amt} ብር!\n💵 {nb} ብር")
        except: pass
        return jsonify({'ok': True, 'balance': nb})
    return jsonify({'ok': False})

@app.route('/api/admin/set_balance', methods=['POST'])
def adm_set_bal():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id'); amt = d.get('amount')
    if uid and amt is not None:
        db_set_balance(uid, int(amt)); return jsonify({'ok': True, 'balance': int(amt)})
    return jsonify({'ok': False})

@app.route('/api/admin/broadcast', methods=['POST'])
def adm_bc():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    msg = d.get('message', '').strip()
    if not msg: return jsonify({'ok': False})
    users = db_all_users(); count = 0
    for uid in users:
        try:
            bot.send_message(uid, f"🙏 <b>ከአስተዳዳሪው</b>\n\n{msg}\n\n💚", parse_mode='HTML')
            count += 1; time.sleep(0.05)
        except: pass
    return jsonify({'ok': True, 'count': count})

@app.route('/api/admin/send_dm', methods=['POST'])
def adm_dm():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    uid = d.get('target_id'); msg = d.get('message', '').strip()
    if uid and msg:
        try:
            bot.send_message(uid, f"📩 <b>የግል</b>\n\n{msg}\n\n🙏", parse_mode='HTML')
            return jsonify({'ok': True})
        except: return jsonify({'ok': False, 'msg': '🙏 መላክ አልተቻለም።'})
    return jsonify({'ok': False})

@app.route('/api/admin/allcards', methods=['POST'])
def adm_cards():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id')
    if rid not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[rid]; res = []
    for uid in r.players.keys():
        u = db_user(uid)
        res.append({'user_id': uid, 'name': get_name(uid), 'card_nums': r.player_card_numbers.get(uid, []),
                    'balance': u['balance'] if u else 0, 'winner': uid in r.winners})
    return jsonify({'players': res})

@app.route('/api/admin/remove_card', methods=['POST'])
def adm_rm_card():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rid = d.get('room_id'); cn = d.get('card_num')
    if rid in rooms and cn:
        r = rooms[rid]
        r.taken_cards.discard(cn - 1)
        for uid in list(r.players.keys()):
            nums = r.player_card_numbers.get(uid, [])
            if cn in nums:
                pos = nums.index(cn)
                r.players[uid].pop(pos); nums.pop(pos)
                if not nums:
                    r.players.pop(uid, None); r.player_card_numbers.pop(uid, None)
                    r.approved_players.discard(uid)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/stats', methods=['POST'])
def adm_stats():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users")
        tu, tb = c.fetchone()
        c.execute("SELECT COUNT(*) FROM game_history")
        tg = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE banned=1")
        bc = c.fetchone()[0]; conn.close()
    return jsonify({'total_users': tu, 'total_balance': tb, 'total_games': tg, 'banned': bc,
                    'jackpot': db_jackpot(),
                    'history': [{'winner': r[0], 'card': r[1], 'prize': r[4], 'pattern': r[5], 'date': r[7]} for r in db_history(10)]})

@app.route('/api/admin/pending_withdrawals', methods=['POST'])
def adm_pw():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    rows = db_pending_tx()
    return jsonify({'pending': [{'id': r[0], 'user_id': r[1], 'type': r[2], 'amount': r[3], 'note': r[4], 'date': r[5]} for r in rows]})

@app.route('/api/admin/approve_withdraw', methods=['POST'])
def adm_aw():
    d = request.json
    if not is_admin(d): return jsonify({'error': 'unauthorized'}), 403
    tid = d.get('transaction_id'); act = d.get('action')
    if tid:
        db_update_tx(tid, 'completed' if act == 'approve' else 'rejected')
        return jsonify({'ok': True})
    return jsonify({'ok': False})

# ================= 🤖 የቦት =================

def get_panel(rid=None):
    m = InlineKeyboardMarkup()
    if rid and rid in rooms:
        m.row(InlineKeyboardButton("🌐 የቢንጎ ገጽ ክፈት", web_app=WebAppInfo(url=f"{WEBAPP_URL}/?room={rid}")))
        m.row(InlineKeyboardButton("▶️ ቁጥር ጥራ", callback_data=f"adm_begin_{rid}"),
              InlineKeyboardButton("🛑 ጨዋታ አቁም", callback_data=f"adm_stop_{rid}"))
        m.row(InlineKeyboardButton("📊 ዳሽቦርድ", callback_data=f"adm_dash_{rid}"),
              InlineKeyboardButton("⚙️ ቅንብሮች", callback_data="adm_settings"))
    else:
        m.row(InlineKeyboardButton("🎮 አዲስ ክፍል ክፈት", callback_data="adm_new_room"))
        m.row(InlineKeyboardButton("📋 የክፍት ክፍሎች", callback_data="adm_list_rooms"))
        m.row(InlineKeyboardButton("⚙️ ቅንብሮች", callback_data="adm_settings"))
    return m

@bot.message_handler(commands=['panel'])
def cmd_panel(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.send_message(msg.chat.id,
        "🎛️ <b>እንኳን ደህና መጡ ውድ አስተዳዳሪ!</b>\n\n🙏 የእርስዎ ማዕከል ነው።",
        reply_markup=get_panel(), parse_mode='HTML')

@bot.message_handler(commands=['balance'])
def cmd_bal(msg):
    uid = msg.from_user.id
    u = db_user(uid) or db_new_user(uid, msg.from_user.first_name)
    bot.reply_to(msg, f"🙏 {u['name']}!\n💰 {u['balance']} ብር\n🏆 {u['total_wins']}\n🎮 {u['total_games']}\n🔗 {u['referral_code']}\n💚", parse_mode='HTML')

@bot.message_handler(commands=['rules'])
def cmd_rules(msg):
    r = (f"📜 <b>ህጎች</b>\n1️⃣ ካርድ: {db_setting('price')}\n2️⃣ ጨዋታ ሲጀምር መግባት አይቻልም\n"
         f"3️⃣ ካርድ ገደብ: {db_setting('max_cards_per_player','2')}\n4️⃣ ማሸነፍ: {db_setting('win_pattern','single')}\n"
         f"5️⃣ ማውጣት: {db_setting('min_withdraw','100')} ብር\n6️⃣ ስጦታ: {db_setting('daily_bonus','10')} ብር\n🙏 💚")
    bot.send_message(msg.chat.id, r, parse_mode='HTML')

@bot.message_handler(commands=['daily'])
def cmd_daily(msg):
    uid = msg.from_user.id
    u = db_user(uid) or db_new_user(uid, msg.from_user.first_name)
    today = datetime.now().strftime('%Y-%m-%d')
    if u['daily_last'] == today:
        bot.reply_to(msg, "🙏 የዛሬ ስጦታ ተቀብለዋል። ነገ ይምጡ! 💚"); return
    bonus = int(db_setting('daily_bonus', '10'))
    db_balance_delta(uid, bonus)
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET daily_last=? WHERE user_id=?", (today, uid))
        conn.commit(); conn.close()
    bot.reply_to(msg, f"🎁 +{bonus} ብር! 💚")

@bot.message_handler(commands=['withdraw'])
def cmd_w(msg):
    try:
        parts = msg.text.split(); amt = int(parts[1]); acc = ' '.join(parts[2:]) if len(parts) > 2 else ''
    except: bot.reply_to(msg, "🙏 /withdraw 100 CBE1000123456"); return
    uid = msg.from_user.id
    u = db_user(uid) or db_new_user(uid, msg.from_user.first_name)
    min_w = int(db_setting('min_withdraw', '100'))
    if amt < min_w: bot.reply_to(msg, f"🙏 አነስተኛው {min_w} ብር።"); return
    if u['balance'] < amt: bot.reply_to(msg, f"🙏 በቂ የለም። ({u['balance']})"); return
    if not acc: bot.reply_to(msg, "🙏 አካውንት አስገባ።"); return
    db_balance_delta(uid, -amt); db_tx(uid, 'withdraw', -amt, 'pending', acc)
    try: bot.send_message(ADMIN_ID, f"💸 {u['name']}\n💰 {amt}\n🏦 {acc}", parse_mode='HTML')
    except: pass
    bot.reply_to(msg, f"🙏 ጥያቄህ ተልኳል።")

@bot.message_handler(commands=['addbalance'])
def cmd_add(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        parts = msg.text.split(); uid = int(parts[1]); amt = int(parts[2])
        nb = db_balance_delta(uid, amt); db_tx(uid, 'admin_add', amt, 'completed', 'በአስተዳዳሪ')
        bot.reply_to(msg, f"✅ {nb} ብር")
        try: bot.send_message(uid, f"🙏 +{amt} ብር!\n💵 {nb} ብር")
        except: pass
    except: bot.reply_to(msg, "🙏 /addbalance ID AMOUNT")

@bot.message_handler(commands=['jackpot'])
def cmd_jp(msg): bot.reply_to(msg, f"🎰 ጃክፖት: <b>{db_jackpot()} ብር</b>", parse_mode='HTML')

@bot.message_handler(commands=['leaderboard'])
def cmd_lb(msg):
    rows = db_leaders(10)
    t = "🏆 <b>ሰንጠረዥ</b>\n"
    for i, r in enumerate(rows, 1):
        m = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        t += f"{m} {r[0]} — {r[1]}\n"
    if not rows: t += "🙏 የለም"
    bot.send_message(msg.chat.id, t, parse_mode='HTML')

@bot.message_handler(commands=['feedback'])
def cmd_fb(msg):
    m = msg.text.replace('/feedback', '').strip()
    if not m: bot.reply_to(msg, "🙏 /feedback አስተያየትህ"); return
    uid = msg.from_user.id; u = db_user(uid) or db_new_user(uid, msg.from_user.first_name)
    try: bot.send_message(ADMIN_ID, f"💬 {u['name']}\n📝 {m}", parse_mode='HTML')
    except: pass
    bot.reply_to(msg, "🙏 ደርሶናል! 💚")

@bot.callback_query_handler(func=lambda c: c.data.startswith('adm_'))
def adm_cb(c):
    global room_counter
    if c.from_user.id != ADMIN_ID:
        bot.answer_callback_query(c.id, "🙏 ለአስተዳዳሪ ብቻ።"); return
    d = c.data; cid = c.message.chat.id

    if d == "adm_new_room":
        rid = room_counter; room_counter += 1
        rooms[rid] = BingoGame(rid)
        rooms[rid].is_active = True; rooms[rid].join_open = True
        rooms[rid].game_state = 'joining'; rooms[rid].chat_id = cid
        rooms[rid].join_deadline = time.time() + 120
        bot.send_message(cid, f"🌟 {rooms[rid].game_name} - ክፍል {rid}\n💰 {db_setting('price')}\n🙏 ገጹን ክፈቱ!",
                         reply_markup=get_panel(rid), parse_mode='HTML')
    elif d == "adm_list_rooms":
        t = "📋 <b>ክፍሎች</b>\n"
        for rid, r in rooms.items():
            t += f"{'🟢' if r.is_active else '🔴'} {rid}: {len(r.approved_players)}\n"
        if not rooms: t = "🙏 የለም"
        bot.send_message(cid, t, parse_mode='HTML')
    elif d.startswith("adm_begin_"):
        rid = int(d.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        if len(r.approved_players) == 0: bot.answer_callback_query(c.id, "🙏 ተጫዋች የለም"); return
        r.join_open = False; r.game_state = 'playing'
        threading.Thread(target=call_loop, args=(rid,), daemon=True).start()
        bot.answer_callback_query(c.id, "▶️")
        bot.send_message(cid, f"▶️ ክፍል {rid} ተጀምሯል! 🍀")
    elif d.startswith("adm_stop_"):
        rid = int(d.split('_')[2])
        if rid in rooms:
            rooms[rid].is_active = False; rooms[rid].game_state = 'finished'
        bot.answer_callback_query(c.id, "🛑")
        bot.send_message(cid, f"🛑 ቆሟል።")
    elif d.startswith("adm_dash_"):
        rid = int(d.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        bot.send_message(cid, f"📊 <b>ክፍል {rid}</b>\n🎮 {r.game_state}\n👥 {len(r.approved_players)}\n📢 {len(r.called_numbers)}\n📦 {len(r.available_numbers)}\n🎰 {db_jackpot()}", parse_mode='HTML')
        bot.answer_callback_query(c.id, "📊")
    elif d == "adm_settings":
        bot.send_message(cid, f"⚙️ ዋጋ: {db_setting('price')}\n🏦 {db_setting('account')}\n⏱️ {db_setting('call_interval')}s\n💹 {db_setting('commission')}%\n🎁 {db_setting('daily_bonus')}\n🎫 {db_setting('max_cards_per_player')}\n🏆 {db_setting('win_pattern')}", parse_mode='HTML')

def call_loop(rid):
    r = rooms.get(rid)
    if not r: return
    iv = int(db_setting('call_interval', '5'))
    tlim = int(db_setting('game_time_limit', '30')) * 60
    st = time.time()
    while r.is_active:
        time.sleep(iv)
        if not r.is_active: break
        if r.paused: continue
        if time.time() - st > tlim:
            if r.chat_id:
                try: bot.send_message(r.chat_id, "⏰ ጊዜ አልቋል።")
                except: pass
            r.is_active = False; r.game_state = 'finished'
            threading.Thread(target=auto_restart_room, args=(rid,), daemon=True).start()
            break
        if not r.available_numbers:
            if r.chat_id:
                try: bot.send_message(r.chat_id, "🙏 ሁሉም ቁጥሮች ተጠርተዋል።")
                except: pass
            r.is_active = False; r.game_state = 'finished'
            threading.Thread(target=auto_restart_room, args=(rid,), daemon=True).start()
            break
        num = r.available_numbers.pop(); r.called_numbers.append(num); r.last_called = num
        if r.chat_id:
            try:
                bot.send_message(r.chat_id, f"🎯 <b>{num}</b>\n📜 {', '.join(map(str, r.called_numbers[-5:]))}", parse_mode='HTML')
            except: pass
        winners = []
        for uid, cards in r.players.items():
            if uid in r.approved_players and uid not in r.winners:
                for card in cards:
                    pat = r.check_bingo(card, r.called_numbers)
                    if pat:
                        r.winners.append(uid); winners.append((uid, card, pat)); break
        if winners:
            for uid, card, pat in winners:
                r.winner_pattern = pat
                r.winner_marked = r.get_marked_numbers(card, r.called_numbers)
                line_nums = r.get_marked_numbers_by_line(card, r.called_numbers, pat)
                name, cn, prize, jp = process_winner(uid, r)
                msg = winner_msg(name, cn, prize, jp, pat, line_nums, r.winner_marked, len(r.called_numbers))
                if r.chat_id:
                    try: bot.send_message(r.chat_id, msg, parse_mode='HTML')
                    except: pass
                try: bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
                except: pass
                try:
                    bot.send_message(uid, f"🌟 <b>እንኳን ደስ አለህ/ሽ!</b>\n💰 {prize} ብር\n🎫 #{cn}\n🏆 {pat}\n🙏", parse_mode='HTML')
                except: pass
            r.is_active = False; r.game_state = 'finished'
            threading.Thread(target=auto_restart_room, args=(rid,), daemon=True).start()
            break

def auto_restart_room(old_rid):
    global room_counter
    time.sleep(30)
    for rid, r in rooms.items():
        if r.is_active and r.game_state in ('joining', 'playing'): return
    rid = room_counter; room_counter += 1
    rooms[rid] = BingoGame(rid)
    rooms[rid].is_active = True; rooms[rid].join_open = True
    rooms[rid].game_state = 'joining'
    rooms[rid].join_deadline = time.time() + 120
    old = rooms.get(old_rid)
    if old and old.chat_id:
        rooms[rid].chat_id = old.chat_id
        try:
            bot.send_message(old.chat_id,
                f"🌟 <b>አዲስ ጨዋታ!</b>\n🎮 ክፍል {rid}\n💰 {db_setting('price')}\n🙏 ገጹን ክፈቱ!",
                reply_markup=get_panel(rid), parse_mode='HTML')
        except: pass

@bot.message_handler(content_types=['photo'])
def on_photo(m):
    uid = m.from_user.id
    u = db_user(uid) or db_new_user(uid, m.from_user.first_name)
    if u['banned']: return
    price = price_int()
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("✅ አጽድቅ", callback_data=f"bal_approve_{uid}"),
           InlineKeyboardButton("❌ ውድቅ", callback_data=f"bal_reject_{uid}"))
    bot.send_message(ADMIN_ID,
        f"🔔 <b>ክፍያ</b>\n👤 {u['name']}\n🆔 {uid}\n💰 {u['balance']}\n💵 +{price}",
        reply_markup=mk, parse_mode='HTML')
    bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
    bot.reply_to(m, f"🙏 {u['name']}!\n✅ ስክሪንሾት ተልኳል።\n💰 {u['balance']} ብር\n💚")

@bot.callback_query_handler(func=lambda c: c.data.startswith('bal_'))
def bal_cb(c):
    if c.from_user.id != ADMIN_ID:
        bot.answer_callback_query(c.id, "🙏 ለአስተዳዳሪ ብቻ"); return
    parts = c.data.split('_'); act = parts[1]; uid = int(parts[2]); price = price_int()
    if act == 'approve':
        nb = db_balance_delta(uid, price); db_tx(uid, 'deposit', price, 'completed', 'ክፍያ')
        bot.answer_callback_query(c.id, "✅")
        try: bot.send_message(uid, f"🌟 <b>ክፍያ ተረጋግጧል!</b>\n💰 +{price}\n💵 {nb}\n🍀", parse_mode='HTML')
        except: pass
    else:
        bot.answer_callback_query(c.id, "❌")
        try: bot.send_message(uid, "🙏 ክፍያ ውድቅ።")
        except: pass

# ================= 🚀 =================

def run_flask():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    init_db()
    Thread(target=run_flask, daemon=True).start()
    print("🌟 ሰርቨሩ ተጀምሯል...")
    bot.polling(none_stop=True)
