"""
Production AI Agent — Part 6 Final Project.

Luồng /ask: API key (401) → rate limit (429) → cost guard (402) → LLM → ghi nhận chi phí.
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask

VERSION = "1.0.0"
START_TIME = time.time()


# ──────────────────────────────────────────────────────────
# Structured logging: mỗi dòng log là một JSON object
# ──────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    # Log của uvicorn cũng đi qua JSON; access log được thay bằng middleware bên dưới.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False


setup_logging()
logger = logging.getLogger("agent")


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ──────────────────────────────────────────────────────────
# App + lifecycle (graceful shutdown)
# ──────────────────────────────────────────────────────────
_ready = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Không tự đăng ký handler SIGTERM: uvicorn đã bắt SIGTERM, đóng cổng, chờ request đang chạy
    # xong rồi mới chạy phần shutdown dưới đây. Handler tự viết sẽ ghi đè và làm process không tắt.
    global _ready
    _ready = True
    log_event(
        "startup",
        environment=settings.environment,
        version=VERSION,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd,
    )
    yield
    _ready = False
    close_redis()
    log_event("shutdown")


app = FastAPI(
    title="Production AI Agent",
    version=VERSION,
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.error(
            "unhandled_exception",
            exc_info=True,
            extra={"fields": {"method": request.method, "path": request.url.path}},
        )
        raise
    log_event(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - start) * 1000, 1),
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Liveness: luôn 200 khi process còn chạy, kể cả khi Redis chưa kết nối được."""
    # async def và không có I/O: chạy thẳng trên event loop nên không phải xếp hàng sau các /ask đang giữ threadpool.
    return {
        "status": "ok",
        "version": VERSION,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness: 503 khi đang khởi động/tắt hoặc Redis không kết nối được."""
    if not _ready:
        raise HTTPException(status_code=503, detail="Agent not ready")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not available")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    log_event(
        "ask",
        question_chars=len(body.question),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 8),
    )
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": round(cost, 8)},
    }
