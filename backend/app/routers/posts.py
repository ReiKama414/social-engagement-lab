import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.database import get_db_connection
from app.models import PostResponse, CreatePostRequest, LikeResponse
from app.routers.auth import get_current_user, get_current_user_optional
from app.middleware.rate_limiter import global_rate_limiter
from app.routers.ws import manager

router = APIRouter(prefix="/api/posts", tags=["posts"])

@router.get("", response_model=List[PostResponse])
def get_posts(request: Request, current_user: Optional[dict] = Depends(get_current_user_optional)):
    user_id = current_user["id"] if current_user else 0
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id, p.user_id, p.caption, p.image_url, p.likes_count, p.created_at,
               u.username as author_username, u.display_name as author_display_name, u.avatar_url as author_avatar_url,
               CASE WHEN l.id IS NOT NULL THEN 1 ELSE 0 END as has_liked
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN likes l ON l.post_id = p.id AND l.user_id = ?
        ORDER BY p.id DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append(PostResponse(
            id=r["id"],
            user_id=r["user_id"],
            author_username=r["author_username"],
            author_display_name=r["author_display_name"],
            author_avatar_url=r["author_avatar_url"],
            caption=r["caption"],
            image_url=r["image_url"],
            likes_count=r["likes_count"],
            has_liked=bool(r["has_liked"]),
            created_at=str(r["created_at"])
        ))
    return results

@router.post("", response_model=PostResponse)
def create_post(req: CreatePostRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO posts (user_id, caption, image_url, likes_count)
        VALUES (?, ?, ?, 0)
    """, (current_user["id"], req.caption, req.image_url))
    post_id = cursor.lastrowid
    conn.commit()

    cursor.execute("""
        SELECT p.id, p.user_id, p.caption, p.image_url, p.likes_count, p.created_at,
               u.username as author_username, u.display_name as author_display_name, u.avatar_url as author_avatar_url
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
    """, (post_id,))
    r = cursor.fetchone()
    conn.close()

    return PostResponse(
        id=r["id"],
        user_id=r["user_id"],
        author_username=r["author_username"],
        author_display_name=r["author_display_name"],
        author_avatar_url=r["author_avatar_url"],
        caption=r["caption"],
        image_url=r["image_url"],
        likes_count=r["likes_count"],
        has_liked=False,
        created_at=str(r["created_at"])
    )

@router.get("/{post_id}", response_model=PostResponse)
def get_post(post_id: int, current_user: Optional[dict] = Depends(get_current_user_optional)):
    user_id = current_user["id"] if current_user else 0
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id, p.user_id, p.caption, p.image_url, p.likes_count, p.created_at,
               u.username as author_username, u.display_name as author_display_name, u.avatar_url as author_avatar_url,
               CASE WHEN l.id IS NOT NULL THEN 1 ELSE 0 END as has_liked
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN likes l ON l.post_id = p.id AND l.user_id = ?
        WHERE p.id = ?
    """, (user_id, post_id))
    r = cursor.fetchone()
    conn.close()

    if not r:
        raise HTTPException(status_code=404, detail="Post not found")

    return PostResponse(
        id=r["id"],
        user_id=r["user_id"],
        author_username=r["author_username"],
        author_display_name=r["author_display_name"],
        author_avatar_url=r["author_avatar_url"],
        caption=r["caption"],
        image_url=r["image_url"],
        likes_count=r["likes_count"],
        has_liked=bool(r["has_liked"]),
        created_at=str(r["created_at"])
    )

@router.post("/{post_id}/like", response_model=LikeResponse)
async def like_post(
    post_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    method: Optional[str] = "API",
    task_id: Optional[str] = None
):
    # 1. Rate Limiting Check
    rate_key = f"user_{current_user['id']}"
    is_limited, count, retry_after = global_rate_limiter.is_rate_limited(rate_key)
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after), "X-RateLimit-Current": str(count)}
        )

    # 2. SQLite Transaction
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check post existence
    cursor.execute("SELECT id, likes_count FROM posts WHERE id = ?", (post_id,))
    post = cursor.fetchone()
    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="Post not found")

    # Check duplicate like
    cursor.execute("SELECT id FROM likes WHERE post_id = ? AND user_id = ?", (post_id, current_user["id"]))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate action: User has already liked this post."
        )

    # Insert like and increment counter atomically
    cursor.execute("""
        INSERT INTO likes (post_id, user_id, method, task_id)
        VALUES (?, ?, ?, ?)
    """, (post_id, current_user["id"], method or "API", task_id))
    like_id = cursor.lastrowid

    cursor.execute("UPDATE posts SET likes_count = likes_count + 1 WHERE id = ?", (post_id,))
    cursor.execute("SELECT likes_count FROM posts WHERE id = ?", (post_id,))
    updated_post = cursor.fetchone()
    new_likes_count = updated_post["likes_count"]

    conn.commit()
    conn.close()

    # Annotate request state for Network Inspector
    request.state.db_delta = {
        "performed": True,
        "action": "INSERT_LIKE_INCREMENT_COUNT",
        "rows_affected": 2,
        "details": {
            "like_id": like_id,
            "post_id": post_id,
            "user_id": current_user["id"],
            "previous_count": post["likes_count"],
            "new_count": new_likes_count
        }
    }

    # Broadcast real-time update
    asyncio.create_task(manager.broadcast({
        "type": "post_liked",
        "data": {
            "post_id": post_id,
            "likes_count": new_likes_count,
            "user_id": current_user["id"],
            "username": current_user["username"],
            "method": method
        }
    }))

    return LikeResponse(
        success=True,
        post_id=post_id,
        likes_count=new_likes_count,
        action="liked",
        method=method or "API",
        user_id=current_user["id"]
    )

