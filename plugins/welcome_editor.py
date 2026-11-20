"""Private welcome editor. Admin checks are repeated for every action."""
import logging
from urllib.parse import urlparse
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import OWNER_ID
from database import all, one, execute
from utils import live_group_admin

log=logging.getLogger(__name__)
pending={}

def kb(rows):
 return InlineKeyboardMarkup(rows)

async def allowed(c,chat_id,user_id):
 # Bot owner must also be an administrator in the target group.
 return await live_group_admin(c,chat_id,user_id)

async def panel(chat_id):
 cfg=await one("SELECT welcome_enabled,welcome_text,title FROM `groups` WHERE chat_id=%s",(chat_id,))
 if not cfg:return None,None
 media=await one("SELECT media_type,button_text,button_url FROM welcome_templates WHERE chat_id=%s",(chat_id,))
 text=("👋 Welcome Editor — "+str(cfg["title"] or chat_id)+
       "\nStatus: "+("ON" if cfg["welcome_enabled"] else "OFF")+
       "\nText: "+("Custom" if cfg["welcome_text"] else "Default")+
       "\nMedia: "+str((media or {}).get("media_type") or "None")+
       "\nButton: "+str((media or {}).get("button_text") or "None")+
       "\n\nChoose what to edit:")
 rows=[
  [InlineKeyboardButton("✏️ Edit text",callback_data=f"wm:edit:{chat_id}:text")],
  [InlineKeyboardButton("🖼 Set photo / GIF / video",callback_data=f"wm:edit:{chat_id}:media")],
  [InlineKeyboardButton("🔗 Edit support button",callback_data=f"wm:edit:{chat_id}:button")],
  [InlineKeyboardButton("🗑 Remove media",callback_data=f"wm:clear:{chat_id}:media"),
   InlineKeyboardButton("🗑 Remove button",callback_data=f"wm:clear:{chat_id}:button")],
  [InlineKeyboardButton("🔄 Toggle welcome",callback_data=f"wm:toggle:{chat_id}")],
  [InlineKeyboardButton("⬅️ My Groups",callback_data="wm:groups")]
 ]
 return text,kb(rows)

