"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401

CHECK = "label_format"


def run(ds, cfg):
    p = cfg["label_format"]
    tol = p["overflow_tol"]
    min_px = p["min_box_px"]
    max_frac = p["max_box_frac"]
    dup_iou = p["dup_box_iou"]
    n_classes = len(ds.classes)

    issues = []
    for img in ds.image_files():
        stem = img.stem
        lines = ds.read_label_lines(stem)     # [(số dòng gốc, nội dung)], đã bỏ dòng trống; None = không có file
        if lines is None:
            continue                           # thiếu file nhãn: việc của check missing_labels
        size = ds.image_size(stem)             # (W, H) px, None nếu ảnh hỏng
        seen = []                              # các box hợp lệ ở những dòng TRƯỚC: (lớp, (cx, cy, w, h))

        for no, text in lines:
            # 1) Cú pháp: phải đúng 5 cột số
            try:
                c, x, y, w, h = parse_yolo_line(text)
            except ValueError as e:
                issues.append(Issue(CHECK, ERROR, "BAD_FORMAT", stem, f"dòng sai định dạng ({e}): {text.strip()!r}", line=no))
                continue

            # 2) ID lớp phải nằm trong 0..n-1
            if not 0 <= c < n_classes:
                issues.append(Issue(CHECK, ERROR, "BAD_CLASS_ID", stem, f"id lớp {c} ngoài 0..{n_classes - 1}", line=no, extra={"id": c}))
                continue

            # 3) Box phải có diện tích
            if w <= 0 or h <= 0:
                issues.append(Issue(CHECK, ERROR, "BOX_ZERO", stem, f"box rỗng: w={w}, h={h}", line=no))
                continue

            box = (x, y, w, h)

            # 4) Tràn ảnh: mức tràn lớn nhất trong 4 mép
            overflow = max(0.0, -(x - w / 2), (x + w / 2) - 1, -(y - h / 2), (y + h / 2) - 1)
            if overflow > tol:
                issues.append(Issue(CHECK, ERROR, "BOX_OUT_OF_IMAGE", stem, f"box tràn ra ngoài ảnh {overflow:.4f}",
                                    line=no, extra={"overflow": round(overflow, 6)}))

            # 5) Box lặp: cùng lớp với một dòng trước và IoU > ngưỡng -> báo ở dòng này (dòng sau)
            for c_prev, b_prev in seen:
                if c_prev == c:
                    iou = iou_xywh(box, b_prev)
                    if iou > dup_iou:
                        issues.append(Issue(CHECK, ERROR, "DUP_BOX", stem, f"box lặp với dòng trước (IoU {iou:.3f})",
                                            line=no, extra={"iou": round(iou, 4)}))
                        break
            seen.append((c, box))

            # 6) Box quá nhỏ (theo pixel, cạnh ngắn) — cần kích thước ảnh
            if size is not None:
                W, H = size
                short = min(w * W, h * H)
                if short < min_px:
                    issues.append(Issue(CHECK, WARN, "BOX_TINY", stem, f"box nhỏ: cạnh ngắn {short:.1f}px < {min_px}px",
                                        line=no, extra={"short_px": round(short, 2)}))

            # 7) Box quá to (tỉ lệ diện tích ảnh)
            if w * h > max_frac:
                issues.append(Issue(CHECK, WARN, "BOX_HUGE", stem, f"box chiếm {w * h:.2%} ảnh > {max_frac:.0%}",
                                    line=no, extra={"area_frac": round(w * h, 4)}))
    return issues
