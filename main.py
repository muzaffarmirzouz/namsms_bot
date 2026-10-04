"""
SMS Tanishuv — Telegram bot + OBS overlay.

Bitta jarayonda ikkita narsa ishlaydi:
  1) Telegram bot (aiogram 3) — tomoshabin e'lon yuboradi, admin tasdiqlaydi.
  2) Veb-server (FastAPI) — OBS Browser Source uchun /overlay sahifasi.
"""
import asyncio
import html
import os
import re
import sqlite3
import time
from pathlib import Path

import aiohttp
import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BotCommandScopeChat, BotCommandScopeDefault,
                           CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# ---------------- Sozlamalar (Railway -> Variables) ----------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_PATH = os.environ.get("DB_PATH", "data.db")
PORT = int(os.environ.get("PORT", "8000"))
BOT_SHOW = os.environ.get("BOT_SHOW", "@NamSMS_bot")          # efirda ko'rinadigan bot nomi
COOLDOWN = int(os.environ.get("COOLDOWN_MIN", "5")) * 60      # bir odam necha daqiqada 1 ta e'lon
MAX_LEN = int(os.environ.get("MAX_LEN", "150"))                # e'lon matni uzunligi
AD_TTL = int(os.environ.get("AD_TTL_SEC", "60"))               # reklama efirda necha soniya turadi
REQUIRED_CHANNEL = os.environ.get("REQUIRED_CHANNEL", "@Namanganliklar_uz").strip()  # bo'sh = tekshirmaslik
MSG_TTL_MIN = int(os.environ.get("MSG_TTL_MIN", "10"))         # tomoshabin xabari efirda necha daqiqa turadi

AUTO_DEFAULT = os.environ.get("AUTO_MODE", "1")                # 1 = oddiy xabarlar avtomat efirga
CITY_NAME = os.environ.get("CITY_NAME", "Namangan")            # ob-havo shahri
CITY_LAT = os.environ.get("CITY_LAT", "40.9983")
CITY_LON = os.environ.get("CITY_LON", "71.6726")

