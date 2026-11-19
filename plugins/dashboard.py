"""Private-chat dashboard for group administrators."""
import logging
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database import all, one, execute
from utils import live_group_admin

log = logging.getLogger(__name__)
SETTINGS = {
    "welcome_enabled": "Welcome",
    "antiflood_enabled": "Anti-flood",
    "links_blocked": "Block links",
    "verify_enabled": "Verification",
}

def keyboard(rows):
    return InlineKeyboardMarkup(rows)

def home():
    return keyboard([
        [InlineKeyboardButton("👥 My Groups", callback_data="gm:groups")],
        [InlineKeyboardButton("🛡 Moderation", callback_data="gm:moderation"),
         InlineKeyboardButton("🎯 Quizzes", callback_data="gm:info:quizzes")],
        [InlineKeyboardButton("🔗 Referrals", callback_data="gm:info:referrals"),
         InlineKeyboardButton("📊 Analytics", callback_data="gm:info:analytics")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="gm:info:help")],
    ])

async def is_group_admin(client, chat_id, user_id):
    return await live_group_admin(client, chat_id, user_id)

async def group_list(client, user_id):
    # Show previously verified groups even if Telegram's peer cache is cold
    # after a restart. Management actions still require live admin checks.
    rows = await all(
        "SELECT g.chat_id,g.title, "
        "CASE WHEN a.user_id IS NULL THEN 0 ELSE 1 END AS remembered "
        "FROM `groups` g LEFT JOIN group_admin_links a "
        "ON a.chat_id=g.chat_id AND a.user_id=%s "
        "ORDER BY g.title LIMIT 100",
        (user_id,),
    )
    buttons = []
    for row in rows:
        verified = await is_group_admin(client, row["chat_id"], user_id)
        if verified:
            await execute(
                "INSERT INTO group_admin_links(chat_id,user_id) VALUES(%s,%s) "
                "ON DUPLICATE KEY UPDATE verified_at=CURRENT_TIMESTAMP",
                (row["chat_id"], user_id),
            )
        if verified or row["remembered"]:
            label = (row["title"] or str(row["chat_id"]))[:42]
            if not verified:
                label += " ⚠️"
            buttons.append([InlineKeyboardButton(
                label, callback_data=f"gm:group:{row['chat_id']}"
            )])
    buttons.append([InlineKeyboardButton("⬅️ Home", callback_data="gm:home")])
    return buttons

async def group_menu(client, chat_id, user_id):
    if not await is_group_admin(client, chat_id, user_id):
        return None
    return keyboard([
        [InlineKeyboardButton("⚙️ Settings", callback_data=f"gm:settings:{chat_id}"),
         InlineKeyboardButton("📊 Analytics", callback_data=f"gm:stats:{chat_id}")],
        [InlineKeyboardButton("🛡 Moderation Panel", callback_data=f"gm:mod:{chat_id}")],
        [InlineKeyboardButton("🔗 Referrals", callback_data=f"gm:refs:{chat_id}")],
        [InlineKeyboardButton("⬅️ My Groups", callback_data="gm:groups")],
    ])

async def settings_menu(chat_id):
    cfg = await one("SELECT * FROM `groups` WHERE chat_id=%s", (chat_id,))
    if not cfg:
        return None
    rows = [[InlineKeyboardButton(
        f"{'✅' if cfg[field] else '❌'} {label}",
        callback_data=f"gm:toggle:{chat_id}:{field}"
    )] for field, label in SETTINGS.items()]
    rows.append([InlineKeyboardButton("⬅️ Group", callback_data=f"gm:group:{chat_id}")])
    return keyboard(rows)


