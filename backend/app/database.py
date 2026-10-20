import sqlite3
import os
import hashlib
import random
import aiosqlite
import asyncio
from typing import Optional

DB_PATH = os.environ.get("LAB_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lab.db"))

def get_db_connection() -> sqlite3.Connection:
    """Synchronous SQLite connection configured for concurrent WAL access."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

async def get_async_db():
    """Asynchronous SQLite connection generator."""
    db = await aiosqlite.connect(DB_PATH, timeout=30.0)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode = WAL;")
    await db.execute("PRAGMA synchronous = NORMAL;")
    await db.execute("PRAGMA busy_timeout = 30000;")
    await db.execute("PRAGMA foreign_keys = ON;")
    try:
        yield db
    finally:
        await db.close()

def init_db():
    """Initialize database tables, indexes, and default admin/posts."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        avatar_url TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, DISABLED, EXPIRED, RATE_LIMITED
        group_tag TEXT NOT NULL DEFAULT 'standard',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
    CREATE INDEX IF NOT EXISTS idx_users_group ON users(group_tag);
    CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        user_agent TEXT,
        ip_address TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        caption TEXT NOT NULL,
        image_url TEXT NOT NULL,
        likes_count INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        method TEXT NOT NULL DEFAULT 'API', -- BROWSER, API
        task_id TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, user_id),
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_likes_post ON likes(post_id);
    CREATE INDEX IF NOT EXISTS idx_likes_user ON likes(user_id);

    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL, -- PLAYWRIGHT, API_BENCHMARK
        post_id INTEGER NOT NULL,
        total_accounts INTEGER NOT NULL,
        concurrency INTEGER NOT NULL DEFAULT 4,
        delay_ms INTEGER NOT NULL DEFAULT 100,
        status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, RUNNING, PAUSED, COMPLETED, CANCELLED
        success_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        error_summary TEXT,
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS task_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        user_id INTEGER,
        username TEXT,
        status TEXT NOT NULL, -- SUCCESS, FAILED
        duration_ms REAL NOT NULL,
        error_message TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);

    CREATE TABLE IF NOT EXISTS inspector_logs (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        user_id INTEGER,
        username TEXT,
        request_headers TEXT NOT NULL,
        request_body TEXT,
        response_body TEXT,
        session_validation TEXT,
        db_delta TEXT,
        duration_ms REAL NOT NULL,
        lifecycle_stages TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_inspector_timestamp ON inspector_logs(timestamp);
    """);

    pwd_hash = hashlib.sha256("password123".encode()).hexdigest()

    # 1. Check if admin user exists, if not seed initial demo content
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    admin = cursor.fetchone()
    if not admin:
        cursor.execute("""
            INSERT INTO users (username, display_name, avatar_url, password_hash, status, group_tag)
            VALUES (?, ?, ?, ?, 'ACTIVE', 'admin')
        """, ("admin", "Lab Admin", "https://api.dicebear.com/7.x/bottts/svg?seed=admin", pwd_hash))

    # 2. Ensure rich creators exist
    rich_creators = [
        ("admin", "Lab Admin", "https://api.dicebear.com/7.x/bottts/svg?seed=admin"),
        ("cyber_explorer", "Cyberpunk Curator", "https://api.dicebear.com/7.x/bottts/svg?seed=cyber"),
        ("coffee_coder", "Dev & Espresso", "https://api.dicebear.com/7.x/bottts/svg?seed=coffee"),
        ("urban_lens", "Taipei City Lights", "https://api.dicebear.com/7.x/bottts/svg?seed=urban"),
        ("cloud_native", "Distributed Systems Lab", "https://api.dicebear.com/7.x/bottts/svg?seed=cloud"),
        ("design_daily", "UI/UX Aesthetics", "https://api.dicebear.com/7.x/bottts/svg?seed=design"),
        ("tokyo_drifter", "Tokyo Neon Vibes", "https://api.dicebear.com/7.x/bottts/svg?seed=tokyo"),
        ("minimal_desk", "Workspace Inspirations", "https://api.dicebear.com/7.x/bottts/svg?seed=desk"),
    ]

    creator_ids = {}
    for u_name, d_name, avatar in rich_creators:
        cursor.execute("SELECT id FROM users WHERE username = ?", (u_name,))
        user_row = cursor.fetchone()
        if user_row:
            creator_ids[u_name] = user_row["id"]
        else:
            cursor.execute("""
                INSERT INTO users (username, display_name, avatar_url, password_hash, status, group_tag)
                VALUES (?, ?, ?, ?, 'ACTIVE', 'creators')
            """, (u_name, d_name, avatar, pwd_hash))
            creator_ids[u_name] = cursor.lastrowid

    # 3. Ensure a cohort of simulated community & bot accounts exist (for realistic like interactions)
    cursor.execute("SELECT COUNT(*) as c FROM users WHERE status = 'ACTIVE'")
    active_user_count = cursor.fetchone()["c"]
    if active_user_count < 80:
        for idx in range(1, 85):
            uname = f"sim_user_{idx:03d}"
            dname = f"Explorer #{idx:03d}"
            avatar = f"https://api.dicebear.com/7.x/bottts/svg?seed={uname}"
            tag = "fleet-alpha" if idx % 2 == 0 else "community"
            cursor.execute("""
                INSERT OR IGNORE INTO users (username, display_name, avatar_url, password_hash, status, group_tag)
                VALUES (?, ?, ?, ?, 'ACTIVE', ?)
            """, (uname, dname, avatar, pwd_hash, tag))

    # 4. Rich posts definitions
    rich_posts = [
        ("cyber_explorer", "Cyberpunk Tokyo Night Walk - Testing social automation algorithms #tokyo #cyberpunk #neon", "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=800&q=80", 42),
        ("cloud_native", "High Concurrency Database Stress Test Lab in action 🚀 10,000 requests/sec! #fastapi #sqlite #wal", "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=800&q=80", 88),
        ("admin", "Playwright Headless Browser Worker Fleet - Automated Verification Pipeline #playwright #automation", "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=800&q=80", 25),
        ("coffee_coder", "Late night coffee & refactoring distributed worker queues ☕💻 #coder #coffeelover #devlife", "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&w=800&q=80", 19),
        ("minimal_desk", "Minimalist dual-monitor workstation setup with ambient backlighting #workspace #desksetup #minimalism", "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=800&q=80", 63),
        ("tokyo_drifter", "Shibuya Crossing rain reflections & neon glow from a drone perspective #streetphotography #tokyo #rain", "https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=800&q=80", 72),
        ("design_daily", "Building real-time WebSocket state synchronization with zero lag #websockets #fullstack #react", "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=800&q=80", 37),
        ("urban_lens", "Sunset reflections on Taipei 101 through the city skyline #taipei #taiwan #cityscape #sunset", "https://images.unsplash.com/photo-1477959858617-67f30bc75b82?auto=format&fit=crop&w=800&q=80", 65),
        ("cyber_explorer", "Mechanical keyboard custom build: Gateron Oil Kings with GMK keycaps #keebs #mechanicalkeyboard", "https://images.unsplash.com/photo-1587829741301-dc798b83add3?auto=format&fit=crop&w=800&q=80", 54),
        ("coffee_coder", "Matcha latte art at our local neighborhood coffee roastery 🍵✨ #matcha #cafe #taipeieats", "https://images.unsplash.com/photo-1536256263959-770b48d82b0a?auto=format&fit=crop&w=800&q=80", 31),
        ("cloud_native", "Server room fiber optic cable routing perfection - Data center aesthetics #sysadmin #datacenter", "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=800&q=80", 56),
        ("admin", "Autonomous AI testing agents monitoring end-to-end user journeys #ai #testing #qa #deepmind", "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=800&q=80", 48),
        ("minimal_desk", "Early morning sunrise over misty mountain ridge after summit climb 🏔️🌅 #outdoors #hiking #nature", "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=800&q=80", 52),
        ("urban_lens", "Deep-dive into sliding window rate limiting algorithms and 429 Retry-After #security #ratelimit #api", "https://images.unsplash.com/photo-1516259762381-22954d7d3ad2?auto=format&fit=crop&w=800&q=80", 49),
        ("tokyo_drifter", "Coastal road trip along the Pacific Ocean highway - Pure freedom 🌊🚗 #roadtrip #ocean #scenic", "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=800&q=80", 67),
        ("design_daily", "Brutalist concrete architecture symmetry in overcast weather #architecture #design #symmetry", "https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=800&q=80", 45),
    ]

    for author_uname, caption, img, target_likes in rich_posts:
        uid = creator_ids.get(author_uname, 1)
        cursor.execute("SELECT id FROM posts WHERE caption = ?", (caption,))
        existing_post = cursor.fetchone()
        if not existing_post:
            cursor.execute("""
                INSERT INTO posts (user_id, caption, image_url, likes_count)
                VALUES (?, ?, ?, 0)
            """, (uid, caption, img))

    # 5. Guaranteed Full Like Synchronization:
    # Every post's likes_count MUST strictly equal the count of real records in the `likes` table.
    import random
    cursor.execute("SELECT id FROM users WHERE status = 'ACTIVE'")
    all_active_uids = [r["id"] for r in cursor.fetchall()]

    cursor.execute("SELECT id, caption FROM posts")
    all_posts = cursor.fetchall()

    caption_target_map = {caption: target_likes for _, caption, _, target_likes in rich_posts}
    methods = ["BROWSER", "API"]

    for p in all_posts:
        pid = p["id"]
        cap = p["caption"]
        target = caption_target_map.get(cap, random.randint(20, 60))

        # Check existing likes in likes table
        cursor.execute("SELECT user_id FROM likes WHERE post_id = ?", (pid,))
        existing_likers = set(r["user_id"] for r in cursor.fetchall())

        needed = target - len(existing_likers)
        if needed > 0 and all_active_uids:
            candidates = [uid for uid in all_active_uids if uid not in existing_likers]
            to_insert = random.sample(candidates, min(needed, len(candidates)))
            for uid in to_insert:
                m = random.choice(methods)
                cursor.execute("""
                    INSERT OR IGNORE INTO likes (post_id, user_id, method, task_id)
                    VALUES (?, ?, ?, 'seed-history')
                """, (pid, uid, m))

        # Update posts.likes_count to match actual rows in likes table
        cursor.execute("SELECT COUNT(*) as c FROM likes WHERE post_id = ?", (pid,))
        actual_count = cursor.fetchone()["c"]
        cursor.execute("UPDATE posts SET likes_count = ? WHERE id = ?", (actual_count, pid))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
