import asyncio,re,time,logging
from collections import defaultdict,deque
from pyrogram import filters,enums
from pyrogram.types import ChatPermissions
from database import ensure_group,one,execute,all
from utils import admin,target,until,log,bot_can
_flood=defaultdict(deque)
async def warn_user(c,chat,user,reason=''):
 await execute('INSERT INTO warnings(chat_id,user_id,count) VALUES(%s,%s,1) ON DUPLICATE KEY UPDATE count=count+1',(chat,user))
 r=await one('SELECT count FROM warnings WHERE chat_id=%s AND user_id=%s',(chat,user))
 await log(c,chat,user,'warn',reason)
 if r['count']>=3:
  if await bot_can(c,chat,'can_restrict_members'):
   await c.restrict_chat_member(chat,user,ChatPermissions(),until_date=until(60))
  await execute('UPDATE warnings SET count=0 WHERE chat_id=%s AND user_id=%s',(chat,user))
 return r['count']
def register(app):
 @app.on_message(filters.command(['ban','unban','kick','mute','unmute','warn','unwarn','warnings']) & filters.group)
 async def actions(c,m):
  if not await admin(c,m):return
  action=m.command[0].lower();uid=await target(m)
  if not uid:return await m.reply_text('Reply to a user or supply a numeric user ID.')
  try:
   member=await c.get_chat_member(m.chat.id,uid)
   if member.status in (enums.ChatMemberStatus.OWNER,enums.ChatMemberStatus.ADMINISTRATOR) and action not in ('warnings',):return await m.reply_text('Cannot moderate administrators.')
  except Exception:pass
  try:
   if action=='warn':
    n=await warn_user(c,m.chat.id,uid,'manual');return await m.reply_text(f'Warning {n}/3')
   if action=='warnings':
    r=await one('SELECT count FROM warnings WHERE chat_id=%s AND user_id=%s',(m.chat.id,uid));return await m.reply_text(f"Warnings: {(r or {}).get('count',0)}/3")
   if action=='unwarn':
    await execute('DELETE FROM warnings WHERE chat_id=%s AND user_id=%s',(m.chat.id,uid))
   elif action in ('ban','kick'):
    await c.ban_chat_member(m.chat.id,uid)
    if action=='kick':await c.unban_chat_member(m.chat.id,uid)
   elif action=='unban':await c.unban_chat_member(m.chat.id,uid)
   elif action=='mute':await c.restrict_chat_member(m.chat.id,uid,ChatPermissions(),until_date=until(60))
   elif action=='unmute':await c.restrict_chat_member(m.chat.id,uid,ChatPermissions(can_send_messages=True,can_send_media_messages=True,can_send_other_messages=True,can_add_web_page_previews=True,can_send_polls=True,can_change_info=False,can_invite_users=True,can_pin_messages=False))
   await log(c,m.chat.id,uid,action);await m.reply_text(f'✅ {action} completed for {uid}')
  except Exception as e:await m.reply_text(f'Action failed: {type(e).__name__}: {e}'[:500])
 @app.on_message(filters.command('purge') & filters.group)
 async def purge(c,m):
  if not await admin(c,m):return
  if not m.reply_to_message:return await m.reply_text('Reply to the first message to delete up to this command (max 100).')
  start=m.reply_to_message.id;end=m.id
  if end-start>100:return await m.reply_text('Maximum 100 messages per purge.')
  try:await c.delete_messages(m.chat.id,list(range(start,end+1)))
  except Exception as e:await m.reply_text(str(e)[:300])
 @app.on_message(filters.command('badword') & filters.group)
 async def badword(c,m):
  if not await admin(c,m):return
  parts=m.text.split(maxsplit=2)
  if len(parts)!=3 or parts[1] not in ('add','del') or not (1<=len(parts[2])<=100):return await m.reply_text('Usage: /badword add|del word')
  word=parts[2].lower().strip()
  if parts[1]=='add':await execute('INSERT IGNORE INTO banned_words(chat_id,word) VALUES(%s,%s)',(m.chat.id,word))
  else:await execute('DELETE FROM banned_words WHERE chat_id=%s AND word=%s',(m.chat.id,word))
  await m.reply_text('Updated blocked words.')
 @app.on_message(filters.group & (filters.text | filters.caption),group=10)
 async def check(c,m):
  if not m.from_user or m.from_user.is_bot or await admin(c,m):return
  if m.text and m.text.startswith('/'):return
  await ensure_group(m.chat.id,m.chat.title)
  r=await one('SELECT * FROM `groups` WHERE chat_id=%s',(m.chat.id,))
  text=(m.text or m.caption or '').lower()
  blocked=False;reason=''
  if r['links_blocked'] and re.search(r'(https?://|www\.|t\.me/)',text):blocked=True;reason='link'
  if not blocked:
   words=await all('SELECT word FROM banned_words WHERE chat_id=%s',(m.chat.id,))
   for item in words:
    if re.search(r'(?<!\w)'+re.escape(item['word'])+r'(?!\w)',text):blocked=True;reason='blocked word';break
  if r['antiflood_enabled']:
   key=(m.chat.id,m.from_user.id);q=_flood[key];now=time.monotonic();q.append(now)
   while q and now-q[0]>r['flood_window']:q.popleft()
   if len(q)>r['flood_limit']:blocked=True;reason='flood';q.clear()
  if blocked:
   try:
    await m.delete();n=await warn_user(c,m.chat.id,m.from_user.id,reason)
    await c.send_message(m.chat.id,f'⚠️ User {m.from_user.id}: {reason}. Warning {n}/3.')
   except Exception:
    logging.exception('Failed to moderate chat=%s user=%s',m.chat.id,m.from_user.id)
  else:await log(c,m.chat.id,m.from_user.id,'message')
