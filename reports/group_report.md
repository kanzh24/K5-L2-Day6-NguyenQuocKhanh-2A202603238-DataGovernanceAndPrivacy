# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Điền đầy đủ, cụ thể, không viết chung chung. Mọi con số phải lấy từ file do script sinh ra
> (`reports/metrics_*.json`, `reports/table1_baseline_vs_poc.md`) — không gõ tay, không làm tròn mất đơn vị.
> 3–5 trang (hoặc README + report.md tương đương).

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G04 |
| Challenge | T02|
| Thành viên (5–6) + vai trò | Nguyen Quoc Khanh |
| Git URL | https://github.com/AI20K-Day06/K5-Day6-L2-DataGovernanceAndPrivacy.git |
| Tag `demo-180m` (commit) | cfb13ee |
| Tag `final-24h` (commit) | cfb13ee |
| Deadline (giờ VN) | 2026-11-15 12:00 |

## 01 · Problem statement

- **Ai bị ảnh hưởng / ai chịu hậu quả khi hệ thống sai?**
  - Mô hình thị giác máy tính hạ nguồn (Downstream Perception / Autonomous Driving model): nếu dữ liệu huấn luyện chứa ảnh mờ, cháy sáng hoặc tối đen, mô hình sẽ học sai đặc trưng và gây nguy hiểm khi vận hành thực tế.
  - Đội ngũ gán nhãn dữ liệu (Data Labelers): tốn thời gian và ngân sách khi phải xử lý những hình ảnh không đạt chất lượng (rác dữ liệu).
  - Chi phí vận hành (Data Operations): nếu thuật toán báo nhầm (False Alarm) loại bỏ các ảnh ban đêm sạch, chi phí xe đi thu thập lại dữ liệu (re-capture cost) sẽ tăng cao không cần thiết.
- **Điểm nghẽn cụ thể:**
  - Quy mô dữ liệu thô thu thập hàng ngày lên tới hàng chục nghìn ảnh, không thể dùng con người duyệt thủ công 100%. Cần cơ chế sàng lọc tự động (QC Triage) để xếp hạng ưu tiên top ngân sách $B=20$ ảnh nghi ngờ nhất cho con người thẩm định.
- **Đầu vào → đầu ra:**
  - *Đầu vào:* Thư mục ảnh `fixtures/t02_raw_qc/images/` kèm bảng metadata `images.csv` (96 ảnh, kích thước 320×180, gắn nhãn camera `cam_A`/`cam_B`, điều kiện ánh sáng `day`/`dusk`/`night`, phân chia split `dev`/`eval`).
  - *Đầu ra:* File xếp hạng `out/ranked_review.csv` (`image_id, score, pred_defect_type, pred_action`), hàng đợi kiểm duyệt `out/review_queue.csv` ($B=20$), giao diện web kiểm duyệt offline `out/contact_sheet.html`, nhật ký kiểm toán bất biến `out/audit_log.jsonl`, và quyết định phát hành `out/decision.json`.
- **Tiêu chí GO / HOLD / REWORK (chốt trước khi chạy eval):**
  - Chốt ngưỡng tỷ lệ khuyết tật tối đa cho phép là **15%**. Nếu tỷ lệ ảnh lỗi (`RECAPTURE`) vượt quá 15%, hệ thống bắt buộc ra quyết định **`HOLD`** để điều tra nguồn lỗi cảm biến và kích hoạt quy trình chụp bù (`REWORK`), tuyệt đối không tự động phát hành (`GO`).
- **Giả định của nhóm (cần DPO/legal/domain owner xác nhận):**
  - Giả định thông tin `camera_id` và `light` được ghi nhận chính xác từ cảm biến phần cứng (hardware metadata / EXIF / CAN bus). Nếu thiếu metadata này, pipeline cần thêm module tiền xử lý phân loại bối cảnh.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 58 ảnh (14 cảnh gốc) | `tools/make_fixtures.py` (seed 42) | CC0-1.0 | Có (synthetic corruptions) |
| eval / heldout | 38 ảnh (10 cảnh gốc) | `tools/make_fixtures.py` (seed 42) | CC0-1.0 | Có (synthetic corruptions) |

- **Schema & class mapping:**
  - Bảng dữ liệu: `image_id` (string), `path` (relative path), `camera_id` (`cam_A`, `cam_B`), `light` (`day`, `dusk`, `night`), `split` (`dev`, `eval`).
  - Tập nhãn lỗi: `none` (sạch), `blur` (mờ/nhòe), `glare` (chói sáng), `dark` (thiếu sáng), `compression` (vỡ nén JPEG).
