"""Admin-only member management and observed activity tracking."""
import logging
from datetime import datetime, timezone
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database import one, all, execute
from utils import admin, target, live_group_admin

logger = logging.getLogger(__name__)

def keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Overview", callback_data=f"mm:overview:{chat_id}"),
         InlineKeyboardButton("🆕 New Members", callback_data=f"mm:new:{chat_id}")],
        [InlineKeyboardButton("🔥 Most Active", callback_data=f"mm:top:{chat_id}"),
         InlineKeyboardButton("💤 Inactive", callback_data=f"mm:inactive:{chat_id}")],
        [InlineKeyboardButton("⚠️ Warnings", callback_data=f"mm:warnings:{chat_id}"),
         InlineKeyboardButton("📜 History", callback_data=f"mm:history:{chat_id}")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"gm:group:{chat_id}")]
    ])

async def report(chat_id, section):
    if section == "overview":
        r = await one("SELECT COUNT(*) tracked, COALESCE(SUM(active=1),0) active, COALESCE(SUM(active=0),0) departed, COALESCE(SUM(active=1 AND verified=0),0) pending FROM members WHERE chat_id=%s", (chat_id,))
        a = await one("SELECT COUNT(*) n FROM member_activity WHERE chat_id=%s AND last_seen>=UTC_TIMESTAMP()-INTERVAL 1 DAY", (chat_id,))
        j = await one("SELECT COUNT(*) n FROM events WHERE chat_id=%s AND event_type='join' AND created_at>=UTC_TIMESTAMP()-INTERVAL 1 DAY", (chat_id,))
        return (f"👥 Member Management (tracked)\n\nTotal observed: {r['tracked']}\nActive tracked: {r['active']}\nLeft: {r['departed']}\nUnverified: {r['pending']}\nJoins in 24h: {j['n']}\nActive senders in 24h: {a['n']}\n\nCounts are based on bot-observed events, not a complete Telegram roster.")
    if section == "new":
        rows = await all("SELECT user_id,first_name,joined_at FROM members WHERE chat_id=%s AND active=1 ORDER BY joined_at DESC LIMIT 15", (chat_id,))
        return "🆕 Recently tracked joins\n" + ("\n".join(f"{r['user_id']} — {(r['first_name'] or 'Unknown')[:25]} ({r['joined_at']})" for r in rows) or "None recorded")
    if section == "top":
        rows = await all("SELECT user_id,message_count,last_seen FROM member_activity WHERE chat_id=%s ORDER BY message_count DESC LIMIT 15", (chat_id,))
        return "🔥 Most active (since tracking began)\n" + ("\n".join(f"{r['user_id']}: {r['message_count']} messages" for r in rows) or "No activity recorded")
    if section == "inactive":
        rows = await all("SELECT m.user_id,m.first_name,a.last_seen FROM members m LEFT JOIN member_activity a ON a.chat_id=m.chat_id AND a.user_id=m.user_id WHERE m.chat_id=%s AND m.active=1 AND (a.last_seen IS NULL OR a.last_seen<UTC_TIMESTAMP()-INTERVAL 7 DAY) ORDER BY a.last_seen ASC LIMIT 15", (chat_id,))
        return "💤 No observed messages in 7 days\n" + ("\n".join(f"{r['user_id']} — {(r['first_name'] or 'Unknown')[:25]} (last: {r['last_seen'] or 'never observed'})" for r in rows) or "No matches") + "\n\nNot proof of Telegram inactivity."
    if section == "warnings":
        rows = await all("SELECT user_id,count FROM warnings WHERE chat_id=%s AND count>0 ORDER BY count DESC LIMIT 15", (chat_id,))
        return "⚠️ Outstanding warnings\n" + ("\n".join(f"{r['user_id']}: {r['count']}" for r in rows) or "No warnings")
    if section == "history":
        rows = await all("SELECT user_id,event_type,created_at FROM events WHERE chat_id=%s ORDER BY id DESC LIMIT 15", (chat_id,))
        return "📜 Recent membership/moderation events\n" + ("\n".join(f"{r['created_at']} {r['event_type']} — {r['user_id']}" for r in rows) or "No events")
    return "Unknown section"

