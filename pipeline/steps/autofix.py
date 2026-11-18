"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401

REMOVE_IMAGE = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
DROP_LINE = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
CLIP_BOX = "BOX_OUT_OF_IMAGE"


def _fx(image, line, action, before, after):
    return {"image": image, "line": line, "action": action, "before": before, "after": after}


def _write_lines(path, lines):
    """Ghi lại file nhãn một lần, xuống dòng kiểu Unix (\\n) trên mọi hệ điều hành."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(ln + "\n" for ln in lines))


def _clip(text):
    """Cắt box về trong [0,1]. Trả về dòng mới, hoặc None nếu sau khi cắt box không còn diện tích."""
    c, x, y, w, h = parse_yolo_line(text)
    x1, x2 = max(0.0, x - w / 2), min(1.0, x + w / 2)
    y1, y2 = max(0.0, y - h / 2), min(1.0, y + h / 2)
    if x2 <= x1 or y2 <= y1:
        return None
    return f"{c} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}"


def fix(ds, issues, cfg):
    errs = [i for i in issues if i.severity == ERROR]     # WARN không bao giờ được động tới
    fixes = []

    # ---- 1) Xoá ảnh + nhãn (trùng, rò rỉ test, hỏng, quá nhỏ). Làm TRƯỚC để bỏ qua issue dòng của ảnh đã xoá.
    removed = set()
    for i in errs:
        if i.code not in REMOVE_IMAGE or i.image in removed:
            continue
        removed.add(i.image)
        img = ds.image_path(i.image)
        lbl = ds.label_path(i.image)
        if img is None and not lbl.exists():
            continue                                       # đã xoá từ trước: không làm gì (idempotent)
        before = img.name if img is not None else lbl.name
        if img is not None:
            img.unlink()
        if lbl.exists():
            lbl.unlink()
        fixes.append(_fx(i.image, None, "remove_image", before, f"đã xoá ({i.code})"))

    # ---- 2) Sửa tên lớp trong data.yaml (một lần, dù có nhiều issue BAD_CLASS_NAME)
    if any(i.code == "BAD_CLASS_NAME" for i in errs):
        try:
            data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:                                  # file thiếu/hỏng: dựng lại từ đầu
            data = {}
        if not isinstance(data, dict):
            data = {}
        old = data.get("names")
        new = {k: n for k, n in enumerate(cfg["classes"])}
        if ds.yaml_names() != new:
            data["names"] = new
            ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            fixes.append(_fx("data.yaml", None, "rename_classes", str(old), str(cfg["classes"])))

    # ---- 3) Thiếu file nhãn: máy KHÔNG bịa nhãn, không tạo file rỗng — chỉ ghi lại để chuyển người gán
    flagged = set()
    for i in errs:
        if i.code == "MISSING_LABEL_FILE" and i.image not in removed and i.image not in flagged:
            flagged.add(i.image)
            fixes.append(_fx(i.image, None, "needs_label", "(không có file)", "chuyển người gán"))

    # ---- 4) Lỗi theo dòng: gom theo file -> {số dòng gốc: {các mã lỗi}}, rồi ghi lại file MỘT lần
    by_file = defaultdict(lambda: defaultdict(set))
    for i in errs:
        if (i.code in DROP_LINE or i.code == CLIP_BOX) and i.line is not None and i.image not in removed:
            by_file[i.image][i.line].add(i.code)

    for stem in sorted(by_file):
        path = ds.label_path(stem)
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()   # GIỮ dòng trống -> số dòng gốc
        out = list(lines)                                   # out[k] = None nghĩa là xoá dòng k+1
        for no in sorted(by_file[stem]):
            if not 1 <= no <= len(lines):
                continue                                    # số dòng không tồn tại: bỏ qua êm
            codes = by_file[stem][no]
            text = lines[no - 1]
            if codes & DROP_LINE:                           # xoá dòng thắng clip: chỉ ghi 1 fix drop_line
                out[no - 1] = None
                fixes.append(_fx(stem, no, "drop_line", text, ""))
                continue
            try:                                            # chỉ còn BOX_OUT_OF_IMAGE
                new = _clip(text)
            except ValueError:
                new = None
            if new is None:                                 # nằm hẳn ngoài ảnh: xoá thay vì ghi box rỗng
                out[no - 1] = None
                fixes.append(_fx(stem, no, "drop_line", text, ""))
            else:
                out[no - 1] = new
                fixes.append(_fx(stem, no, "clip_box", text, new))
        _write_lines(path, [ln for ln in out if ln is not None])

    return fixes
