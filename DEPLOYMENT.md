# Deployment Information

## Public URL

https://agent-production-f63dad29.up.railway.app

## Platform

Railway (project `k5-day14-agent`, environment `production`), deploy từ thư mục `06-lab-complete/` bằng Dockerfile multi-stage. Gồm hai service:

| Service | Nguồn | Vai trò |
|---------|-------|---------|
| `agent` | `06-lab-complete/Dockerfile` | FastAPI agent (uvicorn, 2 workers, user non-root) |
| `Redis` | Railway database template (`redis:8.2`) | Lưu state rate limit và cost guard, nối qua mạng nội bộ Railway |

Cấu hình deploy: [06-lab-complete/railway.toml](06-lab-complete/railway.toml) (`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`).

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên Railway (không ghi key vào repo).

```bash
BASE=https://agent-production-f63dad29.up.railway.app
export AGENT_API_KEY=<key đã đặt trên Railway>
```

### Health Check

```bash
curl -sS "$BASE/health"
# {"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":19.2,"timestamp":"..."}
```

### 4 lệnh tự kiểm của CP6 (chỉ in mã HTTP)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đã chạy (2026-11-26): `200`, `200`, `401`, `200`.

### API Test (with authentication)

```bash
curl -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05}}
```

### Rate limiting (`RATE_LIMIT_PER_MINUTE=10`)

Gửi 14 request liên tiếp bằng cùng một key: 8 request đầu `200` (2 request tự kiểm trước đó đã tính vào cùng cửa sổ 60 giây), các request sau `429`:

```text
200 200 200 200 200 200 200 200 429 429 429 429 429 429
HTTP/1.1 429 Too Many Requests
retry-after: 45
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
```

### Script chấm với URL public

```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://agent-production-f63dad29.up.railway.app
# Result: 12/12 tiêu chí đạt · 44/44 checks passed  →  PASS 12/12
```

## Environment Variables Set

Đặt trên service `agent` (không có giá trị bí mật nào trong repo):

| Biến | Giá trị / nguồn |
|------|-----------------|
| `PORT` | Railway tự cấp; `CMD` đọc `${PORT:-8000}` |
| `ENVIRONMENT` | `production` |
| `AGENT_API_KEY` | key ngẫu nhiên 43 ký tự, đặt qua CLI (không ghi trong repo) |
| `REDIS_URL` | tham chiếu `${{Redis.REDIS_URL}}` tới service Redis của cùng project |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `30.0` |
| `LOG_LEVEL` | `INFO` |

## Cách deploy (đã chạy)

```bash
cd 06-lab-complete
railway login
railway init --name k5-day14-agent
railway add --database redis
railway add --service agent --variables 'ENVIRONMENT=production' ... --variables 'REDIS_URL=${{Redis.REDIS_URL}}'
railway service link agent
railway variable set AGENT_API_KEY --stdin --service agent     # key đọc từ stdin, không nằm trong lệnh
railway up --ci --service agent
railway domain --service agent
```

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
