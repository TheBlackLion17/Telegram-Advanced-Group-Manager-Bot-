import asyncio,logging
from pyrogram import Client
import database
from config import API_ID,API_HASH,BOT_TOKEN
from modules import core,moderation,members,engagement
logging.basicConfig(level=logging.INFO)
app=Client('group_manager',api_id=API_ID,api_hash=API_HASH,bot_token=BOT_TOKEN,workers=8)
for mod in (core,moderation,members,engagement):mod.register(app)
async def main():
 await database.init()
 try:
  await app.start()
  task=asyncio.create_task(engagement.scheduler(app))
  print('Group Manager running')
  try:await asyncio.Event().wait()
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True);await app.stop()
 finally:await database.close()
if __name__=='__main__':asyncio.run(main())
