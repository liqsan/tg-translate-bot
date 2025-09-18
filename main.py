import telebot  
import os  
import re
import json
import logging
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
BOT_TOKEN=os.getenv("token")

BOT_TOKEN = os.getenv("TOKEN")
if not BOT_TOKEN:
    raise RuntimeError ("Переменная окружения TOKEN не найдена. Укажи TOKEN в .env")
                       
bot = telebot.TeleBot(BOT_TOKEN)

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE    = re.compile(r"[A-Za-z]")
ONLY_EMOJI_RE = re.compile(r"^\W+$", re.UNICODE)

TYPE_RU = {
    "sticker": "стикеры",
    "photo": "фотографии",
    "video": "видео",
    "document": "документы",
    "audio": "аудио",
    "voice": "голосовые сообщения",
    "animation": "анимации",
    "video_note": "видеосообщения",
    "emoji": "эмодзи",
    }

STATS_FILE = "stats.json"
stats = {
    "messages_total": 0,
    "by_type": {k: 0 for k in list(TYPE_RU.keys()) + ["text"]},
    "translations": {"ru_to_en": 0, "en_to_ru": 0, "other": 0},
    "users": {}
}


def load_stats():
    global stats
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            logging.exception("Не удалось загрузить stats.json, использую дефолт.")

def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Не удалось сохранить stats.json")

def bump_stat(message, kind):
    stats["messages_total"] += 1
    stats["by_type"][kind] = stats["by_type"].get(kind, 0) + 1
    uid = str(message.from_user.id)
    stats["users"][uid] = stats["users"].get(uid, 0) + 1
    save_stats()

load_stats()
    

@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"/start от {message.from_user.id} ({message.from_user.username})")
    bot.send_message(
        message.chat.id,
        "Привет! Отправь мне текст — я переведу его на русский или английский.\n"
        "Команда: /stats — показать статистику."
    )

@bot.message_handler(commands=['stats'])
def show_stats(message):
    try:
        total = stats.get("messages_total", 0)
        bt = stats.get("by_type", {})
        tr = stats.get("translations", {})
        top = sorted(stats.get("users", {}).items(), key=lambda x: x[1], reverse=True)[:5]
        top_str = "\n".join([f"• {uid}: {cnt}" for uid, cnt in top]) or "—"

        text = (
            f"📊 Статистика бота\n"
            f"Всего сообщений: {total}\n\n"
            f"По типам:\n"
            f"• текст: {bt.get('text',0)}\n"
            f"• эмодзи: {bt.get('emoji',0)}\n"
            f"• фотографии: {bt.get('photo',0)}\n"
            f"• видео: {bt.get('video',0)}\n"
            f"• документы: {bt.get('document',0)}\n"
            f"• аудио: {bt.get('audio',0)}\n"
            f"• голосовые сообщения: {bt.get('voice',0)}\n"
            f"• анимации: {bt.get('animation',0)}\n"
            f"• видеосообщения: {bt.get('video_note',0)}\n"
            f"• стикеры: {bt.get('sticker',0)}\n\n"
            f"Переводы:\n"
            f"• RU → EN: {tr.get('ru_to_en',0)}\n"
            f"• EN → RU: {tr.get('en_to_ru',0)}\n"
            f"• другие: {tr.get('other',0)}\n\n"
            f"Топ пользователей:\n{top_str}"
        )
        bot.send_message(message.chat.id, text)
    except Exception:
        logging.exception("Ошибка /stats")
        bot.send_message(message.chat.id, "Не удалось показать статистику 😕")


@bot.message_handler(content_types=['text'])
def translate_text(message):
    text = message.text.strip()
    if not text:
        return
    
    if ONLY_EMOJI_RE.match(text):
        bump_stat(message, "emoji")
        bot.send_message(message.chat.id, "Я пока не умею обрабатывать эмодзи.")
        return

    bump_stat(message, "text")



    
    if CYRILLIC_RE.search(text) and not LATIN_RE.search(text):
        target_lang = "en"; direction = "ru_to_en"
    elif LATIN_RE.search(text) and not CYRILLIC_RE.search(text):
        target_lang = "ru"; direction = "en_to_ru"
    else:
        target_lang = "en"; direction = "other"

    try:
        translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
        bot.send_message(message.chat.id, translated)
        stats["translations"][direction] = stats["translations"].get(direction, 0) + 1
        save_stats()
    except Exception:
        logging.exception("Ошибка перевода")
        bot.send_message(message.chat.id, "Ошибка перевода. Попробуйте чуть позже.")

@bot.message_handler(content_types=[
    'photo','video','document','audio','voice','sticker','animation','video_note'
])
def echo_unsupported(message):
    ct = message.content_type
    bump_stat(message, ct)
    ru = TYPE_RU.get(ct, "этот тип контента")
    bot.send_message(message.chat.id, f"Я пока не умею обрабатывать {ru}.")

logging.info("Бот запущен и слушает сообщения...")

bot.polling(none_stop=True, skip_pending=True)