def register(app):
 @app.on_message(filters.command("welcomeedit") & filters.private)
 async def editor(c,m):
  if not m.from_user:return
  pending.pop(m.from_user.id,None)
  rows=await all("SELECT chat_id,title FROM `groups` ORDER BY title LIMIT 100")
  buttons=[]
  for row in rows:
   if await allowed(c,row["chat_id"],m.from_user.id):
    buttons.append([InlineKeyboardButton(str(row["title"] or row["chat_id"])[:50],callback_data=f"wm:panel:{row['chat_id']}")])
  if not buttons:return await m.reply_text("No groups available. Connect a group with /connect CHAT_ID first.")
  buttons.append([InlineKeyboardButton("⬅️ Dashboard",callback_data="gm:home")])
  await m.reply_text("👋 Select a group to edit its welcome template:",reply_markup=kb(buttons))

 @app.on_callback_query(filters.regex(r"^wm:"))
 async def callbacks(c,q):
  if not q.message or q.message.chat.type!=enums.ChatType.PRIVATE:return await q.answer("Private chat only.",show_alert=True)
  if not q.from_user:return
  parts=q.data.split(":")
  action=parts[1]
  if action=="groups":
   await q.answer()
   return await editor(c,q.message) if False else await q.message.edit_text("Send /welcomeedit to choose a group.")
  if len(parts)<3:return await q.answer("Invalid action.",show_alert=True)
  try:chat_id=int(parts[2])
  except ValueError:return await q.answer("Invalid group.",show_alert=True)
  if not await allowed(c,chat_id,q.from_user.id):return await q.answer("Group administrator access required.",show_alert=True)
  try:
   if action=="edit" and len(parts)==4 and parts[3] in ("text","media","button"):
    mode=parts[3]
    pending[q.from_user.id]=(chat_id,mode)
    prompt={"text":"Send the welcome text. Use {name}, {group_name}, {user_id}.",
            "media":"Send a photo, GIF or video here in private.",
            "button":"Send BUTTON TITLE | https://t.me/yourchannel"}[mode]
    await q.message.reply_text(prompt+"\nSend /cancel to stop.")
    return await q.answer()
   if action=="clear" and len(parts)==4:
    if parts[3]=="media":
     await execute("UPDATE welcome_templates SET media_file_id=NULL,media_type=NULL WHERE chat_id=%s",(chat_id,))
    elif parts[3]=="button":
     await execute("UPDATE welcome_templates SET button_text=NULL,button_url=NULL WHERE chat_id=%s",(chat_id,))
    else:return await q.answer("Invalid option.",show_alert=True)
   elif action=="toggle":
    await execute("UPDATE `groups` SET welcome_enabled=NOT welcome_enabled WHERE chat_id=%s",(chat_id,))
   elif action!="panel":
    return await q.answer("Unknown action.",show_alert=True)
   text,markup=await panel(chat_id)
   if markup is None:return await q.answer("Group not found.",show_alert=True)
   await q.message.edit_text(text,reply_markup=markup)
   await q.answer()
  except Exception:
   log.exception("Welcome editor callback failed")
   await q.answer("Could not save. Check bot logs.",show_alert=True)

 @app.on_message(filters.private & (filters.text | filters.photo | filters.animation | filters.video),group=5)
 async def editor_input(c,m):
  if not m.from_user or m.from_user.id not in pending:return
  if m.text and m.text.strip()=="/cancel":
   pending.pop(m.from_user.id,None)
   return await m.reply_text("Welcome editing cancelled.")
  if m.text and m.text.startswith("/"):return
  chat_id,mode=pending[m.from_user.id]
  if not await allowed(c,chat_id,m.from_user.id):
   pending.pop(m.from_user.id,None)
   return await m.reply_text("You no longer have administrator access.")
  try:
   if mode=="text":
    if not m.text or not m.text.strip():return await m.reply_text("Send a text message.")
    await execute("UPDATE `groups` SET welcome_text=%s WHERE chat_id=%s",(m.text.strip()[:3500],chat_id))
   elif mode=="media":
    media=None;kind=None
    if m.photo:media=m.photo;kind="photo"
    elif m.animation:media=m.animation;kind="animation"
    elif m.video:media=m.video;kind="video"
    if not media:return await m.reply_text("Send a photo, GIF or video.")
    await execute(
     "INSERT INTO welcome_templates(chat_id,media_file_id,media_type) VALUES(%s,%s,%s) "
     "ON DUPLICATE KEY UPDATE media_file_id=VALUES(media_file_id),media_type=VALUES(media_type)",
     (chat_id,media.file_id,kind))
   elif mode=="button":
    if not m.text:return await m.reply_text("Send BUTTON TITLE | https://t.me/yourchannel")
    parts=[p.strip() for p in m.text.split("|",1)]
    if len(parts)!=2 or not 1<=len(parts[0])<=64 or len(parts[1])>512:
     return await m.reply_text("Format: SUPPORT | https://t.me/yourchannel")
    url=urlparse(parts[1])
    if url.scheme not in ("https","http") or not url.netloc:
     return await m.reply_text("Use a valid https:// URL.")
    await execute(
     "INSERT INTO welcome_templates(chat_id,button_text,button_url) VALUES(%s,%s,%s) "
     "ON DUPLICATE KEY UPDATE button_text=VALUES(button_text),button_url=VALUES(button_url)",
     (chat_id,parts[0],parts[1]))
   pending.pop(m.from_user.id,None)
   text,markup=await panel(chat_id)
   await m.reply_text("✅ Saved!\n\n"+text,reply_markup=markup)
  except Exception:
   log.exception("Welcome editor save failed")
   await m.reply_text("Could not save. Please try again.")
