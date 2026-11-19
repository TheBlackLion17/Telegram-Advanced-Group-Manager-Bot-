import re
from datetime import datetime,timezone,timedelta
from pyrogram import enums
from config import OWNER_ID,LOG_CHAT_ID
from database import one,execute,event
async def admin(client,msg):
 if not msg.from_user:return False
 if msg.from_user.id==OWNER_ID:return True
 try:
  m=await client.get_chat_member(msg.chat.id,msg.from_user.id)
  return m.status in (enums.ChatMemberStatus.OWNER,enums.ChatMemberStatus.ADMINISTRATOR)
 except Exception:return False
async def bot_can(client,chat_id,permission):
 try:
  me=await client.get_me();m=await client.get_chat_member(chat_id,me.id)
  return m.status==enums.ChatMemberStatus.ADMINISTRATOR and bool(getattr(m.privileges,permission,False))
 except Exception:return False
async def target(msg):
 if msg.reply_to_message and msg.reply_to_message.from_user:return msg.reply_to_message.from_user.id
 bits=(msg.text or '').split()
 if len(bits)>1 and bits[1].lstrip('-').isdigit():return int(bits[1])
 return None
async def log(client,chat,user,kind,detail=''):
 await event(chat,user,kind)
 if LOG_CHAT_ID:
  try:await client.send_message(LOG_CHAT_ID,f'{kind} | chat={chat} user={user} {detail}'[:3900])
  except Exception:pass
def until(minutes):return datetime.now(timezone.utc)+timedelta(minutes=minutes)
