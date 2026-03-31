"""
Run this once after creating your bot to find your Telegram chat ID.
1. Start your bot on Telegram (send it any message)
2. Run: python get_chat_id.py
3. Copy the chat ID into your .env file
"""
import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def main():
    bot = Bot(token=TOKEN)
    updates = await bot.get_updates()
    if not updates:
        print("No messages found. Send your bot a message on Telegram first, then run this again.")
        return
    for update in updates:
        if update.message:
            print(f"Chat ID: {update.message.chat.id}")
            print(f"From: {update.message.from_user.first_name}")
            print(f"\nAdd this to your .env:\nTELEGRAM_CHAT_ID={update.message.chat.id}")
            break

asyncio.run(main())
