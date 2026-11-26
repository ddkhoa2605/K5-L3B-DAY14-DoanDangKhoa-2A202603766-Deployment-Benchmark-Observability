# Day 14 - Mission Answers

## Part 1 - Localhost vs Production

Môi trường chạy: WSL2 Ubuntu, `python -c "import os; print(os.name)"` → `posix`, Python 3.12.16.

### Exercise 1.1 - Anti-patterns trong `develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|--------------|------|---------|
| 1 | API key hardcode: `OPENAI_API_KEY = "sk-hardcoded-..."` | 17 | Push lên GitHub là lộ key, không đổi được key nếu không sửa code |
| 2 | Chuỗi kết nối DB có user/password hardcode: `DATABASE_URL = "postgresql://admin:password123@..."` | 18 | Lộ credential; dev và prod không thể dùng DB khác nhau |
| 3 | Config cứng, không đọc từ env: `DEBUG = True`, `MAX_TOKENS = 500` | 21-22 | Đổi cấu hình giữa dev/staging/prod phải sửa code và build lại |
| 4 | `print()` thay cho logging, và còn in ra secret: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 33-38 | Log không có level/timestamp/format JSON, khó tìm kiếm; secret rơi vào log aggregator |
| 5 | Không có health check (`/health`, `/ready`) | - | Platform không biết agent chết hay còn sống nên không tự restart được, load balancer không biết khi nào đưa traffic vào |
| 6 | Port cố định `port=8000` | 52 | Railway/Render inject `PORT` qua env, app bỏ qua nên platform không kết nối được |
| 7 | `host="localhost"` | 51 | Chỉ nhận kết nối từ chính máy đó; trong container sẽ không ai truy cập được từ ngoài |
| 8 | `reload=True` | 53 | Chế độ debug (theo dõi file, tạo process phụ) không nên chạy ở production |
| 9 | Không xử lý SIGTERM / graceful shutdown | - | Platform tắt container thì request đang xử lý bị cắt ngang |

Ngoài ra `/ask` nhận `question` qua query string thay vì JSON body, và không validate đầu vào.

### Exercise 1.2 - Chạy bản develop

Chạy trong WSL: `cd 01-localhost-vs-production/develop && python app.py`. Bản develop nhận `question` qua query (README mục Lưu ý số 3).

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Các kết quả khác khi gọi bản develop:

- `GET /` → `200 {"message":"Hello! Agent is running on my machine :)"}`
- `POST /ask` với JSON body `{"question":"Hello"}` → `422 Unprocessable Entity` (vì endpoint đòi query param)
- `GET /health` → `404` (không có health check)

