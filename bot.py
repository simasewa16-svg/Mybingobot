import telebot
import random
import threading
import time
import os
from flask import Flask
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ⚠️ እዚህ ጋር የአንተን የቴሌግራም ID ተክለው
ADMIN_ID = 5671366303 

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

games = {}
payment_settings = {
    'price': '50 ብር',
    'account': 'CBE 1000123456789',
    'call_interval': 5,
    'win_pattern': 'single'  # single, fullhouse, corners
}
banned_players = set()  # 🛡️ የተከለከሉ ተጫዋቾች
game_history = []  # 📜 የጨዋታ ታሪክ

# ================= 🎛️ የአስተዳዳሪ ፓነል =================

def get_main_panel(game=None):
    markup = InlineKeyboardMarkup()
    
    if game and game.is_active:
        if game.join_open:
            markup.row(
                InlineKeyboardButton("▶️ ቁጥር ጥራ", callback_data="admin_begin_calling"),
                InlineKeyboardButton("🛑 ጨዋታ አቁም", callback_data="admin_stop")
            )
        else:
            markup.row(
                InlineKeyboardButton("🛑 ጨዋታ አቁም", callback_data="admin_stop")
            )
        markup.row(
            InlineKeyboardButton("✅ ሁሉንም አጽድቅ", callback_data="admin_approve_all"),
            InlineKeyboardButton("📊 ዳሽቦርድ", callback_data="admin_dashboard")
        )
        markup.row(
            InlineKeyboardButton("👥 ተጫዋቾች", callback_data="admin_players_menu"),
            InlineKeyboardButton("⚙️ ቅንብሮች", callback_data="admin_settings_menu")
        )
    else:
        markup.row(InlineKeyboardButton("🎮 ጨዋታ ጀምር", callback_data="admin_start_game"))
        markup.row(
            InlineKeyboardButton("⚙️ ቅንብሮች", callback_data="admin_settings_menu"),
            InlineKeyboardButton("📊 ስታቲስቲክስ", callback_data="admin_stats_menu")
        )
        markup.row(
            InlineKeyboardButton("🚫 የተከለከሉ", callback_data="admin_banned_list"),
            InlineKeyboardButton("📢 ማስታወቂያ", callback_data="admin_broadcast_menu")
        )
    return markup

def get_players_menu():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📋 ዝርዝር አሳይ", callback_data="admin_list_players"),
        InlineKeyboardButton("👢 ተጫዋች አስወግድ", callback_data="admin_kick_prompt")
    )
    markup.row(
        InlineKeyboardButton("🚫 ተጫዋች አግድ", callback_data="admin_ban_prompt"),
        InlineKeyboardButton("🔙 ወደ ኋላ", callback_data="admin_back_main")
    )
    return markup

def get_settings_menu():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("💰 ዋጋ ቀይር", callback_data="admin_setprice_prompt"),
        InlineKeyboardButton("🏦 አካውንት ቀይር", callback_data="admin_setaccount_prompt")
    )
    markup.row(
        InlineKeyboardButton("⏱️ የጥሪ ፍጥነት", callback_data="admin_interval_prompt"),
        InlineKeyboardButton("🏆 የማሸነፍ ዓይነት", callback_data="admin_pattern_menu")
    )
    markup.row(InlineKeyboardButton("🔙 ወደ ኋላ", callback_data="admin_back_main"))
    return markup

def get_pattern_menu():
    markup = InlineKeyboardMarkup()
    current = payment_settings.get('win_pattern', 'single')
    markup.row(
        InlineKeyboardButton(f"{'✅' if current=='single' else '⬜'} አንድ መስመር", callback_data="admin_pattern_single"),
        InlineKeyboardButton(f"{'✅' if current=='fullhouse' else '⬜'} ሙሉ ካርድ", callback_data="admin_pattern_fullhouse")
    )
    markup.row(
        InlineKeyboardButton(f"{'✅' if current=='corners' else '⬜'} አራት ማዕዘን", callback_data="admin_pattern_corners"),
        InlineKeyboardButton("🔙 ወደ ኋላ", callback_data="admin_settings_menu")
    )
    return markup

