import json,random,asyncio,logging
from datetime import datetime,timedelta,timezone
from pyrogram import filters
from database import execute,one,all
from utils import admin
def register(app):
 @app.on_message(filters.command('quizadd') & filters.group)
 async def quizadd(c,m):
  if not await admin(c,m):return
  parts=[s.strip() for s in m.text.partition(' ')[2].split('|')]
  if len(parts)!=6:return await m.reply_text('Usage: /quizadd Question | A | B | C | D | correct number (1-4)')
  try:idx=int(parts[5])-1;assert 0<=idx<4
  except Exception:return await m.reply_text('Correct answer must be 1, 2, 3, or 4')
  await execute('INSERT INTO quizzes(question,options_json,correct_index,created_by) VALUES(%s,%s,%s,%s)',(parts[0],json.dumps(parts[1:5]),idx,m.from_user.id))
  await m.reply_text('Quiz saved.')
 @app.on_message(filters.command('quiz') & filters.group)
 async def quiz(c,m):
  rows=await all('SELECT * FROM quizzes ORDER BY RAND() LIMIT 1')
  if not rows:return await m.reply_text('No quizzes yet. Admins: /quizadd')
  r=rows[0]
  await c.send_poll(m.chat.id,r['question'],json.loads(r['options_json']),type='quiz',correct_option_id=r['correct_index'],is_anonymous=False)
 @app.on_message(filters.command('schedule') & filters.group)
 async def schedule(c,m):
  if not await admin(c,m):return
  parts=m.text.split(maxsplit=2)
  if len(parts)<3:return await m.reply_text('Usage: /schedule MINUTES message (max 10080 minutes)')
  try:minutes=int(parts[1]);assert 1<=minutes<=10080
  except Exception:return await m.reply_text('Minutes must be 1–10080.')
  when=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=minutes)
  await execute('INSERT INTO scheduled_posts(chat_id,creator_id,body,send_at) VALUES(%s,%s,%s,%s)',(m.chat.id,m.from_user.id,parts[2][:3900],when))
  await m.reply_text(f'Announcement scheduled in {minutes} minutes (UTC stored).')
async def scheduler(app):
 while True:
  try:
   rows=await all("SELECT * FROM scheduled_posts WHERE status='pending' AND send_at<=UTC_TIMESTAMP() ORDER BY id LIMIT 20")
   for r in rows:
    claimed=await execute("UPDATE scheduled_posts SET status='sending' WHERE id=%s AND status='pending'",(r['id'],))
    if not claimed:continue
    try:
     await app.send_message(r['chat_id'],r['body'])
     await execute("UPDATE scheduled_posts SET status='sent' WHERE id=%s",(r['id'],))
    except Exception:
     await execute("UPDATE scheduled_posts SET status='failed' WHERE id=%s",(r['id'],))
  except Exception:
   logging.exception('Scheduler error')
  await asyncio.sleep(15)