def register(app):
    # Track ordinary text/media messages, including administrators; no message content is stored.
    @app.on_message(filters.group & ~filters.service, group=20)
    async def observe(client, message):
        user = message.from_user
        if not user or user.is_bot:
            return
        try:
            await execute(
                "INSERT INTO member_activity(chat_id,user_id,message_count,last_seen) VALUES(%s,%s,1,UTC_TIMESTAMP()) "
                "ON DUPLICATE KEY UPDATE message_count=message_count+1,last_seen=UTC_TIMESTAMP()",
                (message.chat.id,user.id)
            )
        except Exception:
            logger.exception("Activity tracking failed chat=%s", message.chat.id)

    @app.on_message(filters.command("memberpanel") & filters.group)
    async def panel(client, message):
        if not await admin(client,message):
            return
        await message.reply_text(await report(message.chat.id,"overview"),reply_markup=keyboard(message.chat.id))

    @app.on_message(filters.command("membersearch") & filters.group)
    async def search(client,message):
        if not await admin(client,message):
            return
        query=(message.text or "").partition(" ")[2].strip().lstrip("@")
        if len(query)<2:
            return await message.reply_text("Usage: /membersearch USERNAME_OR_NAME (minimum 2 characters)")
        query=query[:80].replace("%",r"\%").replace("_",r"\_")
        rows=await all(
            "SELECT user_id,first_name,username,active FROM members WHERE chat_id=%s AND (username LIKE %s OR first_name LIKE %s) ORDER BY active DESC,joined_at DESC LIMIT 15",
            (message.chat.id,"%"+query+"%","%"+query+"%")
        )
        await message.reply_text("🔎 Tracked member search\n"+("\n".join(f"{r['user_id']} — {(r['first_name'] or 'Unknown')[:30]} (@{r['username'] or '-'}) — {'active' if r['active'] else 'left'}" for r in rows) or "No matching tracked members."))

    @app.on_message(filters.command("memberactivity") & filters.group)
    async def activity(client,message):
        if not await admin(client,message):
            return
        uid=await target(message)
        if uid is None:
            return await message.reply_text("Reply to a member or use /memberactivity USER_ID")
        r=await one("SELECT message_count,last_seen FROM member_activity WHERE chat_id=%s AND user_id=%s",(message.chat.id,uid))
        await message.reply_text(f"📈 Activity for {uid}\nMessages observed: {(r or {}).get('message_count',0)}\nLast observed: {(r or {}).get('last_seen') or 'Never'} (UTC)")

    @app.on_message(filters.command("inactive") & filters.group)
    async def inactive(client,message):
        if not await admin(client,message):
            return
        await message.reply_text(await report(message.chat.id,"inactive"))

    @app.on_message(filters.command("topmembers") & filters.group)
    async def top(client,message):
        if not await admin(client,message):
            return
        await message.reply_text(await report(message.chat.id,"top"))

    @app.on_message(filters.command("memberhistory") & filters.group)
    async def history(client,message):
        if not await admin(client,message):
            return
        await message.reply_text(await report(message.chat.id,"history"))

    @app.on_callback_query(filters.regex(r"^mm:(overview|new|top|inactive|warnings|history):-?\d+$"))
    async def callback(client,query):
        if not query.from_user or not query.message or query.message.chat.type!=enums.ChatType.PRIVATE:
            return await query.answer("Use the private admin dashboard.",show_alert=True)
        _,section,raw=query.data.split(":")
        chat_id=int(raw)
        if not await live_group_admin(client,chat_id,query.from_user.id):
            return await query.answer("Group administrator access required.",show_alert=True)
        try:
            await query.message.edit_text(await report(chat_id,section),reply_markup=keyboard(chat_id))
            await query.answer()
        except Exception:
            logger.exception("Member dashboard failed chat=%s",chat_id)
            await query.answer("Could not load report.",show_alert=True)
