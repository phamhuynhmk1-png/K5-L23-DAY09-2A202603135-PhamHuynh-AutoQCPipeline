"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401

CHECK = "second_opinion"


def _labels_with_line_numbers(ds, stem):
    """[(số dòng gốc, id_lớp, (cx, cy, w, h))] của các dòng nhãn HỢP LỆ; dòng hỏng / id lạ bị bỏ qua (check khác báo)."""
    out = []
    for no, text in ds.read_label_lines(stem) or []:
        try:
            c, x, y, w, h = parse_yolo_line(text)
        except ValueError:
            continue
        if 0 <= c < len(ds.classes):
            out.append((no, c, (x, y, w, h)))
    return out


def run(ds, cfg, preds=None):
    p = cfg["second_opinion"]
    conf_min, min_area = p["conf"], p["min_area_px"]
    fp_conf = p["fp_conf"]
    iou_missing, iou_match, iou_loose = p["iou_missing"], p["iou_match"], p["iou_loose"]

    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    issues = []
    for img in ds.image_files():
        stem = img.stem
        if stem not in preds or ds.read_label_lines(stem) is None:
            continue                                    # không có dự đoán / chưa có file nhãn: bỏ qua
        size = ds.image_size(stem)
        if size is None:
            continue                                    # ảnh hỏng: không tính được diện tích px
        W, H = size

        labels = _labels_with_line_numbers(ds, stem)
        rows = [r for r in preds[stem] if len(r) >= 6]  # mỗi dự đoán: [lớp, conf, cx, cy, w, h]

        # ---- (A) Từ phía MODEL: model thấy vật -> nhãn có box tương ứng không?
        P = [r for r in rows if r[1] >= conf_min and (r[4] * W) * (r[5] * H) >= min_area]
        for r in P:
            r_cls, r_conf, r_box = int(r[0]), float(r[1]), tuple(r[2:6])
            cands = []                                  # (IoU, lớp nhãn) của các nhãn chồng đủ nhiều
            for _, c, box in labels:
                iou = iou_xywh(r_box, box)
                if iou >= iou_missing:
                    cands.append((iou, c))

            if not cands:                               # (1) không nhãn nào phủ vật này
                issues.append(Issue(CHECK, WARN, "POSSIBLE_MISSING", stem,
                                    f"model thấy lớp {ds.classes[r_cls] if 0 <= r_cls < len(ds.classes) else r_cls} "
                                    f"(conf {r_conf:.2f}) nhưng nhãn không có box",
                                    extra={"conf": r_conf, "cls": r_cls}))
                continue

            same = [iou for iou, c in cands if c == r_cls]
            if same:                                    # (2) có nhãn cùng lớp
                best = max(same)
                if best < iou_loose:
                    issues.append(Issue(CHECK, WARN, "POSSIBLE_LOOSE_BOX", stem,
                                        f"box nhãn lệch/lỏng so với model (IoU {best:.2f} < {iou_loose})",
                                        extra={"conf": r_conf, "iou": round(best, 4), "cls": r_cls}))
                continue                                # IoU đủ tốt: nhãn đúng lớp đã phủ vật -> không cờ

            best_other, other_cls = max(cands)          # (3) chỉ có nhãn khác lớp: lấy cái chồng nhiều nhất
            if best_other >= iou_match:
                issues.append(Issue(CHECK, WARN, "POSSIBLE_WRONG_CLASS", stem,
                                    f"nhãn là {ds.classes[other_cls]} nhưng model thấy "
                                    f"{ds.classes[r_cls] if 0 <= r_cls < len(ds.classes) else r_cls} "
                                    f"(conf {r_conf:.2f}, IoU {best_other:.2f})",
                                    extra={"conf": r_conf, "iou": round(best_other, 4),
                                           "label_cls": other_cls, "pred_cls": r_cls}))
            # IoU khác lớp trong [iou_missing, iou_match): mơ hồ -> không cờ

        # ---- (B) Từ phía NHÃN: box nhãn có khớp vật nào model thấy không?
        F = [r for r in rows if r[1] >= fp_conf]        # ngưỡng thấp hơn, KHÔNG lọc diện tích
        for no, c, box in labels:
            best = max((iou_xywh(tuple(r[2:6]), box) for r in F), default=0.0)
            if best < iou_missing:
                issues.append(Issue(CHECK, WARN, "POSSIBLE_FALSE_POS", stem,
                                    f"box nhãn lớp {ds.classes[c]} không khớp vật nào model thấy (IoU tốt nhất {best:.2f})",
                                    line=no, extra={"iou": round(best, 4), "cls": c}))
    return issues
