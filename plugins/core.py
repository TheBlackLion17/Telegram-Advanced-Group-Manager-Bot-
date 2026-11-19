from pyrogram import filters
from plugins.dashboard import home
from database import ensure_group,one,execute,all
from utils import admin,log
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
 @app.on_message(filters.command('settings') & filters.group)
 async def settings(c,m):
  if not await admin(c,m):return
  await ensure_group(m.chat.id,m.chat.title)
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
