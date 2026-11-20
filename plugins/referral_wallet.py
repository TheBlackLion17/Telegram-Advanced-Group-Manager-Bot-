"""Referral wallet: ₹1 per unique verified invite, ₹100 minimum withdrawal.

Credits only joins with a Telegram-provided, bot-created invite link. No historical
backfill or speculative attribution. All monetary operations use row locks.
"""
import logging
import re
from pyrogram import filters, enums
from database import one, all, execute, pool
from utils import live_group_admin

log = logging.getLogger(__name__)
MIN_WITHDRAW = 100
RATE = 1

async def credit(chat_id, user_id):
    """New verified referrals enter a 24-hour hold before crediting."""
    from plugins.referral_growth import hold
    return await hold(chat_id,user_id)

async def attributed_join(chat_id, user, inviter):
    """Save the first legitimate attribution; never replace an existing inviter."""
    if not inviter or inviter==user.id or user.is_bot:
        return
    await execute(
        "INSERT INTO members(chat_id,user_id,first_name,username,active,invited_by,verified) "
        "VALUES(%s,%s,%s,%s,1,%s,0) ON DUPLICATE KEY UPDATE "
        "invited_by=IF(invited_by IS NULL AND active=1,VALUES(invited_by),invited_by)",
        (chat_id,user.id,user.first_name,user.username,inviter))

async def wallet(chat_id,user_id):
    row=await one("SELECT earned,available,reserved,paid FROM referral_wallets WHERE chat_id=%s AND user_id=%s",
                  (chat_id,user_id))
    return row or dict(earned=0,available=0,reserved=0,paid=0)

def wallet_text(row):
    return (f"💰 Referral Wallet\nReward: ₹1 per verified referral\n"
            f"Total earned: ₹{row['earned']}\nAvailable: ₹{row['available']}\n"
            f"Pending withdrawals: ₹{row['reserved']}\nPaid: ₹{row['paid']}\n"
            f"Minimum withdrawal: ₹{MIN_WITHDRAW}\n"
            "Payouts require manual administrator approval.")

async def withdraw(chat,user,amount):
    import database
    async with database.pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT available FROM referral_wallets WHERE chat_id=%s AND user_id=%s FOR UPDATE",
                    (chat,user))
                row=await cur.fetchone()
                if not row or row[0]<amount:
                    await conn.rollback()
                    return None
                await cur.execute(
                    "UPDATE referral_wallets SET available=available-%s,reserved=reserved+%s "
                    "WHERE chat_id=%s AND user_id=%s",(amount,amount,chat,user))
                await cur.execute(
                    "INSERT INTO referral_withdrawals(chat_id,user_id,amount,status) VALUES(%s,%s,%s,'pending')",
                    (chat,user,amount))
                request_id=cur.lastrowid
            await conn.commit()
            return request_id
        except Exception:
            await conn.rollback()
            raise

async def decide(request_id, action, admin_id):
    """Approval records actual external payment; rejection returns reserved funds."""
    import database
    async with database.pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT chat_id,user_id,amount,status FROM referral_withdrawals WHERE id=%s FOR UPDATE",
                    (request_id,))
                r=await cur.fetchone()
                if not r or r[3]!="pending":
                    await conn.rollback()
                    return None
                chat,user,amount,_=r
                await cur.execute(
                    "SELECT reserved FROM referral_wallets WHERE chat_id=%s AND user_id=%s FOR UPDATE",
                    (chat,user))
                w=await cur.fetchone()
                if not w or w[0]<amount:
                    await conn.rollback()
                    return None
                if action=="paid":
                    await cur.execute(
                        "UPDATE referral_wallets SET reserved=reserved-%s,paid=paid+%s "
                        "WHERE chat_id=%s AND user_id=%s",(amount,amount,chat,user))
                else:
                    await cur.execute(
                        "UPDATE referral_wallets SET reserved=reserved-%s,available=available+%s "
                        "WHERE chat_id=%s AND user_id=%s",(amount,amount,chat,user))
                await cur.execute(
                    "UPDATE referral_withdrawals SET status=%s,reviewed_by=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s",
                    (action,admin_id,request_id))
            await conn.commit()
            return chat,user,amount
        except Exception:
            await conn.rollback()
            raise

