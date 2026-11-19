from pyrogram import filters
from plugins.dashboard import home
from database import ensure_group,one,execute,all
from utils import admin,log,live_group_admin,telegram_api
def register(app):
 @app.on_message(filters.group, group=-1)
 async def remember_group(c,m):
  # Re-register groups observed after a deployment, even without /settings.
  if m.chat and m.chat.id:
   await ensure_group(m.chat.id,m.chat.title or str(m.chat.id))

 @app.on_chat_member_updated()
 async def remember_bot_membership(c,update):
  # Register immediately when the bot is added or promoted in a group.
  try:
   chat=update.chat
   member=update.new_chat_member
   if not chat or not member or not member.user:
    return
   me=await c.get_me()
   if member.user.id!=me.id:
    return
   from pyrogram import enums
   if member.status in (enums.ChatMemberStatus.MEMBER,
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.OWNER):
    await ensure_group(chat.id,chat.title or str(chat.id))
  except Exception:
   import logging
   logging.exception("Failed to register group from membership update")

 @app.on_message(filters.command(['start','help']) & filters.private)
 async def start(c,m):
  await m.reply_text('🛡 Advanced Group Manager\nAdd me to your group as admin with Delete, Restrict, Invite and Pin permissions.\n\nGroup commands: /help /rules /settings /stats /warn /ban /mute /referral /quiz\n\nUse the buttons below or /dashboard.',reply_markup=home())
 @app.on_message(filters.command('help') & filters.group)
 async def help_group(c,m):
  await m.reply_text('🛡 Commands\nAdmin: /settings /setrules /setwelcome /welcome on|off /antiflood on|off /links on|off /verify on|off /badword add|del WORD /warn /unwarn /ban /unban /kick /mute /unmute /purge /schedule MINUTES text /quizadd question | option1 | option2 | option3 | option4 | correct(1-4)\nMembers: /rules /stats /referral /leaderboard /quiz')
 @app.on_message(filters.command('settings') & filters.private)
 async def private_settings(c,m):
  await m.reply_text(
   "⚙️ Group settings must be configured inside your Telegram group.\n"
   "Send /settings in the group, or use /connect CHAT_ID here "
   "to recover a missing group. Send /id in the group to get its ID."
  )

 @app.on_message(filters.command('id') & filters.group)
 async def chat_id(c,m):
  if not await admin(c,m):return
  await ensure_group(m.chat.id,m.chat.title or str(m.chat.id))
  await execute(
   "INSERT INTO group_admin_links(chat_id,user_id) VALUES(%s,%s) "
   "ON DUPLICATE KEY UPDATE verified_at=CURRENT_TIMESTAMP",
   (m.chat.id,m.from_user.id)
  )
  await m.reply_text(
   f"Group ID: \u0060{m.chat.id}\u0060\n"
   "In the bot's private chat, send /connect followed by this ID."
  )

 @app.on_message(filters.command('connect') & filters.private)
 async def connect(c,m):
  parts=(m.text or "").split()
  if len(parts)!=2 or not parts[1].lstrip('-').isdigit():
   return await m.reply_text("Usage: /connect -1001234567890\nUse /id inside your group to get the ID.")
  chat_id=int(parts[1])
  if chat_id>=0:
   return await m.reply_text("Please provide a Telegram group or supergroup ID.")
  try:
   chat=await telegram_api("getChat",chat_id=chat_id)
   if chat.get("type") not in ("group","supergroup"):
    return await m.reply_text("That ID does not belong to a group.")
   me=await c.get_me()
   bot_member=await telegram_api("getChatMember",chat_id=chat_id,user_id=me.id)
   if bot_member.get("status") not in ("member","administrator","creator"):
    return await m.reply_text("Bot is not a member of that group.")
   if not await live_group_admin(c,chat_id,m.from_user.id):
    return await m.reply_text("Only group administrators can connect this group.")
   title=chat.get("title") or str(chat_id)
   await ensure_group(chat_id,title)
   await execute(
    "INSERT INTO group_admin_links(chat_id,user_id) VALUES(%s,%s) "
    "ON DUPLICATE KEY UPDATE verified_at=CURRENT_TIMESTAMP",
    (chat_id,m.from_user.id)
   )
   await m.reply_text(f"✅ Group registered: {title}\nOpen /dashboard → My Groups.")
  except Exception:
   import logging
   logging.exception("Group connection failed for chat=%s",chat_id)
   await m.reply_text("Unable to verify this group. Check that the bot is still an administrator.")

 @app.on_message(filters.command('settings') & filters.group)
 async def settings(c,m):
  if not await admin(c,m):return
  await ensure_group(m.chat.id,m.chat.title)
  await execute(
   "INSERT INTO group_admin_links(chat_id,user_id) VALUES(%s,%s) "
   "ON DUPLICATE KEY UPDATE verified_at=CURRENT_TIMESTAMP",
   (m.chat.id,m.from_user.id)
  )
  row=await one('SELECT * FROM `groups` WHERE chat_id=%s',(m.chat.id,))
  await m.reply_text('⚙️ Settings\n'+'\n'.join(f'{k}: {row[k]}' for k in ('welcome_enabled','antiflood_enabled','links_blocked','verify_enabled','flood_limit','flood_window')))
 @app.on_message(filters.command(['welcome','antiflood','links','verify']) & filters.group)
 async def toggle(c,m):
  if not await admin(c,m):return
  parts=m.text.split();key=m.command[0].lower();fields={'welcome':'welcome_enabled','antiflood':'antiflood_enabled','links':'links_blocked','verify':'verify_enabled'}
  if len(parts)!=2 or parts[1].lower() not in ('on','off'):return await m.reply_text(f'Usage: /{key} on|off')
  await ensure_group(m.chat.id,m.chat.title)
  await execute(f'UPDATE `groups` SET {fields[key]}=%s WHERE chat_id=%s',(parts[1].lower()=='on',m.chat.id))
  await m.reply_text(f'{key} set to {parts[1].lower()}')
 @app.on_message(filters.command(['setrules','setwelcome']) & filters.group)
 async def set_text(c,m):
  if not await admin(c,m):return
  value=m.text.partition(' ')[2].strip()
  if not value:return await m.reply_text('Supply text after command')
  field='rules' if m.command[0].lower()=='setrules' else 'welcome_text'
  await ensure_group(m.chat.id,m.chat.title)
  await execute(f'UPDATE `groups` SET {field}=%s WHERE chat_id=%s',(value[:3500],m.chat.id))
  await m.reply_text('Saved')
 @app.on_message(filters.command('rules') & filters.group)
 async def rules(c,m):
  r=await one('SELECT rules FROM `groups` WHERE chat_id=%s',(m.chat.id,))
  await m.reply_text((r or {}).get('rules') or 'Group rules have not been set.')
 @app.on_message(filters.command('stats') & filters.group)
 async def stats(c,m):
  rows=await all('SELECT event_type,COUNT(*) AS n FROM events WHERE chat_id=%s AND created_at >= UTC_TIMESTAMP()-INTERVAL 1 DAY GROUP BY event_type',(m.chat.id,))
  members=await one('SELECT COUNT(*) AS n FROM members WHERE chat_id=%s AND active=1',(m.chat.id,))
  await m.reply_text('📊 Last 24 hours (observed)\n'+'\n'.join(f"{r['event_type']}: {r['n']}" for r in rows)+f"\nTracked active members: {members['n']}")
