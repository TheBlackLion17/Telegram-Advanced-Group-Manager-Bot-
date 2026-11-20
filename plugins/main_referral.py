"""One owner-configured default referral group for private bot users."""
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database import one, execute, ensure_group
from config import OWNER_ID
from plugins.referral_wallet import wallet, wallet_text, withdraw
from utils import live_group_admin, telegram_api
import logging
import re

logger = logging.getLogger(__name__)

async def main_group():
    return await one("SELECT chat_id,title,join_url FROM referral_main_group WHERE slot=1")

async def referral_link(client,chat,user):
    row=await one("SELECT invite_link FROM invite_links WHERE chat_id=%s AND creator_id=%s ORDER BY invite_link LIMIT 1",(chat,user))
    if row:
        return row["invite_link"]
    link=await client.create_chat_invite_link(chat,name=f"ref-{user}",creates_join_request=False)
    await execute("INSERT INTO invite_links(chat_id,invite_link,creator_id) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE creator_id=VALUES(creator_id)",
                  (chat,link.invite_link,user))
    return link.invite_link

def menu(row):
    buttons=[]
    if row["join_url"]:
        buttons.append([InlineKeyboardButton("📢 Join Main Group",url=row["join_url"])])
    buttons.extend([
        [InlineKeyboardButton("🔗 My Referral Link",callback_data="mainref:link")],
        [InlineKeyboardButton("💰 My Balance",callback_data="mainref:balance"),
         InlineKeyboardButton("💸 Withdraw",callback_data="mainref:withdraw")],
        [InlineKeyboardButton("🛡 Admin Dashboard",callback_data="gm:groups")]
    ])
    return InlineKeyboardMarkup(buttons)

