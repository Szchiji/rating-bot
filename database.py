import os
import asyncpg
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get('DATABASE_URL')
# 全局连接池，Bot 和 Web 都使用它
db_pool = None

async def init_db_pool():
    """初始化数据库连接池"""
    global db_pool
    if db_pool:
        return
        
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")
    
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        print("Database connection pool successfully initialized.")
    except Exception as e:
        print(f"FATAL ERROR: Could not connect to database: {e}")
        raise

async def init_schema():
    """初始化数据库表结构 (已包含 banned_users 的 time 字段)"""
    await init_db_pool()

    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS ratings (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(32),
                rec INTEGER DEFAULT 0,
                black INTEGER DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS votes (
                chat_id BIGINT NOT NULL, 
                voter_id BIGINT NOT NULL, 
                target_id BIGINT NOT NULL,
                type VARCHAR(10) NOT NULL,
                time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                evidence_msg_id BIGINT,              
                PRIMARY KEY(chat_id, voter_id, target_id, type)
            );
            
            CREATE TABLE IF NOT EXISTS admins (user_id BIGINT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS allowed_chats (chat_id BIGINT PRIMARY KEY);
            
            -- IMPORTANT: banned_users 增加了 time 字段支持 Web UI
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY, 
                username VARCHAR(32),
                time TIMESTAMP WITH TIME ZONE DEFAULT NOW() 
            ); 
            
            CREATE TABLE IF NOT EXISTS bot_settings (key VARCHAR(50) PRIMARY KEY, value TEXT);
            
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                min_join_days INTEGER DEFAULT 0,    
                force_channel_id BIGINT DEFAULT 0   
            );
        ''')
        
        await conn.execute("""
            INSERT INTO bot_settings (key, value) VALUES ($1, $2) 
            ON CONFLICT (key) DO NOTHING
        """, 'welcome', '<b>狼猎信誉系统</b>\n\n@用户查看信誉\n推荐+1 拉黑-1\n24h内同人只能投一次')

# --- 核心操作函数 ---

async def get_stats(user_id: int):
    """通过 user_id 获取信誉统计"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT rec, black, username FROM ratings WHERE user_id = $1", user_id)
        return (row['rec'], row['black'], row['username']) if row else (0, 0, None)

async def add_vote(chat_id: int, voter_id: int, target_id: int, typ: str, username: str, evidence_msg_id: int = None):
    """添加投票记录和更新信誉，支持记录 evidence_msg_id"""
    async with db_pool.acquire() as conn:
        col = "rec" if typ == "rec" else "black"
        
        await conn.execute(f"""
            INSERT INTO ratings (user_id, username, {col}) VALUES ($1, $2, 1) 
            ON CONFLICT (user_id) DO UPDATE SET {col}=ratings.{col}+1, username=EXCLUDED.username
        """, target_id, username)
        
        await conn.execute(f"""
            INSERT INTO votes (chat_id, voter_id, target_id, type, time, evidence_msg_id) 
            VALUES ($1, $2, $3, $4, NOW(), $5) 
            ON CONFLICT (chat_id, voter_id, target_id, type) DO UPDATE SET time = EXCLUDED.time, evidence_msg_id = EXCLUDED.evidence_msg_id
        """, chat_id, voter_id, target_id, typ, evidence_msg_id)

async def can_vote(chat_id: int, voter_id: int, target_id: int, typ: str):
    """检查 24 小时投票限制"""
    async with db_pool.acquire() as conn:
        cutoff = datetime.now() - timedelta(hours=24)
        row = await conn.fetchrow(
            "SELECT 1 FROM votes WHERE chat_id=$1 AND voter_id=$2 AND target_id=$3 AND type=$4 AND time>$5", 
            chat_id, voter_id, target_id, typ, cutoff
        )
        return row is None

async def is_banned(user_id: int):
    """检查用户是否被封禁"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM banned_users WHERE user_id = $1", user_id)
        return row is not None

async def get_banned_list():
    """获取所有被封禁的用户列表 (包含 time 字段，用于 Web UI)"""
    try:
        async with db_pool.acquire() as conn:
            # 确保查询包含 time 字段
            return await conn.fetch("SELECT user_id, username, time FROM banned_users")
    except Exception as e:
        print(f"Database Error in get_banned_list: {e}")
        return []

async def unban_user(user_id: int):
    """解禁用户"""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM banned_users WHERE user_id = $1", user_id)

async def ban_user(user_id: int, username: str):
    """封禁用户"""
    async with db_pool.acquire() as conn:
        # 确保插入时设置了 time=NOW()
        await conn.execute("INSERT INTO banned_users (user_id, username, time) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username, time=NOW()", user_id, username)

async def clear_user_data(user_id: int):
    """清除用户所有记录"""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM ratings WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM votes WHERE target_id = $1 OR voter_id = $1", user_id)

async def get_chat_settings(chat_id: int):
    """获取群组设置，用于投票门槛和强制关注 (Bot 使用)"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT min_join_days, force_channel_id FROM chat_settings WHERE chat_id = $1", chat_id)
        return row if row else {'min_join_days': 0, 'force_channel_id': 0}

async def get_chat_settings_list():
    """获取所有群组设置列表 (用于 Web UI)"""
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetch("SELECT chat_id, min_join_days, force_channel_id FROM chat_settings")
    except Exception as e:
        print(f"Database Error in get_chat_settings_list: {e}")
        return []

async def get_allowed_chats():
    """获取所有已授权的群组 ID"""
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT chat_id FROM allowed_chats")

async def save_admin(uid: int):
    """保存管理员 ID"""
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO admins VALUES ($1) ON CONFLICT (user_id) DO NOTHING", uid)

async def load_admins():
    """加载管理员 ID"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
        return {row['user_id'] for row in rows}

async def save_group(gid: int):
    """保存授权群 ID"""
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO allowed_chats VALUES ($1) ON CONFLICT (chat_id) DO NOTHING", gid)

async def del_group(gid: int):
    """删除授权群 ID"""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM allowed_chats WHERE chat_id = $1", gid)

async def get_welcome_message():
    """获取欢迎消息"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key='welcome'")
        return row['value'] if row else "欢迎使用"

async def set_welcome_message(text: str):
    """设置欢迎消息"""
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", 
                           'welcome', text)