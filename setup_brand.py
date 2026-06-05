"""Bir martalik: BotFather'ga avtomatik tavsif, qisqa tavsif va komandalar qo'yadi.

Ishga tushirish:  py -3.11 setup_brand.py
"""
import asyncio
import os
from dotenv import load_dotenv
from telegram import Bot, BotCommand
from tezbozor_design import BRAND

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")


async def setup():
    bot = Bot(TOKEN)
    
    try:
        # Tavsif (uzun, bot profili ostidagi)
        await bot.set_my_description(BRAND["description"])
        print("✅ Tavsif qo'yildi")
    except Exception as e:
        print(f"❌ Tavsif xatosi: {e}")
    
    try:
        # Qisqa tavsif (bot kartochkasidagi)
        await bot.set_my_short_description(BRAND["short_description"])
        print("✅ Qisqa tavsif qo'yildi")
    except Exception as e:
        print(f"❌ Qisqa tavsif xatosi: {e}")
    
    try:
        # Komandalar ro'yxati
        commands = [BotCommand(cmd, desc) for cmd, desc in BRAND["commands"]]
        await bot.set_my_commands(commands)
        print("✅ Komandalar qo'yildi")
    except Exception as e:
        print(f"❌ Komandalar xatosi: {e}")
    
    print("\n🎉 Tayyor! Botni Telegramda oching va profilni tekshiring.")


if __name__ == "__main__":
    asyncio.run(setup())
