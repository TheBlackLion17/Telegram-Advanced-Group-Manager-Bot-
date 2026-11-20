import aiomysql
from config import DB
pool=None
SCHEMA=[
"""CREATE TABLE IF NOT EXISTS referral_main_group (slot TINYINT PRIMARY KEY,chat_id BIGINT NOT NULL,title VARCHAR(255) NOT NULL,join_url VARCHAR(512) NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS referral_wallets (chat_id BIGINT NOT NULL,user_id BIGINT NOT NULL,earned BIGINT NOT NULL DEFAULT 0,available BIGINT NOT NULL DEFAULT 0,reserved BIGINT NOT NULL DEFAULT 0,paid BIGINT NOT NULL DEFAULT 0,PRIMARY KEY(chat_id,user_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS referral_credits (chat_id BIGINT NOT NULL,referred_id BIGINT NOT NULL,referrer_id BIGINT NOT NULL,amount INT NOT NULL DEFAULT 1,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(chat_id,referred_id),INDEX idx_referrer(chat_id,referrer_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS referral_withdrawals (id BIGINT AUTO_INCREMENT PRIMARY KEY,chat_id BIGINT NOT NULL,user_id BIGINT NOT NULL,amount BIGINT NOT NULL,status VARCHAR(16) NOT NULL DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,reviewed_by BIGINT NULL,reviewed_at DATETIME NULL,INDEX idx_withdrawals(chat_id,status,id),INDEX idx_withdraw_user(chat_id,user_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS security_settings (chat_id BIGINT PRIMARY KEY,duplicate_enabled BOOLEAN NOT NULL DEFAULT FALSE,newcomer_links_enabled BOOLEAN NOT NULL DEFAULT FALSE,raid_enabled BOOLEAN NOT NULL DEFAULT FALSE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS member_activity (chat_id BIGINT NOT NULL,user_id BIGINT NOT NULL,message_count BIGINT NOT NULL DEFAULT 0,last_seen DATETIME NOT NULL,PRIMARY KEY(chat_id,user_id),INDEX idx_member_activity_chat_last(chat_id,last_seen),INDEX idx_member_activity_chat_count(chat_id,message_count)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS welcome_templates (chat_id BIGINT PRIMARY KEY,media_file_id TEXT NULL,media_type VARCHAR(16) NULL,button_text VARCHAR(64) NULL,button_url VARCHAR(512) NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS group_admin_links (chat_id BIGINT NOT NULL,user_id BIGINT NOT NULL,verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,PRIMARY KEY(chat_id,user_id),INDEX idx_admin_user(user_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS `groups` (chat_id BIGINT PRIMARY KEY,title VARCHAR(255),welcome_enabled BOOLEAN NOT NULL DEFAULT TRUE,antiflood_enabled BOOLEAN NOT NULL DEFAULT TRUE,links_blocked BOOLEAN NOT NULL DEFAULT FALSE,verify_enabled BOOLEAN NOT NULL DEFAULT FALSE, rules TEXT, welcome_text TEXT, flood_limit INT NOT NULL DEFAULT 6, flood_window INT NOT NULL DEFAULT 8) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS members (chat_id BIGINT NOT NULL,user_id BIGINT NOT NULL,first_name VARCHAR(255),username VARCHAR(255),joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,active BOOLEAN NOT NULL DEFAULT TRUE,invited_by BIGINT NULL,verified BOOLEAN NOT NULL DEFAULT TRUE,PRIMARY KEY(chat_id,user_id),INDEX idx_ref(chat_id,invited_by)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS warnings (chat_id BIGINT NOT NULL,user_id BIGINT NOT NULL,count INT NOT NULL DEFAULT 0,PRIMARY KEY(chat_id,user_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS banned_words (chat_id BIGINT NOT NULL,word VARCHAR(100) NOT NULL,PRIMARY KEY(chat_id,word)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS invite_links (chat_id BIGINT NOT NULL,invite_link VARCHAR(512) NOT NULL,creator_id BIGINT NOT NULL,PRIMARY KEY(chat_id,invite_link(191))) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS events (id BIGINT AUTO_INCREMENT PRIMARY KEY,chat_id BIGINT NOT NULL,user_id BIGINT NULL,event_type VARCHAR(40) NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,INDEX idx_events(chat_id,event_type,created_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS scheduled_posts (id BIGINT AUTO_INCREMENT PRIMARY KEY,chat_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,body TEXT NOT NULL,send_at DATETIME NOT NULL,status VARCHAR(16) NOT NULL DEFAULT 'pending',INDEX idx_sched(status,send_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS quizzes (id BIGINT AUTO_INCREMENT PRIMARY KEY,question TEXT NOT NULL,options_json TEXT NOT NULL,correct_index INT NOT NULL,created_by BIGINT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
]
async def init():
 global pool
 pool=await aiomysql.create_pool(minsize=1,maxsize=10,**DB)
 for sql in SCHEMA: await execute(sql)
async def close():
 if pool: pool.close(); await pool.wait_closed()
async def execute(sql,args=()):
 async with pool.acquire() as conn:
  async with conn.cursor() as cur:
   await cur.execute(sql,args)
   return cur.lastrowid
async def execute_rowcount(sql,args=()):
 async with pool.acquire() as conn:
  async with conn.cursor() as cur:
   await cur.execute(sql,args)
   return cur.rowcount
async def one(sql,args=()):
 async with pool.acquire() as conn:
  async with conn.cursor(aiomysql.DictCursor) as cur:
   await cur.execute(sql,args);return await cur.fetchone()
async def all(sql,args=()):
 async with pool.acquire() as conn:
  async with conn.cursor(aiomysql.DictCursor) as cur:
   await cur.execute(sql,args);return await cur.fetchall()
async def event(chat,user,kind):
 await execute('INSERT INTO events(chat_id,user_id,event_type) VALUES(%s,%s,%s)',(chat,user,kind))
async def ensure_group(chat,title):
 await execute('INSERT INTO `groups`(chat_id,title) VALUES(%s,%s) ON DUPLICATE KEY UPDATE title=VALUES(title)',(chat,title))
