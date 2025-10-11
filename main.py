import os
import re
import json
import logging
import tempfile
import time
from datetime import datetime, timedelta, UTC
from dotenv import load_dotenv
from deep_translator import GoogleTranslator, MyMemoryTranslator
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
PUNCT_ONLY_RE = re.compile(r"^\s*[\W_]+\s*$", re.UNICODE)

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

bot.set_my_commands(
    [types.BotCommand("start", "начать работу с ботом")],
    scope=types.BotCommandScopeAllPrivateChats()
)

ME = bot.get_me()
BOT_USERNAME = (ME.username or "").lower()
BOT_ID = ME.id

def is_admin_user(message) -> bool:
    uname = (message.from_user.username or "").lower().strip()
    return uname in ALLOWED_STATS_USERS

def reply(chat_id: int, text: str, thread_id=None, parse_mode=None):
    bot.send_message(chat_id, text, message_thread_id=thread_id, parse_mode=parse_mode)

def extract_text_from_message(msg):
    if msg is None:
        return ""
    if getattr(msg, "text", None):
        return (msg.text or "").strip()
    if getattr(msg, "caption", None):
        return (msg.caption or "").strip()
    return ""

def is_bot_mentioned_in_entities(message) -> bool:
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "")
    entities = getattr(message, "entities", None) or getattr(message, "caption_entities", None) or []
    for e in entities:
        if e.type == "mention":
            try:
                segment = text[e.offset:e.offset+e.length]
            except Exception:
                segment = ""
            if segment.lower() == f"@{BOT_USERNAME}":
                return True
        if e.type == "text_mention" and getattr(e, "user", None) and e.user.id == BOT_ID:
            return True
    return False

def remove_bot_mentions(text: str, message) -> str:
    if not text:
        return text
    out = text
    entities = getattr(message, "entities", None) or getattr(message, "caption_entities", None) or []
    cut = []
    for e in entities:
        if e.type == "mention":
            try:
                segment = text[e.offset:e.offset+e.length]
            except Exception:
                segment = ""
            if segment.lower() == f"@{BOT_USERNAME}":
                cut.append((e.offset, e.offset+e.length))
        if e.type == "text_mention" and getattr(e, "user", None) and e.user.id == BOT_ID:
            cut.append((e.offset, e.offset+e.length))
    if cut:
        cut.sort()
        res = []
        i = 0
        for a, b in cut:
            if i < a:
                res.append(out[i:a])
            i = b
        res.append(out[i:])
        out = "".join(res)
    out = out.replace(f"@{BOT_USERNAME}", "")
    return out.strip()

def detect_direction(text: str):
    if CYRILLIC_RE.search(text) and not LATIN_RE.search(text):
        return ("en", "ru_to_en")
    elif LATIN_RE.search(text) and not CYRILLIC_RE.search(text):
        return ("ru", "en_to_ru")
    else:
        return ("en", "other")

def safe_translate(text: str, target_lang: str) -> str:
    err = None
    for attempt in range(3):
        try:
            return GoogleTranslator(source="auto", target=target_lang, timeout=10).translate(text)
        except Exception as e:
            err = e
            time.sleep(0.8 * (2 ** attempt))
    try:
        return MyMemoryTranslator(source="auto", target=target_lang).translate(text)
    except Exception:
        pass
    raise err if err else RuntimeError("translate failed")

def translate_and_reply(message, source_text: str):
    source_text = (source_text or "").strip()
    if not source_text:
        reply(message.chat.id, "Нет текста для перевода.", getattr(message, "message_thread_id", None))
        return
    if ONLY_EMOJI_RE.match(source_text):
        stats_mgr.record_event(message, "emoji")
        stats_mgr.flush()
        reply(message.chat.id, "Я пока не умею обрабатывать эмодзи.", getattr(message, "message_thread_id", None))
        return
    stats_mgr.record_event(message, "text")
    stats_mgr.flush()
    target_lang, direction = detect_direction(source_text)
    try:
        translated = safe_translate(source_text, target_lang)
        reply(message.chat.id, translated, getattr(message, "message_thread_id", None))
        stats_mgr.record_translation(direction)
        stats_mgr.flush()
    except Exception:
        logging.exception("Ошибка перевода")
        reply(message.chat.id, "Перевод временно недоступен. Попробуйте ещё раз позже.", getattr(message, "message_thread_id", None))

@bot.message_handler(commands=['start'])
def start(message):
    reply(
        message.chat.id,
        "Привет! Отправь мне текст — я переведу его на русский или английский.\n"
        "В группах используй: @text_translate_bot в ответ на сообщение которое хочешь перевести.",
        getattr(message, "message_thread_id", None)
    )

@bot.message_handler(commands=['users'])
def users_counter(message):
    if not is_admin_user(message):
        reply(message.chat.id, "Команда /users доступна только администраторам.")
        return
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
    if not is_admin_user(message):
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

def handle_group_trigger_and_translate(message, text_source: str):
    if not (message.chat.type in ["group", "supergroup"]):
        translate_and_reply(message, text_source)
        return
    mentioned = is_bot_mentioned_in_entities(message) or (f"@{BOT_USERNAME}" in (text_source or "").lower())
    if not mentioned:
        return
    cleaned = remove_bot_mentions(text_source or "", message)
    if ((not cleaned) or PUNCT_ONLY_RE.match(cleaned)) and message.reply_to_message:
        source = extract_text_from_message(message.reply_to_message)
        translate_and_reply(message, source)
    elif cleaned:
        translate_and_reply(message, cleaned)
    elif message.reply_to_message:
        source = extract_text_from_message(message.reply_to_message)
        translate_and_reply(message, source)
    else:
        reply(message.chat.id, "Нет текста для перевода.", getattr(message, "message_thread_id", None))

@bot.message_handler(content_types=['text'])
def translate_text(message):
    text = (message.text or "").strip()
    if not text:
        return
    handle_group_trigger_and_translate(message, text)

@bot.message_handler(content_types=['photo','video','document','audio','voice','sticker','animation','video_note'])
def handle_media(message):
    caption = extract_text_from_message(message)
    if message.chat.type in ["group","supergroup"]:
        if not is_bot_mentioned_in_entities(message) and f"@{BOT_USERNAME}" not in caption.lower():
            stats_mgr.record_event(message, message.content_type)
            stats_mgr.flush()
            return
        caption = remove_bot_mentions(caption, message)
        if ((not caption) or PUNCT_ONLY_RE.match(caption)) and message.reply_to_message:
            source = extract_text_from_message(message.reply_to_message)
            translate_and_reply(message, source)
            return
    if caption:
        translate_and_reply(message, caption)
    else:
        stats_mgr.record_event(message, message.content_type)
        stats_mgr.flush()
        reply(message.chat.id, "У этого медиа нет подписи для перевода.", getattr(message, "message_thread_id", None))

logging.info("Бот запущен и слушает сообщения...")
bot.polling(none_stop=True, skip_pending=True, timeout=60)