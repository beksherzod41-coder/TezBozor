#!/bin/bash
# TezBozor — PythonAnywhere deploy script
# Ishlatish: bash deploy.sh

echo "🔄 TezBozor yangilanmoqda..."

# 1. GitHub'dan yangi kodni olamiz
cd ~/TezBozor
git pull origin main

if [ $? -ne 0 ]; then
    echo "❌ Git pull xatosi! Internet yoki repo tekshiring."
    exit 1
fi

# 2. Yangi paketlar o'rnatish (requirements.txt o'zgargan bo'lsa)
pip3.11 install -q -r requirements.txt

# 3. Eski bot jarayonini to'xtatamiz
pkill -f "python3.11 main.py" 2>/dev/null || true
sleep 2

# 4. Yangi botni background da ishga tushiramiz
nohup python3.11 main.py >> bot.log 2>&1 &
BOT_PID=$!

sleep 3

# 5. Bot ishga tushganini tekshiramiz
if kill -0 $BOT_PID 2>/dev/null; then
    echo "✅ Bot muvaffaqiyatli ishga tushdi! (PID: $BOT_PID)"
    echo "📋 Logni ko'rish: tail -f bot.log"
else
    echo "❌ Bot ishga tushmadi! Logni tekshiring:"
    tail -20 bot.log
    exit 1
fi