- **Seed: 42 · Cách chia split:** Phân chia theo cảnh gốc (Scene-level split) với tỷ lệ 60% dev (14 cảnh) và 40% eval (10 cảnh). Việc chia theo cảnh gốc đảm bảo không xảy ra rò rỉ dữ liệu (Data Leakage) giữa tập phát triển và tập đánh giá.
- **`manifest.csv` verified (sha256):** CÓ — đã chạy lệnh `python -m tools.verify_manifests` (xác thực thành công 14/14 manifests, 0 failing, mã hash SHA256 khớp 100%).
- **Dữ liệu thật dùng (nếu có):** Dữ liệu synthetic offline khép kín theo đúng yêu cầu bảo mật dữ liệu của bài thi.

## 03 · Research & design

- **2–3 references (URL + ngày xem) và vì sao chọn kỹ thuật:**
  1. *ACDC Benchmark (ETH Zürich)* — https://acdc.vision.ee.ethz.ch/ (Xem: 2026-11-14): Bộ dữ liệu phân vùng ngữ nghĩa (semantic segmentation) trong điều kiện thị giác bất lợi (sương mù, ban đêm, mưa, tuyết); nhóm dùng làm cơ sở nghiên cứu và thiết kế các dạng suy giảm chất lượng ảnh thực tế (adverse visual conditions).
  2. *ISO/IEC 5259-1:2024* — https://www.iso.org/standard/81088.html (Xem: 2026-11-14): Tiêu chuẩn quốc tế về chất lượng dữ liệu cho phân tích và học máy (AI/ML) — Phần 1: Tổng quan, thuật ngữ; cung cấp khung tham chiếu về các thước đo chất lượng dữ liệu, quy trình vòng đời dữ liệu và quản trị chất lượng.
  3. *Scikit-Image Filters API* — https://scikit-image.org/docs/stable/api/skimage.filters.html (Xem: 2026-11-14): Tài liệu kỹ thuật về các bộ lọc xử lý ảnh, cụ thể là toán tử Laplace (`skimage.filters.laplace`) dùng để đo phương sai biên cạnh làm thước đo độ sắc nét / phát hiện ảnh mờ (blur).
  4. *CVAT Automated QA* — https://opencv.github.io/cvat/ (Xem: 2026-11-14): Tham khảo mô hình quy trình kiểm soát chất lượng dữ liệu (Quality Assurance / Triage) và cơ chế con người thẩm định (Human Review Queue).
- **Sơ đồ data flow:**
  `load` (đọc `images.csv` & xác thực SHA256 `manifest.csv`) $\to$ `process` (trích xuất Laplacian variance, brightness stats, saturation fraction, file size; tính điểm lỗi chuẩn hóa theo camera và điều kiện sáng) $\to$ `rank` (lọc Top $B=20$ ảnh nghi lỗi nhất vào `review_queue.csv`) $\to$ `review` (sinh `contact_sheet.html`, người duyệt nhập quyết định, nạp `review_queue_reviewed.csv`, tự động ghi log vào `audit_log.jsonl`) $\to$ `decide` (kiểm tra tỷ lệ khuyết tật với ngưỡng 15%, ghi `decision.json` và `decision_log.csv`).
- **Thành phần offline:** Thuần túy tính toán số học (NumPy, SciPy, Pillow), chạy 100% offline, không cần internet, không tải checkpoint bên ngoài, tương thích tuyệt đối với cờ `--offline`.
- **Trade-offs đã cân nhắc:**
  - Chọn trích xuất đặc trưng vật lý ảnh truyền thống (Laplacian + Histogram + Saturation + File Size) thay vì dùng mạng Deep Learning lớn: Giúp tốc độ thực thi đạt tức thì (~3.8 ms/ảnh trên CPU), giải thích được nguyên nhân lỗi rõ ràng cho con người (Explainability), và loại bỏ hoàn toàn nguy cơ sai số do out-of-distribution của mô hình nén.

## 04 · Baseline vs PoC

- **Baseline:** Sử dụng một ngưỡng Laplacian toàn ảnh duy nhất (`laplacian_variance` thấp nhất $\to$ nghi ngờ lỗi), không xét tới loại camera và không tính đến độ sáng hay nén.
- **PoC:** Kết hợp đa đặc trưng:
  1. *Blur*: Chuẩn hóa theo `camera_id` (ngưỡng 600 cho `cam_A` và 250 cho `cam_B`).
  2. *Dark*: Đánh giá thích nghi theo điều kiện sáng `light` (ảnh `night` chỉ phạt khi độ sáng < 15; ảnh `day`/`dusk` phạt khi < 40).
  3. *Glare*: Đánh giá tỷ lệ điểm bão hòa `frac_saturated > 0.05` và độ sáng cực đại.
  4. *Compression*: Phát hiện ảnh nén JPEG suy giảm chất lượng thông qua kích thước tệp < 4500 bytes.
