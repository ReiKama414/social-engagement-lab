from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- Auth Models ---
class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    group_tag: Optional[str] = "standard"

class LoginRequest(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: str
    status: str
    group_tag: str
    created_at: str

class AuthResponse(BaseModel):
    token: str
    user: UserResponse
    expires_at: str

class ExpireSessionRequest(BaseModel):
    token: Optional[str] = None
    username: Optional[str] = None

# --- Post Models ---
class CreatePostRequest(BaseModel):
    caption: str
    image_url: str

class PostResponse(BaseModel):
    id: int
    user_id: int
    author_username: str
    author_display_name: str
    author_avatar_url: str
    caption: str
    image_url: str
    likes_count: int
    has_liked: bool = False
    created_at: str

class LikeResponse(BaseModel):
    success: bool
    post_id: int
    likes_count: int
    action: str # "liked" or "unliked"
    method: str = "API"
    user_id: int

# --- Account Models ---
class BatchAccountCreateRequest(BaseModel):
    count: int = Field(..., ge=1, le=10000, description="100, 1000, 5000, 10000")
    group_tag: Optional[str] = "batch"
    prefix: Optional[str] = "bot"
    pre_generate_sessions: bool = True

class BatchAccountActionRequest(BaseModel):
    account_ids: Optional[List[int]] = None
    group_tag: Optional[str] = None
    status: Optional[str] = None # filter
    action: str # "enable", "disable", "expire_sessions", "delete"

class AccountStatsResponse(BaseModel):
    total_accounts: int
    active_accounts: int
    disabled_accounts: int
    expired_sessions: int
    group_counts: Dict[str, int]

# --- Task & Automation Models ---
class CreateTaskRequest(BaseModel):
    type: str = "PLAYWRIGHT" # "PLAYWRIGHT" or "API_BENCHMARK"
    post_id: int
    total_accounts: int = 10
    concurrency: int = 2 # Worker pool limit
    delay_ms: int = 200
    group_tag: Optional[str] = None
    headless: bool = True

class TaskControlRequest(BaseModel):
    action: str # "start", "pause", "resume", "cancel"

class TaskStatusResponse(BaseModel):
    id: str
    type: str
    post_id: int
    total_accounts: int
    concurrency: int
    delay_ms: int
    status: str # PENDING, RUNNING, PAUSED, COMPLETED, CANCELLED
    success_count: int
    failure_count: int
    created_at: str
    updated_at: str
    error_summary: Optional[str] = None

class TaskLogItem(BaseModel):
    id: int
    task_id: str
    user_id: Optional[int]
    username: Optional[str]
    status: str
    duration_ms: float
    error_message: Optional[str]
    created_at: str

# --- Load Testing Models ---
class StartLoadTestRequest(BaseModel):
    post_id: int
    account_count: int = 1000
    concurrency: int = 50
    group_tag: Optional[str] = None
    rate_limit_per_worker: Optional[int] = 0 # 0 means unlimited

class LoadTestMetricResponse(BaseModel):
    running: bool
    total_requests: int
    success_count: int
    failure_count: int
    rps: float
    avg_latency_ms: float
    p50_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    db_writes_per_sec: float
    duration_sec: float
    errors_breakdown: Dict[str, int]
