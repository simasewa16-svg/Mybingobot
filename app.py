import telebot
import random
import threading
import time
import os
from flask import Flask, render_template, request, jsonify
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

ADMIN_ID = 5671366303
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://mybingobot.onrender.com')

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ================= 📦 የጨዋታ ክፍል =================

class BingoGame:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}
        self.player_card_numbers = {}
        self.called_numbers = []
        self.available_numbers = [i for i in range(1, 91)]
        random.shuffle(self.available_numbers)
        self.is_active = False
        self.join_open = False
        self.game_state = 'idle'
        self.winners = []
        self.card_pool = self.generate_card_pool(200)
        self.taken_cards = set()
        self.pending_players = set()
        self.approved_players = set()
        self.used_receipts = set()
        self.chat_id = None
        self.join_deadline = None
        self.game_name = "ዘና ቢንጎ ከድጎ"
        self.last_called = None
        self.paused = False
        self.winner_name = None
        self.winner_card = None

    def generate_single_card(self):
        card = []
        cols = [list(range(1, 19)), list(range(19, 37)), list(range(37, 55)),
                list(range(55, 73)), list(range(73, 91))]
        for col in cols:
            card.append(random.sample(col, 5))
        card_matrix = [[card[c][r] for c in range(5)] for r in range(5)]
        card_matrix[2][2] = "⭐"
        return card_matrix

    def generate_card_pool(self, count):
        pool, seen = [], set()
        while len(pool) < count:
            card = self.generate_single_card()
            if str(card) not in seen:
                seen.add(str(card))
                pool.append(card)
        return pool

    def check_bingo(self, card, called):
        called_set = set(called)
        for row in card:
            if all(str(num) == "⭐" or num in called_set for num in row):
                return True
        for c in range(5):
            if all(str(card[r][c]) == "⭐" or card[r][c] in called_set for r in range(5)):
                return True
        if all(str(card[i][i]) == "⭐" or card[i][i] in called_set for i in range(5)):
            return True
        if all(str(card[i][4-i]) == "⭐" or card[i][4-i] in called_set for i in range(5)):
            return True
        return False

rooms = {}
room_counter = 1

payment_settings = {
    'price': '50 ብር',
    'account': 'CBE 1000123456789',
    'call_interval': 5,
    'commission': 15,
}

banned_players = set()
user_balances = {}
user_names = {}
game_history = []

def get_user_name(uid):
    if uid in user_names:
        return user_names[uid]
    try:
        info = bot.get_chat(uid)
        name = f"@{info.username}" if info.username else info.first_name
    except:
        name = f"ተጫዋች"
    user_names[uid] = name
    return name

def get_price_int():
    try:
        return int(''.join(filter(str.isdigit, payment_settings['price'])))
    except:
        return 50

# ================= 🌐 API =================

@app.route('/')
def index():
    return render_template('index.html')

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
        'room_id': room_id,
        'game_name': r.game_name,
        'game_state': r.game_state,
        'is_active': r.is_active,
        'join_open': r.join_open,
        'time_left': time_left,
        'players': len(r.approved_players),
        'pending': len(r.pending_players),
        'called': r.called_numbers,
        'called_count': len(r.called_numbers),
        'remaining': len(r.available_numbers),
        'price': payment_settings['price'],
        'winners': r.winners,
        'winner_name': r.winner_name,
        'winner_card': r.winner_card,
        'taken_cards': list(r.taken_cards),
        'total_cards': len(r.card_pool),
        'last_called': r.last_called,
        'paused': r.paused,
    })

@app.route('/api/user_info', methods=['POST'])
def api_user_info():
    data = request.json
    uid = data.get('user_id')
    return jsonify({
        'user_id': uid,
        'name': get_user_name(uid),
        'balance': user_balances.get(uid, 0),
        'is_admin': uid == ADMIN_ID,
        'banned': uid in banned_players,
        'account': payment_settings['account'],
        'price': payment_settings['price'],
        'price_int': get_price_int(),
    })