async def moderation_menu(chat_id):
    cfg = await one("SELECT * FROM `groups` WHERE chat_id=%s", (chat_id,))
    if not cfg:
        return None
    controls = [
        ("antiflood_enabled", "🛡 Anti-Flood"),
        ("links_blocked", "🔗 Block Links"),
        ("welcome_enabled", "👋 Welcome"),
        ("verify_enabled", "🔐 Verification"),
    ]
    rows = [[InlineKeyboardButton(
        f"{'✅' if cfg[field] else '❌'} {label}",
        callback_data=f"gm:modtoggle:{chat_id}:{field}"
    )] for field, label in controls]
    rows.extend([
        [InlineKeyboardButton("⚠️ Warnings", callback_data=f"gm:modhelp:{chat_id}:warnings"),
         InlineKeyboardButton("🚫 Banned Words", callback_data=f"gm:modhelp:{chat_id}:words")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"gm:group:{chat_id}")],
    ])
    return keyboard(rows)

MOD_HELP = {
    "warnings": (
        "⚠️ Warning Management\n\n"
        "Reply to a member's message in the group:\n"
        "/warn — Add warning\n"
        "/warnings — Check warnings\n"
        "/unwarn — Clear warnings\n\n"
        "At 3 warnings, the bot applies a temporary restriction."
    ),
    "words": (
        "🚫 Banned Words\n\n"
        "Use these commands in your group:\n"
        "/badword add WORD\n"
        "/badword del WORD\n\n"
        "The bot checks messages against the blocked-word list."
    ),
}

INFO = {
    "moderation": "🛡 Moderation\nIn your group: /warn, /ban, /mute, /unmute, /purge, /badword add|del WORD. Admin permissions are required.",
    "quizzes": "🎯 Quizzes\nIn your group: /quiz to start a quiz. Admins: /quizadd Question | A | B | C | D | 1-4.",
    "referrals": "🔗 Referrals\nIn your group: /referral to generate a tracked invite link, /leaderboard for rankings.",
    "analytics": "📊 Analytics\nChoose My Groups → your group → Analytics for tracked activity from the last 24 hours.",
    "help": "ℹ️ Help\nUse My Groups to configure groups where you are an administrator. Add this bot as group admin with required permissions. Group commands remain available in the group.",
}