def get_stats_menu():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📜 የጨዋታ ታሪክ", callback_data="admin_game_history"),
        InlineKeyboardButton("🏆 አሸናፊዎች", callback_data="admin_winners_list")
    )
    markup.row(InlineKeyboardButton("🔙 ወደ ኋላ", callback_data="admin_back_main"))
    return markup

def get_broadcast_menu():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📢 ሁሉንም አሳውቅ", callback_data="admin_broadcast_all"),
        InlineKeyboardButton("✅ የጸደቁትን ብቻ", callback_data="admin_broadcast_approved")
    )
    markup.row(InlineKeyboardButton("🔙 ወደ ኋላ", callback_data="admin_back_main"))
    return markup

@bot.message_handler(commands=['panel'])
def show_admin_panel(message):
    if message.from_user.id != ADMIN_ID: 
        return
    chat_id = message.chat.id
    game = games.get(chat_id)
    bot.send_message(chat_id, "🎛️ <b>የአስተዳዳሪ ፓነል</b>\n\nእባክህ የምትፈልገውን ተግባር ምረጥ፦", reply_markup=get_main_panel(game), parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_actions(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ ይህ ለአስተዳዳሪ ብቻ ነው!")
        return
    
    chat_id = call.message.chat.id
    action = call.data.replace('admin_', '')
    game = games.get(chat_id)

    # ===== ዋና ገጽ =====
    if action == "back_main":
        bot.edit_message_text("🎛️ <b>የአስተዳዳሪ ፓነል</b>\n\nእባክህ የምትፈልገውን ተግባር ምረጥ፦", chat_id, call.message.message_id, reply_markup=get_main_panel(game), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif action == "players_menu":
        bot.edit_message_text("👥 <b>የተጫዋቾች አስተዳደር</b>\n\nምን ማድረግ ትፈልጋለህ?", chat_id, call.message.message_id, reply_markup=get_players_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif action == "settings_menu":
        bot.edit_message_text("⚙️ <b>ቅንብሮች</b>\n\nምን መቀየር ትፈልጋለህ?", chat_id, call.message.message_id, reply_markup=get_settings_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif action == "stats_menu":
        bot.edit_message_text("📊 <b>ስታቲስቲክስ</b>\n\nምን ማየት ትፈልጋለህ?", chat_id, call.message.message_id, reply_markup=get_stats_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif action == "broadcast_menu":
        bot.edit_message_text("📢 <b>ማስታወቂያ</b>\n\nለማን መላክ ትፈልጋለህ?", chat_id, call.message.message_id, reply_markup=get_broadcast_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif action == "pattern_menu":
        bot.edit_message_text("🏆 <b>የማሸነፍ ዓይነት</b>\n\nአሁን ያለው: " + payment_settings.get('win_pattern', 'single'), chat_id, call.message.message_id, reply_markup=get_pattern_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    # ===== የጨዋታ ተግባራት =====
    elif action == "start_game":
        if game and game.is_active:
            bot.answer_callback_query(call.id, "⚠️ ጨዋታ አስቀድሞ ተጀምሯል!")
            return
        start_new_game(chat_id)
        bot.answer_callback_query(call.id, "🎮 ጨዋታ ተጀምሯል!")
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_panel(games.get(chat_id)))

    elif action == "begin_calling":
        if not game or not game.is_active:
            bot.answer_callback_query(call.id, "⚠️ ምንም ንቁ ጨዋታ የለም!")
            return
        if len(game.approved_players) == 0:
            bot.answer_callback_query(call.id, "⚠️ እስካሁን የጸደቀ ተጫዋች የለም!")
            return
        game.join_open = False
        bot.send_message(chat_id, "▶️ ጨዋታው ተጀምሯል! ቁጥሮች በየ" + str(payment_settings['call_interval']) + " ሰከንዱ ይጠራሉ...")
        threading.Thread(target=auto_call_loop, args=(chat_id,), daemon=True).start()
        bot.answer_callback_query(call.id, "ቁጥሮች መጠራት ጀመሩ!")
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_panel(games.get(chat_id)))

    elif action == "approve_all":
        if not game:
            bot.answer_callback_query(call.id, "⚠️ ምንም ጨዋታ የለም!")
            return
        pending_count = len(game.pending_players)
        if pending_count == 0:
            bot.answer_callback_query(call.id, "⚠️ በመጠበቅ ላይ ያለ ተጫዋች የለም!")
            return
        for uid in list(game.pending_players):
            game.approved_players.add(uid)
            game.pending_players.discard(uid)
            try:
                bot.send_message(uid, "✅ ክፍያዎ ተረጋግጧል! አሁን ጨዋታውን መጫወት ይችላሉ።")
            except: pass
        bot.answer_callback_query(call.id, f"✅ {pending_count} ተጫዋቾች ጸድቀዋል!")

    elif action == "dashboard":
        if not game:
            bot.answer_callback_query(call.id, "⚠️ ምንም ጨዋታ የለም!")
            return
        text = "📊 <b>ዳሽቦርድ</b> 📊\n\n"
        text += f"🎮 ሁኔታ: {'🟢 ንቁ' if game.is_active else '🔴 የቆመ'}\n"
        text += f"🚪 መቀላቀል: {'🔓 ክፍት' if game.join_open else '🔒 ተዘግቷል'}\n\n"
        text += f"👥 የጸደቁ: {len(game.approved_players)}\n"
        text += f"⏳ በመጠበቅ: {len(game.pending_players)}\n"
        text += f"🎫 ካርዶች: {len(game.taken_cards)} / 100\n\n"
        text += f"📢 የተጠሩ: {len(game.called_numbers)}\n"
        text += f"📦 የቀሩ: {len(game.available_numbers)}\n"
        if game.called_numbers:
            text += f"📜 የመጨረሻ 5: {', '.join(game.called_numbers[-5:])}\n"
        bot.send_message(ADMIN_ID, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "ዳሽቦርድ በግል ተልኳል!")

    elif action == "stop":
        if game:
            game.is_active = False
            bot.send_message(chat_id, "🔴 ጨዋታው በአስተዳዳሪው ተቋርጧል።")
            bot.answer_callback_query(call.id, "ጨዋታው ቆሟል!")
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_panel(games.get(chat_id)))
        else:
            bot.answer_callback_query(call.id, "ምንም ጨዋታ የለም!")

    # ===== የተጫዋች አስተዳደር =====
    elif action == "list_players":
        if not game:
            bot.answer_callback_query(call.id, "⚠️ ምንም ጨዋታ የለም!")
            return
        text = "👥 <b>የተጫዋቾች ዝርዝር</b>\n\n"
        text += f"✅ የጸደቁ ({len(game.approved_players)}):\n"
        for uid in game.approved_players:
            card_num = game.player_card_numbers.get(uid, "?")
            text += f"• ID: {uid} | ካርድ: {card_num}\n"
        text += f"\n⏳ በመጠበቅ ({len(game.pending_players)}):\n"
        for uid in game.pending_players:
            card_num = game.player_card_numbers.get(uid, "?")
            text += f"• ID: {uid} | ካርድ: {card_num}\n"
        bot.send_message(ADMIN_ID, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "ዝርዝር በግል ተልኳል!")

    elif action == "kick_prompt":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "👢 <b>ተጫዋች ለማስወገድ:</b> <code>/kick USER_ID</code> ብለህ ጻፍ\nለምሳሌ: <code>/kick 5671366303</code>", parse_mode='HTML')

    elif action == "ban_prompt":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "🚫 <b>ተጫዋች ለማገድ:</b> <code>/ban USER_ID</code> ብለህ ጻፍ\nለምሳሌ: <code>/ban 5671366303</code>", parse_mode='HTML')

    elif action == "banned_list":
        text = "🚫 <b>የተከለከሉ ተጫዋቾች</b>\n\n"
        if banned_players:
            for uid in banned_players:
                text += f"• ID: {uid}\n"
            text += "\n🔓 ለማንሳት: <code>/unban USER_ID</code>"
        else:
            text += "ምንም የተከለከለ ተጫዋች የለም።"
        bot.send_message(ADMIN_ID, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "በግል ተልኳል!")

    # ===== ቅንብሮች =====
    elif action == "setprice_prompt":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "💰 <b>ዋጋ ለመቀየር:</b> <code>/setprice 100 ብር</code>", parse_mode='HTML')

    elif action == "setaccount_prompt":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "🏦 <b>አካውንት ለመቀየር:</b> <code>/setaccount CBE 1000123456789</code>", parse_mode='HTML')

    elif action == "interval_prompt":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "⏱️ <b>የጥሪ ፍጥነት ለመቀየር:</b> <code>/setinterval 5</code> (በሰከንድ)", parse_mode='HTML')

    elif action.startswith("pattern_"):
        pattern = action.replace("pattern_", "")
        payment_settings['win_pattern'] = pattern
        pattern_names = {'single': 'አንድ መስመር', 'fullhouse': 'ሙሉ ካርድ', 'corners': 'አራት ማዕዘን'}
        bot.edit_message_text(f"🏆 የማሸነፍ ዓይነት ወደ <b>{pattern_names[pattern]}</b> ተቀይሯል!", chat_id, call.message.message_id, reply_markup=get_pattern_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id, "ተቀይሯል!")

    # ===== ስታቲስቲክስ =====
    elif action == "game_history":
        text = "📜 <b>የጨዋታ ታሪክ</b>\n\n"
        if game_history:
            for i, g in enumerate(game_history[-10:], 1):
                text += f"{i}. 🎮 {g.get('chat_title', 'Unknown')}\n"
                text += f"   🏆 አሸናፊ: {g.get('winner_name', 'Unknown')} (ካርድ: {g.get('card_num', '?')})\n"
                text += f"   📅 {g.get('date', '?')}\n\n"
        else:
            text += "እስካሁን የተጫወተ ጨዋታ የለም።"
        bot.send_message(ADMIN_ID, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "በግል ተልኳል!")

    elif action == "winners_list":
        text = "🏆 <b>የአሸናፊዎች ስታቲስቲክስ</b>\n\n"
        winner_count = {}
        for g in game_history:
            name = g.get('winner_name', 'Unknown')
            winner_count[name] = winner_count.get(name, 0) + 1
        if winner_count:
            sorted_winners = sorted(winner_count.items(), key=lambda x: x[1], reverse=True)
            for i, (name, count) in enumerate(sorted_winners[:10], 1):
                text += f"{i}. 🏆 {name} - {count} ጊዜ\n"
        else:
            text += "እስካሁን አሸናፊ የለም።"
        bot.send_message(ADMIN_ID, text, parse_mode='HTML')
        bot.answer_callback_query(call.id, "በግል ተልኳል!")

    # ===== ማስታወቂያ =====
    elif action == "broadcast_all":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "📢 <b>ማስታወቂያ ለመላክ:</b> <code>/broadcast የመልእክት ጽሑፍ</code>", parse_mode='HTML')

    elif action == "broadcast_approved":
        bot.answer_callback_query(call.id, "መልእክት ላክ")
        bot.send_message(chat_id, "📢 <b>ለተጸደቁት ብቻ ለመላክ:</b> <code>/broadcastvip የመልእክት ጽሑፍ</code>", parse_mode='HTML')

