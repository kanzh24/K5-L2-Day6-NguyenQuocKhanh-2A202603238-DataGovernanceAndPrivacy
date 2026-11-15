# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T02 |
| Primary metric (tên đúng như evaluator in ra) | Defect Recall@B (B=20, trên split eval) |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | image |
| Công thức + numerator / denominator | Defect Recall@B = GT defects in top-B / Total GT defects; kèm Precision@B = GT defects in top-B / B |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | Khớp theo khóa `image_id` |
| Candidate pool cố định | 96 ảnh synthetic từ 24 cảnh gốc (`fixtures/t02_raw_qc/images.csv`), độ phân giải 320×180 |
| Review budget B / K | B = 20 |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Chỉnh hoàn toàn trên split `dev`: blur threshold chuẩn hóa theo `camera_id` (cam_A: 600, cam_B: 250); dark threshold theo điều kiện ánh sáng (`night`: mean < 15, `day`/`dusk`: mean < 40); glare fraction > 0.05; compression file_size < 4500 bytes. Cố định toàn bộ trước khi eval. |
| Eval split (không dùng để tune) | eval (40% số cảnh gốc, 38 ảnh, heldout) |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | False alarm in top-B theo slice `light` (day, dusk, night) |
| Slices sẽ báo cáo (≥2) | 1. Slice điều kiện chiếu sáng `light` (day, dusk, night); 2. Slice phần cứng `camera_id` (cam_A, cam_B); 3. Phân bố loại lỗi `defect_type` (blur, dark, glare, compression) |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Wilson score interval 95% cho tỷ lệ Recall@B và False alarm rate |
| Ngày giờ chốt + người chốt | 2026-11-15 08:00 (UTC+7) · Nguyen Quoc Khanh  |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