@app.route('/api/join', methods=['POST'])
def api_join():
    data = request.json
    user_id = data.get('user_id')
    room_id = data.get('room_id')
    card_num = data.get('card_num')

    if user_id in banned_players:
        return jsonify({'ok': False, 'msg': '🙏 ይቅርታ አድርግልን፣ አገልግሎቱን ለመጠቀም ፈቃድ የለህም። ለግንዛቤህ እናመሰግናለን።'})
    if room_id not in rooms:
        return jsonify({'ok': False, 'msg': '🙏 ይቅርታ አድርግልን፣ ይህ ክፍል አልተገኘም። እባክህ ከጥቂት ቆይታ በኋላ እንደገና ሞክር።'})
    r = rooms[room_id]
    if r.game_state == 'playing' or r.game_state == 'finished':
        return jsonify({'ok': False, 'msg': '🙏 በአክብሮት እናሳውቅ፣ ጨዋታው ቀድሞ ተጀምሯል። እባክህ በትዕግስት ተጠብቀህ በሚቀጥለው ጨዋታ ተሳተፍ።'})
    if not r.join_open:
        return jsonify({'ok': False, 'msg': '⏰ የመግቢያ ጊዜው አልፎ አልቋል። እባክህ በትዕግስት ተጠብቀህ ለሚቀጥለው ጨዋታ ዝግጁ ሁን።'})
    if user_id in r.players:
        return jsonify({'ok': False, 'msg': '🙏 በአክብሮት እናሳውቅ፣ ቀድመህ ካርድ መርጠሃል። እባክህ የተመረጠውን ካርድህን ተመልከት።'})
    
    card_index = card_num - 1
    if card_index < 0 or card_index >= len(r.card_pool):
        return jsonify({'ok': False, 'msg': '🙏 ይቅርታ አድርግልን፣ ይህ ካርድ አልተገኘም። እባክህ ሌላ ካርድ ምረጥ።'})
    if card_index in r.taken_cards:
        return jsonify({'ok': False, 'msg': f'🙏 በአክብሮት እናሳውቅ፣ ካርድ {card_num} ቀድሞ በሌላ ተጫዋች ተመርጧል። እባክህ ሌላ ካርድ ምረጥ። ስለ ግንዛቤህ እናመሰግናለን።'})

    # 💰 የባላንስ ማረጋገጫ
    price = get_price_int()
    balance = user_balances.get(user_id, 0)
    
    if balance < price:
        return jsonify({
            'ok': False,
            'msg': f'🙏 ውድ ተጫዋች፣ ካርድ ለመምረጥ በቂ ባላንስ የለህም።\n\n💰 የአሁኑ ባላንስ: {balance} ብር\n💵 የሚያስፈልግ: {price} ብር\n\n🏦 የክፍያ አካውንት: {payment_settings["account"]}\n\n🙏 እባክህ በትህትና እንጠይቅሃለን — {price} ብር ወደ አካውንቱ ላክ።\n📸 የክፍያ ስክሪንሾት ወደ ቦቱ ላክ።\n✅ አስተዳዳሪው ባጸደቀ ቅጽበት ባላንስህ ይጨመራል።\n\n💚 ስለ ትዕግስትህ እና ስለ ግንዛቤህ ከልብ እናመሰግናለን።',
            'need_payment': True,
            'balance': balance,
            'price': price,
            'account': payment_settings['account']
        })
    
    user_balances[user_id] = balance - price
    r.taken_cards.add(card_index)
    selected_card = r.card_pool[card_index]
    r.players[user_id] = selected_card
    r.player_card_numbers[user_id] = card_num
    r.approved_players.add(user_id)
    user_names[user_id] = get_user_name(user_id)
    
    try:
        bot.send_message(ADMIN_ID,
            f"🎫 <b>ውድ አስተዳዳሪ፣ አዲስ ካርድ ተመረጠ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 ተጫዋች: {get_user_name(user_id)}\n"
            f"🆔 መለያ: {user_id}\n"
            f"🎫 የተመረጠ ካርድ: #{card_num}\n"
            f"💰 የተቀነሰ: {price} ብር\n"
            f"💵 ቀሪ ባላንስ: {user_balances[user_id]} ብር",
            parse_mode='HTML')
    except: pass

    return jsonify({
        'ok': True,
        'card': selected_card,
        'card_num': card_num,
        'called': r.called_numbers,
        'new_balance': user_balances[user_id],
    })

