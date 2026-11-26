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

## Part 3 - Cloud Deployment

## Part 4 - API Security

## Part 5 - Scaling & Reliability

## Part 6 - Production Ready Checklist

## AI Log