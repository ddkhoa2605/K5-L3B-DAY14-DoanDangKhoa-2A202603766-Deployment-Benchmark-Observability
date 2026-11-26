# Benchmark & Observability Report — Day 14

> Mọi con số trong file này lấy từ report JSON trong [reports/](reports/) (bản gốc ở `06-lab-complete/benchmark-observability/develop/reports/`). Phần 4–6 là CP8 (Observability stack, scaling, kết luận).

**Họ tên:** Đoàn Đăng Khoa
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 + WSL2 (Ubuntu), AMD Ryzen 7 6800H (16 luồng), 7.5 GB RAM cấp cho WSL2, Python 3.12.16. Agent và công cụ tải (`load_test.py`) chạy **trên cùng một máy**, mỗi bên là một process Python. Mock LLM, không gọi API thật.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency bình thường của agent khoảng 190 ms (p50), nên 500 ms cho khoảng 2.6 lần dư địa cho jitter và hàng đợi. Đặt theo p95 (không phải trung bình) để một phần nhỏ request chậm vẫn bị tính. Ngưỡng này cũng cho thấy giới hạn: một request "chậm bất thường" tốn khoảng 1.7 s, nên khi hơn khoảng 5% request chậm thì p95 vượt SLO (xem 2.2) |
| Error rate `/ask` | < 2 % | Mock LLM chủ động lỗi khoảng 1% (`MOCK_ERROR_RATE`, trả 503) nên SLO phải lỏng hơn mức lỗi nền đó, nhưng đủ chặt để phát hiện lỗi tăng gấp đôi. Với mẫu 300 request, 1% chỉ là khoảng 3 lỗi nên số đo dao động từ 0% đến 1.7% giữa các lần chạy |
| Accuracy trên golden dataset | ≥ 85 % | Bằng ngưỡng của job CI (`--min-accuracy 0.85`). Với 23 câu, mỗi câu sai làm accuracy giảm 4.3 điểm %, nên 85% cho phép tối đa 3 câu sai |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Mỗi mức: 300 request (không tính request warm-up), agent v2 mặc định (`MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`), lưu vào `reports/load_v2_c{N}.json`.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.13 | 186.8 | 220.5 | 1697.8 | 0.00% (300×200) | PASS |
| 10 | 38.2 | 189.9 | 218.5 | 1663.4 | 1.33% (4×503) | PASS |
| 50 | 125.78 | 197.2 | 256.3 | 1684.2 | 0.67% (2×503) | PASS |
| 100 | 134.59 | 210.8 | 333.8 | 1681.4 | 1.67% (5×503) | PASS |

**Nhận xét:** RPS **không tăng tuyến tính** trên toàn dải. RPS theo concurrency gần đúng định luật Little: RPS ≈ concurrency / latency trung bình. Với `c=1`: 1 / 0.2423 s = 4.13 req/s, khớp đúng số đo. Lên `c=10` thì RPS gấp 9.2 lần (gần tuyến tính, vì request chờ nhau rất ít), nhưng từ `c=50` trở lên đường cong phẳng dần: `c=50` → `c=100` RPS chỉ tăng từ 125.78 lên 134.59 (gấp 1.07 lần dù concurrency gấp đôi) và p95 tăng từ 256 ms lên 334 ms. Lưu ý các đợt chạy ở `c ≥ 50` chỉ kéo dài khoảng 2.2–2.4 giây, trong đó có cả đoạn khởi động và đuôi chờ request chậm nhất (1.7 s), nên RPS ở các mức này bị đánh giá thấp.

Để biết nguyên nhân, mình chạy thêm tải ổn định 15 giây (`--duration 15`, **không lưu trong `reports/`**) và đo CPU:

| Concurrency | RPS (ổn định) | p95 (ms) | CPU server | CPU `load_test.py` |
|---|---|---|---|---|
| 50 | 198.25 | 221.9 | khoảng 28% | khoảng 25% |
| 100 | 111.14 | 3212.9 | khoảng 14% | khoảng 97% |
| 200 | 65.11 | 6762.3 | khoảng 12% | 100% |