Log của server cho thấy secret bị in thẳng ra:

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
```

Kết luận: chạy được và trả lời đúng, nhưng chưa production-ready (không có health check, lộ secret trong log, chỉ nghe trên localhost, port cố định).

### Exercise 1.3 - So sánh develop và production

Bản production chạy bằng `cp .env.example .env && python app.py`. Kết quả:

```text
GET  /health → 200 {"status":"ok","uptime_seconds":3.0,"version":"1.0.0","environment":"development",...}
GET  /ready  → 200 {"ready":true}
POST /ask (JSON {"question":"Hello"}) → 200 {"question":"Hello","answer":"Tôi là AI agent...","model":"gpt-4o-mini"}
POST /ask (JSON {}) → 422 (thiếu question)
SIGTERM → "Shutting down / Waiting for application shutdown / Application shutdown complete / Finished server process"
```

| Feature | Basic (`develop`) | Advanced (`production`) | Tại sao quan trọng? |
|---------|-------------------|-------------------------|---------------------|
| Config | Hardcode trong code (`app.py:17-22`) | Đọc từ env vars qua `Settings` dataclass (`config.py:17-35`), có `validate()` fail fast | Cùng một image chạy được ở dev/staging/prod chỉ bằng cách đổi env. Secret không nằm trong Git |
| Secrets | `OPENAI_API_KEY = "sk-..."` và in ra log | `os.getenv("OPENAI_API_KEY")`, không bao giờ log (`app.py:110-115` chỉ log độ dài câu hỏi) | Lộ key = mất tiền và dữ liệu. `.env` nằm trong `.gitignore`, chỉ commit `.env.example` |
| Host / Port | `localhost`, `8000` cứng (`app.py:51-52`) | `HOST=0.0.0.0`, `PORT` từ env (`config.py:17-18`, `app.py:196-197`) | Container phải bind `0.0.0.0` mới nhận được traffic từ ngoài; Railway/Render chọn port rồi inject vào `PORT` |
| Health check | Không có (404) | `GET /health` (liveness, `app.py:135`) và `GET /ready` (readiness, 503 khi chưa sẵn sàng, `app.py:152`) | Platform dựa vào `/health` để restart container chết, load balancer dựa vào `/ready` để không gửi traffic vào instance đang khởi động |
| Logging | `print()` kèm secret | Logging với level, format JSON, chỉ log metadata (`app.py:28-32`) | Log có cấu trúc để Datadog/Loki parse, lọc theo level, và không làm lộ secret |
| Shutdown | Tắt đột ngột | `lifespan` (`app.py:39-67`) + handler SIGTERM (`app.py:180-189`): đặt `is_ready=False`, chờ request đang chạy xong | Mỗi lần deploy/scale-down platform gửi SIGTERM; nếu cắt ngang thì user nhận lỗi và có thể mất dữ liệu |
| Debug / reload | `reload=True` cứng | `reload=settings.debug`, mặc định `DEBUG=false` (`app.py:198`) | Reload sinh process phụ và theo dõi file, không nên chạy ở production |
| Input | Query param, không validate | JSON body, trả 422 nếu thiếu `question` (`app.py:107-108`) | API thống nhất, từ chối đầu vào sai sớm |
| CORS | Không có | Chỉ cho phép origins cấu hình (`app.py:77-82`) | Chặn web lạ gọi API ngoài ý muốn |

### Câu hỏi thảo luận

1. **Push code có API key hardcode lên GitHub public thì sao?** Bot quét secret thường phát hiện key trong vài phút và có thể bị dùng ngay, dẫn đến mất tiền hoặc lộ dữ liệu. Xóa commit sau đó không đủ vì key đã nằm trong lịch sử Git và các bản fork, nên phải revoke key và tạo key mới.
2. **Tại sao stateless quan trọng khi scale?** Khi chạy nhiều instance sau load balancer, request tiếp theo có thể rơi vào instance khác. Nếu state nằm trong RAM của từng instance thì sẽ mất hoặc không nhất quán; state phải đưa ra ngoài (Redis/DB) để mọi instance đều đọc được và có thể bật/tắt tuỳ ý.
3. **Dev/prod parity nghĩa là gì?** Giữ môi trường dev càng gần production càng tốt (cùng loại backing service, cùng OS/runtime nhờ Docker, cùng cách cấu hình qua env), chỉ khác giá trị config. Nhờ đó lỗi "chạy được trên máy tôi" được phát hiện trước khi deploy.

### Phát hiện thêm khi chạy thật

Khi chạy bản production, log của app (`logger.info(json.dumps(...))`) **không xuất hiện**, chỉ thấy `WARNING:root:OPENAI_API_KEY not set — using mock LLM`. Nguyên nhân: `config.py:46` gọi `logging.warning(...)` khi import, lúc đó root logger chưa cấu hình nên Python tự gọi `basicConfig` mặc định (level WARNING, format thường). Sau đó `logging.basicConfig(...)` ở `app.py:28` không còn tác dụng, nên cả format JSON lẫn level INFO đều không được áp dụng. Cách sửa: gọi `basicConfig` trước khi import `config`, hoặc truyền `force=True`. Mình chưa sửa vì phần này là code mẫu của bài, nhưng nên nhớ khi viết `06-lab-complete`.

## Part 2 - Docker Containerization

Môi trường: WSL2 Ubuntu, Docker 29.4.0, Compose v5.1.1. Build từ gốc repo (README mục Lưu ý số 4).

### Exercise 2.1 - Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (dòng 8), bản Python đầy đủ gồm cả trình biên dịch và công cụ build.
2. **Working directory:** `/app` (dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong thư mục này.
3. **Tại sao `COPY requirements.txt` trước:** Docker cache theo từng layer. File requirements ít đổi, nên layer `pip install` (tốn thời gian nhất) được dùng lại từ cache khi chỉ sửa code. Nếu `COPY . .` đứng trước, mỗi lần sửa một dòng code sẽ làm layer đó và mọi layer sau nó mất cache, nên phải cài lại toàn bộ dependencies.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/đối số mặc định, dễ bị ghi đè khi chạy `docker run image <lệnh khác>`. `ENTRYPOINT` là chương trình cố định của container, tham số truyền khi `docker run` được nối thêm vào sau nó, muốn thay phải dùng `--entrypoint`. Dockerfile này dùng `CMD ["python", "app.py"]` nên có thể ghi đè để debug, ví dụ `docker run -it my-agent:develop sh`.

### Exercise 2.2 - Build và chạy bản develop

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name cp2-develop -p 8000:8000 my-agent:develop
```