# ---------------- Filtr ----------------
# So'kinish va haqoratlar: xabar darhol RAD etiladi (efirga ham, adminga ham bormaydi).
# So'zning boshi yoziladi: "sikay" -> "sikaymi", "sikaman" ham ushlanadi.
BLOCK_WORDS = [
    "jalab", "jalap", "qanjiq", "kanjik", "sikay", "sikam", "sikib", "sikdi", "sikish", "sikt",
    "qotoq", "qo'toq", "ko'tak", "haromi", "itvach", "dalbayob", "dolboyob", "dolbayob",
    "suka", "blyat", "blat", "bilat", "pidor", "pidar", "nahuy", "naxuy", "xuev", "xuyn", "huyn",
    "pizd", "yeban", "yebat", "eban", "mudak", "gandon", "chmo", "shalava", "shlux", "shlyux",
    "fohisha", "foxisha", "faxisha", "qahba", "kaxba", "qanjik",
    "сука", "бля", "нахуй", "хуев", "хуйн", "хую", "пизд", "ебан", "ебат", "ёбан", "пидор", "пидар",
    "мудак", "гандон", "чмо", "шлюх", "шалава", "жалаб", "қанжиқ", "канжик", "сикай",
    "сикам", "сикиш", "қотоқ", "хароми", "далбаёб", "долбоёб", "фохиша", "қаҳба", "кахба",
]
# Shubhali so'zlar: xabar adminga TEKSHIRUVGA yuboriladi.
SUSPECT_WORDS = [
    "pul", "dollar", "so'm", "sotaman", "sotiladi", "sotuv", "kredit", "qarz", "daromad",
    "ishlash", "ish bor", "bonus", "aksiya", "reklama", "kazino", "stavka", "bukmeker", "1xbet",
    "intim", "18+", "seks", "sex", "seksi", "massaj", "masaj", "kvartira", "yotoq",
    "vip", "telegram", "instagram", "insta", "tiktok", "kanal", "obuna", "lichka", "lichkaga",
    "nomer", "raqam", "telefon", "aloqa", "yoz menga",
    "деньг", "доллар", "продам", "продаю", "кредит", "заработ", "интим", "секс", "массаж",
    "казино", "ставк", "канал", "подпис", "номер", "телефон", "личк",
]
LINK_RE = re.compile(r"(https?://|www\.|t\.me/|@\w{4,}|\b\w+\.(uz|com|ru|org|net|me)\b)", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
DIGITS_RE = re.compile(r"\d{3,}")          # 3+ raqam ketma-ket (bo'lak-bo'lak raqam yozish)
LETTER = r"a-zа-яёўқғҳ'"

# ---------------- Baza ----------------
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists users(
    id integer primary key, adult integer default 0, banned integer default 0);
create table if not exists msgs(
    id integer primary key autoincrement, user_id integer, name text, text text,
    status text default 'pending', created real, aired real);
create table if not exists reqs(
    id integer primary key autoincrement, from_id integer, from_name text,
    msg_id integer, text text, created real);
create table if not exists ads(
    id integer primary key autoincrement, text text, active integer default 1, created real);
create table if not exists pins(
    id integer primary key autoincrement, text text, active integer default 1, created real);
create table if not exists settings(k text primary key, v text);
create table if not exists words(word text primary key, kind text);
""")
db.commit()
for _sql in ("alter table users add column phone text", "alter table msgs add column phone text"):
    try:
        db.execute(_sql)   # eski bazaga yangi ustun qo'shish (bor bo'lsa xato beradi, e'tibor bermaymiz)
    except sqlite3.OperationalError:
        pass
db.commit()


def setting(k: str, default: str) -> str:
    row = db.execute("select v from settings where k=?", (k,)).fetchone()
    return row["v"] if row else default


def set_setting(k: str, v: str):
    db.execute("insert or replace into settings(k, v) values(?,?)", (k, v))
    db.commit()


def norm(text: str) -> str:
    t = text.lower()
    for a in "ʻ’`ʼ‘":
        t = t.replace(a, "'")
    t = re.sub(r"(.)\1+", r"\1", t)          # "suuuka" -> "suka", "massaj" -> "masaj"
    return t


def build_re(words):
    stems = sorted({norm(w) for w in words if w.strip()}, key=len, reverse=True)
    if not stems:
        return None
    return re.compile(rf"(?<![{LETTER}])(" + "|".join(re.escape(s) for s in stems) + ")", re.I)


BLOCK_RE = SUSPECT_RE = None


def reload_words():
    """Asosiy ro'yxat + admin bot orqali qo'shgan so'zlar."""
    global BLOCK_RE, SUSPECT_RE
    extra = db.execute("select word, kind from words").fetchall()
    BLOCK_RE = build_re(BLOCK_WORDS + [r["word"] for r in extra if r["kind"] == "block"])
    SUSPECT_RE = build_re(SUSPECT_WORDS + [r["word"] for r in extra if r["kind"] == "suspect"])


reload_words()


def get_user(uid: int) -> sqlite3.Row:
    db.execute("insert or ignore into users(id) values(?)", (uid,))
    db.commit()
    return db.execute("select * from users where id=?", (uid,)).fetchone()


def bad_reason(text: str) -> str | None:
    """Darhol rad etiladigan narsalar."""
    if LINK_RE.search(text):
        return "Havola yoki @username yozish mumkin emas."
    if PHONE_RE.search(text):
        return ("Raqamni xabar ichiga yozmang. Keyingi qadamda tasdiqlangan raqamingizni "
                "efirga qo'shishingiz mumkin.")
    if BLOCK_RE and BLOCK_RE.search(norm(text)):
        return "Xabarda odobsiz so'z bor. Efirga chiqmaydi."
    return None


def suspect_reason(name: str, text: str) -> str | None:
    """Admin tekshirishi kerak bo'lgan narsalar. None bo'lsa avtomat efirga chiqadi."""
    if SUSPECT_RE:
        m = SUSPECT_RE.search(norm(text)) or SUSPECT_RE.search(norm(name))
        if m:
            return f"shubhali so'z: «{m.group(1)}»"
    if DIGITS_RE.search(text):
        return "xabarda raqamlar bor"
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) >= 15 and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        return "katta harflar bilan baqirish"
    return None


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, url=d) if d.startswith("http")
         else InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def fmt_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("998"):
        return f"+998 {d[3:5]} {d[5:8]} {d[8:10]} {d[10:12]}"
    return "+" + d


def user_link(user) -> str:
    name = html.escape(user.full_name or "Foydalanuvchi")
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{name}</a>'


# ---------------- Bot ----------------
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
state: dict[int, dict] = {}   # uid -> {"step": "name"|"text"|"phone"|"contact", ...}

HELP = (
    "<b>Qanday ishlaydi?</b>\n"
    "1. Ismingiz, yoshingiz, shahringiz va xabaringizni yozasiz.\n"
    f"2. Xabaringiz efirda {MSG_TTL_MIN} daqiqa aylanib turadi va o'zi o'chadi.\n"
    "3. Xohlasangiz, telefon raqamingizni ham efirga chiqarishingiz mumkin. Buning uchun "
    "raqamingizni Telegram orqali tasdiqlaysiz, shunda u rostdan ham sizniki ekanligi tekshiriladi.\n\n"
    "Xabar ichiga raqam, havola yoki @username yozib bo'lmaydi."
)

CHANNEL_URL = f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}" if REQUIRED_CHANNEL else ""


async def is_subscribed(uid: int) -> bool:
    if not REQUIRED_CHANNEL or uid in ADMIN_IDS:
        return True
    try:
        mem = await bot.get_chat_member(REQUIRED_CHANNEL, uid)
    except Exception as e:
        # Bot kanalga admin qilinmagan bo'lsa tekshira olmaydi: foydalanuvchini to'xtatmaymiz
        print(f"[sub] {REQUIRED_CHANNEL} tekshirib bo'lmadi (bot kanalda adminmi?): {e}")
        return True
    status = getattr(mem.status, "value", mem.status)
    return status in ("member", "administrator", "creator") or \
        (status == "restricted" and getattr(mem, "is_member", False))