@app.route('/api/mycard', methods=['POST'])
def api_mycard():
    data = request.json
    user_id = data.get('user_id')
    room_id = data.get('room_id')
    if room_id not in rooms:
        return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if user_id not in r.players:
        return jsonify({'error': 'no card'}), 404
    card = r.players[user_id]
    called_set = set(r.called_numbers)
    marked = []
    for row in card:
        new_row = []
        for num in row:
            if num == "⭐":
                new_row.append("⭐")
            elif num in called_set:
                new_row.append(f"✅{num}")
            else:
                new_row.append(str(num))
        marked.append(new_row)
    return jsonify({
        'card': marked,
        'card_num': r.player_card_numbers.get(user_id),
        'called': r.called_numbers,
        'balance': user_balances.get(user_id, 0),
    })

@app.route('/api/bingo', methods=['POST'])
def api_bingo():
    data = request.json
    user_id = data.get('user_id')
    room_id = data.get('room_id')
    if room_id not in rooms:
        return jsonify({'ok': False, 'msg': '🙏 ይቅርታ አድርግልን፣ ክፍሉ አልተገኘም።'})
    r = rooms[room_id]
    if user_id not in r.approved_players:
        return jsonify({'ok': False, 'msg': '🙏 ውድ ተጫዋች፣ ገና አልተጸደቅህም። እባክህ ትንሽ ታገስ።'})
    if user_id in r.winners:
        return jsonify({'ok': False, 'msg': '🌟 ውድ ተጫዋች፣ ቀድመህ አሸንፈሃል! እግዚአብሔር ይባርክህ።'})
    if not r.is_active:
        return jsonify({'ok': False, 'msg': '🙏 ይቅርታ፣ ጨዋታው አልተጀመረም።'})
    card = r.players[user_id]
    if r.check_bingo(card, r.called_numbers):
        r.winners.append(user_id)
        card_num = r.player_card_numbers.get(user_id, "?")
        name = get_user_name(user_id)
        r.winner_name = name
        r.winner_card = card_num
        winner_msg = (
            f"🌟🌟🌟 <b>ቢንጎ!</b> 🌟🌟🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎊 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🎊\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>ውድ አሸናፊ:</b> {name}\n"
            f"🎫 <b>ያሸነፍክበት ካርድ:</b> #{card_num}\n"
            f"🎯 <b>ጠቅላላ የተጠሩ:</b> {len(r.called_numbers)} ቁጥሮች\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌟 <i>ይህ የአንተ/የአንቺ ቀን ነው!</i>\n"
            f"🎊 <i>ለድልህ/ሽ ከልብ እንኮነንልሃለን!</i>\n"
            f"🙏 <i>በቀጣይም ተሳትፈህ/ሽ ተጠቃሚ ሁን!</i>"
        )
        if r.chat_id:
            try: bot.send_message(r.chat_id, winner_msg, parse_mode='HTML')
            except: pass
        try: bot.send_message(ADMIN_ID, winner_msg, parse_mode='HTML')
        except: pass
        try:
            bot.send_message(user_id,
                f"🌟 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🌟\n\n"
                f"🏆 ውድ አሸናፊ፣ በዚህ ጨዋታ አንተ/አንቺ ተሸላሚ ሆነሃል/ሽ!\n\n"
                f"🎫 ያሸነፍክበት ካርድ: <b>#{card_num}</b>\n"
                f"🎯 ጠቅላላ ጥሪዎች: <b>{len(r.called_numbers)}</b>\n\n"
                f"🙏 ስለ ተሳትፎህ/ሽ ከልብ እናመሰግናለን።\n"
                f"🎊 በቀጣዩ ጨዋታም ተገናኝተን እንደምንደሰት ተስፋ እናደርጋለን!",
                parse_mode='HTML')
        except: pass
        r.is_active = False
        r.game_state = 'finished'
        game_history.append({
            'winner': name, 'card': card_num,
            'room': room_id, 'called': len(r.called_numbers),
            'date': time.strftime("%Y-%m-%d %H:%M")
        })
        return jsonify({'ok': True, 'winner': name, 'card_num': card_num})
    return jsonify({'ok': False, 'msg': '🙏 ውድ ተጫዋች፣ ገና አልተሸነፍክም። እባክህ ካርድህን በጥንቃቄ ተመልከት። ስለ ትዕግስትህ እናመሰግናለን።'})

# ================= 🔐 ADMIN API =================

