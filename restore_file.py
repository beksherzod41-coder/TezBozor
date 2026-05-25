# This script will restore the seller_profile function to a working state
with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and replace the seller_profile function with a working version
new_seller_profile = '''async def seller_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user_by_telegram_id(update.effective_user.id)
    
    keyboard = [
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")],
    ]
    
    avg_rating = db.get_seller_avg_rating(user['id'])
    
    landmark_text = user['shop_landmark'] or "Ko'rsatilmagan"
    working_days_text = user['working_days'] or "Ko'rsatilmagan"
    working_hours_text = user['working_hours'] or "Ko'rsatilmagan"
    telegram_text = user['telegram_username'] or "Ko'rsatilmagan"
    
    await query.edit_message_text(
        f"🏪 SOTUVCHI PROFILI\\n\\n"
        f"Do'kon: {user['shop_name']}\\n"
        f"Manzil: {user['shop_address']}\\n"
        f"Mo'ljal: {landmark_text}\\n"
        f"Ish kunlari: {working_days_text}\\n"
        f"Ish vaqti: {working_hours_text}\\n"
        f"Telegram: {telegram_text}\\n"
        f"Telefon: {user['phone_number']}\\n"
        f"⭐ Reyting: {avg_rating:.1f}/5.0\\n"
        f"Ro'yxatdan o'tgan: {user['created_at']}\\n\\n"
        f"TezBozor sotuvchisiz!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

'''

# Find the seller_profile function and replace it
in_function = False
function_start = -1
function_end = -1

for i, line in enumerate(lines):
    if 'async def seller_profile' in line:
        in_function = True
        function_start = i
    elif in_function and line.strip().startswith('async def') and 'seller_profile' not in line:
        function_end = i
        break
    elif in_function and i > function_start and line.strip() == '':
        # Check if next line is a new function
        if i + 1 < len(lines) and lines[i + 1].strip().startswith('async def'):
            function_end = i
            break

if function_start != -1 and function_end != -1:
    # Replace the function
    lines[function_start:function_end] = [new_seller_profile]
    print("Replaced seller_profile function")
else:
    print("Could not find seller_profile function boundaries")

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("File restored")