Từ `c=100` trở lên, **nút thắt là chính công cụ tải**: một process Python dùng một lõi CPU ở mức 97–100%, trong khi agent chỉ dùng khoảng 12–14% một lõi. Latency "đo được" ở các mức này (p95 hàng nghìn ms) phần lớn là thời gian request chờ trong event loop của client, không phải thời gian server xử lý. Vì vậy mình **không** kết luận được sức chịu tải thật của server từ `load_test.py` ở `c ≥ 100`; số `c=1…50` đáng tin hơn (ở `c=50` tải ổn định đạt 198 req/s với p95 222 ms, gần với dự đoán 50 / 0.2367 s ≈ 211 req/s). Phép đo CPU là một lần lấy mẫu `top`, chỉ để chỉ hướng. Muốn đo sức chịu tải server cần công cụ tải mạnh hơn (Locust headless nhiều worker, ở CP8).

### 2.2 Tail latency

Agent v2, `--requests 300 --concurrency 20`. Mỗi hàng là lần chạy chính được lưu trong `reports/load_v2_slow_{rate}.json`; hai lần lặp lại (không lưu, cùng lệnh) cho thấy mức dao động của mẫu:

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | SLO p95 ≤ 500 | Lặp lại #2 / #3 (avg, p95, p99) |
|---|---|---|---|---|---|
| 0 | 189.8 | 217.3 | 223.3 | PASS | 189.0/216.5/222.3 · 190.6/217.9/221.7 |
| 0.03 (mặc định) | 259.7 | 231.4 | 1705.2 | PASS | 219.8/220.5/1687.9 · 281.3/**1675.0**/1714.2 |
| 0.1 | 321.0 | 1688.8 | 1714.3 | **FAIL** (exit code 1) | 359.1/1688.8/1713.9 · 400.4/1697.0/1713.2 |

**Nhận xét:**
- **p99 nhạy nhất.** Chỉ cần 3% request chậm, p99 nhảy từ khoảng 223 ms lên khoảng 1700 ms (gấp 7.6 lần), vì p99 nằm ngay trong vùng 1% request chậm nhất. Request chậm trong mock tốn thêm 1500 ms nên p99 lúc nào cũng quanh 1.7 s khi tỉ lệ chậm vượt 1%.
- **p95 là "bậc thang" theo tỉ lệ chậm.** p95 chỉ nhảy lên 1.7 s khi hơn 5% request chậm. Ở 3%, hai trong ba lần chạy p95 vẫn khoảng 220–231 ms, nhưng lần lặp #3 p95 = 1675 ms vì mẫu 300 request ngẫu nhiên có hơn 5% request chậm. Điều đó nghĩa là **SLO p95 đặt gần ngưỡng sẽ lúc xanh lúc đỏ** với cùng một cấu hình; ở 10% thì cả 3 lần đều đỏ.
- **avg tăng tuyến tính và che mất vấn đề.** Từ 190 ms lên khoảng 254 ms (trung bình 3 lần, mức 3%) và khoảng 360 ms (mức 10%), khớp dự đoán `190 + tỉ lệ × 1500 ≈ 235 và 340 ms`. Ở mức 3%, avg chỉ tăng khoảng 33% trong khi p99 tăng gấp 7.6 lần, nên nhìn avg sẽ tưởng gần như bình thường trong khi cứ 100 người thì 3 người chờ gần 2 giây.
- **Vì sao SLO không nên đặt theo average:** avg là một số trung hoà, một nhóm nhỏ người dùng rất chậm bị "pha loãng" bởi đa số người dùng nhanh. SLO theo percentile (p95/p99) mô tả trải nghiệm của nhóm kém nhất và là thứ người dùng thật phàn nàn.

### 2.3 Exercise 7.1 — Đọc metrics

Gọi `POST /ask` rồi `GET /metrics` trên agent v2 (cổng 8002):

- **Counter** (chỉ tăng): `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total{type="input"} 91.0`, `llm_cost_usd_total 4.665e-05`.
- **Gauge** (lên xuống): `agent_in_flight_requests 0.0`, `agent_info{model="mock-llm-small",version="v2"} 1.0`.
- **Histogram** (bucket + `_count` + `_sum`): `http_request_duration_seconds_bucket{le="0.2",route="/ask"}`, `llm_request_duration_seconds_*`, và metric mình thêm `agent_question_length_chars_*` (`_count 1`, `_sum 40.0`).

