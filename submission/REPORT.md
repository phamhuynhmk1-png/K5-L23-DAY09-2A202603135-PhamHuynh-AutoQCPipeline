# Báo cáo Day 09 — Phạm Huỳnh, 2A202603135

## 1. Kết luận trước
Pipeline kết luận **Release** (mã thoát 0). Vào **224** ảnh, intake nhận **202/224** (loại 22: CORRUPT_IMAGE 2, BAD_SIZE 3, DUP_IMAGE_EXACT 8, DUP_IMAGE_NEAR 4, LEAK_TEST 5), xuất **202** ảnh ra `submission/export/clean_v1`. Lý do: sau autofix và 80 ảnh người duyệt, `07_error_list_v3` còn **0 ERROR**, chỉ **16/202 ảnh (7.9%)** còn cảnh báo, dưới ngưỡng Hold 10%.

## 2. Lỗi và phân việc
Từ `02_error_list_v1` (dòng lỗi / số ảnh). Các mã intake (CORRUPT, BAD_SIZE, DUP_*, LEAK_TEST) bị loại ở bước 1.

| Mã lỗi | Số dòng / ảnh | Ai sửa | Vì sao |
|---|---:|---|---|
| CORRUPT_IMAGE, BAD_SIZE | 2 / 3 ảnh | máy (loại ảnh) | ảnh không đọc được / < 250 px, không dùng được |
| DUP_IMAGE_EXACT, DUP_IMAGE_NEAR | 8 / 4 ảnh | máy (loại ảnh) | trùng làm lệch phân phối, giữ 1 bản |
| LEAK_TEST | 5 ảnh | máy (loại ảnh) | trùng ảnh test → thổi phồng điểm đánh giá |
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX | 3 / 6 / 4 / 7 dòng | máy (drop_line, 20 dòng) | dòng hỏng hoặc thừa, không có cách sửa đúng ngoài xoá |
| BOX_OUT_OF_IMAGE | 8 dòng | máy (clip_box, 8) | chỉ tràn mép, cắt về [0,1] giữ được vật |
| BAD_CLASS_NAME | 2 tên (Person, Bus) | máy (rename_classes) | sai hoa/thường trong `data.yaml`, đổi tên là chắc chắn |
| MISSING_LABEL_FILE | 6 ảnh | **người** (NEEDS_LABEL) | máy không được bịa nhãn |
| POSSIBLE_MISSING / FALSE_POS / WRONG_CLASS / LOOSE_BOX | 32 / 29 (27 ảnh) / 14 / 12 | **người** | chỉ là nghi vấn từ model lớn, cần mắt người xác nhận |
| EMPTY_LABEL, BOX_TINY, BOX_HUGE, CLASS_RARE | 12 / 6 (4 ảnh) / 3 / 4 | **người** | cảnh báo quy tắc dự án, có thể hợp lệ |

Tổng 35 sửa máy (`03_fixes`): drop_line 20, clip_box 8, needs_label 6, rename_classes 1.