# ================= 🎮 የጨዋታ ሎጂክ =================

def start_new_game(chat_id):
    games[chat_id] = BingoGame()
    games[chat_id].is_active = True
    games[chat_id].join_open = True
    
    bot.send_message(chat_id, "🎲 <b>የምዝገባ ደረጃ ተከፍቷል!</b> 🎲\n\nካርድ ለመምረጥ ከታች ያሉትን ቁጥሮች ተጠቀሙ:", parse_mode='HTML')
    markup = get_card_grid(1, games[chat_id].taken_cards)
    bot.send_message(chat_id, "👇 ገጽ 1/4:", reply_markup=markup)

def get_card_grid(page, taken_cards):
    markup = InlineKeyboardMarkup()
    start_num = (page - 1) * 25 + 1
    end_num = min(page * 25, 100)
    row = []
    for i in range(start_num, end_num + 1):
        if (i - 1) in taken_cards:
            row.append(InlineKeyboardButton("❌", callback_data="taken"))
        else:
            row.append(InlineKeyboardButton(str(i), callback_data=f"select_{i-1}"))
        if len(row) == 5:
            markup.row(*row)
            row = []
    if row: markup.row(*row)
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ ወደኋላ", callback_data=f"page_{page-1}"))
    if page < 4: nav_row.append(InlineKeyboardButton("ወደፊት ➡️", callback_data=f"page_{page+1}"))
    if nav_row: markup.row(*nav_row)
    return markup