**Vì sao `route` dùng `route.path` thay vì URL thật?** Mình gọi 3 URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`); middleware gộp cả ba vào **một** series: `http_requests_total{method="GET",route="unmatched",status="404"} 3.0`. Nếu dùng `request.url.path`, mỗi URL lạ là một giá trị label mới nên một bot quét hàng nghìn đường dẫn sẽ sinh hàng nghìn time series (mỗi series của histogram còn nhân thêm hơn 10 bucket), làm Prometheus tốn RAM và truy vấn chậm. Đây chính là vấn đề cardinality.

**Nhiệm vụ thêm metric:** đã thêm `QUESTION_LENGTH = Histogram("agent_question_length_chars", ..., buckets=(20, 50, 100, 200, 500, 1000, 2000))` và `QUESTION_LENGTH.observe(len(body.question))` trong `develop/app.py`. Dùng Histogram thay vì label `length=...` vì độ dài có vô số giá trị.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Golden dataset 23 câu; chấm bằng keyword (đúng khi chứa ≥ 60% `expected_keywords`).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.5 | 109.1 | 113.7 |
| Tổng cost (USD) | 0.00041 | 0.000762 | 0.00079 |
| Cost / câu đúng (USD) | 0.00040995 | 0.00003627 | 0.00003436 |
| Quality gate | FAIL (accuracy < 80%) | PASS | PASS (`--min-accuracy 1.0`, 0 regression) |

(File: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.)

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key?") | `token`, `hết hạn`, `chữ ký` | Câu trả lời lúc đó là câu chung chung của mock vì knowledge base không có tài liệu về JWT. Thêm entry `["jwt"]` vào `KNOWLEDGE_BASE` (`develop/utils/mock_llm.py`) nói rõ: API key cố định và không tự hết hạn; JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn |
| `scaling-03` ("Kubernetes HPA scale dựa trên chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry `["hpa", "kubernetes", "autoscal"]` nói HPA scale theo CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi |

Sau khi sửa, tắt rồi bật lại agent v2 (app không tự nạp lại code), chạy eval với `--baseline reports/eval_v2.json --min-accuracy 1.0`: **23/23, 2 câu được cải thiện, 0 regression, Quality gate ✅ PASS**. Khi thêm entry mới, mình kiểm tra nó không "cướp" các câu khác: retrieval chọn tài liệu theo số keyword trùng và entry mới đứng cuối danh sách, nên chỉ thắng khi câu hỏi chứa đúng keyword của nó; 0 regression xác nhận điều đó.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- Chất lượng tăng vọt: 4.3% lên 91.3% (rồi 100% sau khi sửa), vì v2 có bước retrieval đưa tài liệu vào prompt.
- Chi phí mỗi **câu** gần như gấp đôi: avg tokens 57.5 lên 109.1 (+90%), tổng cost 0.00041 lên 0.000762 (+86%) vì prompt dài hơn.
- Nhưng chi phí mỗi **câu đúng** giảm khoảng **11.3 lần** (0.00040995 xuống 0.00003627 USD): v1 tốn tiền cho gần như toàn câu sai. Đây là lý do "cost / câu đúng" tốt hơn "cost / câu" khi so hai phiên bản: nếu chỉ nhìn cost/câu sẽ kết luận nhầm là v2 "đắt hơn".
- Latency p95 gần như không đổi (204.9 ms lên 218.6 ms, +13.7 ms, khoảng +7%), phần chênh là bước retrieval giả lập khoảng 20 ms.
- Hạn chế: eval chỉ có 23 câu nên số latency ở đây chỉ để tham khảo (latency phải đo bằng load test, mục 2). Và việc sửa KB bằng đúng keyword mà dataset mong đợi là "học vẹt theo bài kiểm tra": 100% trên golden dataset không chứng minh agent trả lời tốt các câu ngoài tập đó.

### 3.1 Quality gate và CI (Exercise 7.3)

- Chạy eval v1 với `--baseline reports/eval_v2.json`: báo **20 câu regression** (v2 đúng, v1 sai) và accuracy 4.3%; **exit code = 1** (đo trực tiếp bằng `echo $?`), nên dùng được làm cổng chặn.
- `run_eval.py` thoát với exit code 1 khi accuracy dưới `--min-accuracy` **hoặc** có regression so với `--baseline`, và 0 khi đạt. Kiểm tra với `--min-accuracy 0.85`: v1 → exit 1, v2 (đã sửa) → exit 0.
- Job CI: [.github/workflows/eval.yml](.github/workflows/eval.yml). Job chạy agent v2 với `MOCK_ERROR_RATE=0` (để lỗi giả lập 1% không làm eval dao động), chờ `/health`, rồi chạy `python eval/run_eval.py --min-accuracy 0.85 --baseline ../../../reports/eval_v2_fixed.json`. Step fail → job fail → PR bị chặn (cần bật "Require status checks to pass" cho job `eval` trong branch protection). Mình đã chạy thử đúng các lệnh của job ở máy local: exit code 0, 0 regression, YAML hợp lệ; job chưa chạy trên GitHub Actions thật.

---

## 4. Observability stack (production)

Stack `06-lab-complete/benchmark-observability/production/` chạy bằng `docker compose -p k5-day14-observability` (2 agent + Nginx + Prometheus + Grafana + Jaeger + Locust). Tải nền: Locust headless, 30 user (7.4) rồi 15 user (7.6, lý do ở 4.2). Mọi số liệu dưới đây lấy từ Prometheus API / Jaeger API / log container lúc chạy.

**Lỗi gặp khi dựng stack:** hai agent crash-loop (`Restarting (1)`, `ModuleNotFoundError: No module named 'uvicorn'`). Nguyên nhân: `Dockerfile` copy package vào `/home/agent/.local` nhưng user `agent` có `HOME=/app`, nên Python tìm user-site ở `/app/.local` và không thấy package. Sửa bằng cách thêm `ENV PYTHONUSERBASE=/home/agent/.local` (bản `05-scaling-reliability` đã có dòng này). Cũng chép 2 entry `KnowledgeBase` (HPA, JWT) từ `develop/` sang `production/utils/mock_llm.py` để stack đạt 100% eval.

### 4.1 Screenshot

Thư mục ảnh: `screenshots/` (tên file theo `SUBMISSION.md`).

- [x] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với 2 alert cùng **firing**: `screenshots/prometheus-alert-firing.png` (thấy `agent-slo: FIRING (2)`: `AgentHighErrorRate` và `AgentHighLatencyP95`)

Ảnh được chụp bằng Chromium headless (Playwright) trên đúng các trang Grafana/Jaeger/Prometheus của stack đang chạy, không phải ảnh dựng. Ảnh phụ: `screenshots/grafana-dashboard-incident.png` (dashboard lúc hai lỗi đang bật).

### 4.2 Thí nghiệm "phá hệ thống"

Thời gian tính từ lúc chạy lệnh `docker compose up -d` đổi cấu hình (tạo lại container mất khoảng 2 giây). Đo bằng cách hỏi `GET /api/v1/alerts` của Prometheus mỗi 3 giây; kết quả đã làm tròn theo giây. `scrape_interval` = 5 s, `for` của mỗi rule: lỗi 1m, p95 2m, instance down 30s, cost 2m.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending sau 29 s, **firing sau 89 s** (lặp lại ở lần chạy đồng thời với B: 89 s). Error rate từ 1% lên 20.2% | "Error rate" (stat) và "Requests/s theo status code" (đường 503); trace lỗi trong Jaeger |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | pending sau 29 s, **firing sau 149 s** (lần chạy cùng A: 146 s). p95 từ 0.29 s lên 1.92 s, avg chỉ từ 0.23 s lên 0.65 s | "Latency /ask p50/p95/p99": khoảng cách giữa avg và p95/p99; throughput tụt từ 18.9 xuống 14.7 req/s |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | Chạy sạch (15 user, chi phí nền 1.37 $/giờ): pending sau 39 s, **firing sau 159 s**. Chi phí lên 10.07 $/giờ lúc kết thúc và còn đang tăng vì cửa sổ `rate[5m]` chưa đầy; p95 từ 0.29 s lên 0.67 s | "LLM cost (1h)" và "Cost burn rate (USD/giờ)"; p95 tăng khoảng 2.3 lần vì model lớn chậm hơn 2.5 lần |
| D | `docker pause` 1 instance | `AgentInstanceDown` | pending sau 12 s, **firing sau 42 s** (= 12 s + `for: 30s`) | "Instances up" (từ 2 xuống 1). Panel Error rate vẫn xanh (0.77%) dù Nginx trả 16 lỗi 504 cho client |
| E | `AGENT_VERSION=v1` | **Không có** | không firing | "Retrieval hit ratio" biến mất (không còn request retrieval), tokens/s giảm từ 1099 xuống 527 (-52%), chi phí giảm từ 1.13 xuống 0.73 $/giờ. Các panel Golden Signals vẫn xanh |

**Ghi chú về thiết kế thí nghiệm (quan trọng để đọc đúng bảng):**
- **Chi phí nền đã sát ngưỡng alert.** Ở tải 30 user Locust (khoảng 18.7 req/s, model small) chi phí là **2.39 $/giờ ổn định**, cao hơn ngưỡng 2 $/giờ của `LLMCostBurnRateHigh`, nên alert này **firing ngay cả khi hệ thống khỏe** (mình xác nhận bằng cách tính tay từ tokens/s: 1409 token vào/s × 0.00015 + 735 token ra/s × 0.0006, mỗi 1000 token, bằng 2.39 $/giờ). Vì vậy lần chạy C đầu tiên ở 30 user (firing sau 149 s, chi phí lên 18.8 $/giờ) bị lẫn với alert nền và **không dùng làm số đo C**; mình giảm tải xuống 15 user (chi phí nền 1.37 $/giờ, dưới ngưỡng), chờ alert nền tắt rồi chạy lại C, D, E trong điều kiện sạch. A và B không phụ thuộc chi phí nên giữ nguyên số đo ở 30 user (và đã đo lại ở 15 user: 89 s và 146 s, gần như trùng).
- **Tác dụng phụ khi áp dụng cấu hình:** mỗi lần tạo lại container, `AgentInstanceDown` hiện `pending` khoảng 8–12 giây (target biến mất khỏi DNS rồi quay lại) nhưng không `firing` vì chưa đủ 30 giây.
- Hoàn tác xong thì alert tắt sau: A 53 s, B 56 s, D 6 s, nhưng C mất **290 s** (cửa sổ `rate[5m]` phải trôi hết dữ liệu chi phí cao).
- **D và nginx:** trong lúc pause, Nginx trả cho client 769 × 200, 6 × 503 (lỗi LLM nền) và **16 × 504** (khoảng 2% tổng request), trong khi `err_rate` của agent chỉ 0.77%. Lỗi 504 xảy ra ở Nginx (chờ quá `proxy_read_timeout` 10 s), request chưa bao giờ được agent xử lý xong nên metric của agent không đếm.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

E là lỗi **chất lượng**, không phải lỗi hạ tầng: latency, error rate và số instance đều khỏe (thậm chí p95 giảm từ 0.30 s xuống 0.20 s, chi phí giảm 35% vì v1 không có retrieval), nên không có rule hạ tầng nào bắt được. Mình chạy `run_eval.py` thẳng vào stack lúc đang ở v1 (qua Nginx, có API key): **accuracy 4.3% (1/23), exit code 1**, và sau khi hoàn tác về v2: **100% (23/23), exit code 0**. Cách phát hiện trong thực tế:
1. **Eval trên golden dataset** chạy trong CI trước khi deploy (job `.github/workflows/eval.yml`) và chạy định kỳ (hoặc ngay sau deploy, như phép thử ở trên) vào bản đang chạy thật.
2. **Metric nghiệp vụ/chất lượng làm alert**: ví dụ `agent_retrieval_total{result="hit"}` — ở thí nghiệm E, tỉ lệ hit trở thành `NaN` (series biến mất); một rule kiểu `absent(...)` hoặc "hit ratio < 90%" sẽ bắt được ngay dù không alert hạ tầng nào đỏ.
3. **Đánh giá mẫu trên traffic thật** (LLM-as-judge hoặc người chấm trên 1–5% request) và **tín hiệu từ người dùng** (thumbs up/down, tỉ lệ hỏi lại, khiếu nại).
4. Metric phiên bản (`agent_info{version=...}`) để biết lỗi chất lượng bắt đầu từ lần deploy nào.

### 4.3 Debug bằng trace

Trace chậm nhất trong 1500 trace `POST /ask` lấy được từ Jaeger (stack lúc đó chạy 30 user):

- `trace_id`: `987d42d0440cb1b928a4045d724373cc`
- Tổng thời gian: **1722.1 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1695.5 ms, 98.5%**), với `gen_ai.usage.input_tokens=95`, `gen_ai.usage.output_tokens=55`. `agent.retrieve_context` chỉ 23.8 ms (1.4%). Kết luận: request chậm vì **LLM upstream**, không phải code của agent.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T10:22:37.711155+00:00", "level": "INFO", "service": "observable-agent", "instance": "956c5d40850c", "event": "llm_call", "trace_id": "987d42d0440cb1b928a4045d724373cc", "span_id": "a7c23a415c00b9af", "request_id": "8aa0395ee002", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1695.2}
{"ts": "2026-11-26T10:22:37.711631+00:00", "level": "INFO", "service": "observable-agent", "instance": "956c5d40850c", "event": "http_request", "trace_id": "987d42d0440cb1b928a4045d724373cc", "span_id": "a7c23a415c00b9af", "request_id": "8aa0395ee002", "method": "POST", "route": "/ask", "status": 200, "ms": 1721.5}
```

