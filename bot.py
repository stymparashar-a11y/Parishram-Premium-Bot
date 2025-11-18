
import os
import json
import time
import asyncio
import logging
import hashlib
from datetime import datetime

# timezone lib with fallback
try:
    import pytz
    HAS_PYTZ = True
except Exception:
    HAS_PYTZ = False

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- logging ----------------
logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- CONFIG (edit these) ----------------
BOT_TOKEN = "8320647437:AAHQJn4uDMiwHwOgemgxule2_vu66VwWXdE"  # replace
ADMIN_ID = 8406676409          # replace with your admin id (int)
SECRET_KEY = "PARISHRAM2025"        # should match your HTML generator
TASK_URL = "file:///C:/Users/Satyam%20Thakur/Downloads/bot/Parishram%202025/index.html?status=verified"
BACKUP_CHANNEL = -1002877068674    # channel id where lectures are stored (int)
CHANNEL_IDS = [-1002877068674 , -1003125683775]     # list of channels user must join
INVITE_URLS = ["https://t.me/parishram_2025_1_0" , "https://t.me/+jRyiB6lBAQljNjA1"] 

VERIFY_FILE = "verified.json"
STATS_FILE = "stats.json"
BROADCAST_STATE_FILE = "broadcast_state.json"
SEND_STATE_FILE = "send_state.json"
HELP_STATE_FILE = "help_state.json"

MAX_AGE = 300    # verification token valid seconds (5 minutes)
CODE_LEN = 10
# ---------------------------------------------------

# ---------------- time helpers ----------------
def now_india_str():
    try:
        if HAS_PYTZ:
            tz = pytz.timezone("Asia/Kolkata")
            return datetime.now(tz).strftime("%I:%M %p, %d-%m-%Y")
    except Exception:
        logger.exception("pytz format failed")
    return datetime.utcnow().strftime("%I:%M %p, %d-%m-%Y UTC")

def today_key():
    try:
        if HAS_PYTZ:
            return datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        pass
    return datetime.utcnow().strftime("%Y-%m-%d")

# ---------------- safe json helpers ----------------
def read_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        logger.exception("read_json failed for %s", path)
        return default

def write_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        logger.exception("write_json failed for %s", path)

# ---------------- verified storage ----------------
def load_verified():
    return read_json(VERIFY_FILE, {})

def save_verified(data):
    write_json(VERIFY_FILE, data)

def is_verified(uid):
    data = load_verified()
    return str(uid) in data and data[str(uid)] > time.time()

def set_verified_seconds(uid, sec):
    data = load_verified()
    data[str(uid)] = int(time.time()) + int(sec)
    save_verified(data)

def set_verified_24h(uid):
    set_verified_seconds(uid, 24 * 3600)

# ---------------- stats ----------------
def load_stats():
    stats = read_json(STATS_FILE, {})
    stats.setdefault("lifetime", {})
    stats.setdefault("daily", {})
    lt = stats["lifetime"]
    lt.setdefault("started_users", [])
    lt.setdefault("starts", len(lt.get("started_users", [])))
    lt.setdefault("joined_users", [])
    lt.setdefault("verified_users", [])
    lt.setdefault("video_requests", 0)
    ensure_today(stats)
    write_json(STATS_FILE, stats)
    return stats

def save_stats(data):
    write_json(STATS_FILE, data)

def ensure_today(stats):
    t = today_key()
    stats.setdefault("daily", {})
    if t not in stats["daily"] or not isinstance(stats["daily"][t], dict):
        stats["daily"][t] = {
            "started_users": [],
            "starts": 0,
            "joined_users": [],
            "verified_users": [],
            "video_requests": 0
        }
    d = stats["daily"][t]
    d.setdefault("started_users", [])
    d.setdefault("starts", len(d.get("started_users", [])))
    d.setdefault("joined_users", [])
    d.setdefault("verified_users", [])
    d.setdefault("video_requests", 0)

def stats_add_start(uid):
    uid_s = str(uid)
    stats = load_stats()
    t = today_key()
    ensure_today(stats)
    if uid_s not in stats["lifetime"]["started_users"]:
        stats["lifetime"]["started_users"].append(uid_s)
        stats["lifetime"]["starts"] = len(stats["lifetime"]["started_users"])
    if uid_s not in stats["daily"][t]["started_users"]:
        stats["daily"][t]["started_users"].append(uid_s)
        stats["daily"][t]["starts"] = len(stats["daily"][t]["started_users"])
    save_stats(stats)