```text
$ docker ps
NAMES         IMAGE              PORTS                                         STATUS
cp2-develop   my-agent:develop   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp   Up 4 seconds

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":3.9,"container":true}

$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ docker exec cp2-develop sh -c 'whoami; pwd; ls; python --version'
root
/app
__pycache__  app.py  requirements.txt  utils
Python 3.11.18

$ docker logs cp2-develop
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:32996 - "POST /ask?question=What%20is%20Docker%3F HTTP/1.1" 200 OK
```

Quan sát: app trong container nghe `0.0.0.0` (khác bản `localhost` ở Part 1) nên truy cập được từ host qua `-p 8000:8000`. Container chạy bằng user **root**, đây là điểm yếu bảo mật mà bản advanced sửa.

### Exercise 2.3 - Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`, dòng 16-29):** từ `python:3.11-slim`, cài `gcc`, `libpq-dev` rồi `pip install --user` vào `/root/.local`. Stage này có công cụ build, chỉ để biên dịch và cài dependencies, không dùng để deploy.
- **Stage 2 (`runtime`, dòng 36-72):** bắt đầu lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` (site-packages) và source code, tạo user không phải root `appuser`, thêm `HEALTHCHECK`, chạy `uvicorn` với 2 workers.
- **Tại sao nhỏ hơn:** image cuối không chứa `gcc`, apt cache, pip cache và những thứ của stage builder (các layer của builder bị bỏ đi). Quan trọng hơn là base khác nhau: bản develop dựa trên `python:3.11` đầy đủ, bản advanced dựa trên `python:3.11-slim`. Trong `docker history`, layer cài dependencies của develop là 53.3MB, còn layer copy site-packages của advanced là 40.8MB, nên phần chênh lệch lớn nằm ở base image chứ không phải ở dependencies.

Kích thước đo được:

```text
$ docker images
REPOSITORY:TAG        SIZE
my-agent:develop      1.67GB
my-agent:advanced     240MB
```

| Image | Size (`docker images`) | Size nén (`docker image inspect`) |
|-------|-----------------------:|----------------------------------:|
| `my-agent:develop` (single-stage, `python:3.11`) | 1.67 GB | 426 MB |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 240 MB | 57 MB |
| **Chênh lệch** | **giảm khoảng 86% (nhỏ hơn khoảng 7 lần)** | giảm khoảng 87% |

Hai cột khác nhau vì Docker 29 dùng containerd image store: `docker images` hiển thị dung lượng đã giải nén trên đĩa, còn `Size` trong `docker image inspect` là dung lượng nén. Số trong bài là số đo thực tế trên máy này, không phải số mẫu trong README (800 MB / 160 MB).

Chạy thử container advanced:

```text
$ docker run -d --name cp2-adv -p 8000:8000 my-agent:advanced
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ docker exec cp2-adv whoami
appuser
```

### Exercise 2.4 - Docker Compose stack (`02-docker/production/docker-compose.yml`)

Chạy: `touch .env.local` (file rỗng, đã nằm trong `.gitignore`) rồi `docker compose -p k5-day14-docker up -d --build`.

```text
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 6 seconds (healthy)    8000/tcp
nginx     nginx:alpine            Up 6 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 17 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 17 seconds (healthy)   6379/tcp
```

**Sơ đồ kiến trúc:**

```text
                     Host (máy bạn)
                          │  :80 / :443 (chỉ nginx mở cổng ra ngoài)
        ┌─────────────────▼───────────────────────────────────────┐
        │ network "internal" (bridge, DNS theo tên service)        │
        │                                                          │
        │   ┌─────────┐  proxy_pass   ┌─────────┐                  │
        │   │  nginx  ├──────────────►│  agent  │  FastAPI :8000   │
        │   │ (LB +   │ agent:8000    └───┬──┬──┘  (non-root,      │
        │   │ rate    │                   │  │      2 workers)     │
        │   │ limit)  │      redis:6379 ◄─┘  └─► qdrant:6333       │
        │   └─────────┘      ┌───────┐         ┌────────┐          │
        │                    │ redis │         │ qdrant │          │
        │                    └───┬───┘         └───┬────┘          │
        └────────────────────────┼─────────────────┼───────────────┘
                          volume redis_data   volume qdrant_data
