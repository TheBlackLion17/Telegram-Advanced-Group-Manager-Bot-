import os
from dotenv import load_dotenv
load_dotenv()
API_ID=int(os.environ['API_ID'])
API_HASH=os.environ['API_HASH']
BOT_TOKEN=os.environ['BOT_TOKEN']
OWNER_ID=int(os.environ['OWNER_ID'])
DB=dict(host=os.getenv('MYSQL_HOST','127.0.0.1'),port=int(os.getenv('MYSQL_PORT','3306')),user=os.environ['MYSQL_USER'],password=os.environ['MYSQL_PASSWORD'],db=os.getenv('MYSQL_DATABASE','group_manager'),autocommit=True,charset='utf8mb4')
LOG_CHAT_ID=int(os.getenv('LOG_CHAT_ID','0'))
