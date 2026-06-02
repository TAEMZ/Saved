import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

import re
import os
import glob
from datetime import datetime, timedelta
import pytz
import dateparser
from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    ForceReply, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PasswordHashInvalidError, PhoneCodeExpiredError,
)

import database
import config
import encryption  # noqa: F401 (used indirectly by database)
import userlang
from translations import t, LANGUAGES, LANG_CODES

database.init_db()
userlang.init()

# Kept-alive Telethon clients during the /sync verification flow.
active_clients = {}
# Per-chat UI state (in-memory; fine for polling mode).
last_list_cb = {}     # chat_id -> callback string to return to from a card
last_search = {}      # chat_id -> last search query

PAGE = 6
PRESET_TAGS = ["work", "read", "important", "todo", "idea", "later"]
EMOJI = {'photo': '🖼', 'video': '🎬', 'document': '📄',
         'audio': '🎵', 'voice': '🎤', 'text': '📝'}
CMDS = [("start", "cmd_start"), ("list", "cmd_list"), ("tags", "cmd_tags"),
        ("search", "cmd_search"), ("language", "cmd_language"),
        ("timezone", "cmd_timezone"), ("sync", "cmd_sync"), ("help", "cmd_help")]
# Cap how many media files /sync will download & re-upload (each is a network round trip).
SYNC_MEDIA_LIMIT = 60
# Escalating "you haven't looked at this in a while" nudges, in days.
# An item is nudged once it's been untouched for THRESHOLDS[nudge_count] days.
NUDGE_THRESHOLDS = [7, 14, 30, 60, 120]
DIGEST_MAX_ITEMS = 8


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def L(chat_id):
    return userlang.get_language(chat_id) or "en"


def get_tz(chat_id):
    return database.get_user_timezone(chat_id) or "UTC"


def _tz(tzstr):
    try:
        return pytz.timezone(tzstr)
    except Exception:
        try:
            if tzstr.startswith(('+', '-')):
                return pytz.FixedOffset(int(tzstr) * 60)
        except Exception:
            pass
    return pytz.utc


def valid_tz(s):
    s = s.strip()
    if s.startswith(('+', '-')):
        try:
            return -12 <= int(s) <= 14
        except ValueError:
            return False
    try:
        pytz.timezone(s)
        return True
    except Exception:
        return False


def get_tomorrow_morning_in_utc(tzstr):
    now = datetime.now(_tz(tzstr))
    tm = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return tm.astimezone(pytz.utc).replace(tzinfo=None)


def parse_when(text, tzstr):
    """Flexible free-text time parser for custom reminders.
    Handles 'in 5 hours', 'after 5 hours', 'Sep 4', 'tomorrow 3pm',
    '2026-09-04 15:00', etc. Returns a naive-UTC datetime in the future, or None."""
    s = (text or "").strip()
    # Normalize a couple of common phrasings dateparser is picky about.
    s = re.sub(r'^\s*after\b', 'in', s, flags=re.IGNORECASE)
    rt = parse_relative_time_for_user(s, tzstr)
    if rt and rt <= datetime.utcnow():
        # If it parsed to the past (e.g. a bare time earlier today), don't accept it.
        return None
    return rt


def parse_relative_time_for_user(text, tzstr):
    user_tz = _tz(tzstr)
    now_local = datetime.now(user_tz)
    tl = text.lower().strip()
    if tl == "tonight":
        nt = now_local.replace(hour=20, minute=0, second=0, microsecond=0)
        if nt <= now_local:
            nt += timedelta(days=1)
        return nt.astimezone(pytz.utc).replace(tzinfo=None)
    parsed = dateparser.parse(text, settings={
        'PREFER_DATES_FROM': 'future',
        'RELATIVE_BASE': now_local.replace(tzinfo=None),
        'TIMEZONE': tzstr, 'TO_TIMEZONE': 'UTC'})
    return parsed.replace(tzinfo=None) if parsed else None


def fmt_time(dt_naive_utc, tzstr):
    try:
        local = dt_naive_utc.replace(tzinfo=pytz.utc).astimezone(_tz(tzstr))
        return local.strftime("%b %d, %H:%M")
    except Exception:
        return str(dt_naive_utc)


def _label(m):
    s = (m['text'] or '').replace('\n', ' ').strip()
    if not s:
        s = {'photo': 'Photo', 'video': 'Video', 'document': 'File',
             'audio': 'Audio', 'voice': 'Voice'}.get(m['media_type'], '(empty)')
    if len(s) > 38:
        s = s[:35] + '…'
    return f"{EMOJI.get(m['media_type'], '📝')} {s}"


def has_media(msg):
    return msg['media_type'] != 'text' and (msg['media_file_id'] or msg['telegram_message_id'])