def register(app):
    @app.on_message(filters.command("dashboard") & filters.private)
    async def dashboard(client, message):
        await message.reply_text("🛡 Group Manager Dashboard\nChoose a section:", reply_markup=home())

    @app.on_callback_query(filters.regex(r"^gm:"))
    async def dashboard_callback(client, query):
        if not query.message or query.message.chat.type != enums.ChatType.PRIVATE:
            return await query.answer("Open the bot in private chat.", show_alert=True)
        data = query.data.split(":")
        try:
            action = data[1]
            user_id = query.from_user.id
            if action == "home" and len(data) == 2:
                text, markup = "🛡 Group Manager Dashboard\nChoose a section:", home()
            elif action == "moderation" and len(data) == 2:
                buttons = await group_list(client, user_id)
                text = "🛡 Select a group to manage moderation:"
                markup = keyboard(buttons)
            elif action == "mod" and len(data) == 3:
                chat_id = int(data[2])
                if not await is_group_admin(client, chat_id, user_id):
                    return await query.answer("Administrator access required.", show_alert=True)
                markup = await moderation_menu(chat_id)
                text = "🛡 Moderation Panel\nTap to enable or disable protection."
                if markup is None:
                    return await query.answer("Group not registered.", show_alert=True)
            elif action == "modtoggle" and len(data) == 4:
                chat_id = int(data[2])
                field = data[3]
                if not await is_group_admin(client, chat_id, user_id):
                    return await query.answer("Administrator access required.", show_alert=True)
                if field not in SETTINGS:
                    return await query.answer("Invalid setting.", show_alert=True)
                await execute(
                    f"UPDATE `groups` SET {field}=NOT {field} WHERE chat_id=%s",
                    (chat_id,)
                )
                markup = await moderation_menu(chat_id)
                text = "🛡 Moderation Panel\nSettings updated."
            elif action == "modhelp" and len(data) == 4:
                chat_id = int(data[2])
                topic = data[3]
                if not await is_group_admin(client, chat_id, user_id):
                    return await query.answer("Administrator access required.", show_alert=True)
                if topic not in MOD_HELP:
                    return await query.answer("Unknown option.")
                text = MOD_HELP[topic]
                markup = keyboard([[
                    InlineKeyboardButton("⬅️ Moderation", callback_data=f"gm:mod:{chat_id}")
                ]])
            elif action == "groups" and len(data) == 2:
                buttons = await group_list(client, user_id)
                text, markup = ("👥 Your admin groups:" if len(buttons) > 1
                                else "No managed groups are visible.\n\n"
                                     "1. Send /id inside the group as an admin.\n"
                                     "2. Send /connect CHAT_ID here in private.\n"
                                     "3. Open My Groups again.\n\n"
                                     "Existing saved groups are not deleted when this list is empty."), keyboard(buttons)
            elif action == "info" and len(data) == 3 and data[2] in INFO:
                text, markup = INFO[data[2]], keyboard([[InlineKeyboardButton("⬅️ Home", callback_data="gm:home")]])
            elif action in ("group", "settings", "stats", "refs", "toggle") and len(data) in (3, 4):
                chat_id = int(data[2])
                if not await is_group_admin(client, chat_id, user_id):
                    return await query.answer("You must be an administrator of this group.", show_alert=True)
                if action == "toggle":
                    if len(data) != 4 or data[3] not in SETTINGS:
                        return await query.answer("Invalid setting.", show_alert=True)
                    field = data[3]  # Strict whitelist prevents SQL identifier injection.
                    await execute(f"UPDATE `groups` SET {field}=NOT {field} WHERE chat_id=%s", (chat_id,))
                    action = "settings"
                if action == "group":
                    markup = await group_menu(client, chat_id, user_id)
                    cfg = await one("SELECT title FROM `groups` WHERE chat_id=%s", (chat_id,))
                    text = f"👥 {(cfg or {}).get('title') or chat_id}\nSelect a section:"
                elif action == "settings":
                    markup = await settings_menu(chat_id)
                    text = "⚙️ Group Settings\nTap a setting to toggle it."
                elif action == "stats":
                    stats = await all("SELECT event_type,COUNT(*) AS n FROM events WHERE chat_id=%s AND created_at>=UTC_TIMESTAMP()-INTERVAL 1 DAY GROUP BY event_type", (chat_id,))
                    members = await one("SELECT COUNT(*) AS n FROM members WHERE chat_id=%s AND active=1", (chat_id,))
                    text = "📊 Last 24 hours (tracked)\n" + ("\n".join(f"{r['event_type']}: {r['n']}" for r in stats) or "No events recorded") + f"\nActive tracked members: {(members or {}).get('n', 0)}"
                    markup = keyboard([[InlineKeyboardButton("⬅️ Group", callback_data=f"gm:group:{chat_id}")]])
                else:
                    refs = await all("SELECT invited_by,COUNT(*) AS n FROM members WHERE chat_id=%s AND active=1 AND invited_by IS NOT NULL GROUP BY invited_by ORDER BY n DESC LIMIT 10", (chat_id,))
                    text = "🔗 Referral leaderboard\n" + ("\n".join(f"{i}. {r['invited_by']}: {r['n']}" for i,r in enumerate(refs,1)) or "No tracked referrals yet")
                    markup = keyboard([[InlineKeyboardButton("⬅️ Group", callback_data=f"gm:group:{chat_id}")]])
                if markup is None:
                    return await query.answer("Group is not registered. Send /settings in the group.", show_alert=True)
            else:
                return await query.answer("Unknown dashboard action.", show_alert=True)
            await query.message.edit_text(text, reply_markup=markup)
            await query.answer()
        except Exception:
            log.exception("Dashboard callback failed")
            await query.answer("Could not load dashboard. Try again.", show_alert=True)