async def ask_subscribe(chat_id: int):
    await bot.send_message(
        chat_id,
        f"Botdan foydalanish uchun {REQUIRED_CHANNEL} kanaliga a'zo bo'ling.\n\n"
        "A'zo bo'lgach, «A'zo bo'ldim» tugmasini bosing.",
        reply_markup=kb([("Kanalga o'tish", CHANNEL_URL)], [("A'zo bo'ldim", "sub:check")]))


async def ask_name(chat_id: int, uid: int):
    state[uid] = {"step": "name"}
    await bot.send_message(chat_id, "Ismingiz, yoshingiz va shahringizni yozing.\n"
                                    "Masalan: <i>Aziz, 25, Namangan</i>",
                           reply_markup=ReplyKeyboardRemove())


async def begin(chat_id: int, uid: int):
    """Obuna -> 18+ -> ism. Har bosqichda yetishmayotganini so'raydi."""
    u = get_user(uid)
    if u["banned"]:
        return
    if not await is_subscribed(uid):
        return await ask_subscribe(chat_id)
    if not u["adult"]:
        return await bot.send_message(
            chat_id, "Assalomu alaykum! Bu SMS CHAT bo'limi.\n\n"
                     "Bo'lim faqat 18 yoshdan kattalar uchun. Sizga 18 yosh to'lganmi?",
            reply_markup=kb([("Ha, 18 yoshdan kattaman", "age:yes")], [("Yo'q", "age:no")]))
    await bot.send_message(chat_id, HELP)
    await ask_name(chat_id, uid)


@dp.message(CommandStart())
async def cmd_start(m: Message):
    await begin(m.chat.id, m.from_user.id)


@dp.callback_query(F.data == "sub:check")
async def cb_sub(c: CallbackQuery):
    if await is_subscribed(c.from_user.id):
        await c.message.edit_reply_markup()
        await c.answer("Rahmat!")
        await begin(c.message.chat.id, c.from_user.id)
    else:
        await c.answer(f"Siz hali {REQUIRED_CHANNEL} kanaliga a'zo emassiz.", show_alert=True)


@dp.callback_query(F.data.startswith("age:"))
async def cb_age(c: CallbackQuery):
    await c.message.edit_reply_markup()
    if c.data == "age:yes":
        db.execute("update users set adult=1 where id=?", (c.from_user.id,))
        db.commit()
        await begin(c.message.chat.id, c.from_user.id)
    else:
        await c.message.answer("Kechirasiz, bu bo'lim faqat 18 yoshdan kattalar uchun.")
    await c.answer()


@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(HELP)