class BingoGame:
    def __init__(self):
        self.players = {} 
        self.player_card_numbers = {} 
        self.called_numbers = [] 
        self.available_numbers = self.generate_pool() 
        self.is_active = False
        self.join_open = False
        self.winners = [] 
        self.card_pool = self.generate_card_pool(100) 
        self.taken_cards = set() 
        self.pending_players = set() 
        self.approved_players = set() 
        self.used_receipts = set() 

    def generate_pool(self):
        pool = []
        for i in range(1, 16): pool.append(f"B-{i}")
        for i in range(16, 31): pool.append(f"I-{i}")
        for i in range(31, 46): pool.append(f"N-{i}")
        for i in range(46, 61): pool.append(f"G-{i}")
        for i in range(61, 76): pool.append(f"O-{i}")
        random.shuffle(pool)
        return pool

    def generate_single_card(self):
        card = []
        cols = [list(range(1, 16)), list(range(16, 31)), list(range(31, 46)), list(range(46, 61)), list(range(61, 76))]
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

    def format_card_for_player(self, card, called_numbers):
        text = "🎲 <b>የአንተ የቢንጎ ካርድ</b> 🎲\n\n"
        text += "  B        I        N        G        O\n"
        text += "----------------------------------------\n"
        letters = ["B", "I", "N", "G", "O"]
        for row in card:
            row_text = []
            for c_idx, num in enumerate(row):
                if num == "⭐":
                    row_text.append("   ⭐   ")
                else:
                    formatted_num = f"{letters[c_idx]}-{num}"
                    if formatted_num in called_numbers:
                        row_text.append(f"🟢 {num}") 
                    else:
                        row_text.append(f"⚪ {num}") 
            text += " ".join(row_text) + "\n"
        return text

    def check_bingo(self, card, called):
        called_set = set(called)
        letters = ["B", "I", "N", "G", "O"]
        pattern = payment_settings.get('win_pattern', 'single')
        
        # አግድም
        for row in card:
            if all(str(num) == "⭐" or f"{letters[i]}-{num}" in called_set for i, num in enumerate(row)): return True
        # ቀጥ ያለ
        for c in range(5):
            if all(str(card[r][c]) == "⭐" or f"{letters[c]}-{card[r][c]}" in called_set for r in range(5)): return True
        # ሰያፍ
        if all(str(card[i][i]) == "⭐" or f"{letters[i]}-{card[i][i]}" in called_set for i in range(5)): return True
        if all(str(card[i][4-i]) == "⭐" or f"{letters[4-i]}-{card[i][4-i]}" in called_set for i in range(5)): return True
        
        # ሙሉ ካርድ (Full House)
        if pattern == 'fullhouse':
            if all(str(card[r][c]) == "⭐" or f"{letters[c]}-{card[r][c]}" in called_set for r in range(5) for c in range(5)):
                return True
        
        # አራት ማዕዘን (Four Corners)
        if pattern == 'corners':
            corners = [card[0][0], card[0][4], card[4][0], card[4][4]]
            if all(f"{letters[0]}-{corners[0]}" in called_set, f"{letters[4]}-{corners[1]}" in called_set, 
                   f"{letters[0]}-{corners[2]}" in called_set, f"{letters[4]}-{corners[3]}" in called_set):
                return True
        
        return False

