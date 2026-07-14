import asyncio
import os
import re
import subprocess
import time
import uuid
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image
from pyrogram import filters
from pyrogram.enums import MessageEntityType, ParseMode
from pyrogram.types import Message

from Elevenyts import app
from Elevenyts.misc import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AFK_CMDS = ("afk", "gafk", "unafk", "ungafk", "afklist")
DIVIDER = "━━━━━━━━━━━━━━━━━━"
TMP_DIR = "cache"
os.makedirs(TMP_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _mention(user) -> str:
    """HTML mention anchor. Safe against missing first_name."""
    name = (getattr(user, "first_name", None) or "User").strip() or "User"
    # Escape minimal HTML in the visible name
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def _format_since_time(ts: float) -> str:
    try:
        return time.strftime("%d %b %Y, %H:%M", time.localtime(ts))
    except Exception:
        return "unknown"


def _parse_command_and_reason(message: Message) -> Tuple[str, str]:
    """Return (command, reason). Reason may be empty."""
    text = (message.text or message.caption or "").strip()
    if not text:
        return "", ""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@", 1)[0].lower()
    reason = parts[1].strip() if len(parts) > 1 else ""
    return cmd, reason


def _get_trigger(message: Message) -> str:
    """First word (command token) without slash / bot suffix."""
    text = (message.text or message.caption or "").strip()
    if not text:
        return ""
    first = text.split(maxsplit=1)[0]
    return first.lstrip("/").split("@", 1)[0].lower()


# ---------------------------------------------------------------------------
# Sticker → JPEG conversion (PIL primary, ffmpeg fallback)
# ---------------------------------------------------------------------------

async def _sticker_to_jpeg(client, sticker) -> Optional[str]:
    """
    Download a sticker, convert to JPEG, upload as a photo, return the resulting
    photo file_id. Cleans up temp files. Returns None on failure.
    """
    src_path = os.path.join(TMP_DIR, f"stk_{uuid.uuid4().hex}")
    jpg_path = src_path + ".jpg"
    downloaded = None
    try:
        downloaded = await client.download_media(sticker.file_id, file_name=src_path)
        if not downloaded or not os.path.exists(downloaded):
            return None

        ok = False
        # --- PIL path (works for .webp static stickers) ---
        try:
            with Image.open(downloaded) as im:
                im.load()
                if im.mode != "RGB":
                    im = im.convert("RGB")
                im.save(jpg_path, "JPEG", quality=90)
                ok = True
        except Exception:
            ok = False

        # --- ffmpeg fallback (animated .webm / .tgs won't open in PIL) ---
        if not ok:
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg", "-y", "-i", downloaded,
                        "-vframes", "1", "-vf", "scale=512:-1",
                        jpg_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                ok = (proc.returncode == 0 and os.path.exists(jpg_path))
            except Exception:
                ok = False

        if not ok or not os.path.exists(jpg_path):
            return None

        # Upload as photo to obtain a reusable photo file_id
        try:
            sent = await client.send_photo(
                chat_id="me",
                photo=jpg_path,
                disable_notification=True,
            )
            file_id = None
            if sent and sent.photo:
                file_id = sent.photo.file_id
            try:
                await sent.delete()
            except Exception:
                pass
            return file_id
        except Exception:
            return None
    finally:
        for p in (downloaded, jpg_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Media extraction from an AFK-setting message
# ---------------------------------------------------------------------------

async def _extract_afk_media(client, message: Message) -> Optional[str]:
    """
    Look at the message and its reply for a supported media.
    Returns a file_id (photo/animation/video), or a converted photo file_id
    when a sticker is provided. None if no media.
    """
    candidates = [message]
    if message.reply_to_message:
        candidates.append(message.reply_to_message)

    for m in candidates:
        if not m:
            continue
        if m.photo:
            return m.photo.file_id
        if m.animation:
            return m.animation.file_id
        if m.video:
            return m.video.file_id
        if m.sticker:
            converted = await _sticker_to_jpeg(client, m.sticker)
            if converted:
                return converted
    return None


# ---------------------------------------------------------------------------
# Atomic claim helpers (prevent duplicate notifications)
# ---------------------------------------------------------------------------

async def _claim_afk_notification(chat_id: int, user_id: int, ttl: int = 5) -> bool:
    """Atomic set-once claim for AFK mention notifications."""
    key = f"_afk_notif_{chat_id}_{user_id}"
    now = time.time()
    try:
        res = await db.cache.find_one_and_update(
            {"_id": key, "$or": [{"exp": {"$lte": now}}, {"exp": {"$exists": False}}]},
            {"$set": {"_id": key, "exp": now + ttl}},
            upsert=True,
            return_document=False,
        )
        # If nothing matched (exp still in future), the upsert would raise a
        # duplicate key handled by Motor; treat "no prior doc" as claim success.
        return res is None or res.get("exp", 0) <= now
    except Exception:
        # Duplicate key = someone already holds the claim
        return False


async def _claim_welcome_back(chat_id: int, user_id: int, ttl: int = 5) -> bool:
    """Atomic set-once claim for Welcome Back messages."""
    key = f"_wb_notif_{chat_id}_{user_id}"
    now = time.time()
    try:
        res = await db.cache.find_one_and_update(
            {"_id": key, "$or": [{"exp": {"$lte": now}}, {"exp": {"$exists": False}}]},
            {"$set": {"_id": key, "exp": now + ttl}},
            upsert=True,
            return_document=False,
        )
        return res is None or res.get("exp", 0) <= now
    except Exception:
        return False


# ---------------------------------------------------------------------------
# UI Cards
# ---------------------------------------------------------------------------

def _afk_card(name_html: str, duration: str, since: str, reason: str, is_global: bool) -> str:
    label = " [ɢʟᴏʙᴀʟ]" if is_global else ""
    reason = reason.strip() or "None"
    return (
        f"{DIVIDER}\n"
        f"<b>💤 AFK MODE{label}</b>\n\n"
        f"<b>👤 User:</b>\n{name_html}\n\n"
        f"<b>⏱ Away:</b>\n{duration}\n\n"
        f"<b>📅 Since:</b>\n{since}\n\n"
        f"<b>📝 Reason:</b>\n{reason}\n"
        f"{DIVIDER}"
    )


def _welcome_back_card(name_html: str, duration: str, reason: str) -> str:
    reason = reason.strip() or "None"
    return (
        f"{DIVIDER}\n"
        f"<b>✨ Welcome Back</b>\n\n"
        f"<b>👤</b> {name_html}\n\n"
        f"<b>⏱ AFK Time</b>\n{duration}\n\n"
        f"<b>📝 Reason</b>\n{reason}\n"
        f"{DIVIDER}"
    )


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------

async def _send_afk_reply(message: Message, text: str, media_file_id: Optional[str]):
    try:
        if media_file_id:
            try:
                return await message.reply_photo(
                    photo=media_file_id,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    quote=True,
                )
            except Exception:
                pass
        return await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            quote=True,
        )
    except Exception:
        return None


async def _send_welcome_back(client, chat_id: int, reply_to: Optional[int],
                             text: str, media_file_id: Optional[str]):
    try:
        if media_file_id:
            try:
                return await client.send_photo(
                    chat_id=chat_id,
                    photo=media_file_id,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=reply_to,
                )
            except Exception:
                pass
        return await client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_to_message_id=reply_to,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fetch AFK record (local + global merged view)
# ---------------------------------------------------------------------------

async def _fetch_afk(chat_id: int, user_id: int):
    """Return (record, is_global_only). Local takes precedence for display."""
    local = await db.get_afk(chat_id, user_id)
    if local:
        return local, False
    g = await db.get_gafk(user_id)
    if g:
        return g, True
    return None, False


# ---------------------------------------------------------------------------
# Welcome-back flow (used by watcher + /unafk + /ungafk)
# ---------------------------------------------------------------------------

async def _run_welcome_back(client, message: Message, user, *, force_local=False,
                            force_global=False):
    """
    Removes AFK entries (based on force flags OR any that exist), then sends
    a single Welcome Back message using stored media.
    """
    chat_id = message.chat.id
    user_id = user.id

    local = await db.get_afk(chat_id, user_id)
    g = await db.get_gafk(user_id)

    remove_local = bool(local) and (force_local or not force_global or True)
    remove_global = bool(g) and (force_global or not force_local or True)

    # When explicit force flag is set, honor it strictly:
    if force_local and not force_global:
        remove_global = False
    if force_global and not force_local:
        remove_local = False

    picked = local or g
    if not picked:
        return False

    if not await _claim_welcome_back(chat_id, user_id, ttl=5):
        # Still remove records silently to avoid stale state
        if remove_local and local:
            try:
                await db.remove_afk(chat_id, user_id)
            except Exception:
                pass
        if remove_global and g:
            try:
                await db.remove_gafk(user_id)
            except Exception:
                pass
        return False

    started = float(picked.get("time") or picked.get("since") or time.time())
    reason = picked.get("reason") or ""
    media_file_id = picked.get("media_file_id")

    duration = _format_duration(time.time() - started)

    if remove_local and local:
        try:
            await db.remove_afk(chat_id, user_id)
        except Exception:
            pass
    if remove_global and g:
        try:
            await db.remove_gafk(user_id)
        except Exception:
            pass

    text = _welcome_back_card(_mention(user), duration, reason)
    await _send_welcome_back(
        client,
        chat_id=chat_id,
        reply_to=message.id,
        text=text,
        media_file_id=media_file_id,
    )
    return True


# ---------------------------------------------------------------------------
# /afk  and  /gafk
# ---------------------------------------------------------------------------

@app.on_message(
    filters.command(["afk", "gafk"], prefixes=["/", "!", "."])
    & filters.group
    & ~app.bl_users,
    group=9,
)
async def set_afk_handler(client, message: Message):
    user = message.from_user
    if not user:
        return

    cmd, reason = _parse_command_and_reason(message)
    is_global = (cmd == "gafk")

    media_file_id = await _extract_afk_media(client, message)

    payload = {
        "reason": reason,
        "time": time.time(),
        "media_file_id": media_file_id,
    }

    try:
        if is_global:
            await db.set_gafk(user.id, payload)
        else:
            await db.set_afk(message.chat.id, user.id, payload)
    except Exception:
        return

    # Claim so the very next mention (if any) doesn't fire redundantly right after set
    await _claim_afk_notification(message.chat.id, user.id, ttl=2)

    duration = _format_duration(0)
    since = _format_since_time(payload["time"])
    text = _afk_card(_mention(user), duration, since, reason, is_global)

    await _send_afk_reply(message, text, media_file_id)

    try:
        await message.delete()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# /unafk  and  /ungafk
# ---------------------------------------------------------------------------

@app.on_message(
    filters.command(["unafk", "ungafk"], prefixes=["/", "!", "."])
    & filters.group
    & ~app.bl_users,
    group=9,
)
async def unafk_handler(client, message: Message):
    user = message.from_user
    if not user:
        return
    cmd = _get_trigger(message)
    if cmd == "ungafk":
        await _run_welcome_back(client, message, user, force_global=True)
    else:
        await _run_welcome_back(client, message, user, force_local=True)

    try:
        await message.delete()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# /afklist
# ---------------------------------------------------------------------------

@app.on_message(
    filters.command("afklist", prefixes=["/", "!", "."])
    & filters.group
    & ~app.bl_users,
    group=9,
)
async def afk_list(client, message: Message):
    chat_id = message.chat.id
    try:
        rows = await db.get_all_afk(chat_id)
    except Exception:
        rows = []

    if not rows:
        try:
            await message.reply_text(
                f"{DIVIDER}\n<b>💤 AFK LIST</b>\n\nNo one is AFK here.\n{DIVIDER}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    lines = [f"{DIVIDER}", "<b>💤 AFK LIST</b>", ""]
    for row in rows:
        uid = row.get("user_id") or row.get("_id")
        if not uid:
            continue
        try:
            user = await app.get_users(uid)
        except Exception:
            continue
        started = float(row.get("time") or row.get("since") or time.time())
        duration = _format_duration(time.time() - started)
        reason = (row.get("reason") or "None").strip() or "None"
        lines.append(f"• {_mention(user)} — <i>{duration}</i> — {reason}")
    lines.append(DIVIDER)

    try:
        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Mention target extraction
# ---------------------------------------------------------------------------

async def _collect_mention_targets(client, message: Message) -> list:
    """Return a deduplicated list of target user objects mentioned in this
    message (reply target + entities in text and caption). Skips the sender."""
    seen_ids: set = set()
    targets = []

    sender_id = message.from_user.id if message.from_user else 0

    def _add(u):
        if not u:
            return
        if u.id == sender_id:
            return
        if getattr(u, "is_bot", False):
            return
        if u.id in seen_ids:
            return
        seen_ids.add(u.id)
        targets.append(u)

    # 1) Reply target
    if message.reply_to_message and message.reply_to_message.from_user:
        _add(message.reply_to_message.from_user)

    # 2) Entities in text/caption
    text = message.text or message.caption or ""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for ent in entities:
        try:
            if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
                _add(ent.user)
            elif ent.type == MessageEntityType.MENTION:
                username = text[ent.offset: ent.offset + ent.length].lstrip("@").strip()
                if not username:
                    continue
                try:
                    u = await app.get_users(username)
                    _add(u)
                except Exception:
                    continue
        except Exception:
            continue

    return targets


# ---------------------------------------------------------------------------
# AFK watcher (group=10)
# ---------------------------------------------------------------------------

_AFK_CMD_RE = re.compile(r"^[!./](afk|gafk|unafk|ungafk|afklist)(@\w+)?(\s|$)", re.IGNORECASE)


def _is_afk_command(message: Message) -> bool:
    text = (message.text or message.caption or "").strip()
    if not text:
        return False
    return bool(_AFK_CMD_RE.match(text))


@app.on_message(filters.group & ~app.bl_users, group=10)
async def afk_watcher(client, message: Message):
    # Ignore service / non-user messages
    if not message.from_user:
        return

    sender = message.from_user

    # 1) If the SENDER is AFK and this is a normal (non-AFK-command) message,
    #    trigger Welcome Back and stop.
    if not _is_afk_command(message):
        local = await db.get_afk(message.chat.id, sender.id)
        g = await db.get_gafk(sender.id)
        if local or g:
            await _run_welcome_back(client, message, sender)
            return

    # 2) Otherwise, look for AFK targets referenced in this message.
    if _is_afk_command(message):
        # Setting/removing AFK — do not fire mention notifications
        return

    try:
        targets = await _collect_mention_targets(client, message)
    except Exception:
        targets = []

    if not targets:
        return

    # Per-message dedup so reply+mention of same user doesn't double-fire
    notified: set = set()

    for target in targets:
        if target.id in notified:
            continue

        record, is_global = await _fetch_afk(message.chat.id, target.id)
        if not record:
            continue

        # Atomic claim per (chat, user) with short TTL — prevents dupes across
        # local + global simultaneous entries.
        if not await _claim_afk_notification(message.chat.id, target.id, ttl=5):
            notified.add(target.id)
            continue

        started = float(record.get("time") or record.get("since") or time.time())
        reason = record.get("reason") or ""
        media_file_id = record.get("media_file_id")

        duration = _format_duration(time.time() - started)
        since = _format_since_time(started)

        text = _afk_card(_mention(target), duration, since, reason, is_global)
        await _send_afk_reply(message, text, media_file_id)

        notified.add(target.id)
