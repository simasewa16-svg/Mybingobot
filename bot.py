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
    'account': 'CBE 1000123456789'
}

# 🎯 የካርድ ምርጫ ቁልፎችን በገጽ (Page) የሚያዘጋጅ ተግባር
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
        
        if len(row) == 5: # በአንድ ረድፍ 5 ቁልፎች
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
        
    # የገጽ ማሻገሪያ ቁልፎች
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ ወደኋላ", callback_data=f"page_{page-1}"))
    if page < 4:
        nav_row.append(InlineKeyboardButton("ወደፊት ➡️", callback_data=f"page_{page+1}"))
    if nav_row:
        markup.row(*nav_row)
        
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
        pool = []
        seen = set()
        while len(pool) < count:
            card = self.generate_single_card()
            card_str = str(card)
            if card_str not in seen:
                seen.add(card_str)
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
        for row in card:
            if all(str(num) == "⭐" or f"{letters[i]}-{num}" in called_set for i, num in enumerate(row)): return True
        for c in range(5):
            if all(str(card[r][c]) == "⭐" or f"{letters[c]}-{card[r][c]}" in called_set for r in range(5)): return True
        if all(str(card[i][i]) == "⭐" or f"{letters[i]}-{card[i][i]}" in called_set for i in range(5)): return True
        if all(str(card[i][4-i]) == "⭐" or f"{letters[4-i]}-{card[i][4-i]}" in called_set for i in range(5)): return True
        return False

def auto_call_loop(chat_id):
    game = games.get(chat_id)
    if not game: return

    while game.is_active:
        time.sleep(5) 
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
            
            if len(new_winners) > 1:
                bot.send_message(chat_id, "⚠️ በርካታ አሸናፊዎች ተገኝተዋል! ሽልማቱ በእኩል ይካፈላል።")
            
            game.is_active = False
            break

# ================= የአስተዳዳሪ ትዕዛዞች =================