def auto_call_loop(chat_id):
    game = games.get(chat_id)
    if not game: return
    interval = payment_settings.get('call_interval', 5)
    while game.is_active:
        time.sleep(interval) 
        if not game.is_active: break
        if not game.available_numbers:
            bot.send_message(chat_id, "⚠️ ሁሉም ቁጥሮች ተጠርተዋል! ጨዋታው አልቋል።")
            game.is_active = False
            break
        number = game.available_numbers.pop()
        game.called_numbers.append(number)
        recent_calls = ", ".join(game.called_numbers[-5:])
        bot.send_message(chat_id, f"📢 የተጠራ ቁጥር፦ 🎯 *{number}*\n\n📜 የቅርብ ጊዜ ጥሪዎች፦ {recent_calls}\n\n👉 ካርድህን ለማየት /mycard በል", parse_mode='Markdown')

        new_winners = []
        for user_id, card in game.players.items():
            if user_id in game.approved_players and user_id not in game.winners:
                if game.check_bingo(card, game.called_numbers):
                    game.winners.append(user_id)
                    new_winners.append(user_id)
        if len(new_winners) > 0:
            for uid in new_winners:
                card_num = game.player_card_numbers.get(uid, "?")
                try:
                    user_info = bot.get_chat(uid)
                    winner_name = f"@{user_info.username}" if user_info.username else user_info.first_name
                except Exception:
                    winner_name = f"ID: {uid}"
                bot.send_message(chat_id, f"🎉🎉 BINGO! {winner_name} አሸንፏል! (የካርድ ቁጥር: {card_num})")
                bot.send_message(ADMIN_ID, f"🏆 አሸናፊ! {winner_name} (ID: {uid}) | ካርድ ቁጥር: {card_num}")
                
                # 📜 ወደ ታሪክ መመዝገብ
                try:
                    chat_info = bot.get_chat(chat_id)
                    chat_title = chat_info.title if chat_info.title else "Private"
                except:
                    chat_title = "Unknown"
                game_history.append({
                    'chat_title': chat_title,
                    'winner_name': winner_name,
                    'card_num': card_num,
                    'date': time.strftime("%Y-%m-%d %H:%M")
                })
            
            if len(new_winners) > 1:
                bot.send_message(chat_id, "⚠️ በርካታ አሸናፊዎች ተገኝተዋል! ሽልማቱ በእኩል ይካፈላል።")
            game.is_active = False
            break

