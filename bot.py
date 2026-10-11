def format_card_for_player(self, card, called_numbers):
    text = "🎲 <b>የአንተ የቢንጎ ካርድ</b> 🎲\n\n"
    text += "  B        I        N        G        O\n"
    text += "----------------------------------------\n"
    letters = ["B", "I", "N", "G", "O"] # የአምዶች ፊደላት
    
    for row in card:
        row_text = []
        for c_idx, num in enumerate(row):
            if num == "⭐":
                row_text.append("   ⭐   ")
            else:
                # ቁጥሩን ከአምዱ ፊደል ጋር በማጣመር ማመሳከር (ለምሳሌ "N-44")
                formatted_num = f"{letters[c_idx]}-{num}"
                if formatted_num in called_numbers:
                    row_text.append(f"[✅{num}]") 
                else:
                    row_text.append(f"[  {num}]") 
        text += " ".join(row_text) + "\n"
    return text
