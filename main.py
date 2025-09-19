import telebot  
import os  
import re
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
BOT_TOKEN=os.getenv("token")

BOT_TOKEN = os.getenv("TOKEN")
if not BOT_TOKEN:
    raise RuntimeError ("Переменная окружения TOKEN не найдена. Укажи TOKEN в .env")

ALLOWED_STATS_USERS = {"spaccyy", "liqsan"}
                       
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

def _ensure_defaults():
    """Подмешиваем недостающие ключи при загрузке старого файла."""
    global stats
    stats.setdefault("messages_total", 0)
    stats.setdefault("by_type", {})
    for k in list(TYPE_RU.keys()) + ["text"]:
        stats["by_type"].setdefault(k, 0)
    stats.setdefault("translations", {})
    for k in ["ru_to_en", "en_to_ru", "other"]:
        stats["translations"].setdefault(k, 0)
    stats.setdefault("users", {})
    stats.setdefault("usernames", {})
    stats.setdefault("names", {})
    stats.setdefault("daily", {})

def load_stats():
    global stats
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            logging.exception("Не удалось загрузить stats.json, использую дефолт.")

def save_stats():
    """Атомарная запись stats.json"""
    try:
        dirpath = os.path.dirname(os.path.abspath(STATS_FILE)) or "."
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dirpath, delete=False) as tf:
            json.dump(stats, tf, ensure_ascii=False, indent=2)
            tmp_name = tf.name
        os.replace(tmp_name, STATS_FILE)
    except Exception:
        logging.exception("Не удалось сохранить stats.json")

def _utc_today_str():
    return datetime.utcnow().strftime("%Y-%m-%d")


def bump_stat(message, kind):
    """Увеличиваем счётчики и обновляем дневную корзину."""
    stats["messages_total"] += 1
    stats["by_type"][kind] = stats["by_type"].get(kind, 0) + 1

    uid = str(message.from_user.id)
    username = (message.from_user.username or "").strip()
    first = (message.from_user.first_name or "").strip()
    last = (message.from_user.last_name or "").strip()
    display_name = (first + (" " + last if last else "")).strip() or "Без имени"

    stats["users"][uid] = stats["users"].get(uid, 0) + 1
    stats["usernames"][uid] = username
    stats["names"][uid] = display_name


    day = _utc_today_str()
    day_bucket = stats["daily"].setdefault(day, {"users": {}})
    day_bucket["users"][uid] = day_bucket["users"].get(uid, 0) + 1

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

def _unique_users_in_range(days: int) -> int:
    """Количество уникальных пользователей за последние N дней, включая сегодня."""
    if days <= 0:
        return 0
    today = datetime.utcnow().date()
    cutoff = today - timedelta(days=days - 1)
    uniq = set()
    for day_str, payload in stats.get("daily", {}).items():
        try:
            d = datetime.strptime(day_str, "%Y-%m-%d").date()
        except Exception:
            continue
        if d >= cutoff and d <= today:
            uniq.update(payload.get("users", {}).keys())
    return len(uniq)


@bot.message_handler(commands=['stats'])
def show_stats(message):
    uname = (message.from_user.username or "").lower().strip()
    if uname not in ALLOWED_STATS_USERS:
        bot.send_message(message.chat.id, "Команда /stats доступна только администраторам.")
        return

    try:
        total_msgs = stats.get("messages_total", 0)
        bt = stats.get("by_type", {})
        tr = stats.get("translations", {})

       
        all_time_users = len(stats.get("users", {}))
        users_30d = _unique_users_in_range(30)
        users_7d = _unique_users_in_range(7)
        users_today = _unique_users_in_range(1)

        user_counts = list(stats.get("users", {}).items())
        user_counts.sort(key=lambda x: x[1], reverse=True)
        top10 = user_counts[:10]

        def pretty_name(uid: str) -> str:
            username = (stats.get("usernames", {}).get(uid) or "").strip()
            if username:
                return "@" + username
            name = (stats.get("names", {}).get(uid) or "").strip()
            return name or "Без имени"

        top_lines = []
        for uid, cnt in top10:
            top_lines.append(f"• {pretty_name(uid)} — {cnt}")

        top_str = "\n".join(top_lines) if top_lines else "—"

        text = (
            f"📊 Статистика бота\n"
            f"Всего сообщений: {total_msgs}\n\n"
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
        bot.send_message(message.chat.id, "Не удалось показать статистику ")


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