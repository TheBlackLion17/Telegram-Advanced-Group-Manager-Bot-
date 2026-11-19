import asyncio,logging
from pyrogram import Client
import database
from config import API_ID,API_HASH,BOT_TOKEN
from modules import core,moderation,members,engagement
logging.basicConfig(level=logging.INFO)
app=Client('group_manager',api_id=API_ID,api_hash=API_HASH,bot_token=BOT_TOKEN,workers=8)
async def main():
 app.loop=asyncio.get_running_loop()
 app.dispatcher.loop=app.loop
 for mod in (core,moderation,members,engagement):mod.register(app)
 await asyncio.sleep(0)
 logging.info('Registered handler groups: %s',len(app.dispatcher.groups))
 await database.init()
 try:
  await app.start()
  await asyncio.sleep(0.2)
  logging.info('ACTIVE HANDLER GROUPS: %s',len(app.dispatcher.groups))
  if not app.dispatcher.groups:raise RuntimeError('No Pyrogram handlers registered')
  task=asyncio.create_task(engagement.scheduler(app))
  print('Group Manager running')
  try:await asyncio.Event().wait()
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True);await app.stop()
 finally:await database.close()
if __name__=='__main__':asyncio.run(main())