Log ghi `llm_ms=1695.2` và `ms=1721.5`, khớp với span (1695.5 ms và 1722.1 ms).

**Trace lỗi** (tag lỗi, có event `exception`): `trace_id` `dd28d112214d356c7713ce2494dcb9d7`, 111.6 ms, `POST /ask` trả **503**; span `chat mock-llm-small` có `error.type=upstream_unavailable` và event `exception` với `exception.type=utils.mock_llm.LLMError`, `exception.message=Upstream LLM error: 503 Service Unavailable (mock)`. Trong 1500 trace có 24 trace lỗi (1.6%). **Từ log sang trace:** lấy `trace_id` `a0b1e991dfea411661688f4681229dcc` từ dòng log `llm_error` mới nhất của container, dán vào Jaeger thì tìm thấy đúng trace 4 span có `status=ERROR`.

**Trả lời 4 câu hỏi của Exercise 7.4** (đo lúc 30 user, sau khoảng 2 phút):
1. p95 = **0.294 s**, avg = **0.234 s**, p99 = **1.84 s**. p95 chỉ cao hơn avg khoảng 25%, nhưng p99 gấp khoảng 7.9 lần avg: khoảng cách đó chính là tail latency do khoảng 3% request chậm (1.7 s), avg che mất vì bị pha loãng.
2. Có chia đều: **9.31 và 9.24 req/s** cho hai instance (Nginx round-robin).
3. Input tokens/s (**1409**) lớn hơn output tokens/s (**735**) vì prompt gồm system prompt + tài liệu retrieval được chèn vào + câu hỏi, còn output chỉ là câu trả lời ngắn.
4. `curl http://localhost:8080/metrics` trả **404**: `nginx.conf` chặn `/metrics` từ bên ngoài (`location = /metrics { return 404; }`) vì metric lộ thông tin hệ thống (route, lưu lượng); Prometheus scrape trực tiếp từng agent trong mạng nội bộ nên không bị ảnh hưởng. Mình cũng chạy `promtool test rules alert_rules_test.yml`: **SUCCESS**.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh: `docker compose -p k5-day14-observability run --rm locust ... --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_{1,3}`. Dòng `/ask` trong `benchmark-results/scale_{1,3}_stats.csv`. Mỗi agent bị giới hạn 0.5 CPU và 256 MB (theo `docker-compose.yml`).

