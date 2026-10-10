import telebot
import random
import threading
import time
import os
from flask import Flask
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ⚠️ እዚህ ጋር የአንተን የቴሌግራም ID ተክለው (ከ @userinfobot ያገኘኸውን)
ADMIN_ID = 123456789 

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

class BingoGame:
    def __init__(self):
        self.players = {} 
        self.called_numbers = [] 
        self.available_numbers = self.generate_pool() 
        self.is_active = False
        self.join_open = False
        self.card_pool = [self.generate_card() for _ in range(10)] # 10 የተለያዩ ካርዶች
        self.pending_players = set() # ክፍያ የጠበቁ
        self.approved_players = set() # ክፍያ የፈጸሙ

    def generate_pool(self):
        pool = []
        for i in range(1, 16): pool.append(f"B-{i}")
        for i in range(16, 31): pool.append(f"I-{i}")
        for i in range(31, 46): pool.append(f"N-{i}")
        for i in range(46, 61): pool.append(f"G-{i}")
        for i in range(61, 76): pool.append(f"O-{i}")
        random.shuffle(pool)
        return pool

    def generate_card(self):
        card = []
        cols = [list(range(1, 16)), list(range(16, 31)), list(range(31, 46)), list(range(46, 61)), list(range(61, 76))]
        for col in cols:
            card.append(random.sample(col, 5))
        card_matrix = [[card[c][r] for c in range(5)] for r in range(5)]
        card_matrix[2][2] = "⭐"
        return card_matrix

    def format_card_for_player(self, card, called_numbers):
        text = "🎲 <b>የአንተ የቢንጎ ካርድ</b> 🎲\n\n"
        text += "  B        I        N        G        O\n"
        text += "----------------------------------------\n"
        for row in card:
            row_text = []
            for num in row:
                if num == "⭐":
                    row_text.append("   ⭐   ")
                elif str(num) in called_numbers:
                    row_text.append(f"[✅{num}]") 
                else:
                    row_text.append(f"[  {num}]") 
            text += " ".join(row_text) + "\n"
        return text

    def check_bingo(self, card, called):
        called_set = set(called)
        for row in card:
            if all(str(num) in called_set or num == "⭐" for num in row): return True
        for c in range(5):
            if all(str(card[r][c]) in called_set or card[r][c] == "⭐" for r in range(5)): return True
        if all(str(card[i][i]) in called_set or card[i][i] == "⭐" for i in range(5)): return True
        if all(str(card[i][4-i]) in called_set or card[i][4-i] == "⭐" for i in range(5)): return True
        return False

def auto_call_loop(chat_id):
    game = games.get(chat_id)
    if not game: return

    time.sleep(30)
    game.join_open = False
    bot.send_message(chat_id, "🔒 የመቀላቀል ጊዜ አልቋል! ጨዋታው አሁን ይጀመራል...")

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

# ================= የአስተዳዳሪ ትዕዛዞች =================

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
    
    bot.reply_to(message, "🎲 ጨዋታ ተጀመረ! 🎲\n\nለ30 ሰከንድ ብቻ መቀላቀል ይችላሉ!\n\n👇 ካርድ ለመምረጥ ከታች ያሉትን ቁልፎች ተጠቀሙ::")
    
    # የካርድ ምርጫ ቁልፎችን መስራት
    markup = InlineKeyboardMarkup()
    for i in range(5): # 5 ካርዶችን ብቻ እናሳይ
        markup.add(InlineKeyboardButton(f"🎫 ካርድ {i+1}", callback_data=f"select_{i}"))
    bot.send_message(chat_id, "እባክህ የምትፈልገውን ካርድ ምረጥ፦", reply_markup=markup)

    thread = threading.Thread(target=auto_call_loop, args=(chat_id,))
    thread.daemon = True
    thread.start()

