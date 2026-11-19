"""Admin-only member insights and group activity reports.

Uses existing MySQL tables; no schema migration is required.
"""
from pyrogram import filters
from database import one, all
from utils import admin, target


def register(app):
    @app.on_message(filters.command("member") & filters.group)
    async def member_profile(client, message):
        if not await admin(client, message):
            return
        user_id = await target(message)
        if user_id is None:
            return await message.reply_text(
                "Reply to a member or use /member USER_ID."
            )
        chat_id = message.chat.id
        record = await one(
            "SELECT user_id,first_name,username,joined_at,active,invited_by,verified "
            "FROM members WHERE chat_id=%s AND user_id=%s",
            (chat_id, user_id),
        )
        warnings = await one(
            "SELECT count FROM warnings WHERE chat_id=%s AND user_id=%s",
            (chat_id, user_id),
        )
        events = await all(
            "SELECT event_type,COUNT(*) AS total FROM events "
            "WHERE chat_id=%s AND user_id=%s "
            "GROUP BY event_type ORDER BY total DESC LIMIT 8",
            (chat_id, user_id),
        )
        if not record:
            return await message.reply_text(
                "Member not found in tracked records. "
                "Tracking starts when the bot observes a join."
            )
        activity = ", ".join(
            f"{row['event_type']}: {row['total']}" for row in events
        ) or "No recorded events"
        await message.reply_text(
            "👤 Member Profile\n"
            f"ID: {record['user_id']}\n"
            f"Name: {record['first_name'] or 'Unknown'}\n"
            f"Username: @{record['username']}" + ("\n" if record["username"] else "\n")
            + f"Status: {'Active' if record['active'] else 'Left'}\n"
            f"Verified: {'Yes' if record['verified'] else 'No'}\n"
            f"Joined (database): {record['joined_at']}\n"
            f"Invited by: {record['invited_by'] or 'Not tracked'}\n"
            f"Warnings: {(warnings or {}).get('count', 0)}\n"
            f"Recorded events: {activity}"
        )

    @app.on_message(filters.command("members") & filters.group)
    async def members_summary(client, message):
        if not await admin(client, message):
            return
        chat_id = message.chat.id
        counts = await one(
            "SELECT COUNT(*) AS tracked, "
            "COALESCE(SUM(active=1),0) AS active, "
            "COALESCE(SUM(active=0),0) AS left_count, "
            "COALESCE(SUM(active=1 AND verified=0),0) AS unverified "
            "FROM members WHERE chat_id=%s",
            (chat_id,),
        )
        await message.reply_text(
            "👥 Tracked Members\n"
            f"Total tracked: {counts['tracked']}\n"
            f"Active tracked: {counts['active']}\n"
            f"Left: {counts['left_count']}\n"
            f"Awaiting verification: {counts['unverified']}\n\n"
            "Note: This is bot-observed membership, not Telegram's full member count."
        )

    @app.on_message(filters.command("growth") & filters.group)
    async def growth(client, message):
        if not await admin(client, message):
            return
        rows = await all(
            "SELECT DATE(created_at) AS day, "
            "SUM(event_type='join') AS joins, "
            "SUM(event_type='leave') AS leaves "
            "FROM events WHERE chat_id=%s "
            "AND created_at>=UTC_TIMESTAMP()-INTERVAL 7 DAY "
            "AND event_type IN ('join','leave') "
            "GROUP BY DATE(created_at) ORDER BY day",
            (message.chat.id,),
        )
        if not rows:
            return await message.reply_text(
                "📈 No recorded joins or leaves in the last 7 days."
            )
        lines = ["📈 Member Growth (last 7 days, UTC)"]
        for row in rows:
            joins, leaves = int(row["joins"] or 0), int(row["leaves"] or 0)
            lines.append(f"{row['day']}: +{joins} / -{leaves} (net {joins-leaves:+d})")
        await message.reply_text("\n".join(lines))

    @app.on_message(filters.command("modstats") & filters.group)
    async def moderation_stats(client, message):
        if not await admin(client, message):
            return
        rows = await all(
            "SELECT event_type,COUNT(*) AS total FROM events "
            "WHERE chat_id=%s "
            "AND created_at>=UTC_TIMESTAMP()-INTERVAL 7 DAY "
            "AND event_type IN ('warn','unwarn','ban','unban','kick','mute','unmute') "
            "GROUP BY event_type ORDER BY total DESC",
            (message.chat.id,),
        )
        body = "\n".join(
            f"{row['event_type']}: {row['total']}" for row in rows
        ) or "No recorded moderation actions."
        await message.reply_text(
            "🛡 Moderation Activity (last 7 days, UTC)\n" + body
        )