| Số instance | RPS (`/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.51 (cả `/health`: 66.28) | 190 | 230 | 1700 | 76 / 7228 (1.05%) |
| 3 | 59.86 (cả `/health`: 65.97) | 190 | 230 | 1700 | 76 / 7152 (1.06%) |

Toàn bộ 76 lỗi ở mỗi lần là `POST /ask: HTTPError('503 Server Error: Service Unavailable')` (lỗi LLM upstream giả lập khoảng 1%, theo `scale_*_failures.csv`).

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không cải thiện gì**: RPS, p95 và p99 gần như y hệt. Lý do:
- **Tải là vòng kín có thời gian nghĩ**: mỗi user chờ 0.5–2 s (trung bình khoảng 1.25 s) giữa các lần hỏi, nên RPS bị quyết định bởi số user chứ không bởi số instance: `100 / (1.25 + 0.23) ≈ 67 req/s`, đúng bằng số đo (66 req/s). Một agent đã đủ xử lý 100 user với p95 230 ms, nghĩa là **chưa hề bão hòa**, nên thêm instance không có gì để giải quyết. Muốn thấy lợi ích của scale phải tăng tải đến mức một instance quá tải (nhiều user hơn hoặc `wait_time` ngắn hơn).
- **Nút thắt của p99 nằm ở LLM, không phải agent**: p99 1700 ms là thời gian của request "chậm bất thường" của mock LLM (khoảng 3%, +1500 ms). Thêm agent không làm LLM nhanh hơn; xem panel "LLM latency p95 theo model" và span `chat ...` chiếm 98.5% thời gian của trace chậm (mục 4.3).
- Scale còn có giá trị khác ngoài tốc độ: **chịu lỗi** (thí nghiệm D: pause 1 trong 2 instance, hệ thống vẫn phục vụ, chỉ có một lượng nhỏ 504) — nhưng giá trị đó không hiện ra trong bảng RPS/p95.
- Hạn chế: mỗi cấu hình chỉ chạy một lần 2 phút nên chênh lệch nhỏ (ví dụ 60.51 và 59.86 req/s, hai lần đều đúng 76 lỗi) nằm trong dao động ngẫu nhiên, không kết luận gì từ đó.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Percentile quan trọng hơn trung bình, và phải đo bằng công cụ đủ mạnh.** Cùng một hệ thống, avg 0.23 s trông ổn nhưng p99 1.84 s; với 10% request chậm thì p95 đỏ trong khi avg chỉ tăng gấp 1.7 lần. Ngoài ra `load_test.py` (một process Python) tự nó trở thành nút thắt ở `c ≥ 100` (CPU 97–100% trong khi server chỉ 12–14%), nên số đo cũng cần được kiểm tra bằng cách xem **ai** đang bão hòa chứ không phải tin ngay vào con số.
  2. **Hạ tầng xanh không có nghĩa là agent tốt.** Thí nghiệm E (v1) làm accuracy rơi từ 100% xuống 4.3% mà không alert hạ tầng nào kêu (và thậm chí p95/chi phí còn tốt lên). Eval trên golden dataset và metric nghiệp vụ (retrieval hit ratio) mới bắt được. Tương tự, thí nghiệm D cho thấy metric chỉ phản ánh điều *chính service đó* nhìn thấy: 16 lỗi 504 ở Nginx không hiện trên error rate của agent.
  3. **Ngưỡng alert phải được kiểm tra với tải bình thường.** `LLMCostBurnRateHigh` (> 2 $/giờ) firing ngay ở tải nền 30 user (2.39 $/giờ), tức là alert vô nghĩa vì lúc nào cũng đỏ, và nhóm sẽ học cách bỏ qua nó (alert fatigue). Cũng vì thế mình phải giảm tải để đo C cho sạch. Ngưỡng nên tính từ chi phí nền thực tế (baseline) cộng biên độ, hoặc dùng mức tăng so với baseline.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

  - **Giám sát ở tầng load balancer / synthetic check từ bên ngoài** (tỉ lệ 5xx và 504 của Nginx, blackbox probe gọi `/ask` thật), vì metric của agent không thấy lỗi 504 (thí nghiệm D).
  - **Alert chất lượng**: `agent_retrieval_total` hit ratio thấp hoặc series biến mất (`absent`), accuracy của eval định kỳ trên bản đang chạy, và tỉ lệ phản hồi tiêu cực của người dùng.
  - **Alert p99** và/hoặc tỉ lệ request chậm (> 1 s) bên cạnh p95, vì p95 chỉ đổi màu khi hơn khoảng 5% request chậm nên dễ lúc xanh lúc đỏ ở gần ngưỡng.
  - **Budget tuyệt đối theo ngày/tháng và theo user** (kèm cảnh báo ở 80%), thay vì chỉ tốc độ đốt tiền theo giờ; đồng thời đặt lại ngưỡng burn-rate cho đúng với baseline.
  - **Saturation của agent**: CPU throttling của container (giới hạn 0.5 CPU), `agent_in_flight_requests`, và độ trễ hàng đợi; kèm **dashboard lỗi theo `instance`** và `up` của từng target.
  - Alertmanager để gửi cảnh báo thật (Slack/PagerDuty): stack hiện chỉ hiện alert trên trang Prometheus, không có ai được báo.
