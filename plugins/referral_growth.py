"""Phased referral growth: held rewards, reports, payout alerts and opt-in retention."""
import asyncio
import logging
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database import one, all, execute, execute_rowcount
from utils import admin, live_group_admin
from config import OWNER_ID

log = logging.getLogger(__name__)
HOLD_HOURS = 24

async def hold(chat_id, user_id):
    """Reserve one reward for a new verified join; never alter historical credits."""
    import database
    async with database.pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT invited_by,active,verified FROM members WHERE chat_id=%s AND user_id=%s FOR UPDATE",
                    (chat_id,user_id))
                m=await cur.fetchone()
                if not m or not m[0] or m[0]==user_id or not m[1] or not m[2]:
                    await conn.rollback()
                    return False
                await cur.execute(
                    "SELECT 1 FROM referral_credits WHERE chat_id=%s AND referred_id=%s",
                    (chat_id,user_id))
                if await cur.fetchone():
                    await conn.rollback()
                    return False
                await cur.execute(
                    "INSERT IGNORE INTO referral_pending(chat_id,referred_id,referrer_id,release_at) "
                    "VALUES(%s,%s,%s,UTC_TIMESTAMP()+INTERVAL 24 HOUR)",
                    (chat_id,user_id,m[0]))
                inserted=cur.rowcount==1
            await conn.commit()
            return inserted
        except Exception:
            await conn.rollback()
            raise

async def settle(chat_id, user_id):
    """Exactly-once credit after 24h if member is still active and verified."""
    import database
    async with database.pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT referrer_id,status,release_at FROM referral_pending "
                    "WHERE chat_id=%s AND referred_id=%s FOR UPDATE",(chat_id,user_id))
                p=await cur.fetchone()
                if not p or p[1]!="pending":
                    await conn.rollback()
                    return False
                await cur.execute(
                    "SELECT active,verified,invited_by FROM members WHERE chat_id=%s AND user_id=%s",
                    (chat_id,user_id))
                m=await cur.fetchone()
                if not m or not m[0] or not m[1] or m[2]!=p[0]:
                    await cur.execute(
                        "UPDATE referral_pending SET status='cancelled' WHERE chat_id=%s AND referred_id=%s",
                        (chat_id,user_id))
                    await conn.commit()
                    return False
                await cur.execute(
                    "SELECT release_at<=UTC_TIMESTAMP() FROM referral_pending WHERE chat_id=%s AND referred_id=%s",
                    (chat_id,user_id))
                if not (await cur.fetchone())[0]:
                    await conn.rollback()
                    return False
                await cur.execute(
                    "INSERT IGNORE INTO referral_credits(chat_id,referred_id,referrer_id,amount) VALUES(%s,%s,%s,1)",
                    (chat_id,user_id,p[0]))
                if cur.rowcount==1:
                    await cur.execute(
                        "INSERT INTO referral_wallets(chat_id,user_id,earned,available) VALUES(%s,%s,1,1) "
                        "ON DUPLICATE KEY UPDATE earned=earned+1,available=available+1",
                        (chat_id,p[0]))
                await cur.execute(
                    "UPDATE referral_pending SET status='credited' WHERE chat_id=%s AND referred_id=%s",
                    (chat_id,user_id))
            await conn.commit()
            return True
        except Exception:
            await conn.rollback()
            raise

async def growth_report(chat_id):
    r=await one("SELECT COUNT(*) n FROM referral_credits WHERE chat_id=%s",(chat_id,))
    p=await one("SELECT COUNT(*) n FROM referral_pending WHERE chat_id=%s AND status='pending'",(chat_id,))
    w=await one("SELECT COALESCE(SUM(earned),0) earned,COALESCE(SUM(available),0) available,COALESCE(SUM(reserved),0) reserved,COALESCE(SUM(paid),0) paid FROM referral_wallets WHERE chat_id=%s",(chat_id,))
    d=await one("SELECT COUNT(*) n,COALESCE(SUM(amount),0) total FROM referral_withdrawals WHERE chat_id=%s AND status='pending'",(chat_id,))
    j=await one("SELECT COUNT(*) n FROM events WHERE chat_id=%s AND event_type='join' AND created_at>=UTC_TIMESTAMP()-INTERVAL 1 DAY",(chat_id,))
    a=await one("SELECT COUNT(*) n FROM member_activity WHERE chat_id=%s AND last_seen>=UTC_TIMESTAMP()-INTERVAL 7 DAY",(chat_id,))
    return (f"📊 Referral & Growth Dashboard\\n\\n"
            f"Credited referrals: {r['n']}\\n24h reward holds: {p['n']}\\n"
            f"Total earned: ₹{w['earned']}\\nAvailable liability: ₹{w['available']}\\n"
            f"Reserved for payouts: ₹{w['reserved']}\\nMarked paid: ₹{w['paid']}\\n"
            f"Pending payout requests: {d['n']} (₹{d['total']})\\n"
            f"Observed joins (24h): {j['n']}\\nActive message senders (7d): {a['n']}\\n"
            "Activity counts reflect observed bot events only.")

async def period_leaders(chat_id, period):
    intervals={"daily":"1 DAY","weekly":"7 DAY","monthly":"30 DAY","all":"100 YEAR"}
    interval=intervals[period]
    rows=await all(
        "SELECT referrer_id,COUNT(*) n FROM referral_credits "
        f"WHERE chat_id=%s AND created_at>=UTC_TIMESTAMP()-INTERVAL {interval} "
        "GROUP BY referrer_id ORDER BY n DESC,referrer_id LIMIT 10",(chat_id,))
    return f"🏆 {period.title()} credited referral leaderboard\\n"+(
        "\\n".join(f"{i}. {r['referrer_id']} — {r['n']} referrals" for i,r in enumerate(rows,1))
        if rows else "No credited referrals in this period.")

