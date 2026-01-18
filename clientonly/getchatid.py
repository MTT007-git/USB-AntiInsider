"""
Get your chat id for authorization without a key
"""

import os
import dotenv
import telebot

dotenv.load_dotenv(".env")
bot = telebot.TeleBot(os.getenv("USB_TOKEN"))


@bot.message_handler(func=lambda _: True)
def any_message(msg):
    bot.send_message(msg.chat.id, f"Your chat ID: {msg.chat.id}")


bot.polling()
