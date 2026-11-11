"""ตรวจว่า decision ของ movex_match_image (AGENT_IMAGE_DECISION · 11 พ.ย.) จะดึงรูปที่ไม่ใช่ Movex เข้า Movex ไหม
ไม่เรียก Gemini ไม่เสียเงิน · ใช้ ViT + RetrieverV4 ตัวเดียวกับ agent

    python eval\\diag_image_decision.py --labels "$HOME\\Downloads\\Modutech\\labels_test_40.csv" ^
        --labels "E:\\Project2\\image_test_ready\\labels_control.csv" ^
        --dir modutech="$HOME\\Downloads\\Modutech" -o ..\\diag_image_decision.csv

--labels  csv ที่มีคอลัมน์ path (อ้างจากโฟลเดอร์ของไฟล์ csv) และ brand (ว่าง = modutech) — ชุดเดียวกับเทสรูป
--dir     แบรนด์=โฟลเดอร์ ไล่ทุกรูปในโฟลเดอร์ย่อย (ใส่ได้หลายครั้ง) · รูปที่ซ้ำกับ --labels นับครั้งเดียว
ผลที่ต้องดู: รูปที่ไม่ใช่ Movex แต่ได้ brand = "movex" (= agent จะไม่ถามแบรนด์และตอบเป็น Movex) ต้องเป็น 0
"""
import argparse
import collections
import csv
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["AGENT_IMAGE_DECISION"] = "1"
from agent import movex_tools as MX  # noqa: E402
from agent import tools_impl as T  # noqa: E402

EXT = (".jpg", ".jpeg", ".png", ".jfif", ".webp", ".bmp")


def collect(a) -> list[tuple[str, str]]:
    seen, out = set(), []
    for lab in a.labels:
        base = os.path.dirname(os.path.abspath(lab))
        for r in csv.DictReader(open(lab, encoding="utf-8-sig")):
            p = os.path.normcase(os.path.abspath(os.path.join(base, r["path"])))
            if p not in seen and os.path.isfile(p):
                seen.add(p)
                out.append((p, (r.get("brand") or "modutech").strip().lower()))
    for spec in a.dir:
        brand, _, folder = spec.partition("=")
        for dp, _dn, fns in os.walk(folder):
            for fn in sorted(fns):
                p = os.path.normcase(os.path.abspath(os.path.join(dp, fn)))
                if fn.lower().endswith(EXT) and p not in seen:
                    seen.add(p)
                    out.append((p, brand.strip().lower()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", action="append", default=[])
    ap.add_argument("--dir", action="append", default=[], help="แบรนด์=โฟลเดอร์ เช่น modutech=C:\\รูป")
    ap.add_argument("-o", "--out", default="diag_image_decision.csv")
    a = ap.parse_args()
    items = collect(a)
    if not items:
        print("❌ ไม่พบรูป — ตรวจ --labels / --dir")
        return 2
    print(f"รูปทั้งหมด {len(items)} · " + " · ".join(f"{b} {n}" for b, n in collections.Counter(b for _p, b in items).items()))
    os.makedirs(T.IMAGE_DIR, exist_ok=True)
    rows, tally = [], collections.Counter()
    for i, (path, brand) in enumerate(items, 1):
        name = f"diagdec_{i}{os.path.splitext(path)[1].lower().replace('.jfif', '.jpg')}"
        shutil.copy(path, os.path.join(T.IMAGE_DIR, name))
        r = json.loads(MX.movex_match_image(name, 5))
        d = r.get("decision") or {"brand": "error", "action": r.get("error", "")[:60]}
        v = r.get("vit_signal") or {}
        tally[(brand, d["brand"], d["action"])] += 1
        rows.append({"path": path, "true_brand": brand, "decision_brand": d["brand"], "action": d["action"],
                     "product_id": d.get("product_id", ""), "series": d.get("series", ""),
                     "vit_series": v.get("series"), "vit_conf": v.get("confidence"), "dominant": v.get("dominant"),
                     "top_pid": v.get("top_pid")})
        if i % 20 == 0:
            print(f"   {i}/{len(items)}")
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("\nแบรนด์จริง → decision.brand / action")
    for (b, db, act), n in sorted(tally.items()):
        print(f"   {b:9s} → {db:9s} {act:10s} {n}")
    leak = [r for r in rows if r["true_brand"] != "movex" and r["decision_brand"] == "movex"]
    movex = [r for r in rows if r["true_brand"] == "movex"]
    print(f"\nรูปที่ไม่ใช่ Movex แต่ถูกตัดสินเป็น Movex: {len(leak)} / {len(rows) - len(movex)}")
    for r in leak:
        print(f"   ⚠️ {r['true_brand']} {r['path']} · ViT {r['vit_series']} {r['vit_conf']} → {r['product_id']}")
    if movex:
        hit = sum(r["decision_brand"] == "movex" for r in movex)
        print(f"รูป Movex ที่ตัดสินเป็น Movex ได้เลย: {hit} / {len(movex)} (ที่เหลือ agent จะถามแบรนด์เหมือนเดิม)")
    print(f"\nบันทึกทุกรูป → {a.out}")
    return 1 if leak else 0


if __name__ == "__main__":
    sys.exit(main())