def register(app):
    @app.on_chat_member_updated(group=5)
    async def track_join(client, update):
        try:
            old=update.old_chat_member
            new=update.new_chat_member
            if not new or not new.user or new.user.is_bot:
                return
            active={enums.ChatMemberStatus.MEMBER,enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,enums.ChatMemberStatus.RESTRICTED}
            if old and old.status in active:
                return
            if new.status not in active:
                return
            invite=getattr(update,"invite_link",None)
            link=getattr(invite,"invite_link",None)
            if not link:
                return
            ref=await one("SELECT creator_id FROM invite_links WHERE chat_id=%s AND invite_link=%s",
                          (update.chat.id,link))
            if not ref or ref["creator_id"]==new.user.id:
                return
            # For joins before the ordinary service handler, preserve attribution.
            existing=await one("SELECT active,verified FROM members WHERE chat_id=%s AND user_id=%s",
                               (update.chat.id,new.user.id))
            if not existing:
                await execute(
                    "INSERT IGNORE INTO members(chat_id,user_id,first_name,username,active,invited_by,verified) "
                    "VALUES(%s,%s,%s,%s,1,%s,0)",
                    (update.chat.id,new.user.id,new.user.first_name,new.user.username,ref["creator_id"]))
            else:
                await attributed_join(update.chat.id,new.user,ref["creator_id"])
            # Verification handler credits when verification is enabled.
            cfg=await one("SELECT verify_enabled FROM `groups` WHERE chat_id=%s",(update.chat.id,))
            if cfg and not cfg["verify_enabled"]:
                await execute("UPDATE members SET verified=1 WHERE chat_id=%s AND user_id=%s",
                              (update.chat.id,new.user.id))
                await credit(update.chat.id,new.user.id)
        except Exception:
            log.exception("Referral join attribution failed")

    @app.on_message(filters.command("balance") & filters.group)
    async def balance(client,message):
        if not message.from_user:
            return
        await message.reply_text(wallet_text(await wallet(message.chat.id,message.from_user.id)))

    @app.on_message(filters.command("withdraw") & filters.group)
    async def request(client,message):
        if not message.from_user:
            return
        args=(message.text or "").split()
        if len(args)!=2 or not args[1].isdigit():
            return await message.reply_text("Usage: /withdraw 100 (minimum ₹100).")
        amount=int(args[1])
        if amount<MIN_WITHDRAW or amount>100000:
            return await message.reply_text("Withdrawal must be between ₹100 and ₹100,000.")
        request_id=await withdraw(message.chat.id,message.from_user.id,amount)
        if request_id is None:
            return await message.reply_text("Insufficient available balance.")
        await message.reply_text(
            f"✅ Withdrawal request #{request_id} for ₹{amount} submitted. "
            "Funds are reserved until an admin marks the payment as paid or rejects it. "
            "No money has been transferred.")

    @app.on_message(filters.command("withdrawals") & filters.group)
    async def withdrawals(client,message):
        if not message.from_user:
            return
        from utils import admin
        if not await admin(client,message):
            return
        rows=await all(
            "SELECT id,user_id,amount,created_at FROM referral_withdrawals "
            "WHERE chat_id=%s AND status='pending' ORDER BY id LIMIT 20",
            (message.chat.id,))
        body="\n".join(f"#{r['id']} — user {r['user_id']} — ₹{r['amount']} ({r['created_at']})" for r in rows)
        await message.reply_text("💸 Pending withdrawal requests\n"+(body or "None")+
            "\n\nAfter making a real payment: /payapprove REQUEST_ID\nTo reject: /payreject REQUEST_ID")

    @app.on_message(filters.command(["payapprove","payreject"]) & filters.group)
    async def review(client,message):
        if not message.from_user or not await live_group_admin(client,message.chat.id,message.from_user.id):
            return
        args=(message.text or "").split()
        if len(args)!=2 or not args[1].isdigit():
            return await message.reply_text("Usage: /payapprove REQUEST_ID or /payreject REQUEST_ID")
        request_id=int(args[1])
        row=await one("SELECT chat_id FROM referral_withdrawals WHERE id=%s",(request_id,))
        if not row or row["chat_id"]!=message.chat.id:
            return await message.reply_text("Request not found in this group.")
        action="paid" if message.command[0].lower()=="payapprove" else "rejected"
        result=await decide(request_id,action,message.from_user.id)
        if not result:
            return await message.reply_text("Request already handled or unavailable.")
        await message.reply_text(
            f"✅ Request #{request_id} marked {action}. ₹{result[2]} for user {result[1]}."+
            (" Ensure you already sent the money externally." if action=="paid" else " Reserved balance returned."))

    @app.on_message(filters.command("wallethelp") & filters.group)
    async def help_wallet(client,message):
        await message.reply_text(
            "💰 Referral rewards: ₹1 per verified, uniquely attributed join.\n"
            "/referral — create your invite link\n/balance — view your wallet\n"
            "/withdraw 100 — request manual payout\n"
            "Admins: /withdrawals, /payapprove ID, /payreject ID\n"
            "No automatic payments. Historical joins are not credited.")