async def resend_media(bot, chat, msg, caption=None):
    """Re-send a saved media item. Prefers the permanent file_id; falls back to
    copy_message for items that only have an original message reference."""
    fid = msg['media_file_id']
    mt = msg['media_type']
    try:
        if fid:
            if mt == 'photo':
                await bot.send_photo(chat, fid, caption=caption)
            elif mt == 'video':
                await bot.send_video(chat, fid, caption=caption)
            elif mt == 'document':
                await bot.send_document(chat, fid, caption=caption)
            elif mt == 'audio':
                await bot.send_audio(chat, fid, caption=caption)
            elif mt == 'voice':
                await bot.send_voice(chat, fid, caption=caption)
            else:
                return False
            return True
        if msg['telegram_message_id']:
            await bot.copy_message(chat, chat, msg['telegram_message_id'])
            return True
    except Exception:
        # Last-ditch fallback to copy if the file_id send failed.
        if msg['telegram_message_id']:
            try:
                await bot.copy_message(chat, chat, msg['telegram_message_id'])
                return True
            except Exception:
                return False
    return False


def _home_row(lang):
    return [InlineKeyboardButton(t('m_home', lang), callback_data="menu:home")]


async def _del_job(context):
    chat, mid = context.job.data
    try:
        await context.bot.delete_message(chat, mid)
    except Exception:
        pass


async def send_temp(context, chat, text, secs=6):
    """Send a transient confirmation that auto-deletes, to avoid clutter."""
    try:
        m = await context.bot.send_message(chat, text)
        if context.job_queue:
            context.job_queue.run_once(_del_job, secs, data=(chat, m.message_id))
    except Exception:
        pass


async def _edit(query, render):
    text, kb, md = render
    try:
        await query.edit_message_text(
            text, reply_markup=kb,
            parse_mode="Markdown" if md else None,
            disable_web_page_preview=True)
    except Exception:
        pass


async def _reply(update, render):
    text, kb, md = render
    await update.message.reply_text(
        text, reply_markup=kb,
        parse_mode="Markdown" if md else None,
        disable_web_page_preview=True)


# ----------------------------------------------------------------------------
# View builders -> (text, markup, use_markdown)
# ----------------------------------------------------------------------------
def render_menu(chat_id):
    lang = L(chat_id)
    name = database.get_display_name(chat_id)
    greet = t('greet', lang, name=name) if name else t('greet_anon', lang)
    digest_btn = (t('m_digest_on', lang) if database.get_digest_enabled(chat_id)
                  else t('m_digest_off', lang))
    rows = [
        [InlineKeyboardButton(t('m_list', lang), callback_data="menu:list"),
         InlineKeyboardButton(t('m_tags', lang), callback_data="menu:tags")],
        [InlineKeyboardButton(t('m_lang', lang), callback_data="menu:lang"),
         InlineKeyboardButton(t('m_tz', lang), callback_data="menu:tz")],
        [InlineKeyboardButton(t('m_sync', lang), callback_data="menu:sync"),
         InlineKeyboardButton(digest_btn, callback_data="menu:digest")],
        [InlineKeyboardButton(t('m_help', lang), callback_data="menu:help")],
    ]
    return greet + "\n\n" + t('welcome', lang), InlineKeyboardMarkup(rows), True


def render_help(chat_id):
    lang = L(chat_id)
    return t('help', lang), InlineKeyboardMarkup([_home_row(lang)]), True


def render_language(chat_id):
    lang = L(chat_id)
    rows, cur = [], []
    for code, label in LANGUAGES:
        cur.append(InlineKeyboardButton(label, callback_data=f"lang:{code}"))
        if len(cur) == 2:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append(_home_row(lang))
    return t('choose_language', lang), InlineKeyboardMarkup(rows), False


