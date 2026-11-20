import logging
from pyrogram import filters,enums
from pyrogram.types import InlineKeyboardMarkup,InlineKeyboardButton,ChatPermissions
from database import ensure_group,one,execute,all
from utils import log,admin,until
from plugins.referral_wallet import credit
DEFAULT_WELCOME = (
 "HEY, {name}! 👋\n"
 "WELCOME TO OUR {group_name} 📺\n\n"
 "YOU CAN FIND MOVIES / SERIES / ANIMES ETC. FROM HERE. ENJOY! 😉"
)

async def send_welcome(client, message, user, cfg):
 chat_id=message.chat.id
 settings=await one("SELECT * FROM welcome_templates WHERE chat_id=%s",(chat_id,))
 template=cfg.get("welcome_text") or DEFAULT_WELCOME
 text=(template.replace("{name}",user.first_name or "friend")
               .replace("{group_name}",message.chat.title or "our group")
               .replace("{user_id}",str(user.id)))
 buttons=[]
 if settings and settings.get("button_text") and settings.get("button_url"):
  buttons.append([InlineKeyboardButton(settings["button_text"],url=settings["button_url"])])
 if cfg["verify_enabled"]:
  buttons.append([InlineKeyboardButton("✅ I am human",callback_data=f"verify:{chat_id}:{user.id}")])
 markup=InlineKeyboardMarkup(buttons) if buttons else None
 media_id=settings.get("media_file_id") if settings else None
 media_type=settings.get("media_type") if settings else None
 try:
  if media_id and media_type=="photo":
   await client.send_photo(chat_id,media_id,caption=text[:1024],reply_markup=markup)
  elif media_id and media_type=="animation":
   await client.send_animation(chat_id,media_id,caption=text[:1024],reply_markup=markup)
  elif media_id and media_type=="video":
   await client.send_video(chat_id,media_id,caption=text[:1024],reply_markup=markup)
  else:
   await client.send_message(chat_id,text[:4000],reply_markup=markup)
 except Exception:
  logging.exception("Welcome media failed for chat=%s; sending text",chat_id)
  try:
   await client.send_message(chat_id,text[:4000],reply_markup=markup)
  except Exception:
   logging.exception("Welcome message failed for chat=%s",chat_id)

def register(app):
 @app.on_message(filters.new_chat_members & filters.group)
 async def join(c,m):
  await ensure_group(m.chat.id,m.chat.title)
  cfg=await one('SELECT * FROM `groups` WHERE chat_id=%s',(m.chat.id,))
  for u in m.new_chat_members:
   if u.is_bot:continue
   inviter=None
   # Pyrogram 2.0.x join service messages may not expose invite_link.
   # Never let optional referral metadata prevent member registration or welcome.
   invite=getattr(m,'invite_link',None)
   invite_url=getattr(invite,'invite_link',None) if invite else None
   if invite_url:
    try:
     ref=await one('SELECT creator_id FROM invite_links WHERE chat_id=%s AND invite_link=%s',(m.chat.id,invite_url))
     if ref and ref['creator_id']!=u.id:inviter=ref['creator_id']
    except Exception:
     logging.exception('Referral lookup failed chat=%s user=%s',m.chat.id,u.id)
   await execute('INSERT INTO members(chat_id,user_id,first_name,username,active,invited_by,verified) VALUES(%s,%s,%s,%s,1,%s,%s) ON DUPLICATE KEY UPDATE first_name=VALUES(first_name),username=VALUES(username),active=1,invited_by=COALESCE(invited_by,VALUES(invited_by)),verified=VALUES(verified),joined_at=CURRENT_TIMESTAMP',(m.chat.id,u.id,u.first_name,u.username,inviter,not cfg['verify_enabled']))
   if inviter and not cfg['verify_enabled']:
    await credit(m.chat.id,u.id)
   await log(c,m.chat.id,u.id,'join')
   if cfg['verify_enabled']:
    try:
     await c.restrict_chat_member(m.chat.id,u.id,ChatPermissions())
    except Exception:
     logging.exception("Could not restrict new member chat=%s user=%s",m.chat.id,u.id)
   if cfg['welcome_enabled']:
    await send_welcome(c,m,u,cfg)

 @app.on_callback_query(filters.regex(r'^verify:-?\d+:\d+$'))
 async def verify(c,q):
  _,chat,user=q.data.split(':');chat=int(chat);user=int(user)
  if q.from_user.id!=user:return await q.answer('This button belongs to another member.',show_alert=True)
  if not q.message or q.message.chat.id!=chat:return await q.answer('Invalid verification chat.',show_alert=True)
  record=await one('SELECT verified FROM members WHERE chat_id=%s AND user_id=%s',(chat,user))
  if not record:return await q.answer('Verification record not found.',show_alert=True)
  try:
   await c.restrict_chat_member(chat,user,ChatPermissions(can_send_messages=True,can_send_media_messages=True,can_send_other_messages=True,can_add_web_page_previews=True,can_send_polls=True,can_invite_users=True))
   await execute('UPDATE members SET verified=1 WHERE chat_id=%s AND user_id=%s',(chat,user))
   await credit(chat,user)
   await q.answer('Verified!');await q.message.edit_text('✅ Verification complete.')
  except Exception:return await q.answer('Verification failed; contact an admin.',show_alert=True)
 @app.on_message(filters.left_chat_member & filters.group)
 async def leave(c,m):
  u=m.left_chat_member
  if u:
   await execute('UPDATE members SET active=0 WHERE chat_id=%s AND user_id=%s',(m.chat.id,u.id))
   await execute("UPDATE referral_pending SET status='cancelled' WHERE chat_id=%s AND referred_id=%s AND status='pending'",(m.chat.id,u.id))
   await log(c,m.chat.id,u.id,'leave')
 @app.on_message(filters.command('referral') & filters.group)
 async def referral(c,m):
  if not m.from_user:return
  try:
   link=await c.create_chat_invite_link(m.chat.id,name=f'ref-{m.from_user.id}',creates_join_request=False)
   await execute('INSERT INTO invite_links(chat_id,invite_link,creator_id) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE creator_id=VALUES(creator_id)',(m.chat.id,link.invite_link,m.from_user.id))
   await m.reply_text(f'🔗 Your referral link:\n{link.invite_link}\n\n💰 Earn ₹1 per verified, uniquely tracked referral.\nMinimum manual withdrawal: ₹100.\nUse /balance and /withdraw 100.')
  except Exception as e:await m.reply_text('Bot needs invite-link admin permission: '+str(e)[:200])
 @app.on_message(filters.command('leaderboard') & filters.group)
 async def leaderboard(c,m):
  rows=await all('SELECT referrer_id AS invited_by,COUNT(*) n FROM referral_credits WHERE chat_id=%s GROUP BY referrer_id ORDER BY n DESC LIMIT 10',(m.chat.id,))
  await m.reply_text('🏆 Referral leaderboard (credited verified joins)\n'+'\n'.join(f"{i}. {r['invited_by']} — {r['n']}" for i,r in enumerate(rows,1)) if rows else 'No tracked referrals yet.')