# ================= የተጫዋቾች ተግባራት =================

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def handle_pagination(call):
    chat_id = call.message.chat.id
    if chat_id not in games or not games[chat_id].is_active or not games[chat_id].join_open:
        bot.answer_callback_query(call.id, "ይቅርታ፣ የመምረጫ ጊዜው አልፏል!")
        return
    page = int(call.data.split('_')[1])
    markup = get_card_grid(page, games[chat_id].taken_cards)
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id, f"ገጽ {page}/4")

@bot.callback_query_handler(func=lambda call: call.data == 'taken')
def handle_taken(call):
    bot.answer_callback_query(call.id, "ይህ ካርድ አስቀድሞ ተወስዷል! እባክህ ሌላ ምረጥ።")

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def handle_card_selection(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if user_id in banned_players:
        bot.answer_callback_query(call.id, "🚫 አንተ ተከልክለሃል!")
        return
    
    if chat_id not in games or not games[chat_id].is_active or not games[chat_id].join_open:
        bot.answer_callback_query(call.id, "ይቅርታ፣ የመምረጫ ጊዜው አልፏል!")
        return
    game = games[chat_id]
    if user_id in game.players:
        bot.answer_callback_query(call.id, "⛔ አንተ አስቀድመህ ካርድ መርጠሃል!")
        return
    card_index = int(call.data.split('_')[1])
    if card_index in game.taken_cards:
        bot.answer_callback_query(call.id, "ይህ ካርድ ተወስዷል!")
        return
    game.taken_cards.add(card_index)
    selected_card = game.card_pool[card_index]
    game.players[user_id] = selected_card
    game.player_card_numbers[user_id] = card_index + 1
    game.pending_players.add(user_id)
    try:
        markup = get_card_grid(1, game.taken_cards)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)
    except: pass
    bot.answer_callback_query(call.id, f"ካርድ {card_index + 1} ተመርጧል!")
    payment_text = (
        "💳 <b>የክፍያ ማረጋገጫ</b>\n\n"
        f"💰 ዋጋ: <b>{payment_settings['price']}</b>\n"
        f"🏦 አካውንት: <b>{payment_settings['account']}</b>\n\n"
        "እባክህ ከፍለህ ስክሪንሾት ወደዚህ ቦት ላክ።\n"
        "⚠️ አንድ ደረሰኝ ለአንድ ጨዋታ ብቻ!"
    )
    bot.send_message(user_id, payment_text, parse_mode='HTML')
    bot.send_message(user_id, "👇 ካርድህ:\n\n" + game.format_card_for_player(selected_card, []), parse_mode='HTML')