def check_admin(data):
    return data.get('user_id') == ADMIN_ID

@app.route('/api/admin/allcards', methods=['POST'])
def api_admin_allcards():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    result = []
    for uid, card in r.players.items():
        result.append({
            'user_id': uid,
            'name': get_user_name(uid),
            'card_num': r.player_card_numbers.get(uid),
            'card': card,
            'approved': uid in r.approved_players,
            'winner': uid in r.winners,
            'balance': user_balances.get(uid, 0),
        })
    return jsonify({'players': result})

@app.route('/api/admin/call_number', methods=['POST'])
def api_admin_call_number():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    num = data.get('number')
    if room_id not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if num in r.called_numbers:
        return jsonify({'ok': False, 'msg': '🙏 በአክብሮት እናሳውቅ፣ ቁጥሩ ቀድሞ ተጠርቷል።'})
    if num in r.available_numbers:
        r.available_numbers.remove(num)
    r.called_numbers.append(num)
    r.last_called = num
    return jsonify({'ok': True})

@app.route('/api/admin/force_win', methods=['POST'])
def api_admin_force_win():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    target = data.get('target_user_id')
    if room_id not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if target in r.players:
        r.winners.append(target)
        card_num = r.player_card_numbers.get(target, "?")
        name = get_user_name(target)
        r.winner_name = name
        r.winner_card = card_num
        if r.chat_id:
            try:
                bot.send_message(r.chat_id,
                    f"🌟 ውድ ተጫዋቾች፣ በአስተዳዳሪው ውሳኔ መሰረት {name} አሸናፊ ሆኗል! (ካርድ #{card_num})\n\n🙏 ለሁሉም ተሳታፊዎች ከልብ እናመሰግናለን።",
                    parse_mode='HTML')
            except: pass
        r.is_active = False
        r.game_state = 'finished'
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/toggle_pause', methods=['POST'])
def api_admin_toggle_pause():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    r.paused = not r.paused
    return jsonify({'paused': r.paused})

