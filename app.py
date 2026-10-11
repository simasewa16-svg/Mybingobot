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
}

banned_players = set()

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

@app.route('/api/join', methods=['POST'])
def api_join():
    data = request.json
    user_id = data.get('user_id')
    room_id = data.get('room_id')
    card_num = data.get('card_num')

    if user_id in banned_players:
        return jsonify({'ok': False, 'msg': '🚫 ተከልክለሃል!'})
    if room_id not in rooms:
        return jsonify({'ok': False, 'msg': '⚠️ ክፍል አልተገኘም'})
    r = rooms[room_id]
    if r.game_state == 'playing' or r.game_state == 'finished':
        return jsonify({'ok': False, 'msg': '🔒 ጨዋታ ተጀምሯል! ሌላ ጨዋታ ጠብቅ።'})
    if not r.join_open:
        return jsonify({'ok': False, 'msg': '⏰ የመግቢያ ጊዜ አልፏል!'})
    if user_id in r.players:
        return jsonify({'ok': False, 'msg': '⛔ ካርድ መርጠሃል!'})
    card_index = card_num - 1
    if card_index < 0 or card_index >= len(r.card_pool):
        return jsonify({'ok': False, 'msg': '⚠️ ካርድ አልተገኘም'})
    if card_index in r.taken_cards:
        return jsonify({'ok': False, 'msg': f'❌ ካርድ {card_num} አስቀድሞ ተወስዷል!'})

    r.taken_cards.add(card_index)
    selected_card = r.card_pool[card_index]
    r.players[user_id] = selected_card
    r.player_card_numbers[user_id] = card_num
    r.pending_players.add(user_id)

    return jsonify({
        'ok': True,
        'card': selected_card,
        'card_num': card_num,
        'called': r.called_numbers,
        'payment': {
            'price': payment_settings['price'],
            'account': payment_settings['account'],
        }
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
        'approved': user_id in r.approved_players,
    })

@app.route('/api/bingo', methods=['POST'])
def api_bingo():
    data = request.json
    user_id = data.get('user_id')
    room_id = data.get('room_id')
    if room_id not in rooms:
        return jsonify({'ok': False, 'msg': 'Room አልተገኘም'})
    r = rooms[room_id]
    if user_id not in r.approved_players:
        return jsonify({'ok': False, 'msg': 'አልተጸደቅክም'})
    if user_id in r.winners:
        return jsonify({'ok': False, 'msg': 'አስቀድመህ አሸንፈሃል'})
    if not r.is_active:
        return jsonify({'ok': False, 'msg': 'ጨዋታው አልተጀመረም'})
    card = r.players[user_id]
    if r.check_bingo(card, r.called_numbers):
        r.winners.append(user_id)
        card_num = r.player_card_numbers.get(user_id, "?")
        try:
            info = bot.get_chat(user_id)
            name = f"@{info.username}" if info.username else info.first_name
        except:
            name = f"ID: {user_id}"
        r.winner_name = name
        r.winner_card = card_num
        winner_msg = (
            f"🎉🎉🎉 <b>BINGO!</b> 🎉🎉🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>እንኳን ደስ ያለህ/ሽ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>አሸናፊ:</b> {name}\n"
            f"🎫 <b>የካርድ ቁጥር:</b> #{card_num}\n"
            f"🎯 <b>የተጠሩ ቁጥሮች:</b> {len(r.called_numbers)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌟 <i>ጨዋታው በዚህ አብቅቷል!</i>\n"
            f"🎊 <i>እንኳን ደስ አለህ/ሽ!</i>"
        )
        if r.chat_id:
            try: bot.send_message(r.chat_id, winner_msg, parse_mode='HTML')
            except: pass
        bot.send_message(ADMIN_ID, winner_msg, parse_mode='HTML')
        try:
            bot.send_message(user_id,
                f"🎉🎉🎉 <b>እንኳን ደስ ያለህ/ሽ!</b> 🎉🎉🎉\n\n"
                f"🏆 አንተ/አንቺ አሸናፊ ነህ/ነሽ!\n"
                f"🎫 የካርድህ ቁጥር: <b>#{card_num}</b>\n"
                f"🎯 ጠቅላላ የተጠሩ ቁጥሮች: <b>{len(r.called_numbers)}</b>\n\n"
                f"🌟 ግሩም ጨዋታ ነበር! በቀጣዩ ጨዋታ እንገናኝ! 🎊",
                parse_mode='HTML')
        except: pass
        r.is_active = False
        r.game_state = 'finished'
        return jsonify({
            'ok': True,
            'winner': name,
            'card_num': card_num,
            'winner_id': user_id
        })
    return jsonify({'ok': False, 'msg': '❌ ገና አልተሸነፍክም'})