@bot.message_handler(content_types=['photo'])
def handle_payment_screenshot(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if user_id in banned_players:
        bot.reply_to(message, "🚫 አንተ ተከልክለሃል!")
        return
    
    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "ምንም ንቁ ጨዋታ የለም።")
        return
    if user_id not in games[chat_id].players:
        bot.reply_to(message, "እባክህ በመጀመሪያ ካርድ ምረጥ።")
        return
    game = games[chat_id]
    if user_id in game.approved_players:
        bot.reply_to(message, "⛔ አንተ አስቀድመህ ተጸድቀሃል!")
        return
    file_id = message.photo[-1].file_unique_id
    if file_id in game.used_receipts:
        bot.reply_to(message, "⛔ ይህ ደረሰኝ አስቀድሞ ተልኳል!")
        return
    game.used_receipts.add(file_id)
    admin_text = (
        f"🔔 <b>አዲስ የክፍያ ማረጋገጫ!</b>\n\n"
        f"👤 ተጫዋች: {message.from_user.first_name}\n"
        f"🆔 ID: {user_id}\n"
        f"💬 Chat ID: {chat_id}\n\n"
        f"👉 ለማጽደቅ ይህንን መልእክት Reply አድርገህ /approve በል።\n"
        f"👉 ሁሉንም በአንድ ጊዜ ለማጽደቅ /panel ተጠቀም።"
    )
    bot.send_message(ADMIN_ID, admin_text, parse_mode='HTML')
    bot.forward_message(ADMIN_ID, chat_id, message.message_id)
    bot.reply_to(message, "✅ ስክሪንሾትዎ ለአስተዳዳሪው ተልኳል።")

@bot.message_handler(commands=['mycard'])
def show_my_card(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "ምንም ንቁ ጨዋታ የለም።")
        return
    if user_id not in games[chat_id].players:
        bot.reply_to(message, "አንተ ተጫዋች አይደለህም።")
        return
    if user_id not in games[chat_id].approved_players:
        bot.reply_to(message, "⏳ ክፍያህ እንዲረጋገጥ ጠብቅ።")
        return
    game = games[chat_id]
    card = game.players[user_id]
    bot.send_message(user_id, game.format_card_for_player(card, game.called_numbers), parse_mode='HTML')

@bot.message_handler(commands=['bingo'])
def call_bingo(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "ምንም ንቁ ጨዋታ የለም።")
        return
    if user_id not in games[chat_id].players or user_id not in games[chat_id].approved_players:
        bot.reply_to(message, "አንተ ተጫዋች አይደለህም ወይም ክፍያህ አልተረጋገጠም።")
        return
    game = games[chat_id]
    card = game.players[user_id]
    if user_id in game.winners:
        bot.reply_to(message, "አንተ አስቀድመህ ቢንጎ ብለሃል!")
        return
    if game.check_bingo(card, game.called_numbers):
        game.winners.append(user_id)
        card_num = game.player_card_numbers.get(user_id, "?")
        bot.reply_to(message, f"🎉🎉 BINGO! @{message.from_user.username} አሸንፏል! (ካርድ: {card_num})")
        if len(game.winners) > 1:
            bot.send_message(chat_id, "⚠️ በርካታ አሸናፊዎች! ሽልማቱ ይካፈላል።")
        bot.send_message(ADMIN_ID, f"🏆 አሸናፊ! ID: {user_id} | ካርድ: {card_num}")
        game.is_active = False 
    else:
        bot.reply_to(message, "❌ ገና አልተሸነፍክም። (የውሸት ሙከራ)")

# ================= 🎯 የአስተዳዳሪ ትዕዛዞች =================