def stats_add_join(uid):
    uid_s = str(uid)
    stats = load_stats()
    t = today_key()
    ensure_today(stats)
    if uid_s not in stats["lifetime"]["joined_users"]:
        stats["lifetime"]["joined_users"].append(uid_s)
    if uid_s not in stats["daily"][t]["joined_users"]:
        stats["daily"][t]["joined_users"].append(uid_s)
    save_stats(stats)

def stats_add_verify(uid):
    uid_s = str(uid)
    stats = load_stats()
    t = today_key()
    ensure_today(stats)
    if uid_s not in stats["lifetime"]["verified_users"]:
        stats["lifetime"]["verified_users"].append(uid_s)
    if uid_s not in stats["daily"][t]["verified_users"]:
        stats["daily"][t]["verified_users"].append(uid_s)
    save_stats(stats)

def stats_add_video_request(uid):
    stats = load_stats()
    t = today_key()
    ensure_today(stats)
    stats["lifetime"]["video_requests"] = stats["lifetime"].get("video_requests", 0) + 1
    stats["daily"][t]["video_requests"] = stats["daily"][t].get("video_requests", 0) + 1
    save_stats(stats)

# ---------------- token helpers ----------------
def make_code(ts):
    return hashlib.sha256(f"{ts}-{SECRET_KEY}".encode()).hexdigest()[:CODE_LEN]

def validate_token(payload):
    if not payload.startswith("verify_"):
        return False
    try:
        payload = payload.replace("verify_", "")
        code, ts_s = payload.split("_", 1)
        ts = int(ts_s)
    except Exception:
        return False
    now = int(time.time())
    if now - ts > MAX_AGE or ts - now > 10:
        return False
    return code == make_code(ts)

# ---------------- channel UI ----------------
async def check_channels(bot, uid):
    for cid in CHANNEL_IDS:
        try:
            m = await bot.get_chat_member(cid, uid)
            if getattr(m, "status", "") in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True

def join_keyboard():
    rows = []
    for link in INVITE_URLS:
        rows.append([InlineKeyboardButton("📢 Join Channel", url=link)])
    rows.append([InlineKeyboardButton("I Joined ✔", callback_data="recheck")])
    return InlineKeyboardMarkup(rows)

def verify_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify Now", url=TASK_URL)]])