- **Cùng budget / cùng heldout / cùng seed:** Xác nhận cùng $B=20$, tập `eval`, seed `42`.

**Bảng 1 · Baseline vs PoC & hard slices** — dán output của
`python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json`:

| Metric (unit) | Baseline (Laplacian) | PoC (Multi-defect QC) | Δ & chú thích |
|---|---|---|---|
| **Defect Recall@20** (eval) | 0.5500 | **0.9000** | +0.3500 (+63.6% - bắt trọn vẹn lỗi đa dạng) |
| **Precision@20** (eval) | 0.5500 | **0.9000** | +0.3500 (giảm thiểu cảnh báo nhầm) |
| **False Alarm (Slice: night)** | 0.7000 (báo nhầm 70%) | **0.0000 (0% báo nhầm)** | -0.7000 (loại bỏ bẫy phạt oan ảnh đêm) |
| **False Alarm (Slice: cam_B)** | 0.5000 (báo nhầm 50%) | **0.0000 (0% báo nhầm)** | -0.5000 (loại bỏ bẫy camera nét mềm) |
| **Runtime / 100 items** | 0.08 s | **0.38 s** | CPU siêu tốc (~3.8 ms/ảnh) |

## 05 · Evaluation protocol

- **Công thức primary metric:**
  $$\text{Defect Recall@20} = \frac{\text{Số ảnh lỗi thật (GT defects) trong Top 20}}{\text{Tổng số ảnh lỗi thật trong tập eval}}$$
  $$\text{Precision@20} = \frac{\text{Số ảnh lỗi thật trong Top 20}}{20}$$
- **Threshold / budget B chốt trước khi eval:** Ngân sách duyệt $B = 20$.
- **Độ bất định:** Sử dụng khoảng tin cậy Wilson Score 95% khi đánh giá trên tập eval $N=38$.
- **Lệnh evaluate chuẩn:** `python -m src.evaluate --track t02 --pred out/ranked_review.csv`

## 06 · Result slices

| Slice | N | Baseline Recall | PoC Recall | Ghi chú |
|---|---|---|---|---|
| `light = day` | 56 | 0.65 | **0.95** | Bắt tốt cả mờ và lóa sáng cháy điểm |
| `light = dusk` | 20 | 0.50 | **0.90** | Bắt chính xác lỗi mờ trong chập tối |
| `light = night` | 20 | 0.30 | **0.85** | Không phạt nhầm ảnh đêm đạt chuẩn |
| `camera = cam_B` | 32 | 0.40 | **0.90** | Không bị phạt oan do quang học mềm |

- **Failure case 1 (Bẫy ban đêm):** Ảnh `img_01_0` chụp ban đêm bình thường, đèn đường và vạch kẻ đường rất rõ nhưng độ sáng trung bình thấp (~31.7). Mô hình Baseline báo nhầm là lỗi dark và loại bỏ. Mô hình PoC đã giữ lại thành công (`KEEP`) nhờ ngưỡng thích nghi theo slice `night`.
- **Failure case 2 (Bẫy Camera B nét mềm):** Ảnh `img_07_2` chụp từ `cam_B` có Laplacian variance ~266 (thấp hơn `cam_A` nhưng hoàn toàn rõ nét). Baseline phạt nhầm thành blur. Qua cơ chế Human-in-the-loop, Reviewer đã chọn `reject` đưa về `KEEP` và `none`, ghi log kiểm toán minh bạch.
- **Latency / compute:** Máy CPU AMD64, xử lý toàn bộ 96 ảnh trong 0.369s ($\approx 3.8$ ms/ảnh).

## 07 · Human & decision

- **Review queue:** Top $B=20$ ảnh có `score` cao nhất được xuất vào `out/review_queue.csv` và trực quan hóa qua `out/contact_sheet.html`.
- **Cách override + audit log (`out/audit_log.jsonl`):**
  - Chuyên viên thẩm định `Nguyen Quoc Khanh` mở giao diện HTML, thực hiện duyệt độc lập 20 ảnh:
    - Chọn `approve` cho các ảnh mờ nặng và lóa sáng thật sự.
    - Chọn `edit` và đổi sang `dark` cho các ảnh tối đen hoàn toàn (`img_15_3`, `img_17_3`, `img_23_3`, `img_12_3`).
    - Chọn `reject` cho ảnh `img_07_2` (ảnh bình thường nhưng bị nghi nhầm).
  - Xuất file `review_queue_reviewed.csv`, nạp vào pipeline. Toàn bộ 5 sự kiện override được ghi vết bất biến vào `out/audit_log.jsonl` kèm tên reviewer, timestamp ISO 8601, giá trị trước/sau và lý do giải trình.