# ---------- Admin buyruqlari ----------
@dp.message(Command("stat"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stat(m: Message):
    r = {s: n for s, n in db.execute("select status, count(*) from msgs group by status")}
    users = db.execute("select count(*) from users").fetchone()[0]
    await m.answer(f"Foydalanuvchilar: {users}\nKutilmoqda: {r.get('pending', 0)}\n"
                   f"Efirda: {r.get('live', 0)}\nArxiv: {r.get('archived', 0)}\n"
                   f"Rad etilgan: {r.get('rejected', 0)}\nEfirdan olingan: {r.get('removed', 0)}\n\n"
                   "Avtomat rejim: " + ("YOQIQ" if setting("auto", AUTO_DEFAULT) == "1" else "O'CHIQ"))


@dp.message(Command("tozala"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_clear(m: Message):
    db.execute("update msgs set status='archived' where status='live'")
    db.commit()
    await m.answer("Efirdagi qator tozalandi.")


FILTER_HELP = (
    "<b>Avtomat rejim va filtr:</b>\n"
    "<code>/avto</code> — avtomat rejimni yoqish/o'chirish\n"
    "<code>/taqiq so'z</code> — so'kinish ro'yxatiga qo'shish (darhol rad etiladi)\n"
    "<code>/shubha so'z</code> — shubhali ro'yxatga qo'shish (sizga tekshiruvga keladi)\n"
    "<code>/ochir so'z</code> — siz qo'shgan so'zni olib tashlash\n"
    "<code>/sozlar</code> — siz qo'shgan so'zlar\n\n"
    "So'zning boshini yozish kifoya: <code>/shubha kvartir</code> — "
    "kvartira, kvartiraga, kvartirada hammasini ushlaydi."
)


@dp.message(Command("avto"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_auto(m: Message):
    new = "0" if setting("auto", AUTO_DEFAULT) == "1" else "1"
    set_setting("auto", new)
    if new == "1":
        await m.answer("<b>Avtomat rejim YOQILDI.</b>\nOddiy xabarlar darhol efirga chiqadi, "
                       "shubhalilari sizga tekshiruvga keladi.\n\n" + FILTER_HELP)
    else:
        await m.answer("<b>Avtomat rejim O'CHIRILDI.</b>\nEndi har bir xabarni siz tasdiqlaysiz.")


async def add_word(m: Message, command: CommandObject, kind: str):
    word = norm(" ".join((command.args or "").split()))
    if len(word) < 2:
        return await m.answer(FILTER_HELP)
    db.execute("insert or replace into words(word, kind) values(?,?)", (word, kind))
    db.commit()
    reload_words()
    label = "so'kinish (darhol rad)" if kind == "block" else "shubhali (tekshiruvga)"
    await m.answer(f"«{html.escape(word)}» {label} ro'yxatiga qo'shildi.")


@dp.message(Command("taqiq"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_block_word(m: Message, command: CommandObject):
    await add_word(m, command, "block")


@dp.message(Command("shubha"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_suspect_word(m: Message, command: CommandObject):
    await add_word(m, command, "suspect")


@dp.message(Command("ochir"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_del_word(m: Message, command: CommandObject):
    word = norm(" ".join((command.args or "").split()))
    cur = db.execute("delete from words where word=?", (word,))
    db.commit()
    reload_words()
    await m.answer(f"«{html.escape(word)}» olib tashlandi." if cur.rowcount
                   else "Bu so'z siz qo'shgan ro'yxatda yo'q. (Asosiy ro'yxat kod ichida.)")


@dp.message(Command("sozlar"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_words(m: Message):
    rows = db.execute("select word, kind from words order by kind, word").fetchall()
    b = [r["word"] for r in rows if r["kind"] == "block"]
    s = [r["word"] for r in rows if r["kind"] == "suspect"]
    mode = "YOQIQ" if setting("auto", AUTO_DEFAULT) == "1" else "O'CHIQ"
    await m.answer(f"Avtomat rejim: <b>{mode}</b>\n\n"
                   f"<b>Siz qo'shgan taqiqlar:</b> {html.escape(', '.join(b)) or '—'}\n"
                   f"<b>Siz qo'shgan shubhalilar:</b> {html.escape(', '.join(s)) or '—'}\n\n"
                   f"Asosiy ro'yxatda yana {len(BLOCK_WORDS)} ta so'kinish va "
                   f"{len(SUSPECT_WORDS)} ta shubhali so'z bor.\n\n" + FILTER_HELP)


AD_HELP = ("<b>Reklama buyruqlari:</b>\n"
           "<code>/reklama Matn</code> — reklamani efirga chiqarish\n"
           "<code>/reklamalar</code> — oxirgi reklamalar, qayta chiqarish\n\n"
           f"Reklama {AD_TTL} soniya efirda turadi va o'zi o'chadi. U alohida joyda "
           "(yuqori chapda) va pastki qatorda, boshqa rangda, ismsiz chiqadi.")


def ad_kb(ad_id: int):
    return kb([("Yana chiqarish", f"adre:{ad_id}"), ("Hozir o'chirish", f"addel:{ad_id}")])


@dp.message(Command("reklama"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_ad(m: Message, command: CommandObject):
    text = " ".join((command.args or "").split())
    if not text:
        return await m.answer(AD_HELP)
    if len(text) > 200:
        return await m.answer(f"Reklama juda uzun ({len(text)} belgi). 200 belgigacha qisqartiring.")
    cur = db.execute("insert into ads(text, created) values(?,?)", (text, time.time()))
    db.commit()
    await m.answer(f"Reklama efirga chiqdi, {AD_TTL} soniyadan keyin o'zi o'chadi.\n\n"
                   f"<b>R{cur.lastrowid}</b>: {html.escape(text)}", reply_markup=ad_kb(cur.lastrowid))


@dp.message(Command("reklamalar"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_ads(m: Message):
    rows = db.execute("select id, text from ads where active=1 order by id desc limit 10").fetchall()
    if not rows:
        return await m.answer("Hali reklama yo'q.\n\n" + AD_HELP)
    for r in reversed(rows):
        await m.answer(f"<b>R{r['id']}</b>: {html.escape(r['text'])}", reply_markup=ad_kb(r["id"]))


# ---------- Admin e'loni: faqat pastki qatorda, o'chirmaguncha aylanadi ----------
@dp.message(Command("elon"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_pin(m: Message, command: CommandObject):
    text = " ".join((command.args or "").split())
    if not text:
        return await m.answer("<b>Admin e'loni</b> pastki qatorda alohida rangda chiqadi va "
                              "o'chirmaguningizcha aylanib turadi. Ekranda kartochka bo'lib chiqmaydi.\n\n"
                              "<code>/elon Matn</code> — qo'shish\n<code>/elonlar</code> — ro'yxat va o'chirish")
    if len(text) > 200:
        return await m.answer(f"E'lon juda uzun ({len(text)} belgi). 200 belgigacha qisqartiring.")
    cur = db.execute("insert into pins(text, created) values(?,?)", (text, time.time()))
    db.commit()
    await m.answer(f"E'lon pastki qatorga qo'shildi va o'chirmaguningizcha aylanadi.\n\n"
                   f"<b>E{cur.lastrowid}</b>: {html.escape(text)}",
                   reply_markup=kb([("O'chirish", f"pindel:{cur.lastrowid}")]))


@dp.message(Command("elonlar"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_pins(m: Message):
    rows = db.execute("select id, text from pins where active=1 order by id").fetchall()
    if not rows:
        return await m.answer("Qatorda admin e'loni yo'q.\nQo'shish: <code>/elon Matn</code>")
    for r in rows:
        await m.answer(f"<b>E{r['id']}</b>: {html.escape(r['text'])}",
                       reply_markup=kb([("O'chirish", f"pindel:{r['id']}")]))


@dp.callback_query(F.data.startswith("pindel:"))
async def cb_pin_del(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return await c.answer("Faqat admin uchun", show_alert=True)
    db.execute("update pins set active=0 where id=?", (int(c.data.split(":")[1]),))
    db.commit()
    await c.message.edit_text(c.message.html_text + "\n\n<b>O'chirildi</b>")
    await c.answer("Qatordan olindi")


@dp.callback_query(F.data.startswith(("addel:", "adre:")))
async def cb_ad(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return await c.answer("Faqat admin uchun", show_alert=True)
    act, ad_id = c.data.split(":")
    if act == "adre":
        db.execute("update ads set created=?, active=1 where id=?", (time.time(), int(ad_id)))
        note = f"Yana efirga chiqdi ({AD_TTL} soniya)"
    else:
        db.execute("update ads set created=0 where id=?", (int(ad_id),))
        note = "Efirdan olindi"
    db.commit()
    await c.answer(note)


@dp.callback_query(F.data.regexp(r"^(del|delban):\d+$"))
async def cb_admin_remove(c: CallbackQuery):
    """Avtomat chiqqan xabarni efirdan olish."""
    if c.from_user.id not in ADMIN_IDS:
        return await c.answer("Faqat admin uchun", show_alert=True)
    act, mid = c.data.split(":")
    msg = db.execute("select * from msgs where id=?", (int(mid),)).fetchone()
    if not msg or msg["status"] not in ("live", "archived"):
        await c.message.edit_reply_markup()
        return await c.answer("Allaqachon olingan")
    db.execute("update msgs set status='removed' where id=?", (msg["id"],))
    note = "Efirdan olindi"
    if act == "delban":
        db.execute("update users set banned=1 where id=?", (msg["user_id"],))
        note = "Efirdan olindi va bloklandi"
    db.commit()
    await c.message.edit_text(c.message.html_text + f"\n\n<b>{note}</b> ({html.escape(c.from_user.first_name)})")
    await c.answer(note)


@dp.callback_query(F.data.regexp(r"^(ok|no|ban):\d+$"))
async def cb_admin(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return await c.answer("Faqat admin uchun", show_alert=True)
    act, mid = c.data.split(":")
    msg = db.execute("select * from msgs where id=?", (int(mid),)).fetchone()
    if not msg or msg["status"] != "pending":
        await c.message.edit_reply_markup()
        return await c.answer("Allaqachon ko'rib chiqilgan")
    if act == "ok":
        db.execute("update msgs set status='live', aired=? where id=?", (time.time(), msg["id"]))
        note, user_text = "EFIRGA CHIQDI", ("Xabaringiz efirga chiqdi!\n"
                                            f"U {MSG_TTL_MIN} daqiqa efirda turadi, keyin o'zi o'chadi.")
    else:
        db.execute("update msgs set status='rejected' where id=?", (msg["id"],))
        note, user_text = "Rad etildi", "Afsuski, xabaringiz efirga chiqmadi. Qoidalarni tekshirib, qayta yuboring."
        if act == "ban":
            db.execute("update users set banned=1 where id=?", (msg["user_id"],))
            note, user_text = "Rad etildi va bloklandi", None
    db.commit()
    await c.message.edit_text(c.message.html_text + f"\n\n<b>{note}</b> ({html.escape(c.from_user.first_name)})")
    if user_text:
        try:
            await bot.send_message(msg["user_id"], user_text)
        except Exception:
            pass
    await c.answer(note)


# ---------- Oddiy matn: e'lon yig'ish ----------
async def ask_phone(chat_id: int, uid: int):
    """Xabar tayyor: telefon raqam efirga chiqsinmi?"""
    state[uid]["step"] = "phone"
    saved = get_user(uid)["phone"]
    rows = []
    if saved:
        rows.append([(f"Ha, {fmt_phone(saved)} chiqsin", "ph:saved")])
        rows.append([("Boshqa raqamni tasdiqlash", "ph:new")])
    else:
        rows.append([("Ha, raqamim chiqsin", "ph:new")])
    rows.append([("Yo'q, raqamsiz", "ph:no")])
    await bot.send_message(chat_id, "Telefon raqamingiz ham efirda chiqsinmi?\n\n"
                                    "Raqam faqat Telegram orqali tasdiqlangandan keyin chiqadi, "
                                    "shunda u rostdan ham sizniki ekanligi tekshiriladi.",
                           reply_markup=kb(*rows))


@dp.callback_query(F.data.startswith("ph:"))
async def cb_phone(c: CallbackQuery):
    uid = c.from_user.id
    st = state.get(uid)
    await c.message.edit_reply_markup()
    await c.answer()
    if not st or st.get("step") != "phone":
        return await c.message.answer("Qaytadan boshlash uchun /start bosing.")
    if c.data == "ph:no":
        return await finalize(c.message.chat.id, c.from_user, None)
    if c.data == "ph:saved":
        return await finalize(c.message.chat.id, c.from_user, get_user(uid)["phone"])
    st["step"] = "contact"
    await c.message.answer(
        "Pastdagi «Raqamimni yuborish» tugmasini bosing. Telegram raqamingizni o'zi yuboradi, "
        "qo'lda yozish shart emas.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Raqamimni yuborish", request_contact=True)],
                      [KeyboardButton(text="Raqamsiz yuborish")]],
            resize_keyboard=True, one_time_keyboard=True))


@dp.message(F.contact)
async def on_contact(m: Message):
    uid = m.from_user.id
    st = state.get(uid)
    if not st or st.get("step") != "contact":
        return await m.answer("Qaytadan boshlash uchun /start bosing.", reply_markup=ReplyKeyboardRemove())
    if m.contact.user_id != uid:
        return await m.answer("Faqat o'zingizning raqamingizni yuborishingiz mumkin. "
                              "«Raqamimni yuborish» tugmasini bosing.")
    phone = re.sub(r"\D", "", m.contact.phone_number)
    db.execute("update users set phone=? where id=?", (phone, uid))
    db.commit()
    await m.answer(f"Raqamingiz tasdiqlandi: {fmt_phone(phone)}", reply_markup=ReplyKeyboardRemove())
    await finalize(m.chat.id, m.from_user, phone)


async def finalize(chat_id: int, user, phone: str | None):
    """Xabarni saqlaydi: toza bo'lsa darhol efirga, shubhali bo'lsa adminga."""
    uid = user.id
    st = state.pop(uid, None)
    if not st or "text" not in st:
        return await bot.send_message(chat_id, "Qaytadan boshlash uchun /start bosing.",
                                      reply_markup=ReplyKeyboardRemove())
    name, text = st["name"], st["text"]
    now = time.time()
    auto = setting("auto", AUTO_DEFAULT) == "1"
    why = suspect_reason(name, text) if auto else "avtomat rejim o'chiq"
    phone_line = f"\nTelefon (tasdiqlangan): {fmt_phone(phone)}" if phone else ""

    if why is None:
        # Toza xabar: admin kutmasdan darhol efirga
        cur = db.execute("insert into msgs(user_id, name, text, phone, status, created, aired) "
                         "values(?,?,?,?,'live',?,?)", (uid, name, text, phone, now, now))
        db.commit()
        mid = cur.lastrowid
        await bot.send_message(chat_id,
                               f"Xabaringiz efirga chiqdi!\n"
                               f"U {MSG_TTL_MIN} daqiqa efirda turadi, keyin o'zi o'chadi.\n\n"
                               f"Yana yozmoqchi bo'lsangiz, {COOLDOWN // 60} daqiqadan keyin /start bosing.",
                               reply_markup=ReplyKeyboardRemove())
        card = (f"<b>Avtomat efirga chiqdi #{mid}</b>\n{html.escape(name)}\n\n"
                f"{html.escape(text)}{phone_line}\n\nYuboruvchi: {user_link(user)}")
        buttons = kb([("Efirdan olish", f"del:{mid}"), ("Olish va bloklash", f"delban:{mid}")])
        silent = True      # admin telefoni jiringlamaydi
    else:
        # Shubhali xabar: admin tekshiradi
        cur = db.execute("insert into msgs(user_id, name, text, phone, created) values(?,?,?,?,?)",
                         (uid, name, text, phone, now))
        db.commit()
        mid = cur.lastrowid
        await bot.send_message(chat_id, "Qabul qilindi! Moderator tekshirgach efirga chiqadi.",
                               reply_markup=ReplyKeyboardRemove())
        card = (f"<b>Tekshiruv kerak #{mid}</b> ({html.escape(why)})\n{html.escape(name)}\n\n"
                f"{html.escape(text)}{phone_line}\n\nYuboruvchi: {user_link(user)}")
        buttons = kb([("Efirga", f"ok:{mid}"), ("Rad etish", f"no:{mid}")],
                     [("Rad etish va bloklash", f"ban:{mid}")])
        silent = False
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, card, reply_markup=buttons, disable_notification=silent)
        except Exception:
            pass


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    uid = m.from_user.id
    u = get_user(uid)
    if u["banned"]:
        return
    if not u["adult"] or not await is_subscribed(uid):
        return await begin(m.chat.id, uid)
    st = state.get(uid)
    if not st:
        return await ask_name(m.chat.id, uid)

    if st["step"] == "name":
        name = " ".join(m.text.split())[:40]
        age = re.search(r"\b(\d{2})\b", name)
        if not age:
            return await m.answer("Yoshingizni ham yozing. Masalan: <i>Aziz, 25, Namangan</i>")
        if int(age.group(1)) < 18:
            state.pop(uid, None)
            return await m.answer("Kechirasiz, bu bo'lim faqat 18 yoshdan kattalar uchun.")
        if reason := bad_reason(name):
            return await m.answer(reason)
        st.update(step="text", name=name)
        return await m.answer(f"Endi efirga chiqadigan xabaringizni yozing ({MAX_LEN} belgigacha).\n"
                              "Masalan: <i>Salom, jiddiy tanishuv uchun yozing</i>\n\n"
                              f"Xabaringiz efirda {MSG_TTL_MIN} daqiqa turadi va keyin o'zi o'chadi.")

    if st["step"] == "text":
        text = " ".join(m.text.split())
        if len(text) > MAX_LEN:
            return await m.answer(f"Xabar juda uzun ({len(text)} belgi). {MAX_LEN} belgigacha qisqartiring.")
        if reason := bad_reason(text):
            return await m.answer(reason + " Qayta yozing.")
        last = db.execute("select created from msgs where user_id=? and status in ('pending','live') "
                          "order by created desc limit 1", (uid,)).fetchone()
        if last and time.time() - last["created"] < COOLDOWN:
            left = int((COOLDOWN - (time.time() - last["created"])) // 60) + 1
            state.pop(uid, None)
            return await m.answer(f"Keyingi xabarni {left} daqiqadan keyin yuborishingiz mumkin.")
        st["text"] = text
        return await ask_phone(m.chat.id, uid)

    if st["step"] == "phone":
        return await m.answer("Yuqoridagi tugmalardan birini tanlang: raqamingiz chiqsinmi yoki yo'q.")

    if st["step"] == "contact":
        if m.text.strip().lower().startswith("raqamsiz"):
            return await finalize(m.chat.id, m.from_user, None)
        return await m.answer("Raqamni qo'lda yozib bo'lmaydi. Pastdagi «Raqamimni yuborish» tugmasini "
                              "bosing yoki «Raqamsiz yuborish»ni tanlang.")


# ---------------- Valyuta kursi va ob-havo (avtomat) ----------------
INFO: dict[str, str | None] = {"kurs": None, "havo": None}

WEATHER_UZ = {
    0: "ochiq osmon", 1: "asosan ochiq", 2: "qisman bulutli", 3: "bulutli",
    45: "tuman", 48: "tuman", 51: "mayda yomg'ir", 53: "mayda yomg'ir", 55: "mayda yomg'ir",
    56: "muzli yomg'ir", 57: "muzli yomg'ir", 61: "yomg'ir", 63: "yomg'ir", 65: "kuchli yomg'ir",
    66: "muzli yomg'ir", 67: "muzli yomg'ir", 71: "qor", 73: "qor", 75: "kuchli qor", 77: "qor",
    80: "jala", 81: "jala", 82: "kuchli jala", 85: "qor", 86: "kuchli qor",
    95: "momaqaldiroq", 96: "do'l bilan momaqaldiroq", 99: "do'l bilan momaqaldiroq",
}


def money(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def temp(x: float) -> str:
    t = round(x)
    return f"+{t}°" if t > 0 else f"{t}°"


async def get_json(s: aiohttp.ClientSession, url: str):
    async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def update_rates(s: aiohttp.ClientSession):
    data = await get_json(s, "https://cbu.uz/uz/arkhiv-kursov-valyut/json/")
    by = {d["Ccy"]: d for d in data}
    parts = []
    for ccy, name, digits in (("USD", "Dollar", 0), ("EUR", "Yevro", 0), ("RUB", "Rubl", 2)):
        d = by.get(ccy)
        if not d:
            continue
        rate, diff = float(d["Rate"]), float(d["Diff"])
        val = money(rate) if digits == 0 else f"{rate:.2f}"
        step = money(abs(diff)) if digits == 0 else f"{abs(diff):.2f}"
        arrow = f"▲{step}" if diff > 0 else f"▼{step}" if diff < 0 else ""
        parts.append(f"{name} {val} {arrow}".strip())
    if parts:
        INFO["kurs"] = " · ".join(parts) + " so'm"


async def update_weather(s: aiohttp.ClientSession):
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={CITY_LAT}&longitude={CITY_LON}"
           "&current=temperature_2m,weather_code"
           "&daily=temperature_2m_max,temperature_2m_min"
           "&timezone=Asia%2FTashkent&forecast_days=1")
    d = await get_json(s, url)
    cur, day = d["current"], d["daily"]
    sky = WEATHER_UZ.get(int(cur["weather_code"]), "")
    INFO["havo"] = (f"{CITY_NAME}: hozir {temp(cur['temperature_2m'])}, {sky}. "
                    f"Bugun {temp(day['temperature_2m_min'][0])}…{temp(day['temperature_2m_max'][0])}")


INFO_META = {"ts": 0.0, "hour": ""}   # oxirgi yangilanish vaqti (efirga chiqarish signali)


async def refresh_info(announce: bool = True):
    """Kurs va ob-havoni yangilaydi. announce=True bo'lsa efirda kartochka bo'lib chiqadi."""
    async with aiohttp.ClientSession() as s:
        for job in (update_rates, update_weather):
            try:
                await job(s)
            except Exception as e:
                print(f"[info] {job.__name__} xato: {e}")
    if announce and (INFO["kurs"] or INFO["havo"]):
        INFO_META["ts"] = time.time()
        INFO_META["hour"] = time.strftime("%H:%M", time.gmtime(time.time() + 5 * 3600))  # Toshkent vaqti


async def info_loop():
    """Ishga tushganda bir marta oladi, keyin har soat boshida (14:00, 15:00...) yangilab efirga beradi.
    Xato bo'lsa eski ma'lumot qoladi."""
    await refresh_info(announce=False)
    while True:
        await asyncio.sleep(3600 - time.time() % 3600 + 5)   # keyingi soat boshigacha (+5 soniya)
        await refresh_info(announce=True)


@dp.message(Command("malumot"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_info_now(m: Message):
    await refresh_info(announce=True)
    await m.answer("Kurs va ob-havo yangilandi va hozir efirga chiqadi:\n\n"
                   f"{html.escape(INFO['kurs'] or 'kurs olinmadi')}\n{html.escape(INFO['havo'] or 'ob-havo olinmadi')}")


# ---------------- Veb-server (OBS overlay) ----------------
app = FastAPI(docs_url=None, redoc_url=None)
OVERLAY_HTML = (Path(__file__).parent / "overlay.html").read_text(encoding="utf-8")


@app.get("/")
def root():
    return {"ok": True, "overlay": "/overlay"}


@app.get("/overlay", response_class=HTMLResponse)
def overlay():
    # no-store: OBS sahifani eslab qolmasin, yangilanish darhol ko'rinsin
    return HTMLResponse(OVERLAY_HTML.replace("{{BOT_SHOW}}", html.escape(BOT_SHOW)),
                        headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/live")
def api_live():
    now = time.time()
    # Faqat oxirgi MSG_TTL_MIN daqiqada chiqqan xabarlar; eskilari qatordan o'zi tushib qoladi
    rows = db.execute("select id, name, text, phone, aired from msgs where status='live' and aired>? "
                      "order by aired desc limit 12", (now - MSG_TTL_MIN * 60,)).fetchall()
    ads = db.execute("select id, text, created from ads where active=1 and created>? order by created",
                     (now - AD_TTL,)).fetchall()
    info = [{"kind": k, "text": v} for k, v in INFO.items() if v]
    pins = db.execute("select id, text from pins where active=1 order by id").fetchall()
    return {"now": now, "ad_ttl": AD_TTL, "items": [{**dict(r), "phone": fmt_phone(r["phone"]) if r["phone"] else ""} for r in rows],
            "ads": [dict(a) for a in ads], "info": info, "pins": [dict(p) for p in pins],
            "info_ts": INFO_META["ts"], "info_hour": INFO_META["hour"]}


USER_COMMANDS = [
    BotCommand(command="start", description="Efirga xabar yuborish"),
    BotCommand(command="help", description="Qanday ishlaydi"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Admin buyruqlari ro'yxati"),
    BotCommand(command="stat", description="Statistika"),
    BotCommand(command="tozala", description="Efirdagi qatorni tozalash"),
    BotCommand(command="reklama", description="Reklama chiqarish: /reklama Matn"),
    BotCommand(command="reklamalar", description="Oxirgi reklamalar, qayta chiqarish"),
    BotCommand(command="elon", description="Pastki qatorga doimiy e'lon: /elon Matn"),
    BotCommand(command="elonlar", description="Doimiy e'lonlar ro'yxati va o'chirish"),
    BotCommand(command="malumot", description="Kurs va ob-havoni hozir efirga berish"),
    BotCommand(command="avto", description="Avtomat rejimni yoqish/o'chirish"),
    BotCommand(command="taqiq", description="So'kinish qo'shish: /taqiq so'z"),
    BotCommand(command="shubha", description="Shubhali so'z qo'shish: /shubha so'z"),
    BotCommand(command="ochir", description="Qo'shilgan so'zni o'chirish: /ochir so'z"),
    BotCommand(command="sozlar", description="Qo'shilgan so'zlar va rejim holati"),
]


async def setup_menu():
    """Oddiy foydalanuvchiga 3 ta, adminlarga hamma buyruqlar menyusi."""
    try:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        print(f"[menu] umumiy menyu xato: {e}")
    for admin in ADMIN_IDS:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin))
        except Exception as e:
            print(f"[menu] admin {admin} menyu xato (u botga /start bosmagan bo'lishi mumkin): {e}")


@dp.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_admin(m: Message):
    await setup_menu()   # admin keyin /start bosgan bo'lsa ham menyu yangilanadi
    lines = "\n".join(f"/{c.command} — {html.escape(c.description)}" for c in ADMIN_COMMANDS[2:])
    await m.answer("<b>Admin buyruqlari:</b>\n" + lines)


async def main():
    await setup_menu()
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning"))
    await asyncio.gather(server.serve(), dp.start_polling(bot), info_loop())


if __name__ == "__main__":
    asyncio.run(main())