def register(app):
    @app.on_message(filters.command("setmaingroup") & filters.group)
    async def set_main(client,message):
        if not message.from_user or message.from_user.id!=OWNER_ID:
            return
        if not await live_group_admin(client,message.chat.id,message.from_user.id):
            return await message.reply_text("You must be a group administrator.")
        # Bot must be able to create per-member invite links.
        try:
            me=await client.get_me()
            member=await client.get_chat_member(message.chat.id,me.id)
            if not getattr(getattr(member,"privileges",None),"can_invite_users",False):
                return await message.reply_text("Give the bot Invite Users admin permission first.")
        except Exception:
            return await message.reply_text("Could not verify the bot's group permissions.")
        args=(message.text or "").split(maxsplit=1)
        join_url=args[1].strip() if len(args)==2 else None
        if join_url and not (join_url.startswith("https://t.me/") or join_url.startswith("https://telegram.me/")):
            return await message.reply_text("Usage: /setmaingroup https://t.me/yourgroup (optional join URL)")
        await ensure_group(message.chat.id,message.chat.title)
        await execute(
            "INSERT INTO referral_main_group(slot,chat_id,title,join_url) VALUES(1,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE chat_id=VALUES(chat_id),title=VALUES(title),join_url=VALUES(join_url)",
            (message.chat.id,message.chat.title,join_url))
        await message.reply_text("✅ Default referral group saved. New private /start messages will use this group.")

    @app.on_message(filters.command("setmaingroup") & filters.private)
    async def set_main_private(client,message):
        if not message.from_user or message.from_user.id!=OWNER_ID:
            return await message.reply_text("Only the configured bot owner can set the main referral group.")
        args=(message.text or "").split(maxsplit=1)
        if len(args)!=2:
            return await message.reply_text("Usage: /setmaingroup https://t.me/Movies_Hub_OG")
        url=args[1].strip().rstrip("/")
        match=re.fullmatch(r"https://(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{4,31})",url,re.I)
        if not match:
            return await message.reply_text("Send a public Telegram group URL, for example: /setmaingroup https://t.me/Movies_Hub_OG")
        username="@"+match.group(1)
        try:
            chat=await telegram_api("getChat",chat_id=username)
            if chat.get("type") not in ("group","supergroup"):
                return await message.reply_text("That link does not point to a Telegram group.")
            chat_id=int(chat["id"])
            owner=await telegram_api("getChatMember",chat_id=chat_id,user_id=OWNER_ID)
            if owner.get("status") not in ("administrator","creator"):
                return await message.reply_text("You must be an administrator of this group.")
            me=await client.get_me()
            bot=await telegram_api("getChatMember",chat_id=chat_id,user_id=me.id)
            if bot.get("status")!="administrator" or not bot.get("can_invite_users",False):
                return await message.reply_text("Make the bot a group administrator with Invite Users permission.")
            title=chat.get("title") or username
            await ensure_group(chat_id,title)
            await execute(
                "INSERT INTO referral_main_group(slot,chat_id,title,join_url) VALUES(1,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE chat_id=VALUES(chat_id),title=VALUES(title),join_url=VALUES(join_url)",
                (chat_id,title,url))
            await message.reply_text(
                f"✅ Default referral group saved: {title}\n"
                f"Group ID: {chat_id}\nSend /start to open your referral menu.")
        except Exception:
            logger.exception("Unable to configure main referral group from private chat")
            await message.reply_text("Unable to verify the group. Confirm the group URL and bot permissions, then try again.")

    @app.on_message(filters.command("clearmaingroup") & filters.private)
    async def clear_main(client,message):
        if message.from_user and message.from_user.id==OWNER_ID:
            await execute("DELETE FROM referral_main_group WHERE slot=1")
            await message.reply_text("Default referral group cleared.")

    @app.on_message(filters.command("start") & filters.private,group=1)
    async def start(client,message):
        row=await main_group()
        if not row:
            return
        await message.reply_text(
            f"👋 Welcome to the Referral Program!\n\n"
            f"📢 Main group: {row['title']}\n"
            "🎁 Earn ₹1 for each verified referral.\n"
            "💰 Minimum withdrawal: ₹100.\n"
            "💸 Payments require manual admin approval.\n\n"
            "Use the buttons below to begin.",
            reply_markup=menu(row))

    @app.on_message(filters.command(["referral","balance","withdraw"]) & filters.private,group=1)
    async def private_wallet(client,message):
        row=await main_group()
        if not row:
            return await message.reply_text("Main referral group is not configured yet.")
        user=message.from_user
        if not user:
            return
        cmd=message.command[0].lower()
        if cmd=="balance":
            return await message.reply_text(wallet_text(await wallet(row["chat_id"],user.id)))
        if cmd=="referral":
            try:
                link=await referral_link(client,row["chat_id"],user.id)
                return await message.reply_text(f"🔗 Your referral link:\n{link}\n\n₹1 per verified referral.")
            except Exception:
                return await message.reply_text("Unable to create an invite link. Check bot admin permissions.")
        args=(message.text or "").split()
        if len(args)!=2 or not args[1].isdigit():
            return await message.reply_text("Usage: /withdraw 100")
        amount=int(args[1])
        if not 100<=amount<=100000:
            return await message.reply_text("Withdrawal must be between ₹100 and ₹100,000.")
        request_id=await withdraw(row["chat_id"],user.id,amount)
        if request_id is None:
            return await message.reply_text("Insufficient available balance.")
        await message.reply_text(f"✅ Withdrawal request #{request_id} for ₹{amount} submitted. Payment is pending manual approval.")

    @app.on_callback_query(filters.regex(r"^mainref:(link|balance|withdraw)$"))
    async def callback(client,query):
        if not query.from_user or not query.message:
            return
        row=await main_group()
        if not row:
            return await query.answer("Referral group not configured.",show_alert=True)
        action=query.data.split(":")[1]
        if action=="link":
            try:
                link=await referral_link(client,row["chat_id"],query.from_user.id)
                await query.message.reply_text(f"🔗 Your referral link:\n{link}\n\nEarn ₹1 per verified referral.")
            except Exception:
                await query.answer("Unable to create referral link. Check bot permissions.",show_alert=True)
                return
        elif action=="balance":
            await query.message.reply_text(wallet_text(await wallet(row["chat_id"],query.from_user.id)))
        else:
            await query.message.reply_text("💸 To request a withdrawal, send /withdraw 100 (or a larger amount).")
        await query.answer()
