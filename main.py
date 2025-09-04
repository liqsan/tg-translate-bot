import telebot  
import os  
import re
import logging
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BOT_TOKEN=os.getenv("token")

bot = telebot.TeleBot(BOT_TOKEN)

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE    = re.compile(r"[A-Za-z]")


@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"Получена команда /start от {message.from_user.id} ({message.from_user.username})")
    bot.send_message(message.chat.id, "Привет! Отправь мне текст, и я переведу его на английский язык.")

@bot.message_handler(content_types=['text'])
def translate_text(message):
    text = message.text.strip()
    if not text:
        return
    
    if CYRILLIC_RE.search(text):
        target_lang = "en"
    elif LATIN_RE.search(text):
        target_lang = "ru"
    else:
        target_lang = "en"

    try:
        translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
        bot.send_message(message.chat.id, translated)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка перевода: {e}")

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