# ---------------- admin notifications ----------------
async def admin_notify_start(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        txt = (
            f"🟢 New user started the bot\n"
            f"• Name: {user.first_name or 'User'}\n"
            f"• Username: @{user.username or 'N/A'}\n"
            f"• ID: {user.id}\n"
            f"• Time: {now_india_str()}"
        )
        await context.bot.send_message(ADMIN_ID, txt)
    except Exception:
        logger.exception("admin_notify_start failed")

async def admin_notify_verify(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        txt = (
            f"✅ A New User verified for (24h)\n"
            f"• Name: {user.first_name or 'User'}\n"
            f"• Username: @{user.username or 'N/A'}\n"
            f"• ID: {user.id}\n"
            f"• Time: {now_india_str()}"
        )
        await context.bot.send_message(ADMIN_ID, txt)
    except Exception:
        logger.exception("admin_notify_verify failed")

# ---------------- one-shot state helpers ----------------
def set_send_state_once(target_uid):
    write_json(SEND_STATE_FILE, {"active": True, "user_id": int(target_uid)})

def get_send_target_once():
    data = read_json(SEND_STATE_FILE, {"active": False})
    if data.get("active"):
        return data.get("user_id")
    return None

def clear_send_state_once():
    write_json(SEND_STATE_FILE, {"active": False, "user_id": None})

def set_broadcast_wait_once():
    write_json(BROADCAST_STATE_FILE, {"waiting": True})

def is_broadcast_wait_once():
    return read_json(BROADCAST_STATE_FILE, {"waiting": False}).get("waiting", False)

def clear_broadcast_wait_once():
    write_json(BROADCAST_STATE_FILE, {"waiting": False})

def set_help_mode(uid):
    write_json(HELP_STATE_FILE, {"active": True, "user_id": int(uid)})

def is_help_for(uid):
    data = read_json(HELP_STATE_FILE, {"active": False})
    return data.get("active", False) and data.get("user_id") == int(uid)

def clear_help_mode():
    write_json(HELP_STATE_FILE, {"active": False, "user_id": None})

# Clear one-shot states on startup to avoid stale state
def clear_one_shot_states_on_startup():
    try:
        if os.path.exists(SEND_STATE_FILE):
            write_json(SEND_STATE_FILE, {"active": False, "user_id": None})
        if os.path.exists(BROADCAST_STATE_FILE):
            write_json(BROADCAST_STATE_FILE, {"waiting": False})
        if os.path.exists(HELP_STATE_FILE):
            write_json(HELP_STATE_FILE, {"active": False, "user_id": None})
    except Exception:
        logger.exception("clear_one_shot_states_on_startup failed")

# ---------------- Command Handlers ----------------

# /start
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    text = update.message.text or ""
    arg = ""
    if " " in text:
        arg = text.split(" ", 1)[1].strip()

    # stats + admin notify
    try:
        stats_add_start(uid)
        await admin_notify_start(context, user)
    except Exception:
        logger.exception("start stats/notify error")

    # verification payload
    if arg.startswith("verify_"):
        if validate_token(arg):
            set_verified_24h(uid)
            stats_add_verify(uid)
            invite = INVITE_URLS[0] if INVITE_URLS else TASK_URL
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Open Parishram 2025 🔥", url=invite)]])
            instr = (
                "🎉 You're verified for the next *24 hours*!\n\n"
                "Follow these steps to get your video:\n"
                "1️⃣ Open *Parishram 2025*\n"
                "2️⃣ Choose the lecture video you want\n"
                "3️⃣ Tap *Watch Now* (or note the message ID)\n\n"
                "I’ll send your video instantly 😊"
            )
            await update.message.reply_text(instr, reply_markup=kb, parse_mode="Markdown")
            try:
                await admin_notify_verify(context, user)
            except Exception:
                logger.exception("admin notify verify error")
        else:
            await update.message.reply_text("❌ This verification link is invalid. Try again.")
        return

    # lecture request arg /start lec_<id>
    if arg.startswith("lec_"):
        try:
            msgid = int(arg.replace("lec_", ""))
        except:
            return await update.message.reply_text("⚠ Invalid lecture link. Go to Parishram 2025 and follow the steps.")

        if not await check_channels(context.bot, uid):
            return await update.message.reply_text("Please join the required channel first.", reply_markup=join_keyboard())

        stats_add_join(uid)

        if not is_verified(uid):
            return await update.message.reply_text("🔐 Please verify first to unlock this video and many more video till 24 hours", reply_markup=verify_keyboard())

        stats_add_video_request(uid)

        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=BACKUP_CHANNEL, message_id=msgid)
        except Exception:
            logger.exception("copy_message failed")
            return await update.message.reply_text("❌ Unable to fetch this video.Go to Parishram 2025 and follow the steps.")
        return

    # normal start
    if not await check_channels(context.bot, uid):
        return await update.message.reply_text("Hi! Please join the required channel first.", reply_markup=join_keyboard())

    stats_add_join(uid)

    if is_verified(uid):
        invite = INVITE_URLS[0] if INVITE_URLS else TASK_URL
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Open Parishram 2025 🔥", url=invite)]])
        instr = (
            "You're already verified 🎉\n\n"
            "Follow these steps to get your video:\n"
            "1️⃣ Open *Parishram 2025*\n"
            "2️⃣ Choose the lecture video\n"
            "3️⃣ Tap *Watch Now*\n\n"
            "I'll send your lecture instantly 😊"
        )
        return await update.message.reply_text(instr, reply_markup=kb, parse_mode="Markdown")

    await update.message.reply_text(
        "Hey! 👋\nTo unlock *24 hours unlimited video access*, please complete a quick verification.",
        reply_markup=verify_keyboard()
    )

# recheck callback (I Joined)
async def cb_recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()
    if not await check_channels(context.bot, uid):
        return await q.edit_message_text("You are Still not joined. Please join and press I Joined.", reply_markup=join_keyboard())
    stats_add_join(uid)
    await q.edit_message_text("✔ You're joined. Tap Verify Now to continue.", reply_markup=verify_keyboard())
    try:
        await context.bot.send_message(uid, "Tap Verify Now to complete verification.", reply_markup=verify_keyboard())
    except Exception:
        pass

# /help: enable help mode for one-message forwarding
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    set_help_mode(uid)
    await update.message.reply_text("💬 Support mode enabled. Please type your message and it will be forwarded to our admin.")

# /send one-shot: admin uses then sends one message that will be delivered
async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ You are Not authorized.")
    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /send <userid>")
    try:
        target = int(context.args[0])
    except Exception:
        return await update.message.reply_text("Invalid user id.")
    set_send_state_once(target)
    await update.message.reply_text(f"📩 Ready — send one message now and it will be delivered to `{target}` ", parse_mode="Markdown")

# /broadcast one-shot
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ You are Not authorized.")
    set_broadcast_wait_once()
    await update.message.reply_text("📣 Broadcast mode enabled — send one message now to deliver to all started users.")

# admin verify and reject
async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ You are Not authorized.")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /verify <userid> <days>")
    try:
        uid = int(context.args[0]); days = int(context.args[1])
    except:
        return await update.message.reply_text("Invalid input.")
    set_verified_seconds(uid, days * 86400)
    stats_add_verify(uid)
    try:
        await context.bot.send_message(uid, f"🎉 Your verification was approved by admin. Valid for {days} day(s).")
    except Exception:
        logger.exception("failed notify verify user")
        return await update.message.reply_text(f"Verified {uid} but couldn't message them (they may not have started the bot).")
    await update.message.reply_text(f"✅ User {uid} verified for {days} day(s).")