@app.route('/api/admin/start_game', methods=['POST'])
def api_admin_start_game():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id not in rooms: return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if len(r.approved_players) == 0:
        return jsonify({'ok': False, 'msg': '🙏 ውድ አስተዳዳሪ፣ እስካሁን የተጸደቀ ተጫዋች የለም። እባክህ በመጀመሪያ ተጫዋቾች እንዲቀላቀሉ ጥራ።'})
    r.join_open = False
    r.game_state = 'playing'
    threading.Thread(target=auto_call_loop, args=(room_id,), daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/admin/reset', methods=['POST'])
def api_admin_reset():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id in rooms: del rooms[room_id]
    return jsonify({'ok': True})

@app.route('/api/admin/set_name', methods=['POST'])
def api_admin_set_name():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    name = data.get('name', '').strip()
    if room_id in rooms and name:
        rooms[room_id].game_name = name
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_price', methods=['POST'])
def api_admin_set_price():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    price = data.get('price', '').strip()
    if price:
        payment_settings['price'] = price
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_account', methods=['POST'])
def api_admin_set_account():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    acc = data.get('account', '').strip()
    if acc:
        payment_settings['account'] = acc
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_interval', methods=['POST'])
def api_admin_set_interval():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    iv = data.get('interval')
    if iv and 1 <= iv <= 60:
        payment_settings['call_interval'] = iv
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/set_commission', methods=['POST'])
def api_admin_set_commission():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    c = data.get('commission')
    if c is not None and 0 <= c <= 50:
        payment_settings['commission'] = c
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/ban', methods=['POST'])
def api_admin_ban():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    uid = data.get('target_id')
    if uid:
        banned_players.add(uid)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/unban', methods=['POST'])
def api_admin_unban():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    uid = data.get('target_id')
    if uid:
        banned_players.discard(uid)
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/add_balance', methods=['POST'])
def api_admin_add_balance():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    uid = data.get('target_id')
    amount = data.get('amount')
    if uid and amount:
        user_balances[uid] = user_balances.get(uid, 0) + int(amount)
        return jsonify({'ok': True, 'balance': user_balances[uid]})
    return jsonify({'ok': False})

@app.route('/api/admin/set_balance', methods=['POST'])
def api_admin_set_balance():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    uid = data.get('target_id')
    amount = data.get('amount')
    if uid and amount is not None:
        user_balances[uid] = int(amount)
        return jsonify({'ok': True, 'balance': user_balances[uid]})
    return jsonify({'ok': False})

@app.route('/api/admin/broadcast', methods=['POST'])
def api_admin_broadcast():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    msg = data.get('message', '').strip()
    if not msg: return jsonify({'ok': False})
    count = 0
    users = set()
    for rid, r in rooms.items():
        for uid in list(r.approved_players) + list(r.pending_players):
            users.add(uid)
    for uid in users:
        try:
            bot.send_message(uid,
                f"🙏 <b>ውድ ተጫዋች፣ ከአስተዳዳሪው መልእክት</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{msg}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💚 ስለ ተሳትፎህ ከልብ እናመሰግናለን።",
                parse_mode='HTML')
            count += 1
        except: pass
    return jsonify({'ok': True, 'count': count})

@app.route('/api/admin/send_dm', methods=['POST'])
def api_admin_send_dm():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    uid = data.get('target_id')
    msg = data.get('message', '').strip()
    if uid and msg:
        try:
            bot.send_message(uid,
                f"📩 <b>ውድ ተጫዋች፣ ከአስተዳዳሪው የግል መልእክት</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n{msg}\n━━━━━━━━━━━━━━━━━━━━\n"
                f"🙏 ስለ ትዕግስትህ እናመሰግናለን።",
                parse_mode='HTML')
            return jsonify({'ok': True})
        except:
            return jsonify({'ok': False, 'msg': '🙏 ይቅርታ፣ መልእክቱን መላክ አልቻልንም።'})
    return jsonify({'ok': False})

@app.route('/api/admin/stats', methods=['POST'])
def api_admin_stats():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    total_users = len(user_balances)
    total_balance = sum(user_balances.values())
    total_games = len(game_history)
    return jsonify({
        'total_users': total_users,
        'total_balance': total_balance,
        'total_games': total_games,
        'history': game_history[-20:][::-1],
        'banned': list(banned_players),
        'balances': {str(k): v for k, v in user_balances.items()},
        'names': {str(k): v for k, v in user_names.items()},
    })

@app.route('/api/admin/remove_card', methods=['POST'])
def api_admin_remove_card():
    data = request.json
    if not check_admin(data): return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    card_num = data.get('card_num')
    if room_id in rooms and card_num:
        r = rooms[room_id]
        idx = card_num - 1
        r.taken_cards.discard(idx)
        for uid in list(r.players.keys()):
            if r.player_card_numbers.get(uid) == card_num:
                r.players.pop(uid, None)
                r.player_card_numbers.pop(uid, None)
                r.approved_players.discard(uid)
                break
        return jsonify({'ok': True})
    return jsonify({'ok': False})

# ================= 🤖 የቦት =================

def get_main_panel(room_id=None):
    markup = InlineKeyboardMarkup()
    if room_id and room_id in rooms:
        markup.row(InlineKeyboardButton("🌐 የቢንጎ ገጽ ክፈት",
                     web_app=WebAppInfo(url=f"{WEBAPP_URL}/?room={room_id}")))
        markup.row(
            InlineKeyboardButton("✅ ሁሉንም አጽድቅ", callback_data=f"adm_appr_{room_id}"),
            InlineKeyboardButton("▶️ ቁጥር ጥራ", callback_data=f"adm_begin_{room_id}")
        )
        markup.row(
            InlineKeyboardButton("🛑 ጨዋታ አቁም", callback_data=f"adm_stop_{room_id}"),
            InlineKeyboardButton("📊 ዳሽቦርድ", callback_data=f"adm_dash_{room_id}")
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
        "🎛️ <b>እንኳን ደህና መጡ፣ ውድ አስተዳዳሪ!</b>\n\n"
        "🙏 ይህ የእርስዎ የግል ማዕከል ነው።\n"
        "እባክህ ከታች ካሉት አማራጮች የሚፈልጉትን ይምረጡ፦",
        reply_markup=get_main_panel(), parse_mode='HTML')

@bot.message_handler(commands=['balance'])
def show_balance(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0)
    bot.reply_to(message,
        f"🙏 ውድ ተጫዋች፣\n\n"
        f"💰 የአሁኑ ባላንስዎ: <b>{bal} ብር</b>\n\n"
        f"💚 ስለ ተሳትፎዎ ከልብ እናመሰግናለን!",
        parse_mode='HTML')

@bot.message_handler(commands=['addbalance'])
def add_balance_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        amt = int(parts[2])
        user_balances[uid] = user_balances.get(uid, 0) + amt
        bot.reply_to(message, f"✅ በአክብሮት ተጨምሯል። አዲስ ባላንስ: {user_balances[uid]} ብር")
        try:
            bot.send_message(uid,
                f"🙏 ውድ ተጫዋች፣\n\n"
                f"💰 ባላንስዎ በአስተዳዳሪው ተረጋግጦ <b>{amt} ብር</b> ተጨምሯል!\n\n"
                f"💵 አሁን ያለዎት: <b>{user_balances[uid]} ብር</b>\n\n"
                f"🎫 አሁን ካርድ መምረጥ ይችላሉ። መልካም እድል! 🍀",
                parse_mode='HTML')
        except: pass
    except:
        bot.reply_to(message, "🙏 እባክህ እንዲህ ጻፍ: /addbalance USER_ID AMOUNT")

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
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>{rooms[rid].game_name} - ክፍል {rid}</b> በአክብሮት ተከፍቷል!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 የጨዋታ አስተዋጽኦ: <b>{payment_settings['price']}</b>\n"
            f"🎫 የካርዶች ብዛት: <b>1-{len(rooms[rid].card_pool)}</b>\n"
            f"⏱️ የመግቢያ ጊዜ: <b>2 ደቂቃ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🙏 እባካችሁ በታች ያለውን የቢንጎ ገጽ ከፍታችሁ የሚወዱትን ካርድ ምረጡ።\n"
            f"💚 ስለ ተሳትፎአችሁ ከልብ እናመሰግናለን!",
            reply_markup=get_main_panel(rid), parse_mode='HTML')

    elif data == "adm_list_rooms":
        text = "📋 <b>የክፍት ክፍሎች ዝርዝር</b>\n\n"
        for rid, r in rooms.items():
            status = "🟢 ንቁ" if r.is_active else "🔴 የቆመ"
            text += f"{status} | ክፍል {rid}: {len(r.approved_players)} ተጫዋቾች\n"
        if not rooms: text = "🙏 እስካሁን ክፍት ክፍል የለም።"
        bot.send_message(chat_id, text, parse_mode='HTML')

    elif data.startswith("adm_appr_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        pending = list(r.pending_players)
        for uid in pending:
            r.approved_players.add(uid)
            r.pending_players.discard(uid)
            try:
                bot.send_message(uid, "✅ በአክብሮት ተረጋግጧል! መልካም ጨዋታ።")
            except: pass
        bot.answer_callback_query(call.id, f"✅ {len(pending)} ተጸድቀዋል")
        bot.send_message(chat_id, f"✅ በአክብሮት {len(pending)} ተጫዋቾች ጸድቀዋል።")

    elif data.startswith("adm_begin_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        if len(r.approved_players) == 0:
            bot.answer_callback_query(call.id, "🙏 እስካሁን ተጫዋች የለም።")
            return
        r.join_open = False
        r.game_state = 'playing'
        threading.Thread(target=auto_call_loop, args=(rid,), daemon=True).start()
        bot.answer_callback_query(call.id, "▶️ በአክብሮት ተጀምሯል")
        bot.send_message(chat_id, f"▶️ ክፍል {rid} ጨዋታ በአክብሮት ተጀምሯል። መልካም እድል! 🍀")

    elif data.startswith("adm_stop_"):
        rid = int(data.split('_')[2])
        if rid in rooms:
            rooms[rid].is_active = False
            rooms[rid].game_state = 'finished'
        bot.answer_callback_query(call.id, "🛑 ቆሟል")
        bot.send_message(chat_id, f"🛑 ክፍል {rid} በአክብሮት ተቋርጧል።")

    elif data.startswith("adm_dash_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        text = f"📊 <b>ዳሽቦርድ - ክፍል {rid}</b>\n\n"
        text += f"🎮 ሁኔታ: {r.game_state}\n"
        text += f"👥 የጸደቁ: {len(r.approved_players)}\n"
        text += f"⏳ በመጠበቅ: {len(r.pending_players)}\n"
        text += f"📢 የተጠሩ: {len(r.called_numbers)}\n"
        text += f"📦 የቀሩ: {len(r.available_numbers)}\n"
        bot.send_message(chat_id, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "📊 ዳሽቦርድ ተልኳል")

    elif data == "adm_settings":
        bot.send_message(chat_id,
            "⚙️ <b>የአስተዳዳሪ ቅንብሮች</b>\n\n"
            f"💰 ዋጋ: {payment_settings['price']}\n"
            f"🏦 አካውንት: {payment_settings['account']}\n"
            f"⏱️ ፍጥነት: {payment_settings['call_interval']} ሰከንድ\n\n"
            "🙏 ለመቀየር:\n"
            "<code>/setprice 50 ብር</code>\n"
            "<code>/setaccount CBE 1000123456789</code>\n"
            "<code>/setinterval 5</code>",
            parse_mode='HTML')

def auto_call_loop(room_id):
    r = rooms.get(room_id)
    if not r: return
    interval = payment_settings.get('call_interval', 5)
    while r.is_active:
        time.sleep(interval)
        if not r.is_active: break
        if r.paused: continue
        if not r.available_numbers:
            if r.chat_id:
                try:
                    bot.send_message(r.chat_id,
                        "🙏 ውድ ተጫዋቾች፣ ሁሉም ቁጥሮች ተጠርተዋል።\n"
                        "🎊 ጨዋታው በዚህ አብቅቷል።\n"
                        "💚 ስለ ተሳትፎአችሁ ከልብ እናመሰግናለን!",
                        parse_mode='HTML')
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
        for uid, card in r.players.items():
            if uid in r.approved_players and uid not in r.winners:
                if r.check_bingo(card, r.called_numbers):
                    r.winners.append(uid)
                    new_winners.append(uid)
        if new_winners:
            for uid in new_winners:
                name = get_user_name(uid)
                card_num = r.player_card_numbers.get(uid, "?")
                r.winner_name = name
                r.winner_card = card_num
                winner_msg = (
                    f"🌟🌟🌟 <b>ቢንጎ!</b> 🌟🌟🌟\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎊 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🎊\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>ውድ አሸናፊ:</b> {name}\n"
                    f"🎫 <b>ያሸነፍክበት ካርድ:</b> #{card_num}\n"
                    f"🎯 <b>ጠቅላላ ጥሪዎች:</b> {len(r.called_numbers)}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🙏 <i>ስለ ተሳትፎህ/ሽ ከልብ እናመሰግናለን!</i>\n"
                    f"🎊 <i>ለድልህ/ሽ እንኮነንልሃለን!</i>"
                )
                if r.chat_id:
                    try: bot.send_message(r.chat_id, winner_msg, parse_mode='HTML')
                    except: pass
                try: bot.send_message(ADMIN_ID, winner_msg, parse_mode='HTML')
                except: pass
                try:
                    bot.send_message(uid,
                        f"🌟 <b>ከልብ እንኳን ደስ አለህ/ሽ!</b> 🌟\n\n"
                        f"🏆 ውድ አሸናፊ፣ በዚህ ጨዋታ አንተ/አንቺ ተሸላሚ ሆነሃል/ሽ!\n\n"
                        f"🎫 ያሸነፍክበት ካርድ: <b>#{card_num}</b>\n"
                        f"🎯 ጠቅላላ ጥሪዎች: <b>{len(r.called_numbers)}</b>\n\n"
                        f"🙏 ስለ ተሳትፎህ/ሽ ከልብ እናመሰግናለን።\n"
                        f"🎊 በቀጣዩ ጨዋታም እንድንገናኝ ተስፋ እናደርጋለን!",
                        parse_mode='HTML')
                except: pass
                game_history.append({
                    'winner': name, 'card': card_num,
                    'room': room_id, 'called': len(r.called_numbers),
                    'date': time.strftime("%Y-%m-%d %H:%M")
                })
            r.is_active = False
            r.game_state = 'finished'
            break

# ================= 📥 የክፍያ ስክሪንሾት =================

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = message.from_user.id
    if uid in banned_players: return
    file_id = message.photo[-1].file_unique_id
    price = get_price_int()
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ አጽድቅ", callback_data=f"bal_approve_{uid}"),
        InlineKeyboardButton("❌ ውድቅ", callback_data=f"bal_reject_{uid}")
    )
    bot.send_message(ADMIN_ID,
        f"🔔 <b>ውድ አስተዳዳሪ፣ አዲስ የክፍያ ስክሪንሾት ደርሷል</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች: {message.from_user.first_name}\n"
        f"🆔 መለያ: {uid}\n"
        f"💰 የአሁን ባላንስ: {user_balances.get(uid, 0)} ብር\n"
        f"💵 ሊጨመር: +{price} ብር\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🙏 እባክህ በአክብሮት ተመልከተው አጽድቅ ወይም ውድቅ አድርግ።",
        reply_markup=markup, parse_mode='HTML')
    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    bot.reply_to(message,
        f"🙏 ውድ ተጫዋች፣\n\n"
        f"✅ የክፍያ ስክሪንሾትዎ በአክብሮት ለአስተዳዳሪው ተልኳል።\n\n"
        f"⏳ በትዕግስት ማረጋገጫውን ይጠብቁ።\n"
        f"💰 የአሁን ባላንስ: {user_balances.get(uid, 0)} ብር\n\n"
        f"💚 ስለ ትዕግስትዎ እና ስለ ተሳትፎዎ ከልብ እናመሰግናለን!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('bal_'))
def handle_balance_approve(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🙏 ይቅርታ፣ ይህ ለአስተዳዳሪ ብቻ ነው።")
        return
    parts = call.data.split('_')
    action = parts[1]
    uid = int(parts[2])
    price = get_price_int()
    
    if action == 'approve':
        user_balances[uid] = user_balances.get(uid, 0) + price
        bot.answer_callback_query(call.id, f"✅ ተጨምሯል")
        try:
            bot.send_message(uid,
                f"🌟 <b>ውድ ተጫዋች፣ ክፍያዎ በአክብሮት ተረጋግጧል!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 የተጨመረ: <b>+{price} ብር</b>\n"
                f"💵 አሁን ያለዎት: <b>{user_balances[uid]} ብር</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎫 አሁን የሚወዱትን ካርድ መምረጥ ይችላሉ!\n\n"
                f"🙏 ስለ ትዕግስትዎ ከልብ እናመሰግናለን።\n"
                f"🍀 መልካም እድል!",
                parse_mode='HTML')
        except: pass
    else:
        bot.answer_callback_query(call.id, "❌ ውድቅ ተደርጓል")
        try:
            bot.send_message(uid,
                f"🙏 ውድ ተጫዋች፣\n\n"
                f"😔 ይቅርታ አድርግልን፣ የክፍያ ማረጋገጫዎ ውድቅ ሆኗል።\n\n"
                f"🙏 እባክህ በትህትና እንጠይቅሃለን — እንደገና በትክክል ከፍለህ ስክሪንሾት ላክ።\n"
                f"💚 ስለ ግንዛቤህ እናመሰግናለን።",
                parse_mode='HTML')
        except: pass

@bot.message_handler(commands=['setprice'])
def set_price(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        payment_settings['price'] = m.text.split(' ', 1)[1]
        bot.reply_to(m, f"✅ በአክብሮት ተቀይሯል። አዲስ ዋጋ: {payment_settings['price']}")
    except: bot.reply_to(m, "🙏 እባክህ እንዲህ ጻፍ: /setprice 50 ብር")

@bot.message_handler(commands=['setaccount'])
def set_acc(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        payment_settings['account'] = m.text.split(' ', 1)[1]
        bot.reply_to(m, "✅ በአክብሮት ተቀይሯል።")
    except: bot.reply_to(m, "🙏 እባክህ እንዲህ ጻፍ: /setaccount CBE 1000123456789")

@bot.message_handler(commands=['setinterval'])
def set_int(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        payment_settings['call_interval'] = int(m.text.split(' ', 1)[1])
        bot.reply_to(m, "✅ በአክብሮት ተቀይሯል።")
    except: bot.reply_to(m, "🙏 እባክህ እንዲህ ጻፍ: /setinterval 5")

# ================= 🚀 =================

def run_flask():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    print("🌟 ሰርቨሩ በአክብሮት ተጀምሯል...")
    bot.polling(none_stop=True)
