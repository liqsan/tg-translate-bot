import os
import re
import json
import logging
import tempfile
from datetime import datetime, timedelta, UTC
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
import telebot
from telebot import types

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BOT_TOKEN = os.getenv("TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения TOKEN не найдена. Укажи TOKEN в .env")

ALLOWED_STATS_USERS = {"spaccyy", "liqsan"}
STATS_FILE = "stats.json"

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")
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

class StatsManager:
    def __init__(self, path: str, type_ru: dict[str, str]):
        self.path = path
        self.type_ru = type_ru
        self.stats = {
            "messages_total": 0,
            "by_type": {k: 0 for k in list(self.type_ru.keys()) + ["text"]},
            "translations": {"ru_to_en": 0, "en_to_ru": 0, "other": 0},
            "users": {},
            "usernames": {},
            "names": {},
            "daily": {}
        }
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.stats.update(loaded)
            except Exception:
                logging.exception("Не удалось загрузить stats.json, использую дефолт.")
        self._ensure_defaults()

    def flush(self):
        try:
            dirpath = os.path.dirname(os.path.abspath(self.path)) or "."
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dirpath, delete=False) as tf:
                json.dump(self.stats, tf, ensure_ascii=False, indent=2)
                tmp_name = tf.name
            os.replace(tmp_name, self.path)
        except Exception:
            logging.exception("Не удалось сохранить stats.json")

    def _ensure_defaults(self):
        s = self.stats
        s.setdefault("messages_total", 0)
        s.setdefault("by_type", {})
        for k in list(self.type_ru.keys()) + ["text"]:
            s["by_type"].setdefault(k, 0)
        s.setdefault("translations", {})
        for k in ["ru_to_en", "en_to_ru", "other"]:
            s["translations"].setdefault(k, 0)
        s.setdefault("users", {})
        s.setdefault("usernames", {})
        s.setdefault("names", {})
        s.setdefault("daily", {})

    @staticmethod
    def _today_str_utc() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def record_event(self, message, kind: str):
        self.stats["messages_total"] += 1
        self.stats["by_type"][kind] = self.stats["by_type"].get(kind, 0) + 1
        uid = str(message.from_user.id)
        username = (message.from_user.username or "").strip()
        first = (message.from_user.first_name or "").strip()
        last = (message.from_user.last_name or "").strip()
        display_name = (first + (" " + last if last else "")).strip() or "Без имени"
        self.stats["users"][uid] = self.stats["users"].get(uid, 0) + 1
        self.stats["usernames"][uid] = username
        self.stats["names"][uid] = display_name
        day = self._today_str_utc()
        bucket = self.stats["daily"].setdefault(day, {"users": {}})
        bucket["users"][uid] = bucket["users"].get(uid, 0) + 1

    def record_translation(self, direction: str):
        self.stats["translations"][direction] = self.stats["translations"].get(direction, 0) + 1

    def unique_users_in_range(self, days: int) -> int:
        if days <= 0:
            return 0
        today = datetime.utcnow().date()
        cutoff = today - timedelta(days=days - 1)
        uniq = set()
        for day_str, payload in self.stats.get("daily", {}).items():
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d").date()
            except Exception:
                continue
            if cutoff <= d <= today:
                uniq.update(payload.get("users", {}).keys())
        return len(uniq)

    def pretty_name(self, uid: str) -> str:
        username = (self.stats.get("usernames", {}).get(uid) or "").strip()
        if username:
            return f'<a href="https://t.me/{username}">@{username}</a>'
        name = (self.stats.get("names", {}).get(uid) or "").strip()
        if not name or name == "Без имени":
            return f"ID {uid}"
        return name

stats_mgr = StatsManager(STATS_FILE, TYPE_RU)
bot = telebot.TeleBot(BOT_TOKEN)

# Команды: приватные чаты
bot.set_my_commands([
    types.BotCommand("start", "начать работу с ботом"),
    types.BotCommand("users", "количество пользователей"),
    types.BotCommand("stats", "полная статистика (для админов)"),
], scope=types.BotCommandScopeAllPrivateChats())

# Команды: групповые чаты (показываем только /users)
bot.set_my_commands([
    types.BotCommand("users", "количество пользователей"),
], scope=types.BotCommandScopeAllGroupChats())

ME = bot.get_me()
BOT_USERNAME = (ME.username or "").lower()
BOT_ID = ME.id

def reply(chat_id: int, text: str, thread_id=None, parse_mode=None):
    bot.send_message(chat_id, text, message_thread_id=thread_id, parse_mode=parse_mode)

@bot.message_handler(commands=['start'])
def start(message):
    reply(message.chat.id, "Привет! Отправь мне текст — я переведу его на русский или английский.\nВ группах используй: @имябота текст", getattr(message, "message_thread_id", None))