async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ You are Not authorized.")
    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /reject <userid>")
    try:
        uid = int(context.args[0])
    except:
        return await update.message.reply_text("Invalid user id.")
    data = load_verified()
    if str(uid) in data:
        del data[str(uid)]
        save_verified(data)
    try:
        await context.bot.send_message(uid, "⚠ Your verification was removed by admin. Please verify again if you want access.")
    except Exception:
        logger.exception("failed notify reject user")
        return await update.message.reply_text(f"Removed verification for {uid} but couldn't message them.")
    await update.message.reply_text(f"❌ Verification removed for {uid}.")

# /stats
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = load_stats()
    t = today_key()
    ensure_today(stats)
    d = stats["daily"].get(t, {})
    lt = stats["lifetime"]
    msg = (
        f"📊 *Bot Statistics*\n\n"
        f"*Today* ({t})\n"
        f"• Starts: {d.get('starts',0)}\n"
        f"• Joined: {len(d.get('joined_users',[]))}\n"
        f"• Verified: {len(d.get('verified_users',[]))}\n"
        f"• Video Requests: {d.get('video_requests',0)}\n\n"
        f"*Lifetime*\n"
        f"• Starts: {lt.get('starts',0)}\n"
        f"• Joined: {len(lt.get('joined_users',[]))}\n"
        f"• Verified: {len(lt.get('verified_users',[]))}\n"
        f"• Video Requests: {lt.get('video_requests',0)}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------- Master message handler ----------------
# This single handler processes non-command messages and routes them by priority:
# 1) If user is in help mode -> forward message to admin, clear help, reply instructions to user
# 2) If admin has set one-shot send target -> send that message to the target, clear state, notify admin
# 3) If admin has set broadcast wait -> broadcast to all started users, clear state, send admin summary
# 4) Otherwise ignore (or could implement additional flows)
async def master_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only process if there's a message (text/photo/video/document/audio/voice)
    if not update.message:
        return

    sender = update.effective_user
    uid = sender.id

    # 1) HELP MODE for users (user sends one message after /help)
    try:
        if is_help_for(uid):
            # forward message text (or indicate non-text)
            text = update.message.text or "(non-text message)"
            user = update.effective_user
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"📩 *Support Message*\n\nFrom: {user.first_name or 'User'}\nUsername: @{user.username or 'N/A'}\nUser ID: {user.id}\n\nMessage:\n{text}",
                    parse_mode="Markdown"
                )
            except Exception:
                logger.exception("failed to forward help message to admin")
            clear_help_mode()
            # send instructions to user (how to get video)
            invite = INVITE_URLS[0] if INVITE_URLS else TASK_URL
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Open Parishram 2025 🔥", url=invite)]])
            instr = (
                "Thanks — your message was sent to the admin 😊\n\n"
                "Meanwhile, here's how to get your video:\n"
                "1️⃣ Open *Parishram 2025*\n"
                "2️⃣ Choose the lecture you want\n"
                "3️⃣ Tap *Watch Now* or note the message ID\n\n"
                "I'll send your video instantly 😊"
            )
            await update.message.reply_text(instr, reply_markup=kb, parse_mode="Markdown")
            return
    except Exception:
        logger.exception("help flow error")

    # 2) One-shot SEND (admin)
    try:
        target = get_send_target_once()
        if target and uid == ADMIN_ID:
            # Clear state immediately so the one-shot is enforced
            clear_send_state_once()
            try:
                target_id = int(target)
            except:
                await update.message.reply_text("❌ Invalid target id. Aborting.")
                return
            try:
                # send any supported message type
                if update.message.text:
                    await context.bot.send_message(target_id, update.message.text)
                elif update.message.photo:
                    await context.bot.send_photo(target_id, update.message.photo[-1].file_id, caption=update.message.caption or "")
                elif update.message.video:
                    await context.bot.send_video(target_id, update.message.video.file_id, caption=update.message.caption or "")
                elif update.message.document:
                    await context.bot.send_document(target_id, update.message.document.file_id, caption=update.message.caption or "")
                elif update.message.audio:
                    await context.bot.send_audio(target_id, update.message.audio.file_id, caption=update.message.caption or "")
                elif update.message.voice:
                    await context.bot.send_voice(target_id, update.message.voice.file_id, caption=update.message.caption or "")
                else:
                    return await update.message.reply_text("⚠ Unsupported message type for one-shot send.")
                await update.message.reply_text("✅ Message delivered to user. If you want to send again, use /send <userid>.")
            except Exception as e:
                logger.exception("one-shot send failed")
                await update.message.reply_text(f"❌ Failed to deliver to {target_id}: {e}")
            return
    except Exception:
        logger.exception("send one-shot flow error")

    # 3) One-shot BROADCAST (admin)
    try:
        if is_broadcast_wait_once() and uid == ADMIN_ID:
            clear_broadcast_wait_once()
            stats = load_stats()
            users = stats.get("lifetime", {}).get("started_users", [])[:]
            if not users:
                return await update.message.reply_text("⚠ No users to broadcast to.")
            sent = 0
            failed = 0
            failed_list = []
            await update.message.reply_text("📨 Broadcast Started \n You will receive a summary when finished.")
            for uid_s in users:
                try:
                    u = int(uid_s)
                except:
                    failed += 1
                    failed_list.append(str(uid_s))
                    continue
                try:
                    if update.message.text:
                        await context.bot.send_message(u, update.message.text)
                    elif update.message.photo:
                        await context.bot.send_photo(u, update.message.photo[-1].file_id, caption=update.message.caption or "")
                    elif update.message.video:
                        await context.bot.send_video(u, update.message.video.file_id, caption=update.message.caption or "")
                    elif update.message.document:
                        await context.bot.send_document(u, update.message.document.file_id, caption=update.message.caption or "")
                    elif update.message.audio:
                        await context.bot.send_audio(u, update.message.audio.file_id, caption=update.message.caption or "")
                    elif update.message.voice:
                        await context.bot.send_voice(u, update.message.voice.file_id, caption=update.message.caption or "")
                    else:
                        failed += 1
                        failed_list.append(str(u))
                        continue
                    sent += 1
                    # tiny sleep to reduce flood risk (uncomment if you hit limits)
                    # await asyncio.sleep(0.02)
                except Exception:
                    logger.exception("broadcast send failed for %s", uid_s)
                    failed += 1
                    failed_list.append(str(uid_s))
            failed_sample = ", ".join(failed_list[:10])
            more_failed = max(0, len(failed_list) - 10)
            summary = f"📣 Broadcast Completed\n\n✅ Sent: {sent}\n❌ Failed: {failed}\n📊 Total Attempted: {sent + failed}"
            if failed_list:
                summary += f"\n\nSample failed IDs: {failed_sample}"
                if more_failed:
                    summary += f" (+{more_failed} more)"
            try:
                await context.bot.send_message(ADMIN_ID, summary)
            except Exception:
                logger.exception("failed to send broadcast summary to admin")
            return
    except Exception:
        logger.exception("broadcast one-shot flow error")

    # 4) Not a special flow — ignore or you can add other behavior
    return

# ---------------- Startup / main ----------------
def main():
    # clear one-shot states on startup to avoid stale leftover
    clear_one_shot_states_on_startup()

    app = Application.builder().token(BOT_TOKEN).build()

    # user commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_recheck, pattern="recheck"))
    app.add_handler(CommandHandler("help", cmd_help))

    # admin commands
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("verify", cmd_verify))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Master handler: single message handler that routes help/send/broadcast by priority
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, master_message_handler))

    logger.info("BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
