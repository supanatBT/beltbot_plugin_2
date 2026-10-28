"""
data_manifest.py — ลายนิ้วมือ (sha256) ของข้อมูลดิบคู่ข้อมูลที่ซ่อม (28 ต.ค.)

หลักโปรเจกต์ "เก็บของดิบคู่ของที่ซ่อม": จดว่าแต่ละไฟล์มาจากไฟล์ไหน และ hash ตอนนี้เป็นเท่าไร
ใครแก้ไฟล์โดยไม่ผ่าน patch_*.py จะเห็นทันทีตอน --check และใน /health/detail

    & $py data_manifest.py --raw "E:\\...\\modutech_v30.json"     # เขียน DATA_MANIFEST.json
    & $py data_manifest.py --check                               # เทียบไฟล์ตอนนี้กับที่จดไว้

ไฟล์ดิบ modutech_v30.json ไม่ได้อยู่ในรีโป (อยู่ใน Project) — ไม่ส่ง --raw = จดว่า "ไม่พบไฟล์ดิบ" ไม่เดา hash
ห้ามใช้ v29 หรือเก่ากว่า: สคริปต์ปฏิเสธถ้า --raw ไม่ใช่ modutech_v30.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "DATA_MANIFEST.json")

# สายการซ่อม (CHANGELOG_v30_2.md · CHANGELOG_v30_3.md · patch_v30_*.py)
LINEAGE = [
    ("modutech_v30.json", None, "ไฟล์ดิบ (Project) — ห้ามใช้ v29 หรือเก่ากว่า"),
    ("modutech_v30_1.json", "modutech_v30.json", "patch_v30_1.py"),
    ("modutech_v30_2.json", "modutech_v30_1.json", "patch_v30_2.py · CHANGELOG_v30_2.md"),
    ("modutech_v30_3.json", "modutech_v30_2.json", "patch_v30_3.py · CHANGELOG_v30_3.md · ตัวที่บอทใช้"),
]
OTHER = ["extracted_data_v3_machine_ready.json", "modutech_kg.db", "movex_kg.db",
         "brands/modutech/image_gate.npz", "brands/movex/thresholds.json"]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_lfs_pointer(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def entry(path: str, name: str) -> dict:
    if not path or not os.path.isfile(path):
        return {"file": name, "found": False}
    if _is_lfs_pointer(path):
        return {"file": name, "found": False, "note": "เป็นตัวชี้ Git LFS ยังไม่ได้ดึงไฟล์จริง (git lfs pull)"}
    return {"file": name, "found": True, "sha256": sha256(path), "bytes": os.path.getsize(path)}


def build(raw: str | None) -> dict:
    items = []
    for name, parent, how in LINEAGE:
        p = raw if (name == "modutech_v30.json" and raw) else os.path.join(BASE, name)
        e = entry(p, name)
        e.update(parent=parent, made_by=how)
        items.append(e)
    others = [entry(os.path.join(BASE, n), n) for n in OTHER]
    return {"made_at": time.strftime("%Y-%m-%d %H:%M"), "lineage": items, "other": others}


def check(manifest_path: str = OUT) -> list[str]:
    """คืนรายการปัญหา (ว่าง = ตรงทุกไฟล์) — /health/detail เรียกด้วย"""
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    problems = []
    for e in m.get("lineage", []) + m.get("other", []):
        if not e.get("found"):
            continue
        p = os.path.join(BASE, e["file"])
        if e["file"] == "modutech_v30.json" and not os.path.isfile(p):
            continue                                    # ไฟล์ดิบอยู่นอกรีโป — ไม่ตรวจซ้ำ
        now = entry(p, e["file"])
        if not now.get("found"):
            problems.append(f"{e['file']}: หายไป")
        elif now["sha256"] != e["sha256"]:
            problems.append(f"{e['file']}: hash เปลี่ยนจากที่จดไว้")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="พาธของ modutech_v30.json ไฟล์ดิบ")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        if not os.path.isfile(OUT):
            print("❌ ยังไม่มี DATA_MANIFEST.json — รันโดยไม่ใส่ --check ก่อน")
            return 2
        bad = check()
        print("✅ ตรงกับที่จดไว้ทุกไฟล์" if not bad else "⚠️ " + "\n⚠️ ".join(bad))
        return 1 if bad else 0
    if a.raw and os.path.basename(a.raw).lower() != "modutech_v30.json":
        print(f"❌ --raw ต้องเป็น modutech_v30.json (ได้ {os.path.basename(a.raw)}) — ห้ามใช้ v29 หรือเก่ากว่า")
        return 2
    m = build(a.raw)
    for e in m["lineage"] + m["other"]:
        print(f"{'✅' if e.get('found') else '⚠️'} {e['file']}: "
              f"{e.get('sha256', '')[:16] or e.get('note', 'ไม่พบไฟล์')}")
    if os.path.exists(OUT):
        bak = f"{OUT}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(OUT, bak)
        print(f"สำรองไฟล์เดิม → {os.path.basename(bak)}")
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    print(f"✅ เขียน {os.path.basename(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