@bot.message_handler(commands=['users'])
def users_counter(message):
    all_time_users = len(stats_mgr.stats.get("users", {}))
    users_30d = stats_mgr.unique_users_in_range(30)
    users_7d = stats_mgr.unique_users_in_range(7)
    users_today = stats_mgr.unique_users_in_range(1)
    text = (
        "👥 Уникальные пользователи\n"
        f"• За всё время: <b>{all_time_users}</b>\n"
        f"• За 30 дней: <b>{users_30d}</b>\n"
        f"• За 7 дней: <b>{users_7d}</b>\n"
        f"• За сегодня: <b>{users_today}</b>"
    )
    reply(message.chat.id, text, getattr(message, "message_thread_id", None), parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    uname = (message.from_user.username or "").lower().strip()
    if uname not in ALLOWED_STATS_USERS:
        reply(message.chat.id, "Команда /stats доступна только администраторам.")
        return
    try:
        total_msgs = stats_mgr.stats.get("messages_total", 0)
        bt = stats_mgr.stats.get("by_type", {})
        tr = stats_mgr.stats.get("translations", {})
        all_time_users = len(stats_mgr.stats.get("users", {}))
        users_30d = stats_mgr.unique_users_in_range(30)
        users_7d = stats_mgr.unique_users_in_range(7)
        users_today = stats_mgr.unique_users_in_range(1)
        user_counts = list(stats_mgr.stats.get("users", {}).items())
        user_counts.sort(key=lambda x: x[1], reverse=True)
        top10 = user_counts[:10]
        top_lines = [f"• {stats_mgr.pretty_name(uid)} — {cnt}" for uid, cnt in top10]
        top_str = "\n".join(top_lines) if top_lines else "—"
        text = (
            f"📊 <b>Статистика бота</b>\n"
            f"Всего сообщений: <b>{total_msgs}</b>\n\n"
            f"<b>Пользователи</b>\n"
            f"• За всё время: <b>{all_time_users}</b>\n"
            f"• За 30 дней: <b>{users_30d}</b>\n"
            f"• За 7 дней: <b>{users_7d}</b>\n"
            f"• За сегодня: <b>{users_today}</b>\n\n"
            f"<b>По типам</b>\n"
            f"• текст: {bt.get('text',0)}\n"
            f"• эмодзи: {bt.get('emoji',0)}\n"
            f"• фотографии: {bt.get('photo',0)}\n"
            f"• видео: {bt.get('video',0)}\n"
            f"• документы: {bt.get('document',0)}\n"
            f"• аудио: {bt.get('audio',0)}\n"
            f"• голосовые: {bt.get('voice',0)}\n"
            f"• анимации: {bt.get('animation',0)}\n"
            f"• видеосообщения: {bt.get('video_note',0)}\n"
            f"• стикеры: {bt.get('sticker',0)}\n\n"
            f"<b>Переводы</b>\n"
            f"• RU → EN: {tr.get('ru_to_en',0)}\n"
            f"• EN → RU: {tr.get('en_to_ru',0)}\n"
            f"• другие: {tr.get('other',0)}\n\n"
            f"<b>Топ пользователей</b> (10):\n{top_str}"
        )
        reply(message.chat.id, text, getattr(message, "message_thread_id", None), parse_mode="HTML")
    except Exception:
        logging.exception("Ошибка /stats")
        reply(message.chat.id, "Не удалось показать статистику")

@bot.message_handler(content_types=['text'])
def translate_text(message):
    text = (message.text or "").strip()
    if not text:
        return
    in_group = message.chat.type in ["group", "supergroup"]
    if in_group:
        lower = text.lower()
        mention = f"@{BOT_USERNAME}"
        if mention not in lower:
            return
        while mention in lower:
            idx = lower.find(mention)
            text = text[:idx] + text[idx+len(mention):]
            lower = text.lower()
        text = text.strip()
        if not text:
            return
    if ONLY_EMOJI_RE.match(text):
        stats_mgr.record_event(message, "emoji")
        stats_mgr.flush()
        reply(message.chat.id, "Я пока не умею обрабатывать эмодзи.", getattr(message, "message_thread_id", None))
        return
    stats_mgr.record_event(message, "text")
    stats_mgr.flush()
    if CYRILLIC_RE.search(text) and not LATIN_RE.search(text):
        target_lang = "en"; direction = "ru_to_en"
    elif LATIN_RE.search(text) and not CYRILLIC_RE.search(text):
        target_lang = "ru"; direction = "en_to_ru"
    else:
        target_lang = "en"; direction = "other"
    try:
        translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
        reply(message.chat.id, translated, getattr(message, "message_thread_id", None))
        stats_mgr.record_translation(direction)
        stats_mgr.flush()
    except Exception:
        logging.exception("Ошибка перевода")
        reply(message.chat.id, "Ошибка перевода. Попробуйте чуть позже.", getattr(message, "message_thread_id", None))

@bot.message_handler(content_types=['photo','video','document','audio','voice','sticker','animation','video_note'])
def echo_unsupported(message):
    ct = message.content_type
    stats_mgr.record_event(message, ct)
    stats_mgr.flush()
    ru = TYPE_RU.get(ct, "этот тип контента")
    reply(message.chat.id, f"Я пока не умею обрабатывать {ru}.", getattr(message, "message_thread_id", None))

logging.info("Бот запущен и слушает сообщения...")
bot.polling(none_stop=True, skip_pending=True, timeout=60)