# ================= 🔐 Secret Admin API =================

@app.route('/api/admin/allcards', methods=['POST'])
def api_admin_allcards():
    data = request.json
    if data.get('user_id') != ADMIN_ID:
        return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id not in rooms:
        return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    result = []
    for uid, card in r.players.items():
        try:
            info = bot.get_chat(uid)
            name = f"@{info.username}" if info.username else info.first_name
        except:
            name = f"ID: {uid}"
        result.append({
            'user_id': uid,
            'name': name,
            'card_num': r.player_card_numbers.get(uid),
            'card': card,
            'approved': uid in r.approved_players,
            'pending': uid in r.pending_players,
            'winner': uid in r.winners,
        })
    return jsonify({'players': result})

@app.route('/api/admin/call_number', methods=['POST'])
def api_admin_call_number():
    data = request.json
    if data.get('user_id') != ADMIN_ID:
        return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    num = data.get('number')
    if room_id not in rooms:
        return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if num in r.called_numbers:
        return jsonify({'ok': False, 'msg': 'ቁጥሩ አስቀድሞ ተጠርቷል'})
    if num in r.available_numbers:
        r.available_numbers.remove(num)
    r.called_numbers.append(num)
    r.last_called = num
    return jsonify({'ok': True})

@app.route('/api/admin/force_win', methods=['POST'])
def api_admin_force_win():
    data = request.json
    if data.get('user_id') != ADMIN_ID:
        return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    target = data.get('target_user_id')
    if room_id not in rooms:
        return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    if target in r.players:
        r.winners.append(target)
        card_num = r.player_card_numbers.get(target, "?")
        try:
            info = bot.get_chat(target)
            name = f"@{info.username}" if info.username else info.first_name
        except:
            name = f"ID: {target}"
        r.winner_name = name
        r.winner_card = card_num
        if r.chat_id:
            try: bot.send_message(r.chat_id, f"🏆 አስተዳዳሪው {name} አሸናፊ አድርጎታል! (ካርድ: {card_num})")
            except: pass
        r.is_active = False
        r.game_state = 'finished'
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/admin/toggle_pause', methods=['POST'])
def api_admin_toggle_pause():
    data = request.json
    if data.get('user_id') != ADMIN_ID:
        return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id not in rooms:
        return jsonify({'error': 'not found'}), 404
    r = rooms[room_id]
    r.paused = not r.paused
    return jsonify({'paused': r.paused})

@app.route('/api/admin/reset', methods=['POST'])
def api_admin_reset():
    data = request.json
    if data.get('user_id') != ADMIN_ID:
        return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    if room_id in rooms:
        del rooms[room_id]
    return jsonify({'ok': True})

@app.route('/api/admin/set_name', methods=['POST'])
def api_admin_set_name():
    data = request.json
    if data.get('user_id') != ADMIN_ID:
        return jsonify({'error': 'unauthorized'}), 403
    room_id = data.get('room_id')
    name = data.get('name', '').strip()
    if room_id in rooms and name:
        rooms[room_id].game_name = name
        return jsonify({'ok': True})
    return jsonify({'ok': False})

# ================= 🤖 የቦት ክፍል =================

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
        "🎛️ <b>የአስተዳዳሪ ፓነል</b>\n\nምን ማድረግ ትፈልጋለህ?",
        reply_markup=get_main_panel(), parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
