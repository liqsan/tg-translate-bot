import telebot  
import os  
import logging
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BOT_TOKEN=os.getenv("token")

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"Получена команда /start от {message.from_user.id} ({message.from_user.username})")
    bot.send_message(message.chat.id, "Привет! Я эхо-бот. Напиши что-нибудь.")

@bot.message_handler(content_types=['text','photo','video','document','audio','voice','sticker','animation','video_note'])
def echo(message):
    ct = message.content_type
    try: 
        print(ct)
        if ct == 'text':
            bot.send_message(message.chat.id, message.text)
        else:
            bot.send_message(message.chat.id, f"Я пока не умею обрабатывать {ct}")
    except Exception:
        bot.send_message(message.chat.id, f"Ошибка {ct}")
    logging.info(f"Получено сообщение: {message.text} от {message.from_user.id} ({message.from_user.username})")

logging.info("Бот запущен и слушает сообщения...")

bot.polling()
