# ============================================================
# Production Dockerfile — multi-stage, slim, non-root
# Build:  docker build -t agent .   (từ thư mục 06-lab-complete)
# ============================================================

# ── Stage 1: builder — cài dependencies vào một virtualenv ──
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
# Copy requirements trước để layer cài package được cache khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime — chỉ chứa venv + code, không có pip cache hay build tools ──
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1001 agent \
    && useradd --system --uid 1001 --gid agent --home-dir /app --shell /usr/sbin/nologin agent

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent app ./app
COPY --chown=agent:agent utils ./utils

USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=3)"

# sh -c "exec ..." để ${PORT} được thay thế mà uvicorn vẫn là PID 1 và nhận SIGTERM từ `docker stop`.
# --timeout-graceful-shutdown 8 < 10s mặc định của docker stop, tránh bị SIGKILL (exit 137).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