def handle_admin(call):
    global room_counter
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ ለአስተዳዳሪ ብቻ!")
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
            f"🎮 <b>{rooms[rid].game_name} - ክፍል {rid} ተከፍቷል!</b>\n\n"
            f"💰 ዋጋ: {payment_settings['price']}\n"
            f"🎫 ካርዶች: 1-{len(rooms[rid].card_pool)}\n"
            f"⏱️ የመግቢያ ጊዜ: 2 ደቂቃ\n\n"
            f"👇 ተጫዋቾች የቢንጎ ገጹን ከፍተው ካርድ ይምረጡ:",
            reply_markup=get_main_panel(rid), parse_mode='HTML')

    elif data == "adm_list_rooms":
        text = "📋 <b>የክፍት ክፍሎች</b>\n\n"
        for rid, r in rooms.items():
            status = "🟢" if r.is_active else "🔴"
            text += f"{status} ክፍል {rid}: {len(r.approved_players)} ተጫዋቾች | {r.game_state}\n"
        if not rooms: text = "ምንም ክፍል የለም።"
        bot.send_message(chat_id, text, parse_mode='HTML')

    elif data.startswith("adm_appr_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        pending = list(r.pending_players)
        for uid in pending:
            r.approved_players.add(uid)
            r.pending_players.discard(uid)
            try: bot.send_message(uid, "✅ ክፍያዎ ተረጋግጧል!")
            except: pass
        bot.answer_callback_query(call.id, f"✅ {len(pending)} ተጸድቀዋል!")
        bot.send_message(chat_id, f"✅ ክፍል {rid}: {len(pending)} ተጫዋቾች ጸድቀዋል!")

    elif data.startswith("adm_begin_"):
        rid = int(data.split('_')[2])
        if rid not in rooms: return
        r = rooms[rid]
        if len(r.approved_players) == 0:
            bot.answer_callback_query(call.id, "⚠️ ተጫዋች የለም!")
            return
        r.join_open = False
        r.game_state = 'playing'
        threading.Thread(target=auto_call_loop, args=(rid,), daemon=True).start()
        bot.answer_callback_query(call.id, "▶️ ተጀምሯል!")
        bot.send_message(chat_id, f"▶️ ክፍል {rid} ጨዋታ ተጀመረ!")

    elif data.startswith("adm_stop_"):
        rid = int(data.split('_')[2])
        if rid in rooms:
            rooms[rid].is_active = False
            rooms[rid].game_state = 'finished'
        bot.answer_callback_query(call.id, "🛑 ቆሟል!")
        bot.send_message(chat_id, f"🛑 ክፍል {rid} ተቋርጧል።")

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
        text += f"💰 ገቢ: {len(r.approved_players) * 50} ብር\n"
        bot.send_message(chat_id, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "ዳሽቦርድ ተልኳል!")

    elif data == "adm_settings":
        bot.send_message(chat_id,
            "⚙️ <b>ቅንብሮች</b>\n\n"
            "💰 <code>/setprice 50 ብር</code>\n"
            "🏦 <code>/setaccount CBE 1000123456789</code>\n"
            "⏱️ <code>/setinterval 5</code>",
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
                try: bot.send_message(r.chat_id, "⚠️ ሁሉም ቁጥሮች ተጠርተዋል!")
                except: pass
            r.is_active = False
            r.game_state = 'finished'
            break
        num = r.available_numbers.pop()
        r.called_numbers.append(num)
        r.last_called = num
        if r.chat_id:
            try: bot.send_message(r.chat_id, f"📢 ክፍል {room_id}: 🎯 ቁጥር <b>{num}</b>", parse_mode='HTML')
            except: pass

        new_winners = []
        for uid, card in r.players.items():
            if uid in r.approved_players and uid not in r.winners:
                if r.check_bingo(card, r.called_numbers):
                    r.winners.append(uid)
                    new_winners.append(uid)
        if new_winners:
            for uid in new_winners:
                try:
                    info = bot.get_chat(uid)
                    name = f"@{info.username}" if info.username else info.first_name
                except: name = f"ID: {uid}"
                card_num = r.player_card_numbers.get(uid, "?")
                r.winner_name = name
                r.winner_card = card_num
                winner_msg = (
                    f"🎉🎉🎉 <b>BINGO!</b> 🎉🎉🎉\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏆 <b>እንኳን ደስ ያለህ/ሽ!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>አሸናፊ:</b> {name}\n"
                    f"🎫 <b>የካርድ ቁጥር:</b> #{card_num}\n"
                    f"🎯 <b>የተጠሩ ቁጥሮች:</b> {len(r.called_numbers)}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌟 <i>ጨዋታው በዚህ አብቅቷል!</i>\n"
                    f"🎊 <i>እንኳን ደስ አለህ/ሽ!</i>"
                )
                if r.chat_id:
                    try: bot.send_message(r.chat_id, winner_msg, parse_mode='HTML')
                    except: pass
                bot.send_message(ADMIN_ID, winner_msg, parse_mode='HTML')
                try:
                    bot.send_message(uid,
                        f"🎉🎉🎉 <b>እንኳን ደስ ያለህ/ሽ!</b> 🎉🎉🎉\n\n"
                        f"🏆 አንተ/አንቺ አሸናፊ ነህ/ነሽ!\n"
                        f"🎫 የካርድህ ቁጥር: <b>#{card_num}</b>\n"
                        f"🎯 ጠቅላላ የተጠሩ ቁጥሮች: <b>{len(r.called_numbers)}</b>\n\n"
                        f"🌟 ግሩም ጨዋታ ነበር! በቀጣዩ ጨዋታ እንገናኝ! 🎊",
                        parse_mode='HTML')
                except: pass
            r.is_active = False
            r.game_state = 'finished'
            break

# ================= 📥 የክፍያ ስክሪንሾት =================

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = message.from_user.id
    if uid in banned_players: return
    for rid, r in rooms.items():
        if uid in r.pending_players:
            file_id = message.photo[-1].file_unique_id
            if file_id in r.used_receipts:
                bot.reply_to(message, "⛔ ደረሰኙ ተልኳል!")
                return
            r.used_receipts.add(file_id)
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("✅ አጽድቅ", callback_data=f"pay_approve_{uid}_{rid}"),
                InlineKeyboardButton("❌ ውድቅ", callback_data=f"pay_reject_{uid}_{rid}")
            )
            bot.send_message(ADMIN_ID,
                f"🔔 <b>አዲስ ክፍያ!</b>\n\n"
                f"👤 {message.from_user.first_name}\n"
                f"🆔 {uid}\n"
                f"🏠 ክፍል: {rid}\n"
                f"💰 {payment_settings['price']}",
                reply_markup=markup, parse_mode='HTML')
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "✅ ስክሪንሾት ተልኳል።")
            return
    bot.reply_to(message, "⚠️ በመጀመሪያ ካርድ ምረጥ።")

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def handle_pay(call):
    if call.from_user.id != ADMIN_ID: return
    parts = call.data.split('_')
    action = parts[1]
    uid = int(parts[2])
    rid = int(parts[3])
    if rid not in rooms: return
    r = rooms[rid]
    if action == 'approve':
        r.approved_players.add(uid)
        r.pending_players.discard(uid)
        bot.answer_callback_query(call.id, "✅ ጸድቋል!")
        try: bot.send_message(uid, "✅ ክፍያዎ ተረጋግጧል!")
        except: pass
    else:
        r.pending_players.discard(uid)
        r.players.pop(uid, None)
        r.player_card_numbers.pop(uid, None)
        bot.answer_callback_query(call.id, "❌ ውድቅ!")
        try: bot.send_message(uid, "❌ ክፍያዎ ውድቅ ተደርጓል።")
        except: pass

# ================= 🎯 የአስተዳዳሪ ትዕዛዞች =================

@bot.message_handler(commands=['setprice'])
def set_price(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        payment_settings['price'] = m.text.split(' ', 1)[1]
        bot.reply_to(m, f"✅ ዋጋ: {payment_settings['price']}")
    except: bot.reply_to(m, "/setprice 50 ብር")

@bot.message_handler(commands=['setaccount'])
def set_acc(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        payment_settings['account'] = m.text.split(' ', 1)[1]
        bot.reply_to(m, "✅ አካውንት ተቀይሯል")
    except: bot.reply_to(m, "/setaccount CBE 1000123456789")

@bot.message_handler(commands=['setinterval'])
def set_int(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        payment_settings['call_interval'] = int(m.text.split(' ', 1)[1])
        bot.reply_to(m, "✅ ተቀይሯል")
    except: bot.reply_to(m, "/setinterval 5")

# ================= 🚀 ማስጀመሪያ =================

def run_flask():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    print("🚀 ቦቱ እና ዌብ ሰርቨሩ ተጀምረዋል...")
    bot.polling(none_stop=True)