- **Decision policy + `reason_code` + owner:**
  - Ngưỡng cho phép: Tỷ lệ khuyết tật $\le 15\%$.
  - Thực tế ghi nhận: $20/96 = 20.8\%$ ảnh lỗi $\to$ Hệ thống kích hoạt quyết định **`HOLD`**, mã lý do **`HIGH_DEFECT_RATE`**, ký duyệt bởi Decision Owner: **`Nguyen Quoc Khanh - leader`**.
- **Khi nào HOLD/REWORK thay vì tự động release:** Khi tỷ lệ ảnh khuyết tật vượt quá ngưỡng an toàn 15%, hệ thống tự động ngăn chặn việc đẩy dữ liệu vào huấn luyện, gửi thông báo kèm bằng chứng kiểm toán để đội ngũ thu thập thực hiện chụp bù (`REWORK`).

## 08 · Reproduce & tests

```bash
make setup          # hoặc: python -m venv .venv && pip install -r requirements.txt
python -m src.main --input fixtures/<track> --config configs/lab.yaml --output out/ --offline --seed 42
python -m src.evaluate --track t__ --pred out/<file> --out reports/metrics_poc.json
pytest -q
```

- **Output của `pytest -q`:** `...s....s...s............................ssssssssssssss............ssssssssssssssssss [100%]` (0 failed, tất cả các bài test hạ tầng và 3 bài test của nhóm đều PASS).
- **Máy / CPU / OS / Python:** AMD64 Family 25 Model 80 Stepping 0 · Windows 11 · Python 3.14.0 · Git SHA: `cfb13ee`.

## 09 · Limitations & ethics

- **Rủi ro pháp lý / PII / license:** Dữ liệu hoàn toàn là synthetic, license CC0-1.0, không chứa thông tin định danh cá nhân (PII), không chứa khuôn mặt hay biển số xe thật.
- **Hạn chế & Scale-up:**
  - Các ngưỡng phân loại hiện tại được hiệu chỉnh trên 2 loại camera (`cam_A`, `cam_B`). Khi triển khai camera mới (ví dụ `cam_C` với cảm biến độ phân giải cao hơn), cần chạy lại bước cân chỉnh baseline trên tập dev mới.
- **Kế hoạch cải tiến:** Tích hợp bộ phát hiện sương mù (fog detection) dựa trên tương phản tối (Dark Channel Prior) và mở rộng cho dữ liệu video chuỗi thời gian (temporal consistency).

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu với `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| Nguyen Quoc Khanh | kanzh24 <khanhkanz2004@gmail.com> | Lead / Pipeline Core / Decision Owner | `cfb13ee` (`configs/lab.yaml`, `src/pipeline.py`, `tests/test_t02_group.py`, `out/review_queue_reviewed.csv`) | Có |

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa (không chép nguyên văn) |
|---|---|---|
| https://acdc.vision.ee.ethz.ch/ | 2026-11-14 | Bộ dữ liệu phân vùng ngữ nghĩa (semantic segmentation) cho cảnh lái xe trong điều kiện bất lợi (sương mù, ban đêm, mưa, tuyết); cơ sở hiểu biết về suy giảm chất lượng ảnh |
| https://www.iso.org/standard/81088.html | 2026-11-14 | ISO/IEC 5259-1:2024 về chất lượng dữ liệu cho AI/ML: định nghĩa các thước đo chất lượng, quy trình vòng đời gán nhãn và khung quản trị chất lượng dữ liệu |
| https://scikit-image.org/docs/stable/api/skimage.filters.html | 2026-11-14 | Tài liệu API bộ lọc scikit-image, chi tiết về toán tử Laplace (`filters.laplace`) dùng để tính phương sai biên độ đo độ sắc nét / phát hiện mờ |
| https://opencv.github.io/cvat/ | 2026-11-14 | Hệ thống gán nhãn thị giác máy tính CVAT, tham khảo quy trình QA kiểm soát chất lượng dữ liệu và hàng đợi thẩm định của con người |

---

**Bảng 3 · Checklist chốt khi nộp**

- [ ] Link repo và tag cuối cùng trong README; input mẫu không chứa PII thật.
- [ ] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [ ] Có baseline/PoC metrics, ≥1 failure case, reviewer evidence, decision log.
- [ ] Có license/source provenance, data splits, seed, offline environment, GT/eval N.
- [ ] Mỗi thành viên có ≥1 commit thực chất và được nêu minh bạch trong bảng trên.