async def loop(app):
    while True:
        try:
            due=await all(
                "SELECT chat_id,referred_id FROM referral_pending WHERE status='pending' "
                "AND release_at<=UTC_TIMESTAMP() ORDER BY release_at LIMIT 100")
            for r in due:
                await settle(r["chat_id"],r["referred_id"])
            # One notification per pending request. Owner receives no payment details beyond ID, group and amount.
            pending=await all(
                "SELECT w.id,w.chat_id,w.user_id,w.amount FROM referral_withdrawals w "
                "LEFT JOIN referral_alerts a ON a.withdrawal_id=w.id "
                "WHERE w.status='pending' AND a.withdrawal_id IS NULL ORDER BY w.id LIMIT 20")
            for r in pending:
                try:
                    await app.send_message(
                        OWNER_ID,
                        f"💸 Withdrawal request #{r['id']}\\nGroup: {r['chat_id']}\\n"
                        f"User: {r['user_id']}\\nAmount: ₹{r['amount']}\\n"
                        "Pay externally first, then mark paid or reject.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Review payment",callback_data=f"grow:payment:{r['id']}")]]))
                    await execute("INSERT IGNORE INTO referral_alerts(withdrawal_id) VALUES(%s)",(r["id"],))
                except Exception:
                    log.exception("Could not notify owner about withdrawal %s",r["id"])
            # Retention reminders are group-only, opt-in and at most once per seven days.
            groups=await all(
                "SELECT chat_id FROM retention_settings WHERE enabled=1 AND "
                "(last_sent_at IS NULL OR last_sent_at<UTC_TIMESTAMP()-INTERVAL 7 DAY) LIMIT 10")
            for g in groups:
                claimed=await execute_rowcount(
                    "UPDATE retention_settings SET last_sent_at=UTC_TIMESTAMP() "
                    "WHERE chat_id=%s AND enabled=1 AND "
                    "(last_sent_at IS NULL OR last_sent_at<UTC_TIMESTAMP()-INTERVAL 7 DAY)",
                    (g["chat_id"],))
                if claimed:
                    try:
                        await app.send_message(
                            g["chat_id"],
                            "👋 Weekly community check-in! Share what you are watching or "
                            "recommend a series to other members. 🎬")
                    except Exception:
                        log.exception("Retention reminder failed for %s",g["chat_id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Growth scheduler failed")
        await asyncio.sleep(60)

def register(app):
    @app.on_message(filters.command("walletdetails") & filters.group)
    async def details(client,message):
        if not message.from_user:return
        from plugins.referral_wallet import wallet, wallet_text
        chat,user=message.chat.id,message.from_user.id
        pending=await one(
            "SELECT COUNT(*) n FROM referral_pending WHERE chat_id=%s AND referrer_id=%s AND status='pending'",
            (chat,user))
        history=await all(
            "SELECT id,amount,status,created_at FROM referral_withdrawals "
            "WHERE chat_id=%s AND user_id=%s ORDER BY id DESC LIMIT 5",(chat,user))
        lines="\\n".join(f"#{r['id']} ₹{r['amount']} — {r['status']}" for r in history) or "No withdrawals"
        await message.reply_text(
            wallet_text(await wallet(chat,user))+f"\\nPending 24h referrals: {pending['n']}\\n"
            f"Recent withdrawals:\\n{lines}")

    @app.on_message(filters.command("refleaders") & filters.group)
    async def leaders(client,message):
        args=(message.text or "").split()
        period=args[1].lower() if len(args)>1 else "weekly"
        if period not in ("daily","weekly","monthly","all"):
            return await message.reply_text("Usage: /refleaders daily|weekly|monthly|all")
        await message.reply_text(await period_leaders(message.chat.id,period))

    @app.on_message(filters.command("growthdashboard") & filters.group)
    async def dashboard(client,message):
        if not await admin(client,message):return
        await message.reply_text(await growth_report(message.chat.id))

    @app.on_message(filters.command("retention") & filters.group)
    async def retention(client,message):
        if not await admin(client,message):return
        args=(message.text or "").split()
        if len(args)!=2 or args[1].lower() not in ("on","off"):
            return await message.reply_text("Usage: /retention on|off (weekly group reminder)")
        enabled=args[1].lower()=="on"
        await execute(
            "INSERT INTO retention_settings(chat_id,enabled) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)",
            (message.chat.id,enabled))
        await message.reply_text("Weekly group reminder "+("enabled." if enabled else "disabled."))

    @app.on_callback_query(filters.regex(r"^grow:payment:\\d+$"))
    async def payment_info(client,query):
        if not query.from_user or query.from_user.id!=OWNER_ID:
            return await query.answer("Owner only.",show_alert=True)
        request_id=int(query.data.rsplit(":",1)[1])
        row=await one(
            "SELECT id,chat_id,user_id,amount,status FROM referral_withdrawals WHERE id=%s",
            (request_id,))
        if not row:return await query.answer("Request not found.",show_alert=True)
        await query.message.reply_text(
            f"💸 Request #{request_id}\\nGroup: {row['chat_id']}\\nUser: {row['user_id']}\\n"
            f"Amount: ₹{row['amount']}\\nStatus: {row['status']}\\n\\n"
            "For security, mark paid only after transferring money externally. "
            "Use /payapprove ID or /payreject ID in the corresponding group.")
        await query.answer()