@bot.message_handler(commands=['approve'])
def approve_player(message):
    if message.from_user.id != ADMIN_ID: return
    # የተላከው መልእክት reply ሆኖ የመጣ ከሆነ
    if message.reply_to_message:
        try:
            # ከመልእክቱ ውስጥ የተጫዋቹን ID ማውጣት
            text = message.reply_to_message.text
            user_id = int(text.split("ID: ")[1].split("\n")[0])
            chat_id = int(text.split("Chat ID: ")[1].split("\n")[0])
            
            if chat_id in games:
                games[chat_id].approved_players.add(user_id)
                bot.reply_to(message, f"✅ ተጫዋቹ ጸድቋል! (ID: {user_id})")
                bot.send_message(chat_id, f"✅ ክፍያዎ ተረጋግጧል! አሁን ጨዋታውን መጫወት ይችላሉ።")
            else:
                bot.reply_to(message, "⚠️ ንቁ ጨዋታ አልተገኘም።")
        except Exception as e:
            bot.reply_to(message, f"ስህተት: {e}")
    else:
        bot.reply_to(message, "እባክህ የተጫዋቹን የክፍያ መልእክት Reply አድርገህ /approve በል።")

@bot.message_handler(commands=['players'])
def list_players(message):
    if message.from_user.id != ADMIN_ID: return
    chat_id = message.chat.id
    if chat_id not in games: return
    game = games[chat_id]
    
    text = "👥 <b>የተጫዋቾች ዝርዝር</b>\n\n"
    text += f"የጸደቁ (Approved): {len(game.approved_players)}\n"
    text += f"በመጠበቅ ላይ (Pending): {len(game.pending_players)}\n\n"
    
    for uid in game.approved_players:
        text += f"✅ ID: {uid}\n"
    bot.reply_to(message, text, parse_mode='HTML')

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

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def handle_card_selection(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if chat_id not in games or not games[chat_id].is_active or not games[chat_id].join_open:
        bot.answer_callback_query(call.id, "ይቅርታ፣ የመምረጫ ጊዜው አልፏል!")
        return

    game = games[chat_id]
    if user_id in game.players:
        bot.answer_callback_query(call.id, "አንተ አስቀድመህ ካርድ መርጠሃል!")
        return

    card_index = int(call.data.split('_')[1])
    selected_card = game.card_pool[card_index]
    
    game.players[user_id] = selected_card
    game.pending_players.add(user_id)
    
    bot.answer_callback_query(call.id, "ካርድ ተመርጧል! አሁን ክፍያ ያስፈልጋል።")
    
    # የክፍያ መመሪያ መላክ
    payment_text = (
        "💳 <b>የክፍያ ማረጋገጫ</b>\n\n"
        "እባክህ የጨዋታውን መጠን ከፍለህ የክፍያ ስክሪንሾት (Screenshot) ወደዚህ ቦት ላክ።\n"
        "አስተዳዳሪው ሲያረጋግጥ ጨዋታውን መጫወት ትችላለህ።"
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

    # የክፍያ ስክሪንሾቱን ለአስተዳዳሪው መላክ
    admin_text = (
        f"🔔 <b>አዲስ የክፍያ ማረጋገጫ!</b>\n\n"
        f"👤 ተጫዋች: {message.from_user.first_name}\n"
        f"🆔 ID: {user_id}\n"
        f"💬 Chat ID: {chat_id}\n\n"
        f"👉 ለማጽደቅ ይህንን መልእክት Reply አድርገህ /approve በል።"
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
    
    if game.check_bingo(card, game.called_numbers):
        bot.reply_to(message, f"🎉🎉 BINGO! @{message.from_user.username} አሸንፏል! ጨዋታው አብቅቷል።")
        game.is_active = False 
        # ለአስተዳዳሪውም ማሳወቅ
        bot.send_message(ADMIN_ID, f"🏆 አሸናፊ! @{message.from_user.username} (ID: {user_id}) አሸንፏል!")
    else:
        bot.reply_to(message, "❌ ይቅርታ፣ ገና አልተሸነፍክም። ቁጥሮችህን በደንብ አረጋግጥ። (የውሸት ሙከራ ተደርጓል)")

if __name__ == "__main__":
    keep_alive()
    print("ቦቱ መስራት ጀምሯል...")
    bot.polling(none_stop=True)