@bot.message_handler(commands=['setprice'])
def set_price(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        price = message.text.split(' ', 1)[1]
        payment_settings['price'] = price
        bot.reply_to(message, f"✅ ዋጋ ወደ '{price}' ተቀይሯል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /setprice 50 ብር")

@bot.message_handler(commands=['setaccount'])
def set_account(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        account = message.text.split(' ', 1)[1]
        payment_settings['account'] = account
        bot.reply_to(message, f"✅ አካውንት ወደ '{account}' ተቀይሯል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /setaccount CBE 1000123456789")

@bot.message_handler(commands=['setinterval'])
def set_interval(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        interval = int(message.text.split(' ', 1)[1])
        if interval < 1: interval = 1
        payment_settings['call_interval'] = interval
        bot.reply_to(message, f"✅ የጥሪ ፍጥነት ወደ {interval} ሰከንድ ተቀይሯል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /setinterval 5")

@bot.message_handler(commands=['approve'])
def approve_player(message):
    if message.from_user.id != ADMIN_ID: return
    if message.reply_to_message:
        try:
            text = message.reply_to_message.text
            user_id = int(text.split("ID: ")[1].split("\n")[0])
            chat_id = int(text.split("Chat ID: ")[1].split("\n")[0])
            if chat_id in games:
                games[chat_id].approved_players.add(user_id)
                games[chat_id].pending_players.discard(user_id)
                bot.reply_to(message, f"✅ ተጫዋቹ ጸድቋል! (ID: {user_id})")
                bot.send_message(chat_id, f"✅ ክፍያዎ ተረጋግጧል!")
            else:
                bot.reply_to(message, "⚠️ ንቁ ጨዋታ አልተገኘም።")
        except:
            bot.reply_to(message, "ስህተት: የተጫዋቹን መልእክት Reply አድርገህ /approve በል።")
    else:
        bot.reply_to(message, "እባክህ የተጫዋቹን መልእክት Reply አድርገህ /approve በል።")

@bot.message_handler(commands=['kick'])
def kick_player(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text.split()[1])
        chat_id = message.chat.id
        if chat_id in games:
            games[chat_id].players.pop(target_id, None)
            games[chat_id].player_card_numbers.pop(target_id, None)
            games[chat_id].approved_players.discard(target_id)
            games[chat_id].pending_players.discard(target_id)
            bot.reply_to(message, f"👢 ተጫዋች {target_id} ከጨዋታው ተወግዷል።")
            bot.send_message(target_id, "⚠️ ከጨዋታው ተወግደሃል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /kick USER_ID")

@bot.message_handler(commands=['ban'])
def ban_player(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text.split()[1])
        banned_players.add(target_id)
        chat_id = message.chat.id
        if chat_id in games:
            games[chat_id].players.pop(target_id, None)
            games[chat_id].player_card_numbers.pop(target_id, None)
            games[chat_id].approved_players.discard(target_id)
            games[chat_id].pending_players.discard(target_id)
        bot.reply_to(message, f"🚫 ተጫዋች {target_id} ተከልክሏል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /ban USER_ID")

@bot.message_handler(commands=['unban'])
def unban_player(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text.split()[1])
        banned_players.discard(target_id)
        bot.reply_to(message, f"🔓 ተጫዋች {target_id} ከእገዳ ተላቋል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /unban USER_ID")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        msg = message.text.split(' ', 1)[1]
        count = 0
        # ከታሪክ የተሰበሰቡ ተጠቃሚዎች
        users = set()
        for g in game_history:
            # ማንኛውም የተሳተፈ ተጠቃሚ
            pass
        # በአሁኑ ጨዋታ ያሉ
        for chat_id, game in games.items():
            for uid in list(game.approved_players) + list(game.pending_players):
                users.add(uid)
        for uid in users:
            try:
                bot.send_message(uid, f"📢 <b>ማስታወቂያ</b>\n\n{msg}", parse_mode='HTML')
                count += 1
            except: pass
        bot.reply_to(message, f"✅ ለ {count} ተጠቃሚዎች ተልኳል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /broadcast የመልእክት ጽሑፍ")

@bot.message_handler(commands=['broadcastvip'])
def broadcast_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        msg = message.text.split(' ', 1)[1]
        count = 0
        for chat_id, game in games.items():
            for uid in list(game.approved_players):
                try:
                    bot.send_message(uid, f"📢 <b>ማስታወቂያ (VIP)</b>\n\n{msg}", parse_mode='HTML')
                    count += 1
                except: pass
        bot.reply_to(message, f"✅ ለ {count} የጸደቁ ተጠቃሚዎች ተልኳል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /broadcastvip የመልእክት ጽሑፍ")

if __name__ == "__main__":
    keep_alive()
    print("ቦቱ መስራት ጀምሯል...")
    bot.polling(none_stop=True)
