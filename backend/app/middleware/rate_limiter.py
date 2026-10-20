import time
from typing import Dict, Tuple, Optional
from fastapi import Request, HTTPException, status

class RateLimiter:
    def __init__(self, requests_per_minute: int = 120, enabled: bool = True):
        self.requests_per_minute = requests_per_minute
        self.enabled = enabled
        # Key -> list of request timestamps
        self.history: Dict[str, list] = {}

    def is_rate_limited(self, key: str) -> Tuple[bool, int, int]:
        """
        Returns (is_limited, current_count, retry_after_sec)
        """
        if not self.enabled:
            return False, 0, 0

        now = time.time()
        window_start = now - 60.0

        timestamps = self.history.get(key, [])
        # filter out timestamps older than window
        timestamps = [t for t in timestamps if t > window_start]

        if len(timestamps) >= self.requests_per_minute:
            oldest = timestamps[0]
            retry_after = max(1, int(60.0 - (now - oldest)))
            self.history[key] = timestamps
            return True, len(timestamps), retry_after

        timestamps.append(now)
        self.history[key] = timestamps
        return False, len(timestamps), 0

    def clear(self):
        self.history.clear()

global_rate_limiter = RateLimiter(requests_per_minute=120, enabled=True)