@router.post("/{post_id}/unlike", response_model=LikeResponse)
async def unlike_post(
    post_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    # Rate Limiting Check
    rate_key = f"user_{current_user['id']}"
    is_limited, count, retry_after = global_rate_limiter.is_rate_limited(rate_key)
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after), "X-RateLimit-Current": str(count)}
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, likes_count FROM posts WHERE id = ?", (post_id,))
    post = cursor.fetchone()
    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="Post not found")

    cursor.execute("SELECT id FROM likes WHERE post_id = ? AND user_id = ?", (post_id, current_user["id"]))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot unlike: User has not liked this post.")

    cursor.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?", (post_id, current_user["id"]))
    cursor.execute("UPDATE posts SET likes_count = MAX(0, likes_count - 1) WHERE id = ?", (post_id,))
    cursor.execute("SELECT likes_count FROM posts WHERE id = ?", (post_id,))
    updated_post = cursor.fetchone()
    new_likes_count = updated_post["likes_count"]

    conn.commit()
    conn.close()

    request.state.db_delta = {
        "performed": True,
        "action": "DELETE_LIKE_DECREMENT_COUNT",
        "rows_affected": 2,
        "details": {
            "post_id": post_id,
            "user_id": current_user["id"],
            "new_count": new_likes_count
        }
    }

    asyncio.create_task(manager.broadcast({
        "type": "post_unliked",
        "data": {
            "post_id": post_id,
            "likes_count": new_likes_count,
            "user_id": current_user["id"]
        }
    }))

    return LikeResponse(
        success=True,
        post_id=post_id,
        likes_count=new_likes_count,
        action="unliked",
        method="API",
        user_id=current_user["id"]
    )

@router.get("/{post_id}/likes")
def get_post_likes(post_id: int, limit: int = 50, offset: int = 0):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT l.id, l.post_id, l.user_id, l.method, l.task_id, l.created_at,
               u.username, u.display_name, u.avatar_url, u.group_tag
        FROM likes l
        JOIN users u ON l.user_id = u.id
        WHERE l.post_id = ?
        ORDER BY l.id DESC
        LIMIT ? OFFSET ?
    """, (post_id, limit, offset))
    rows = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) as total FROM likes WHERE post_id = ?", (post_id,))
    total = cursor.fetchone()["total"]
    conn.close()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows]
    }

@router.post("/seed")
def seed_more_posts(count: int = 6):
    """Seed additional diverse mock posts into the social feed with synchronized likes records."""
    import random
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE status = 'ACTIVE'")
    user_rows = cursor.fetchall()
    all_user_ids = [r["id"] for r in user_rows] if user_rows else [1]

    extra_posts = [
        ("Coffee art and mechanical switch typing sounds on a rainy afternoon #coffeetime #productivity", "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=800&q=80"),
        ("Tokyo train network speed and neon city lights at midnight #citylife #tokyo #subway", "https://images.unsplash.com/photo-1542051841857-5f90071e7989?auto=format&fit=crop&w=800&q=80"),
        ("Clean code architecture & domain driven design patterns #softwareengineering #cleanarchitecture", "https://images.unsplash.com/photo-1498050108023-c5249f4df085?auto=format&fit=crop&w=800&q=80"),
        ("Foggy morning walk through Jiufen old street lanterns #taiwan #jiufen #travelphotography", "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=800&q=80"),
        ("Dark mode dev workstation setup with Ergodox mechanical keyboard #coding #workspace #minimal", "https://images.unsplash.com/photo-1527689368864-3a821dbccc34?auto=format&fit=crop&w=800&q=80"),
        ("Testing Playwright Chromium worker concurrency with zero dropped frames #playwright #qa", "https://images.unsplash.com/photo-1515378791036-0648a3ef77b2?auto=format&fit=crop&w=800&q=80")
    ]

    methods = ["BROWSER", "API"]
    created = 0
    for i in range(min(count, len(extra_posts))):
        caption, img = extra_posts[i]
        author_id = random.choice(all_user_ids)
        target_likes = random.randint(15, 60)

        cursor.execute("""
            INSERT INTO posts (user_id, caption, image_url, likes_count)
            VALUES (?, ?, ?, 0)
        """, (author_id, caption, img))
        new_post_id = cursor.lastrowid

        # Insert real likers into likes table
        liker_candidates = random.sample(all_user_ids, min(target_likes, len(all_user_ids)))
        for uid in liker_candidates:
            m = random.choice(methods)
            cursor.execute("""
                INSERT OR IGNORE INTO likes (post_id, user_id, method, task_id)
                VALUES (?, ?, ?, 'seed-batch')
            """, (new_post_id, uid, m))

        cursor.execute("SELECT COUNT(*) as c FROM likes WHERE post_id = ?", (new_post_id,))
        actual_likes = cursor.fetchone()["c"]
        cursor.execute("UPDATE posts SET likes_count = ? WHERE id = ?", (actual_likes, new_post_id))
        created += 1

    conn.commit()
    conn.close()
    return {"success": True, "created_count": created, "message": f"Successfully seeded {created} more posts with synchronized likes"}