@bot.message_handler(commands=['setprice'])
def set_price(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        price = message.text.split(' ', 1)[1]
        payment_settings['price'] = price
        bot.reply_to(message, f"✅ የጨዋታው ዋጋ ወደ '{price}' ተቀይሯል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /setprice 50 ብር")

@bot.message_handler(commands=['setaccount'])
def set_account(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        account = message.text.split(' ', 1)[1]
        payment_settings['account'] = account
        bot.reply_to(message, f"✅ የክፍያ አካውንት ወደ '{account}' ተቀይሯል።")
    except:
        bot.reply_to(message, "እባክህ እንዲህ ጻፍ: /setaccount CBE 1000123456789")

@bot.message_handler(commands=['start_game'])
def start_game(message):
    chat_id = message.chat.id
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ ይቅርታ፣ ጨዋታውን ማስጀመር የሚችለው አስተዳዳሪው ብቻ ነው።")
        return

    if chat_id in games and games[chat_id].is_active:
        bot.reply_to(message, "⚠️ ጨዋታ አስቀድሞ ተጀምሯል!")
        return

    games[chat_id] = BingoGame()
    games[chat_id].is_active = True
    games[chat_id].join_open = True
    
    bot.reply_to(message, "🎲 <b>የምዝገባ ደረጃ ተከፍቷል!</b> 🎲\n\nተጫዋቾች ካርድ መምረጥ እና ክፍያ መፈጸም ይችላሉ።\nአስተዳዳሪው ተጫዋቾችን ካጸደቀ በኋላ /begin_calling በማለት ጨዋታውን ይጀመራል።", parse_mode='HTML')
    
    # 🎯 የካርድ ምርጫ ገጽ 1 መላክ
    markup = get_card_grid(1, games[chat_id].taken_cards)
    bot.send_message(chat_id, "👇 ካርድ ለመምረጥ ከታች ያሉትን ቁጥሮች ተጠቀሙ (ገጽ 1/4):", reply_markup=markup)

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

@bot.message_handler(commands=['getcard'])
def get_specific_card(message):
    # ይህ ትዕዛዝ አሁን አያስፈልግም (በቁልፎች ስለሚመረጥ) ነገር ግን ለተጠቃሚዎች እንደ አማራጭ እንተወው
    bot.reply_to(message, "👇 ካርድ ለመምረጥ ከላይ ያሉትን የቁጥር ቁልፎች ተጠቀም::")

@bot.message_handler(commands=['begin_calling'])
def begin_calling(message):
    chat_id = message.chat.id
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ ይቅርታ፣ ጨዋታውን መጀመር የሚችለው አስተዳዳሪው ብቻ ነው።")
        return

    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "⚠️ ምንም ንቁ ጨዋታ የለም። በመጀመሪያ /start_game በል።")
        return

    game = games[chat_id]
    if len(game.approved_players) == 0:
        bot.reply_to(message, "⚠️ እስካሁን የጸደቀ ተጫዋች የለም! እባክህ በመጀመሪያ የክፍያ ስክሪንሾቶችን አጽድቅ።")
        return

    game.join_open = False
    bot.reply_to(message, "▶️ ጨዋታው ተጀምሯል! ቁጥሮች በየ5 ሰከንዱ ይጠራሉ...")
    
    thread = threading.Thread(target=auto_call_loop, args=(chat_id,))
    thread.daemon = True
    thread.start()

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
                bot.send_message(chat_id, f"✅ ክፍያዎ ተረጋግጧል! አሁን ጨዋታውን መጫወት ይችላሉ።")
            else:
                bot.reply_to(message, "⚠️ ንቁ ጨዋታ አልተገኘም።")
        except Exception as e:
            bot.reply_to(message, f"ስህተት: እባክህ የተጫዋቹን የክፍያ መልእክት Reply አድርገህ /approve በል።")
    else:
        bot.reply_to(message, "እባክህ የተጫዋቹን የክፍያ መልእክት Reply አድርገህ /approve በል።")

@bot.message_handler(commands=['approve_all'])
def approve_all(message):
    if message.from_user.id != ADMIN_ID: return
    chat_id = message.chat.id
    
    if chat_id not in games:
        bot.reply_to(message, "⚠️ ምንም ንቁ ጨዋታ የለም።")
        return
        
    game = games[chat_id]
    pending_count = len(game.pending_players)
    
    if pending_count == 0:
        bot.reply_to(message, "⚠️ በመጠበቅ ላይ ያለ ተጫዋች የለም።")
        return
        
    for uid in list(game.pending_players):
        game.approved_players.add(uid)
        game.pending_players.discard(uid)
        try:
            bot.send_message(chat_id, f"✅ ክፍያዎ ተረጋግጧል! አሁን ጨዋታውን መጫወት ይችላሉ።")
        except:
            pass
            
    bot.reply_to(message, f"✅ በአንድ ጊዜ {pending_count} ተጫዋቾች ጸድቀዋል!")
    bot.send_message(ADMIN_ID, f"✅ {pending_count} ተጫዋቾች በአንድ ጊዜ ጸድቀዋል።")

@bot.message_handler(commands=['dashboard'])
def admin_dashboard(message):
    if message.from_user.id != ADMIN_ID: return
    chat_id = message.chat.id
    
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass
        
    if chat_id not in games:
        bot.send_message(ADMIN_ID, "⚠️ በዚህ ቡድን ውስጥ ምንም ንቁ ጨዋታ የለም።")
        return

    game = games[chat_id]
    text = "📊 <b>የአስተዳዳሪ ዳሽቦርድ</b> 📊\n\n"
    text += f"🎮 የጨዋታ ሁኔታ: {'🟢 ንቁ' if game.is_active else '🔴 የቆመ'}\n"
    text += f"🚪 የመቀላቀል ሁኔታ: {'🔓 ክፍት' if game.join_open else '🔒 ተዘግቷል'}\n\n"
    text += f"👥 <b>ተጫዋቾች:</b>\n"
    text += f"✅ የጸደቁ: {len(game.approved_players)}\n"
    text += f"⏳ በመጠበቅ ላይ: {len(game.pending_players)}\n"
    text += f"🎫 የተወሰዱ ካርዶች: {len(game.taken_cards)} / 100\n\n"
    text += f"📢 <b>የቁጥር ሁኔታ:</b>\n"
    text += f"🔢 የተጠሩ: {len(game.called_numbers)}\n"
    text += f"📦 የቀሩ: {len(game.available_numbers)}\n"
    
    if game.called_numbers:
        text += f"📜 የመጨረሻ 5 ጥሪዎች: {', '.join(game.called_numbers[-5:])}\n"

    if game.approved_players:
        text += "\n👤 <b>የተጫዋቾች ዝርዝር (ካርድ ቁጥር):</b>\n"
        for uid in game.approved_players:
            card_num = game.player_card_numbers.get(uid, "?")
            text += f"• ID: {uid} | ካርድ: {card_num}\n"

    bot.send_message(ADMIN_ID, text, parse_mode='HTML')

@bot.message_handler(commands=['stop'])
def stop_game(message):
    chat_id = message.chat.id
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ ጨዋታውን ማቆም የሚችለው አስተዳዳሪው ብቻ ነው።")
        return
    if chat_id in games:
        games[chat_id].is_active = False
        bot.reply_to(message, "🔴 ጨዋታው በአስተዳዳሪው ተቋርጧል።")
    else:
        bot.reply_to(message, "ምንም ንቁ ጨዋታ የለም።")

# ================= የተጫዋቾች ትዕዛዞች =================

@bot.message_handler(commands=['join'])
def join_fallback(message):
    bot.reply_to(message, "👇 ካርድ ለመምረጥ ከላይ ያሉትን የቁጥር ቁልፎች ተጠቀም::")

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def handle_card_selection(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if chat_id not in games or not games[chat_id].is_active or not games[chat_id].join_open:
        bot.answer_callback_query(call.id, "ይቅርታ፣ የመምረጫ ጊዜው አልፏል!")
        return

    game = games[chat_id]
    if user_id in game.players:
        bot.answer_callback_query(call.id, "⛔ አንተ አስቀድመህ ካርድ መርጠሃል! አንድ ሰው አንድ ካርድ ብቻ መውሰድ ይችላል።")
        return

    card_index = int(call.data.split('_')[1])
    if card_index in game.taken_cards:
        bot.answer_callback_query(call.id, "ይህ ካርድ ተወስዷል! እባክህ ሌላ ምረጥ።")
        return
        
    game.taken_cards.add(card_index)
    selected_card = game.card_pool[card_index]
    game.players[user_id] = selected_card
    game.player_card_numbers[user_id] = card_index + 1
    game.pending_players.add(user_id)
    
    # 🎯 የተመረጠውን ካርድ በግርድ (❌) ምልክት ማድረግ
    try:
        markup = get_card_grid(1, game.taken_cards) # ገጹን እንደገና ማደስ
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)
    except Exception:
        pass
        
    bot.answer_callback_query(call.id, f"ካርድ {card_index + 1} ተመርጧል! አሁን ክፍያ ያስፈልጋል።")
    
    payment_text = (
        "💳 <b>የክፍያ ማረጋገጫ</b>\n\n"
        f"💰 የጨዋታው ዋጋ: <b>{payment_settings['price']}</b>\n"
        f"🏦 የክፍያ አካውንት: <b>{payment_settings['account']}</b>\n\n"
        "እባክህ የጨዋታውን መጠን ከፍለህ የክፍያ ስክሪንሾት (Screenshot) ወደዚህ ቦት ላክ።\n"
        "⚠️ አንድ ደረሰኝ ለአንድ ጨዋታ ብቻ ነው! ደጋግመህ ከላክክ ውድቅ ይደረጋል።"
    )
    bot.send_message(user_id, payment_text, parse_mode='HTML')
    bot.send_message(user_id, "👇 ካርድህ ይህ ነው፦\n\n" + game.format_card_for_player(selected_card, []), parse_mode='HTML')

@bot.message_handler(content_types=['photo'])
def handle_payment_screenshot(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "ምንም ንቁ ጨዋታ የለም።")
        return
        
    if user_id not in games[chat_id].players:
        bot.reply_to(message, "እባክህ በመጀመሪያ ካርድ ምረጥ።")
        return

    game = games[chat_id]
    
    if user_id in game.approved_players:
        bot.reply_to(message, "⛔ አንተ አስቀድመህ ተጸድቀሃል! ደጋግመህ መመዝገብ አትችልም።")
        return

    file_id = message.photo[-1].file_unique_id
    if file_id in game.used_receipts:
        bot.reply_to(message, "⛔ ይህ ደረሰኝ አስቀድሞ ተልኳል! እባክህ አዲስ ደረሰኝ ላክ።")
        return
        
    game.used_receipts.add(file_id)

    admin_text = (
        f"🔔 <b>አዲስ የክፍያ ማረጋገጫ!</b>\n\n"
        f"👤 ተጫዋች: {message.from_user.first_name}\n"
        f"🆔 ID: {user_id}\n"
        f"💬 Chat ID: {chat_id}\n\n"
        f"👉 ለማጽደቅ ይህንን መልእክት Reply አድርገህ /approve በል።\n"
        f"👉 ሁሉንም በአንድ ጊዜ ለማጽደቅ /approve_all በል።"
    )
    bot.send_message(ADMIN_ID, admin_text, parse_mode='HTML')
    bot.forward_message(ADMIN_ID, chat_id, message.message_id)
    
    bot.reply_to(message, "✅ የክፍያ ስክሪንሾትዎ ለአስተዳዳሪው ተልኳል። እባክህ ማረጋገጫ ጠብቅ።")

@bot.message_handler(commands=['mycard'])
def show_my_card(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "ምንም ንቁ የቢንጎ ጨዋታ የለም።")
        return
        
    if user_id not in games[chat_id].players:
        bot.reply_to(message, "አንተ የዚህ ጨዋታ ተጫዋች አይደለህም።")
        return

    if user_id not in games[chat_id].approved_players:
        bot.reply_to(message, "⏳ እባክህ በመጀመሪያ ክፍያህ እንዲረጋገጥ ጠብቅ።")
        return

    game = games[chat_id]
    card = game.players[user_id]
    formatted_card = game.format_card_for_player(card, game.called_numbers)
    bot.send_message(user_id, formatted_card, parse_mode='HTML')

@bot.message_handler(commands=['bingo'])
def call_bingo(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in games or not games[chat_id].is_active:
        bot.reply_to(message, "ምንም ንቁ የቢንጎ ጨዋታ የለም።")
        return
    
    if user_id not in games[chat_id].players or user_id not in games[chat_id].approved_players:
        bot.reply_to(message, "አንተ የዚህ ጨዋታ ተጫዋች አይደለህም ወይም ክፍያህ አልተረጋገጠም።")
        return

    game = games[chat_id]
    card = game.players[user_id]
    
    if user_id in game.winners:
        bot.reply_to(message, "አንተ አስቀድመህ ቢንጎ ብለሃል!")
        return

    if game.check_bingo(card, game.called_numbers):
        game.winners.append(user_id)
        card_num = game.player_card_numbers.get(user_id, "?")
        bot.reply_to(message, f"🎉🎉 BINGO! @{message.from_user.username} አሸንፏል! (የካርድ ቁጥር: {card_num})")
        
        if len(game.winners) > 1:
            bot.send_message(chat_id, "⚠️ በርካታ አሸናፊዎች ተገኝተዋል! ሽልማቱ በእኩል ይካፈላል።")
        
        winners_list = "\n".join([f"🏆 {uid}" for uid in game.winners])
        bot.send_message(ADMIN_ID, f"🏆 <b>አሸናፊ(ዎች) ተገኙ!</b>\n\n{winners_list}\n\nጨዋታው በራሱ ቆሟል።", parse_mode='HTML')
        
        game.is_active = False 
    else:
        bot.reply_to(message, "❌ ይቅርታ፣ ገና አልተሸነፍክም። ቁጥሮችህን በደንብ አረጋግጥ። (የውሸት ሙከራ ተደርጓል)")

if __name__ == "__main__":
    keep_alive()
    print("ቦቱ መስራት ጀምሯል...")
    bot.polling(none_stop=True)
