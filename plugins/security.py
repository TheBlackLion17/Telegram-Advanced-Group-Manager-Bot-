"""Optional anti-spam protections; disabled by default for existing groups."""
import logging
import re
import time
from collections import defaultdict, deque
from pyrogram import filters, enums
from pyrogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from database import one, execute
from utils import admin, live_group_admin, bot_can, log, until

logger = logging.getLogger(__name__)
recent = defaultdict(deque)
joins = defaultdict(deque)
raid_until = {}
URL = re.compile(r"(?:https?://|www\\.|t\\.me/)", re.I)
MAX_KEYS = 20000

async def settings(chat):
    await execute("INSERT IGNORE INTO security_settings(chat_id) VALUES(%s)", (chat,))
    return await one("SELECT * FROM security_settings WHERE chat_id=%s", (chat,))

def panel(chat, cfg):
    rows = []
    for field, title in (("duplicate_enabled","🔁 Repeated Messages"),
                         ("newcomer_links_enabled","🔗 Newcomer Links"),
                         ("raid_enabled","🚨 Raid Detection")):
        rows.append([InlineKeyboardButton(
            ("✅ " if cfg[field] else "❌ ") + title,
            callback_data=f"sec:toggle:{chat}:{field}")])
    rows.append([InlineKeyboardButton("⬅️ Group", callback_data=f"gm:group:{chat}")])
    return InlineKeyboardMarkup(rows)

async def remove(client, message, reason):
    try:
        await message.delete()
        await log(client, message.chat.id, message.from_user.id, "security", reason)
    except Exception:
        logger.exception("Security deletion failed chat=%s", message.chat.id)

def register(app):
    @app.on_message(filters.command("security") & filters.group)
    async def security(client, message):
        if not await admin(client, message):
            return
        if len((message.text or "").split()) != 1:
            return
        cfg = await settings(message.chat.id)
        await message.reply_text(
            "🛡 Advanced Security\nProtections are opt-in.\n"
            "Repeated messages: 3 identical posts within 30 seconds.\n"
            "Newcomer links: blocks URLs during the first 10 minutes after a tracked join.\n"
            "Raid detection: alerts admins after 8 joins in 60 seconds; no automatic bans.\n"
            "Use /security duplicate|newcomer|raid on|off to configure."
        )
        await message.reply_text("🛡 Security controls", reply_markup=panel(message.chat.id,cfg))

    @app.on_message(filters.command("security") & filters.group, group=1)
    async def configure(client, message):
        # This is deliberately separate from the default handler group.
        if not await admin(client,message):
            return
        parts=(message.text or "").split()
        if len(parts)!=3:
            return
        fields={"duplicate":"duplicate_enabled","newcomer":"newcomer_links_enabled","raid":"raid_enabled"}
        field=fields.get(parts[1].lower())
        value=parts[2].lower()
        if not field or value not in ("on","off"):
            return await message.reply_text("Usage: /security duplicate|newcomer|raid on|off")
        await settings(message.chat.id)
        await execute(f"UPDATE security_settings SET {field}=%s WHERE chat_id=%s",(value=="on",message.chat.id))
        await message.reply_text(f"🛡 {parts[1]} protection {value}")

    @app.on_message(filters.group & (filters.text | filters.caption), group=11)
    async def check(client, message):
        user=message.from_user
        if not user or user.is_bot or await admin(client,message):
            return
        content=(message.text or message.caption or "").strip()
        if not content or content.startswith("/"):
            return
        cfg=await settings(message.chat.id)
        chat=message.chat.id
        if cfg["newcomer_links_enabled"] and URL.search(content):
            record=await one("SELECT joined_at FROM members WHERE chat_id=%s AND user_id=%s AND active=1",(chat,user.id))
            if record and record["joined_at"]:
                from datetime import datetime,timezone
                joined=record["joined_at"]
                if joined.tzinfo is None:
                    joined=joined.replace(tzinfo=timezone.utc)
                if 0 <= (datetime.now(timezone.utc)-joined).total_seconds() < 600:
                    return await remove(client,message,"newcomer_link")
        if cfg["duplicate_enabled"] and len(content)>=8:
            now=time.monotonic()
            key=(chat,user.id)
            queue=recent[key]
            normalized=" ".join(content.casefold().split())[:500]
            queue.append((now,normalized))
            while queue and now-queue[0][0]>30:
                queue.popleft()
            if sum(1 for _,value in queue if value==normalized)>=3:
                queue.clear()
                return await remove(client,message,"repeated_message")
            if len(recent)>MAX_KEYS:
                recent.clear()

    @app.on_message(filters.new_chat_members & filters.group, group=12)
    async def raid_watch(client,message):
        cfg=await settings(message.chat.id)
        if not cfg["raid_enabled"]:
            return
        chat=message.chat.id
        now=time.monotonic()
        queue=joins[chat]
        queue.extend([now for user in (message.new_chat_members or []) if not user.is_bot])
        while queue and now-queue[0]>60:
            queue.popleft()
        if len(queue)>=8 and now>=raid_until.get(chat,0):
            raid_until[chat]=now+300
            logger.warning("Possible raid chat=%s joins=%s",chat,len(queue))
            try:
                await client.send_message(chat,"🚨 Possible join raid: at least 8 members joined within 60 seconds. Admins, please review recent joins. No users were automatically banned.")
            except Exception:
                logger.exception("Raid alert failed chat=%s",chat)

    @app.on_callback_query(filters.regex(r"^sec:(?:panel:-?\d+|toggle:-?\d+:(?:duplicate_enabled|newcomer_links_enabled|raid_enabled))$"))
    async def callback(client,query):
        if not query.from_user or not query.message or query.message.chat.type!=enums.ChatType.PRIVATE:
            return await query.answer("Use the private dashboard.",show_alert=True)
        parts=query.data.split(":")
        chat=int(parts[2])
        if not await live_group_admin(client,chat,query.from_user.id):
            return await query.answer("Administrator access required.",show_alert=True)
        await settings(chat)
        if parts[1]=="toggle":
            field=parts[3]
            await execute(f"UPDATE security_settings SET {field}=NOT {field} WHERE chat_id=%s",(chat,))
        cfg=await settings(chat)
        await query.message.edit_text("🛡 Advanced Security\nEnable protections for this group:",reply_markup=panel(chat,cfg))
        await query.answer()