```

**Các service được start:** `agent`, `redis`, `qdrant`, `nginx` (4 service).

**Cách chúng giao tiếp:**
- Cả 4 nằm trong mạng bridge `internal`, gọi nhau bằng **tên service** (Docker DNS). Đã kiểm tra: `getent hosts` trong container nginx ra `agent → 172.21.0.4`, `redis → 172.21.0.3`, `qdrant → 172.21.0.2`.
- Chỉ **nginx** publish cổng (80, 443) ra host. `agent`, `redis`, `qdrant` không mở cổng ra ngoài, nên client chỉ vào được qua nginx. Nginx là reverse proxy + load balancer (`upstream agent_backend`), giới hạn 10 req/s mỗi IP, thêm security headers.
- `agent` có `depends_on ... service_healthy` đối với redis và qdrant, nên agent chỉ khởi động sau khi hai service này healthy. `nginx` chỉ `depends_on: agent`.
- `redis` và `qdrant` có volume (`redis_data`, `qdrant_data`) để dữ liệu không mất khi container bị tạo lại.

Kết quả test qua Nginx:

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
{"status":"ok","uptime_seconds":5.6,"version":"2.0.0","timestamp":"2026-11-26T09:00:08.638704"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Header `Server: nginx` và các `X-*` cho thấy request đi qua nginx chứ không gọi thẳng agent. Thử thêm 40 request liên tiếp vào `/`: 23 request đầu trả 200, phần còn lại phần lớn trả **429** (rate limit `10r/s`, `burst=20`), đúng như cấu hình trong `nginx.conf`.

Sau khi test đã dọn bằng `docker compose -p k5-day14-docker down -v`, không còn container, volume hay network nào sót lại.

### Câu hỏi thảo luận

1. **Tại sao `COPY requirements.txt` rồi `RUN pip install` trước `COPY . .`?** Để tận dụng layer cache: dependencies hiếm khi đổi còn code đổi liên tục, nên lần build sau chỉ chạy lại từ bước `COPY` code mà không phải cài lại package.
2. **`.dockerignore` nên chứa gì?** `venv/`, `.venv/`, `__pycache__/`, `.git/`, `*.md`, tests, file IDE/OS. `.env` rất quan trọng vì nếu bị `COPY` vào image thì secret nằm trong layer, ai có image đều đọc được; `venv/` thì to, làm build context nặng và có thể ghi đè môi trường trong container bằng môi trường của máy host.
3. **Mount volume để agent đọc file từ đĩa:** `docker run -v $(pwd)/data:/app/data:ro ...`, hoặc trong Compose dùng `volumes: - ./data:/app/data:ro` (bind mount, thêm `:ro` nếu chỉ đọc) hay named volume cho dữ liệu cần lưu lâu dài như `redis_data`.

### Nhận xét thêm

- `docker-compose.yml` có khai báo `redis` và `qdrant`, nhưng `main.py` của agent không dùng chúng (không import redis/qdrant). Hai service này mới chỉ là hạ tầng chờ sẵn, và stack vẫn chạy bình thường khi không có chúng.
- Upstream của nginx chỉ có một `server agent:8000`. Khi `--scale agent=3` sẽ cần nginx phân giải tên `agent` ra nhiều IP, nội dung của Part 5.

## Part 3 - Cloud Deployment

## Part 4 - API Security

Môi trường: WSL2 Ubuntu, Python 3.12 (venv riêng `day14-p4`, vì `04-api-gateway/production` cần `pydantic>=2.11`). Token JWT đã được che (`<TOKEN>`).

### Exercise 4.1 - API Key authentication (`04-api-gateway/develop/app.py`)

- **API key được check ở đâu?** Hàm dependency `verify_api_key` (`app.py:39-54`) đọc header `X-API-Key` qua `APIKeyHeader(auto_error=False)` (dòng 36), rồi endpoint `/ask` gắn nó bằng `Depends(verify_api_key)` (dòng 70). Giá trị đúng lấy từ biến môi trường `AGENT_API_KEY` (dòng 35). `/` và `/health` không gắn dependency nên là public (platform cần gọi `/health`).
- **Sai key thì sao?** Thiếu header → **401** `Missing API key`; có header nhưng sai giá trị → **403** `Invalid API key`.
- **Rotate key thế nào?** Key không nằm trong code mà đọc từ env, nên chỉ cần đổi `AGENT_API_KEY` trên nền tảng rồi restart/redeploy, không phải sửa code hay build lại. Để đổi key mà không làm gián đoạn client, nên cho server chấp nhận **cả key cũ và key mới** trong một khoảng chuyển tiếp, báo client đổi sang key mới, rồi gỡ key cũ. Code hiện tại chỉ hỗ trợ một key nên phải có một khoảng ngắn client dùng key cũ bị từ chối.

Chạy bằng `AGENT_API_KEY=secret-key-123 python app.py`:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

`GET /health` không cần key → 200. Có key đúng nhưng body `{}` → 422 `question is required`.

Lưu ý: khi khởi động, `app.py:91` còn `print(f"API Key: {API_KEY}")`, tức là in secret ra log, trái với bài học ở Part 1. Và key mặc định `demo-key-change-in-production` (dòng 35) sẽ được dùng nếu quên đặt env, nên production nên bắt buộc có env (fail fast) thay vì rơi về giá trị mặc định.

### Exercise 4.2 - JWT authentication (`04-api-gateway/production/auth.py`)

Luồng JWT: client gửi `POST /auth/token` với username/password → server kiểm tra (`authenticate_user`) → ký token HS256 bằng `JWT_SECRET`, chứa `sub`, `role`, `iat`, `exp` (60 phút) → client gửi lại `Authorization: Bearer <token>` ở mỗi request → `verify_token` kiểm tra chữ ký và hạn rồi lấy ra user và role, không cần tra database ở mỗi request (stateless).

Tài khoản dùng trong bài là `student` / `demo123` (đúng theo README mục Lưu ý số 6).

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"sai"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN>..."}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <TOKEN>x" ...      # token bị sửa
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
{"question":"Explain JWT","answer":"Tôi là AI agent...","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

Giải mã phần payload của token (chỉ base64, không cần secret): `{"sub":"student","role":"user","iat":1795684311,"exp":1795687911}`. Điều này cho thấy payload **đọc được bởi bất kỳ ai**, chỉ **chữ ký** mới chống được việc sửa, nên không được để thông tin nhạy cảm trong JWT.

Các mã lỗi: thiếu token → 401; token hết hạn → 401 (`Token expired`); token sai/bị sửa → 403; body sai (`question` rỗng) → 422 nhờ Pydantic `Field(min_length=1, max_length=1000)`.

### Exercise 4.3 - Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** **Sliding Window** (log timestamp). Mỗi user có một `deque` các timestamp; mỗi request xoá timestamp cũ hơn `window_seconds` rồi đếm số còn lại, nếu `>= max_requests` thì trả 429 (`rate_limiter.py:35-62`).
- **Limit:** user thường **10 request/60 giây** (`rate_limiter_user`, dòng 86); admin **100 request/60 giây** (`rate_limiter_admin`, dòng 87).
- **Bypass cho admin:** không bypass hẳn mà đổi tier. Trong `app.py:141`, `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`, nên tài khoản `teacher` (role `admin`) được hạn mức 100 req/phút. Muốn không giới hạn thật thì phải bỏ qua `limiter.check()` cho role đó.

Vòng lặp 20 request bằng token của `student` (đã có 1 request thành công trước đó, tổng 10 request đầu thành công, request thứ 11 bị chặn):

```text
Request  1: 200 remaining= 8
...
Request  9: 200 remaining= 0
Request 10: 429  {"error": "Rate limit exceeded", "limit": 10, "window_seconds": 60, "retry_after_seconds": 59}
...
Request 20: 429  {"error": "Rate limit exceeded", "limit": 10, "window_seconds": 60, "retry_after_seconds": 59}
```

Response 429 đầy đủ (`curl -i`):

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795684373
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Header `Retry-After` cho client biết phải chờ bao lâu. Trong khi `student` bị chặn, `/health` vẫn trả 200. Với `teacher` (admin), 30 request liên tiếp đều 200. `/admin/stats` trả 403 `Admin only` với `student` và 200 với `teacher`.

**Hạn chế cần biết:** limiter lưu trong RAM của từng process. Chạy nhiều instance thì mỗi instance đếm riêng, nên hạn mức thực tế nhân lên theo số instance (ví dụ 3 instance → 30 req/phút), và restart là đếm lại từ 0. Muốn đúng khi scale phải dùng Redis (nội dung Part 5 và Part 6).

### Exercise 4.4 - Cost guard

**Cách `cost_guard.py` hoạt động:** mỗi user có một `UsageRecord` theo ngày (số token vào/ra, số request). Trước khi gọi LLM, `check_budget(user)` chặn nếu vượt hạn mức, sau khi gọi xong `record_usage` cộng token và tiền (đơn giá gpt-4o-mini). Có hai tầng bảo vệ:
- Budget **theo user**: $1/ngày; vượt → **402 Payment Required**; từ 80% thì ghi log cảnh báo.
- Budget **toàn hệ thống**: $10/ngày; vượt → **503** cho tất cả user (bảo vệ khi nhiều user cùng tiêu tiền).

Mỗi request mock chỉ tốn khoảng $0.00002 nên không thể chạm $1/ngày bằng tay. Để quan sát, mình tạo `CostGuard(daily_budget_usd=0.0005)` từ chính code của bài:

```text
req 1: OK  cost=$0.000135
req 2: OK  cost=$0.000270
req 3: OK  cost=$0.000405
req 4: OK  cost=$0.000540
req 5: HTTP 402 {'error': 'Daily budget exceeded', 'used_usd': 0.00054, 'budget_usd': 0.0005, 'resets_at': 'midnight UTC'}
global budget vượt → user khác chưa tiêu gì vẫn nhận: HTTP 503 Service temporarily unavailable ...
```

**Cài `check_budget(user_id, estimated_cost)` trên Redis** (budget $10/tháng, reset đầu tháng nhờ key chứa `YYYY-MM`). Mình chạy thật trên Redis 7 (container tạm), dùng phiên bản atomic:

```python
def check_budget(user_id: str, estimated_cost: float) -> bool:
    key = f"budget:{user_id}:{datetime.now().strftime('%Y-%m')}"
    new_total = r.incrbyfloat(key, estimated_cost)      # cộng trước (atomic)
    if new_total > 10:
        r.incrbyfloat(key, -estimated_cost)             # vượt thì trả lại
        return False
    r.expire(key, 32 * 24 * 3600)                       # key tự xoá sau 32 ngày
    return True