def _items_keyboard(chat_id, messages, page, nav_prefix):
    lang = L(chat_id)
    total = max(1, (len(messages) + PAGE - 1) // PAGE)
    page = max(0, min(page, total - 1))
    last_list_cb[chat_id] = nav_prefix + str(page)
    rows = []
    for m in messages[page * PAGE:(page + 1) * PAGE]:
        rows.append([InlineKeyboardButton(_label(m), callback_data=f"open:{m['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(t('prev', lang), callback_data=nav_prefix + str(page - 1)))
    if total > 1:
        nav.append(InlineKeyboardButton(t('page_info', lang, cur=page + 1, total=total), callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(t('next', lang), callback_data=nav_prefix + str(page + 1)))
    if nav:
        rows.append(nav)
    rows.append(_home_row(lang))
    return InlineKeyboardMarkup(rows)


def render_list(chat_id, page=0):
    lang = L(chat_id)
    msgs = database.get_active_messages(chat_id)
    if not msgs:
        return t('list_empty', lang), InlineKeyboardMarkup([_home_row(lang)]), False
    kb = _items_keyboard(chat_id, msgs, page, "list:p:")
    return t('list_title', lang), kb, False


def render_tags(chat_id):
    lang = L(chat_id)
    tags = database.get_all_tags(chat_id)
    if not tags:
        return t('tags_empty', lang), InlineKeyboardMarkup([_home_row(lang)]), False
    rows, cur = [], []
    for tg in tags:
        cur.append(InlineKeyboardButton("#" + tg, callback_data=f"tagf:{tg}:0"))
        if len(cur) == 3:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append(_home_row(lang))
    return t('tags_title', lang), InlineKeyboardMarkup(rows), False


def render_tagfilter(chat_id, tag, page=0):
    lang = L(chat_id)
    msgs = database.get_messages_by_tag(chat_id, tag)
    if not msgs:
        return t('filter_title', lang, tag=tag), InlineKeyboardMarkup([_home_row(lang)]), False
    kb = _items_keyboard(chat_id, msgs, page, f"tagf:{tag}:")
    return t('filter_title', lang, tag=tag), kb, False


def render_search(chat_id, query, page=0):
    lang = L(chat_id)
    msgs = database.search_messages(chat_id, query)
    if not msgs:
        return t('search_none', lang, q=query), InlineKeyboardMarkup([_home_row(lang)]), False
    last_search[chat_id] = query
    kb = _items_keyboard(chat_id, msgs, page, "srch:p:")
    return t('search_res', lang, q=query), kb, False


def build_card(chat_id, db_id):
    lang = L(chat_id)
    msg = database.get_message_details(db_id)
    if not msg:
        return "⚠️", InlineKeyboardMarkup([_home_row(lang)]), False
    content = msg['text'] or ""
    if msg['media_type'] != 'text':
        content = f"[{msg['media_type'].capitalize()}] {content}".strip()
    if not content:
        content = "—"
    if len(content) > 350:
        content = content[:347] + "..."
    tags = database.get_message_tags(db_id)
    tags_str = " ".join("#" + x for x in tags) if tags else t('tags_none', lang)
    if msg['reminder_time']:
        try:
            rem = fmt_time(datetime.fromisoformat(msg['reminder_time']), get_tz(chat_id))
        except Exception:
            rem = str(msg['reminder_time'])
    else:
        rem = t('rem_none', lang)
    text = t('card', lang, content=content, tags=tags_str, reminder=rem)
    saved_raw = msg['created_at']
    if saved_raw:
        try:
            text += "\n" + t('saved_on', lang, date=fmt_time(datetime.fromisoformat(saved_raw), get_tz(chat_id)))
        except Exception:
            pass
    rows = [[
        InlineKeyboardButton(t('b_remind', lang), callback_data=f"remopts:{db_id}"),
        InlineKeyboardButton(t('b_tags', lang), callback_data=f"tag:add:{db_id}"),
    ]]
    if has_media(msg):
        rows.append([InlineKeyboardButton(t('b_file', lang), callback_data=f"show:{db_id}")])
    back = last_list_cb.get(chat_id, "menu:list")
    rows.append([
        InlineKeyboardButton(t('b_archive', lang), callback_data=f"arc:{db_id}"),
        InlineKeyboardButton(t('back_list', lang), callback_data=back),
    ])
    return text, InlineKeyboardMarkup(rows), False


def render_rem_options(chat_id, db_id):
    lang = L(chat_id)
    card, _, _ = build_card(chat_id, db_id)
    rows = [
        [InlineKeyboardButton(t('r10m', lang), callback_data=f"rem:10m:{db_id}"),
         InlineKeyboardButton(t('r30m', lang), callback_data=f"rem:30m:{db_id}"),
         InlineKeyboardButton(t('r1h', lang), callback_data=f"rem:1h:{db_id}")],
        [InlineKeyboardButton(t('r3h', lang), callback_data=f"rem:3h:{db_id}"),
         InlineKeyboardButton(t('rtonight', lang), callback_data=f"rem:tonight:{db_id}"),
         InlineKeyboardButton(t('rtom', lang), callback_data=f"rem:tom:{db_id}")],
        [InlineKeyboardButton(t('rmore', lang), callback_data=f"rempick:{db_id}"),
         InlineKeyboardButton(t('rem_custom', lang), callback_data=f"remcustom:{db_id}")],
        [InlineKeyboardButton(t('back', lang), callback_data=f"open:{db_id}")],
    ]
    return t('rem_when', lang) + "\n\n" + card, InlineKeyboardMarkup(rows), False


def render_rem_picker(chat_id, db_id):
    lang = L(chat_id)
    card, _, _ = build_card(chat_id, db_id)
    rows = [
        [InlineKeyboardButton(t('p5m', lang), callback_data=f"rem:m:5:{db_id}"),
         InlineKeyboardButton(t('p15m', lang), callback_data=f"rem:m:15:{db_id}"),
         InlineKeyboardButton(t('p45m', lang), callback_data=f"rem:m:45:{db_id}")],
        [InlineKeyboardButton(t('p2h', lang), callback_data=f"rem:h:2:{db_id}"),
         InlineKeyboardButton(t('p6h', lang), callback_data=f"rem:h:6:{db_id}"),
         InlineKeyboardButton(t('p12h', lang), callback_data=f"rem:h:12:{db_id}")],
        [InlineKeyboardButton(t('p1d', lang), callback_data=f"rem:d:1:{db_id}"),
         InlineKeyboardButton(t('p3d', lang), callback_data=f"rem:d:3:{db_id}"),
         InlineKeyboardButton(t('p7d', lang), callback_data=f"rem:d:7:{db_id}")],
        [InlineKeyboardButton(t('rem_custom', lang), callback_data=f"remcustom:{db_id}")],
        [InlineKeyboardButton(t('back', lang), callback_data=f"remopts:{db_id}")],
    ]
    return t('pick_title', lang) + "\n\n" + card, InlineKeyboardMarkup(rows), False


def render_tag_options(chat_id, db_id):
    lang = L(chat_id)
    card, _, _ = build_card(chat_id, db_id)
    rows = []
    for i in range(0, len(PRESET_TAGS), 3):
        rows.append([InlineKeyboardButton("#" + tg, callback_data=f"tag:set:{tg}:{db_id}")
                     for tg in PRESET_TAGS[i:i + 3]])
    rows.append([InlineKeyboardButton(t('tag_type', lang), callback_data=f"tag:type:{db_id}")])
    rows.append([InlineKeyboardButton(t('back', lang), callback_data=f"open:{db_id}")])
    return t('tag_when', lang) + "\n\n" + card, InlineKeyboardMarkup(rows), False


def render_cb(chat_id, cb):
    """Re-render a list-type view from a stored callback string."""
    parts = cb.split(":")
    if parts[0] == "list":
        return render_list(chat_id, int(parts[2]))
    if parts[0] == "tagf":
        return render_tagfilter(chat_id, parts[1], int(parts[2]))
    if parts[0] == "srch":
        return render_search(chat_id, last_search.get(chat_id, ""), int(parts[2]))
    return render_list(chat_id, 0)


def compute_rem(parts, tzstr):
    now = datetime.utcnow()
    if parts[1] == "m":
        return now + timedelta(minutes=int(parts[2]))
    if parts[1] == "h":
        return now + timedelta(hours=int(parts[2]))
    if parts[1] == "d":
        return now + timedelta(days=int(parts[2]))
    code = parts[1]
    if code == "10m":
        return now + timedelta(minutes=10)
    if code == "30m":
        return now + timedelta(minutes=30)
    if code == "1h":
        return now + timedelta(hours=1)
    if code == "3h":
        return now + timedelta(hours=3)
    if code == "tonight":
        return parse_relative_time_for_user("tonight", tzstr)
    if code == "tom":
        return get_tomorrow_morning_in_utc(tzstr)
    return None


# ----------------------------------------------------------------------------
# Command handlers
# ----------------------------------------------------------------------------
def _capture_name(update):
    try:
        u = update.effective_user
        if u and u.first_name:
            database.set_display_name(update.effective_chat.id, u.first_name)
    except Exception:
        pass


async def start_command(update, context):
    chat = update.effective_chat.id
    _capture_name(update)
    if userlang.get_language(chat) is None:
        await _reply(update, render_language(chat))
    else:
        await _reply(update, render_menu(chat))


async def help_command(update, context):
    await _reply(update, render_help(update.effective_chat.id))


async def language_command(update, context):
    await _reply(update, render_language(update.effective_chat.id))


async def list_command(update, context):
    await _reply(update, render_list(update.effective_chat.id, 0))


async def tags_command(update, context):
    await _reply(update, render_tags(update.effective_chat.id))


async def search_command(update, context):
    chat = update.effective_chat.id
    lang = L(chat)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(t('search_use', lang))
        return
    await _reply(update, render_search(chat, query, 0))


async def timezone_command(update, context):
    chat = update.effective_chat.id
    lang = L(chat)
    await update.message.reply_text(
        t('tz_cur', lang, tz=get_tz(chat)) + "\n\n" + t('tz_prompt', lang),
        reply_markup=ForceReply(selective=True))


# ----------------------------------------------------------------------------
# /sync flow
# ----------------------------------------------------------------------------
async def start_sync(chat, context):
    lang = L(chat)
    if (not config.TELEGRAM_API_ID or str(config.TELEGRAM_API_ID).startswith("YOUR_") or
            not config.TELEGRAM_API_HASH or str(config.TELEGRAM_API_HASH).startswith("YOUR_")):
        await context.bot.send_message(chat, t('sync_unavail', lang))
        return
    database.set_sync_state(chat, 'AWAITING_PHONE')
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton(text=t('sync_share', lang), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)
    await context.bot.send_message(chat, t('sync_intro', lang),
                                   reply_markup=kb, parse_mode="Markdown")


async def sync_command(update, context):
    await start_sync(update.effective_chat.id, context)


async def cancel_command(update, context):
    chat = update.effective_chat.id
    lang = L(chat)
    st = database.get_sync_state(chat)
    if st:
        database.clear_sync_state(chat)
        clean_session_files(chat)
        if chat in active_clients:
            try:
                await active_clients[chat].disconnect()
            except Exception:
                pass
            active_clients.pop(chat, None)
        await update.message.reply_text(t('sync_cancel', lang), reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(t('sync_none', lang))


def clean_session_files(chat_id):
    for fn in glob.glob(f"session_{chat_id}.session*"):
        try:
            os.remove(fn)
        except Exception:
            pass


async def handle_contact(update, context):
    chat = update.effective_chat.id
    lang = L(chat)
    contact = update.message.contact
    if contact.user_id != chat:
        await update.message.reply_text(t('sync_own', lang))
        return
    st = database.get_sync_state(chat)
    if not st or st['state'] != 'AWAITING_PHONE':
        await update.message.reply_text(t('sync_first', lang))
        return
    # Personalize using the name from the shared contact card.
    nm = (contact.first_name or "").strip()
    if contact.last_name:
        nm = (nm + " " + contact.last_name).strip()
    if nm:
        database.set_display_name(chat, nm)
    phone = contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await update.message.reply_text(t('sync_connecting', lang), reply_markup=ReplyKeyboardRemove())
    api_id = int(config.TELEGRAM_API_ID)
    api_hash = config.TELEGRAM_API_HASH
    try:
        if chat in active_clients:
            try:
                await active_clients[chat].disconnect()
            except Exception:
                pass
            active_clients.pop(chat, None)
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
        active_clients[chat] = client
        session_str = client.session.save()
    except Exception as e:
        clean_session_files(chat)
        database.clear_sync_state(chat)
        await update.message.reply_text(t('sync_connfail', lang, err=str(e)))
        return
    database.set_sync_state(chat, 'AWAITING_CODE', phone, sent.phone_code_hash, session_str)
    await update.message.reply_text(t('sync_code', lang))


# ----------------------------------------------------------------------------
# Incoming messages: sync flow / replies / saving
# ----------------------------------------------------------------------------
async def handle_message(update, context):
    chat = update.effective_chat.id
    lang = L(chat)
    message = update.message
    user_text = (message.text or "").strip()

    # 1) Active /sync flow
    st = database.get_sync_state(chat)
    if st:
        state = st['state']
        if state == 'AWAITING_PHONE':
            await message.reply_text(t('sync_mid', lang))
            return
        if state in ('AWAITING_CODE', 'AWAITING_2FA'):
            await _process_sync_auth(update, context, st)
            return

    # 2) Reply to a ForceReply prompt (timezone / tags)
    if message.reply_to_message:
        p = message.reply_to_message.text or ""
        if "ID: TZ" in p:
            s = user_text
            if valid_tz(s):
                database.set_user_timezone(chat, s)
                await send_temp(context, chat, t('tz_set', lang, tz=s))
            else:
                await send_temp(context, chat, t('tz_bad', lang))
            return
        mr = re.search(r"RID:\s*(\d+)", p)
        if mr:
            db_id = int(mr.group(1))
            rt = parse_when(user_text, get_tz(chat))
            if rt:
                database.set_reminder(db_id, rt)
                await send_temp(context, chat, t('rem_set', lang, time=fmt_time(rt, get_tz(chat))))
            else:
                await send_temp(context, chat, t('rem_bad_time', lang), secs=10)
            return
        m = re.search(r"ID:\s*(\d+)", p)
        if m:
            db_id = int(m.group(1))
            tags = [x.strip().lstrip('#').lower() for x in re.split(r"[\s,]+", user_text) if x.strip()]
            for tg in tags:
                if tg:
                    database.add_tag(db_id, tg)
            if tags:
                await send_temp(context, chat, t('tag_added', lang, tags=", ".join("#" + x for x in tags)))
            return

    # 3) Save new content (text, links, photos, files, voice, video, audio)
    media_type, media_file_id = 'text', None
    text_content = message.text or message.caption or ""
    if message.photo:
        media_type, media_file_id = 'photo', message.photo[-1].file_id
    elif message.video:
        media_type, media_file_id = 'video', message.video.file_id
    elif message.animation:
        media_type, media_file_id = 'video', message.animation.file_id
    elif message.document:
        media_type, media_file_id = 'document', message.document.file_id
    elif message.audio:
        media_type, media_file_id = 'audio', message.audio.file_id
    elif message.voice:
        media_type, media_file_id = 'voice', message.voice.file_id

    db_id = database.add_saved_message(
        chat_id=chat, text=text_content, media_type=media_type,
        media_file_id=media_file_id, telegram_message_id=message.message_id)
    for tag in re.findall(r"#([a-zA-Z0-9_]+)", text_content):
        database.add_tag(db_id, tag.lower())

    last_list_cb[chat] = "menu:list"
    text, kb, _ = build_card(chat, db_id)
    await message.reply_text(t('saved', lang) + "\n\n" + text,
                             reply_markup=kb, disable_web_page_preview=True)


async def _process_sync_auth(update, context, st):
    chat = update.effective_chat.id
    lang = L(chat)
    message = update.message
    user_text = (message.text or "").strip()
    state = st['state']
    phone = st['phone']
    code_hash = st['phone_code_hash']
    api_id = int(config.TELEGRAM_API_ID)
    api_hash = config.TELEGRAM_API_HASH

    await message.reply_text("⏳")

    client = active_clients.get(chat)
    if not client:
        client = TelegramClient(StringSession(st.get('session_string') or ''), api_id, api_hash)
        await client.connect()
        active_clients[chat] = client
    try:
        if not client.is_connected():
            await client.connect()

        if state == 'AWAITING_CODE':
            try:
                clean_code = re.sub(r'\D', '', user_text)
                await client.sign_in(phone, clean_code, phone_code_hash=code_hash)
            except SessionPasswordNeededError:
                database.set_sync_state(chat, 'AWAITING_2FA', session_string=client.session.save())
                await message.reply_text(t('sync_2fa', lang))
                return
            except PhoneCodeInvalidError:
                await message.reply_text(t('sync_badcode', lang))
                return
            except PhoneCodeExpiredError:
                await client.disconnect()
                active_clients.pop(chat, None)
                database.clear_sync_state(chat)
                clean_session_files(chat)
                await message.reply_text(t('sync_expired', lang))
                return
        elif state == 'AWAITING_2FA':
            try:
                await client.sign_in(password=user_text)
            except PasswordHashInvalidError:
                await message.reply_text(t('sync_badpw', lang))
                return

        await message.reply_text(t('sync_importing', lang))
        count = 0
        media_done = 0
        async for msg in client.iter_messages('me', limit=100):
            text = msg.text or msg.message or ""
            media_type = 'text'
            if msg.photo:
                media_type = 'photo'
            elif msg.video:
                media_type = 'video'
            elif msg.document:
                media_type = 'document'
            elif msg.voice:
                media_type = 'voice'
            elif msg.audio:
                media_type = 'audio'
            if not text and media_type == 'text':
                continue

            file_id = None
            tg_msg_id = None
            # For media: download via Telethon and re-upload through the bot so we
            # capture a permanent, bot-usable file_id (and deliver the real file).
            if media_type != 'text' and media_done < SYNC_MEDIA_LIMIT:
                try:
                    blob = await client.download_media(msg, file=bytes)
                    if blob:
                        cap = (text[:1000] or None)
                        if media_type == 'photo':
                            sent = await context.bot.send_photo(chat, blob, caption=cap, disable_notification=True)
                            file_id = sent.photo[-1].file_id
                        elif media_type == 'video':
                            sent = await context.bot.send_video(chat, blob, caption=cap, disable_notification=True)
                            file_id = sent.video.file_id
                        elif media_type == 'voice':
                            sent = await context.bot.send_voice(chat, blob, caption=cap, disable_notification=True)
                            file_id = sent.voice.file_id
                        elif media_type == 'audio':
                            sent = await context.bot.send_audio(chat, blob, caption=cap, disable_notification=True)
                            file_id = sent.audio.file_id
                        else:  # document and anything else
                            fname = None
                            try:
                                fname = msg.file.name if msg.file else None
                            except Exception:
                                fname = None
                            sent = await context.bot.send_document(
                                chat, blob, filename=fname or "file", caption=cap,
                                disable_notification=True)
                            file_id = sent.document.file_id
                        tg_msg_id = sent.message_id
                        media_done += 1
                except Exception as e:
                    print(f"sync media import error: {e}")
                    file_id = None
                    tg_msg_id = None

            db_id = database.add_saved_message(
                chat_id=chat, text=text, media_type=media_type,
                media_file_id=file_id, telegram_message_id=tg_msg_id)
            for tag in re.findall(r"#([a-zA-Z0-9_]+)", text):
                database.add_tag(db_id, tag.lower())
            count += 1

        await client.log_out()
        await client.disconnect()
        active_clients.pop(chat, None)
        database.clear_sync_state(chat)
        clean_session_files(chat)
        await message.reply_text(t('sync_done', lang, n=count))
    except Exception as e:
        if chat in active_clients:
            try:
                await active_clients[chat].disconnect()
            except Exception:
                pass
            active_clients.pop(chat, None)
        clean_session_files(chat)
        database.clear_sync_state(chat)
        await message.reply_text(t('sync_failed', lang, err=str(e)))


# ----------------------------------------------------------------------------
# Callback (button) handler
# ----------------------------------------------------------------------------
async def callback_handler(update, context):
    query = update.callback_query
    chat = query.message.chat_id
    lang = L(chat)
    data = query.data
    parts = data.split(":")
    a = parts[0]

    if a == "noop":
        await query.answer()
        return

    if a == "menu":
        sub = parts[1]
        if sub == "home":
            await query.answer()
            await _edit(query, render_menu(chat))
        elif sub == "list":
            await query.answer()
            await _edit(query, render_list(chat, 0))
        elif sub == "tags":
            await query.answer()
            await _edit(query, render_tags(chat))
        elif sub == "help":
            await query.answer()
            await _edit(query, render_help(chat))
        elif sub == "lang":
            await query.answer()
            await _edit(query, render_language(chat))
        elif sub == "tz":
            await query.answer()
            await context.bot.send_message(
                chat, t('tz_cur', lang, tz=get_tz(chat)) + "\n\n" + t('tz_prompt', lang),
                reply_markup=ForceReply(selective=True))
        elif sub == "sync":
            await query.answer()
            await start_sync(chat, context)
        elif sub == "digest":
            new_state = not database.get_digest_enabled(chat)
            database.set_digest_enabled(chat, new_state)
            await query.answer(t('digest_toggled_on' if new_state else 'digest_toggled_off', lang))
            await _edit(query, render_menu(chat))
        return

    if a == "list":
        await query.answer()
        await _edit(query, render_list(chat, int(parts[2])))
        return
    if a == "tagf":
        await query.answer()
        await _edit(query, render_tagfilter(chat, parts[1], int(parts[2])))
        return
    if a == "srch":
        await query.answer()
        await _edit(query, render_search(chat, last_search.get(chat, ""), int(parts[2])))
        return

    if a == "open":
        await query.answer()
        database.mark_seen(int(parts[1]))
        await _edit(query, build_card(chat, int(parts[1])))
        return
    if a == "show":
        await query.answer()
        msg = database.get_message_details(int(parts[1]))
        if msg:
            await resend_media(context.bot, chat, msg)
        return
    if a == "remopts":
        await query.answer()
        await _edit(query, render_rem_options(chat, int(parts[1])))
        return
    if a == "rempick":
        await query.answer()
        await _edit(query, render_rem_picker(chat, int(parts[1])))
        return
    if a == "remcustom":
        db_id = int(parts[1])
        await query.answer()
        await context.bot.send_message(
            chat, t('rem_custom_prompt', lang, id=db_id), reply_markup=ForceReply(selective=True))
        return
    if a == "digestoff":
        database.set_digest_enabled(chat, False)
        await query.answer(t('digest_toggled_off', lang))
        try:
            await query.edit_message_text(t('digest_stopped', lang))
        except Exception:
            pass
        return

    if a == "rem":
        db_id = int(parts[-1])
        rt = compute_rem(parts, get_tz(chat))
        if rt:
            database.set_reminder(db_id, rt)
            await query.answer(t('rem_set', lang, time=fmt_time(rt, get_tz(chat))))
        else:
            await query.answer()
        await _edit(query, build_card(chat, db_id))
        return

    if a == "tag":
        sub = parts[1]
        if sub == "add":
            await query.answer()
            await _edit(query, render_tag_options(chat, int(parts[2])))
        elif sub == "set":
            tg = parts[2]
            db_id = int(parts[3])
            database.add_tag(db_id, tg)
            await query.answer(t('tag_added', lang, tags="#" + tg))
            await _edit(query, build_card(chat, db_id))
        elif sub == "type":
            db_id = int(parts[2])
            await query.answer()
            await context.bot.send_message(
                chat, t('tag_prompt', lang, id=db_id), reply_markup=ForceReply(selective=True))
        return

    if a == "arc":
        db_id = int(parts[1])
        database.mark_as_archived(db_id)
        await query.answer(t('archived', lang))
        await _edit(query, render_cb(chat, last_list_cb.get(chat, "list:p:0")))
        return

    if a == "snz":
        db_id = int(parts[-1])
        now = datetime.utcnow()
        if parts[1] == "10m":
            rt, dur = now + timedelta(minutes=10), t('d10m', lang)
        elif parts[1] == "1h":
            rt, dur = now + timedelta(hours=1), t('d1h', lang)
        else:
            rt, dur = get_tomorrow_morning_in_utc(get_tz(chat)), t('dtom', lang)
        database.set_reminder(db_id, rt)
        await query.answer(t('snoozed', lang, dur=dur))
        try:
            await query.edit_message_text(t('snoozed', lang, dur=dur))
        except Exception:
            pass
        return

    if a == "done":
        db_id = int(parts[1])
        database.mark_as_archived(db_id)
        await query.answer(t('archived', lang))
        try:
            await query.edit_message_text(t('archived', lang))
        except Exception:
            pass
        return

    if a == "lang":
        code = parts[1]
        if code in LANG_CODES:
            userlang.set_language(chat, code)
        nl = L(chat)
        await query.answer(t('language_set', nl))
        await _edit(query, render_menu(chat))
        return

    await query.answer()


# ----------------------------------------------------------------------------
# Reminder delivery
# ----------------------------------------------------------------------------
async def send_reminder_message(bot, item):
    chat = item['chat_id']
    lang = userlang.get_language(chat) or "en"
    db_id = item['id']
    await bot.send_message(chat, t('rem_banner', lang), parse_mode="Markdown")
    delivered = False
    if has_media(item):
        delivered = await resend_media(bot, chat, item)
    if not delivered:
        text = item['text'] or "—"
        if item['media_type'] != 'text':
            text = f"[{item['media_type'].capitalize()}] {text}"
        await bot.send_message(chat, text, disable_web_page_preview=True)
    rows = [
        [InlineKeyboardButton(t('done', lang), callback_data=f"done:{db_id}")],
        [InlineKeyboardButton(t('s10m', lang), callback_data=f"snz:10m:{db_id}"),
         InlineKeyboardButton(t('s1h', lang), callback_data=f"snz:1h:{db_id}"),
         InlineKeyboardButton(t('stom', lang), callback_data=f"snz:tom:{db_id}")],
    ]
    await bot.send_message(chat, t('choose_action', lang), reply_markup=InlineKeyboardMarkup(rows))


async def deliver_due_reminders(bot):
    """Send any reminders that are now due (works with a bare bot, no JobQueue)."""
    for item in database.get_due_reminders():
        try:
            await send_reminder_message(bot, item)
            database.mark_as_reminded(item['id'])
        except Exception as e:
            print(f"reminder error {item.get('id')}: {e}")


async def poll_reminders(context):
    await deliver_due_reminders(context.bot)


def _stale_items(chat):
    """Active items the user hasn't opened within their escalating nudge window,
    skipping anything with a pending user-set reminder."""
    now = datetime.utcnow()
    out = []
    for m in database.get_active_messages(chat, limit=1000):
        if m.get('reminder_time') and not m.get('is_reminded'):
            continue  # a real reminder is already pending; don't double-nag
        seen = m.get('last_seen') or m.get('created_at')
        if not seen:
            continue
        try:
            seen_dt = datetime.fromisoformat(seen)
        except Exception:
            continue
        nc = m.get('nudge_count') or 0
        threshold = NUDGE_THRESHOLDS[min(nc, len(NUDGE_THRESHOLDS) - 1)]
        if (now - seen_dt).days >= threshold:
            out.append(m)
    return out


async def run_digest_all(bot):
    """Nudge each user about items they saved but haven't revisited (bare bot)."""
    for chat in database.get_all_chat_ids():
        try:
            if not database.get_digest_enabled(chat):
                continue
            stale = _stale_items(chat)
            if not stale:
                continue
            stale = stale[:DIGEST_MAX_ITEMS]
            lang = userlang.get_language(chat) or "en"
            name = database.get_display_name(chat)
            header = (t('digest_greet', lang, name=name) if name
                      else t('digest_greet_anon', lang))
            rows = [[InlineKeyboardButton(_label(m), callback_data=f"open:{m['id']}")] for m in stale]
            rows.append([InlineKeyboardButton(t('digest_stop', lang), callback_data="digestoff")])
            await bot.send_message(chat, header, reply_markup=InlineKeyboardMarkup(rows),
                                   disable_web_page_preview=True)
            for m in stale:
                database.bump_nudge(m['id'])
        except Exception as e:
            print(f"digest error for {chat}: {e}")


async def run_digest(context):
    await run_digest_all(context.bot)


async def run_due_jobs(bot):
    """Single entry point for the external cron pinger (webhook hosting).
    Always delivers due reminders; runs the stale-item digest at most every 6h."""
    await deliver_due_reminders(bot)
    stamp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_digest.txt')
    now = datetime.utcnow()
    last = None
    try:
        last = datetime.fromisoformat(open(stamp).read().strip())
    except Exception:
        last = None
    if last is None or (now - last).total_seconds() >= 21600:
        await run_digest_all(bot)
        try:
            open(stamp, 'w').write(now.isoformat())
        except Exception:
            pass


# ----------------------------------------------------------------------------
# App bootstrap
# ----------------------------------------------------------------------------
async def _post_init(app):
    try:
        await app.bot.set_my_commands([BotCommand(c, t(k, 'en')) for c, k in CMDS])
        for code in LANG_CODES:
            if code == 'en':
                continue
            try:
                await app.bot.set_my_commands(
                    [BotCommand(c, t(k, code)) for c, k in CMDS], language_code=code)
            except Exception:
                pass
    except Exception as e:
        print(f"set_my_commands failed: {e}")


def get_bot_app():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("tags", tags_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("timezone", timezone_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(poll_reminders, interval=60, first=10)
        # Check for stale items every 6 hours.
        app.job_queue.run_repeating(run_digest, interval=21600, first=120)
    return app


if __name__ == "__main__":
    print("Starting Saved Messages bot V2 (multilingual, button-driven, media)...")
    application = get_bot_app()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
