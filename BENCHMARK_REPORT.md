# Benchmark & Observability Report — Day 14

> Mọi con số trong file này lấy từ report JSON trong [reports/](reports/) (bản gốc ở `06-lab-complete/benchmark-observability/develop/reports/`). Phần 4–6 (Observability stack, scaling) làm ở CP8 nên chưa điền.

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

*(Điền ở CP8.)*

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Điền ở CP8.)*

## 6. Kết luận

*(Điền khi hoàn thành CP8.)*