```

```text
estimated=$3.0: OK     spent=$3.00
estimated=$3.0: OK     spent=$6.00
estimated=$3.0: OK     spent=$9.00
estimated=$3.0: BLOCK  spent=$9.00     # 12 > 10, được trả lại
estimated=$0.5: OK     spent=$9.50     # vẫn còn chỗ cho request nhỏ hơn
TTL = 2764800 giây = 32 ngày;  user khác (bob) không bị ảnh hưởng
```

Khác với lời giải mẫu trong `CODE_LAB.md` (đọc `get` rồi so sánh rồi `incrbyfloat`): bước đọc và bước ghi tách rời, nên hai request đồng thời có thể cùng đọc "còn $5" rồi cùng được qua, làm vượt budget. Bản trên gộp bước cộng và đọc vào một lệnh `INCRBYFLOAT` atomic. Mình có chạy thử 20 thread đồng thời trên cả hai bản, nhưng kết quả hai bản giống nhau (đều nhận đúng 5 request), tức là **chưa tái hiện được race** trong thí nghiệm này; vì vậy đây là lập luận về thiết kế, không phải điều mình đã chứng minh bằng thực nghiệm.

**Lưu ý code mẫu:** trong `app.py:159` field `budget_remaining_usd` thực chất đang trả `usage.total_cost_usd`, tức số tiền **đã dùng** chứ không phải số còn lại (giá trị `1.9e-05` ở trên là đã dùng). Tên field gây hiểu nhầm, đúng ra phải là `budget_usd - total_cost_usd`.

### Câu hỏi thảo luận

1. **API Key vs JWT vs OAuth2:** API key phù hợp API nội bộ/B2B/MVP (đơn giản, một khoá một client, không có khái niệm user hay hết hạn). JWT khi cần danh tính và quyền theo user (role), stateless, có hạn dùng, dễ scale. OAuth2 khi cần cho phép bên thứ ba truy cập thay mặt user mà không đưa mật khẩu (đăng nhập bằng Google, tích hợp ứng dụng khác).
2. **Rate limit bao nhiêu cho AI agent?** Mỗi request tốn tiền và thời gian nên nên đặt thấp hơn API thường: khoảng 10-20 request/phút cho user thường, cao hơn cho tier trả phí, kèm giới hạn theo ngày. Rate limit bảo vệ **tốc độ** (chống spam, quá tải), còn cost guard bảo vệ **tiền**, cần cả hai vì một request dài và đắt vẫn có thể làm cháy budget dù tần suất thấp, còn spam nhiều request rẻ vẫn có thể làm sập server dù tiền không đáng kể.
3. **Key bị lộ thì sao?** Phát hiện qua: bot quét secret của GitHub (secret scanning), log/metrics bất thường (số request hay chi phí tăng đột ngột, IP lạ), cảnh báo budget. Xử lý: thu hồi/rotate ngay, kiểm tra log xem key đã bị dùng thế nào, đổi key mới qua env rồi redeploy, và xoá key khỏi lịch sử Git nếu nó từng bị commit (revoke vẫn là bước bắt buộc vì lịch sử đã bị sao chép).

### Nhận xét thêm về code mẫu

- `auth.py:22` có `JWT_SECRET` mặc định `super-secret-change-in-production-please`. Nếu quên đặt env thì ai biết giá trị này cũng tự ký được token hợp lệ (kể cả role `admin`). Production nên fail fast khi thiếu secret.
- `DEMO_USERS` lưu mật khẩu dạng plaintext trong code (`auth.py:27-30`), chỉ chấp nhận được cho demo; thực tế cần database và hash mật khẩu (bcrypt/argon2).
- So sánh với README: bản production kết hợp đủ lớp 401 → 429 → 422 → 402, và lớp cost guard nằm sau rate limiter để request bị chặn không tốn tiền.

## Part 5 - Scaling & Reliability

## Part 6 - Production Ready Checklist

## AI Log