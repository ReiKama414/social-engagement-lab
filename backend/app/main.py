import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import init_db
from app.middleware.inspector_middleware import InspectorMiddleware
from app.middleware.rate_limiter import global_rate_limiter
from app.routers import auth, posts, accounts, tasks, inspector, loadtest, ws, mock_social

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure SQLite tables and seed data exist
    init_db()
    yield
    # Shutdown logic if any

app = FastAPI(
    title="Social Engagement Automation Lab API",
    description="High-concurrency Social Media Automation & Interaction Research Platform",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Network Inspector & Lifecycle Middleware
app.add_middleware(InspectorMiddleware)

# Include Routers
app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(accounts.router)
app.include_router(tasks.router)
app.include_router(inspector.router)
app.include_router(loadtest.router)
app.include_router(ws.router)
app.include_router(mock_social.router)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Social Engagement Automation Lab",
        "rate_limiter_enabled": global_rate_limiter.enabled,
        "rate_limit_per_minute": global_rate_limiter.requests_per_minute
    }

@app.post("/api/config/rate-limit")
def configure_rate_limit(enabled: bool = True, requests_per_minute: int = 120):
    global_rate_limiter.enabled = enabled
    global_rate_limiter.requests_per_minute = requests_per_minute
    global_rate_limiter.clear()
    return {
        "success": True,
        "enabled": enabled,
        "requests_per_minute": requests_per_minute
    }

from app.chaos import chaos_config, set_chaos

@app.get("/api/config/chaos")
def get_chaos_config():
    return chaos_config

@app.post("/api/config/chaos")
def set_chaos_config(enabled: bool = False, delay_ms: int = 0, fail_rate: float = 0.0):
    updated = set_chaos(enabled, delay_ms, fail_rate)
    return {"success": True, "chaos": updated}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
