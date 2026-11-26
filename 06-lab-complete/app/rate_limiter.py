"""
Rate limiting (tiêu chí 7).

Sliding window log trên Redis sorted set: mỗi API key tối đa RATE_LIMIT_PER_MINUTE request / 60 giây.
State nằm trong Redis nên mọi worker / instance dùng chung và còn nguyên sau khi restart agent.
Toàn bộ thao tác chạy trong một script Lua để kiểm tra và ghi là atomic giữa các worker,
và dùng giờ của Redis để các instance không bị lệch đồng hồ.
"""
import hashlib
import math
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

_SLIDING_WINDOW = r.register_script(
    """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  if oldest[2] == nil then
    return {0, count, window}
  end
  return {0, count, tonumber(oldest[2]) + window - now}
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return {1, count + 1, 0}
"""
)


def check_rate_limit(key: str) -> None:
    redis_key = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    try:
        allowed, _, retry_ms = _SLIDING_WINDOW(
            keys=[redis_key],
            args=[WINDOW_SECONDS * 1000, settings.rate_limit_per_minute, uuid.uuid4().hex],
        )
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (Redis down)")

    if not allowed:
        retry_after = max(1, math.ceil(retry_ms / 1000))
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": settings.rate_limit_per_minute,
                "window_seconds": WINDOW_SECONDS,
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
            },
        )