**Thứ tự hàng đợi:** `05_review_queue.csv` xếp theo tổng trọng số các mã trên ảnh. Đầu hàng là img_0020 (11.5 = FIXED_DROP_LINE 2 + MISSING 2 + WRONG_CLASS 3 + …), ngay sau là 6 ảnh NEEDS_LABEL (trọng số 10, vì không có nhãn thì ảnh vô dụng). Hàng đợi có **102 ảnh > ngân sách 80**. 80 ảnh đầu chứa **68 ảnh có lỗi ngữ nghĩa** (trên tổng 72 ảnh có lỗi ngữ nghĩa), tức người xem được ~94% số ảnh nghi lỗi ngữ nghĩa. 22 ảnh không được xem là ảnh điểm thấp (≤ 2.0, chủ yếu 1 FALSE_POS hoặc BOX_TINY).

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau, trên calib) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | **10** | DUP_IMAGE_NEAR 1.00/0.50 → 1.00/0.67 | Bắt thêm 2 cặp trùng thật trên raw (img_0223~img_0077 dist 6, đổi màu; img_0186~img_0061 dist 10, cắt + đổi màu) mà không xoá nhầm ảnh tốt. Từ 16 bắt đầu ra cặp sai (xem dưới). |
| `second_opinion.conf` | 0.25 | **0.8** | WRONG_CLASS 0.56/0.83 → **1.00/0.83**; MISSING 0.50/1.00 → 0.67/**0.75**; LOOSE 0.29/0.40 → 0.50/0.20 | Ở 0.25 mỗi cờ chỉ đúng ~1/2, 137/224 ảnh bị cờ, vượt xa ngân sách 80 → người mất thời gian vào báo động giả. 0.8 tăng precision rõ (WRONG_CLASS không còn báo sai) với **giá phải trả**: recall MISSING giảm 1.00 → 0.75 (bỏ sót 2/8 box thiếu ở calib), LOOSE recall còn 0.20. FALSE_POS (0.31/1.00) không đổi vì dùng `fp_conf` cố định. |

Ảnh hưởng trên raw (phash 10): conf 0.25 → hàng đợi 143 ảnh; 0.5 → 130; 0.7 → 118; 0.8 → 102. Tôi đã cân nhắc 0.7 (WRONG_CLASS P 0.62, MISSING R 0.88), chọn 0.8 vì WRONG_CLASS là mã có trọng số cao nhất (3) trong hàng đợi, báo sai ở đây đẩy ảnh sai lên đầu hàng.

**Chỗ calibration đánh lừa:** trên `data/calib`, `phash_dist = 16` cho kết quả *tốt nhất* (DUP_IMAGE_NEAR 1.00/0.83). Nhưng chạy trên raw, 16 làm LEAK_TEST tăng **5 → 11** và NEAR 4 → 7. Mở từng cặp: img_0011~img_0008 (đánh tennis vs trượt tuyết) và img_0177~img_0113 (lướt sóng vs người ngồi bàn) là **ảnh khác hẳn**, chỉ img_0084~img_0074 là trùng thật. Ở 20, LEAK_TEST lên 105 (loại gần nửa lô). Calib chỉ có ít cặp nên precision 1.00 ở đó không đại diện cho raw. Tôi chọn 10 và chấp nhận bỏ sót cặp dist 16.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Gate chặn đúng.** `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb` → kết luận **REWORK**, **mã thoát 20**. Không có người duyệt nên 6 MISSING_LABEL_FILE (ERROR) vẫn còn; thư mục `work/exp_nb` **không được tạo** (không xuất dataset).

**(b) Điểm mù (có bằng chứng):**
1. **Nhầm lớp mà model lớn cũng nhầm:** img_0002 có 2 box `person` gán sai, nhưng yolo26l cũng không phản đối → không có trong 04/05/06/07, lọt vào dataset.
2. **Ảnh phản chiếu:** img_0017 gán `person` cho người trong gương. Model lớn cũng thấy "người" ở đó nên label và dự đoán khớp → không cờ. Đây là lỗi guideline (có nên gán ảnh phản chiếu) mà model không biết.
3. **Ảnh trùng biến đổi mạnh:** cặp img_0084~img_0074 (dist 16) là trùng thật nhưng vượt ngưỡng 10 → vẫn nằm trong dataset.
4. **Do conf 0.8:** recall MISSING 0.75 và LOOSE 0.20 ở calib → box thiếu với conf model < 0.8 và box lỏng nhẹ phần lớn không bị cờ. 22 ảnh trong hàng đợi không được duyệt (budget).

## 5. Train: raw vs clean (tùy chọn)
yolo26n, 20 epoch, imgsz 640, seed 0 và 1, Colab T4.

| biến thể | #ảnh train | số seed | mAP50 | mAP50-95 | precision | recall |
|---|---|---|---|---|---|---|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 202 | 2 | 0.715 ± 0.019 | 0.492 ± 0.014 | 0.795 ± 0.018 | 0.606 ± 0.004 |

Chênh mAP50 (clean − raw) = **−0.011**, nhỏ hơn độ lệch chuẩn giữa seed của clean (0.019); clean seed 0 (0.729) còn cao hơn cả 2 seed raw (0.726), seed 1 (0.701) thấp hơn. ⇒ **Nằm trong nhiễu, chưa kết luận được** clean tốt hơn hay kém hơn.

Giả thuyết và cách kiểm:
1. **Rò rỉ test trong raw:** raw còn 5 ảnh LEAK_TEST trùng ảnh test → điểm raw bị thổi phồng. Kiểm: đánh giá lại trên test sau khi bỏ 5 ảnh test tương ứng.
2. **Clean ít dữ liệu hơn và lớp hiếm nhiễu:** clean ít hơn 22 ảnh (−10%); truck chỉ 30 box, AP50 truck dao động mạnh giữa seed (clean 0.613 / 0.564). Kiểm: thêm seed (≥ 5) và so theo từng lớp.
3. **Clean vẫn còn nhãn sai:** 22 ảnh hàng đợi chưa duyệt, 13 FALSE_POS còn lại, điểm mù §4b. Precision clean cao hơn (0.795 vs 0.764) nhưng recall thấp hơn (0.606 vs 0.649), có thể do xoá box làm ít box dương. Kiểm: duyệt hết hàng đợi rồi train lại.
4. **Test chỉ 100 ảnh:** chênh 0.01 mAP tương đương vài box. Kiểm: bootstrap trên test để có khoảng tin cậy.

## 6. Quyết định và ghi chú AI
**(a)** Quyết định cuối: **Release** dataset `clean_v1` (202 ảnh). Lưu ý cho đợt sau: duyệt nốt 22 ảnh còn lại trong hàng đợi và xử lý điểm mù img_0002 / img_0017 / img_0084~img_0074.

**(b) Có dùng AI (Claude Code).**
- **Prompt chính:** "hỗ trợ viết label_format / gate / autofix / second_opinion theo GUIDE rồi giải thích từng phần"; AI viết code, tôi yêu cầu giải thích từng bước bằng ví dụ thật trước khi chấp nhận.
- **Cách kiểm:** chạy `pytest` (79/79 qua), thử các edge case trong GUIDE, mở `work/viz` đối chiếu ảnh bị cờ, mở từng cặp ảnh ở các mức `phash_dist` trước khi chọn, chạy pipeline 2 lần để kiểm tái lập (chỉ khác `seconds`).
- **Một lần AI sai:** AI chạy `make run` trên Windows mà không lường trước pipeline ghi file CRLF trong khi repo lưu LF (`.gitattributes`), nên `manifest_sha1` local lệch với bản Colab dùng → phải đổi `manifest.json` về LF cho khớp. Ngoài ra `check_submission` báo `pipeline\calibrate.py` nhắc `MANIFEST`/`data/calib`: đây là file có sẵn, không sửa; báo nhầm do đường dẫn Windows dùng `\` không khớp danh sách file được bảo vệ.
