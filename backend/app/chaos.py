import random
import asyncio
from typing import Dict, Any, Tuple

# Global chaos simulator state
chaos_config: Dict[str, Any] = {
    "delay_ms": 0,
    "fail_rate": 0.0,
    "enabled": False
}

def get_chaos() -> Dict[str, Any]:
    return chaos_config

def set_chaos(enabled: bool = False, delay_ms: int = 0, fail_rate: float = 0.0) -> Dict[str, Any]:
    chaos_config["enabled"] = bool(enabled)
    chaos_config["delay_ms"] = max(0, min(2000, int(delay_ms)))
    chaos_config["fail_rate"] = max(0.0, min(0.5, float(fail_rate)))
    return chaos_config

async def evaluate_chaos_for_path(path: str) -> Tuple[bool, float]:
    """
    Evaluates whether chaos should be injected for an HTTP path.
    Returns: (should_inject_500: bool, injected_delay_ms: float)
    Exempts administrative, config, docs, and inspector polling routes.
    """
    if not chaos_config.get("enabled"):
        return False, 0.0

    # Exempt internal control endpoints so the user can always control tasks and turn chaos off
    exempt_prefixes = [
        "/api/config",
        "/api/inspector",
        "/api/tasks",
        "/api/ws",
        "/health",
        "/docs",
        "/openapi.json"
    ]
    if any(path.startswith(prefix) for prefix in exempt_prefixes):
        return False, 0.0

    delay_ms = float(chaos_config.get("delay_ms", 0))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)

    fail_rate = float(chaos_config.get("fail_rate", 0.0))
    should_fail = (random.random() < fail_rate) if fail_rate > 0 else False
    return should_fail, delay_ms
