"""
run_movex_old_retriever.py — หมวด 1 ของสมุดทดสอบ Movex เทอมที่แล้ว (Retriever Top-1) บนระบบใหม่

ไม่เรียก Gemini · ใช้ตัวค้นของบอทตัวจริง (โหลดผ่าน assistant.py เฉพาะแบรนด์ Movex)
ขั้นตอนเหมือนระบบเดิม: RetrieverV4.search(query, ไม่มีรูป, "general") → rank() → อันดับ 1

วางไฟล์นี้ไว้ในโฟลเดอร์ beltbot_plugin_2 แล้วรันด้วย venv ของบอท
    $env:BRANDS = "movex"
    & $BOTPY run_movex_old_retriever.py movex_old_cat1_retriever.csv -o ..\\movex_old_cat1_qi_r1.json

ผลรายข้อ: อันดับ 1 ของระบบใหม่ · ตรงเฉลยไหม · ตรงกับอันดับ 1 ของระบบเดิมไหม
ไม่แก้เฉลย — ข้อที่สมุดมีธงไว้ (flag) แสดงธงคู่กันให้ผู้ตรวจตัดสินเอง
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", help="movex_old_cat1_retriever.csv")
    ap.add_argument("-o", "--out", default="movex_old_cat1_r1.json")
    ap.add_argument("--top", type=int, default=5, help="จำนวนอันดับที่บันทึกต่อข้อ")
    args = ap.parse_args()

    os.environ.setdefault("BRANDS", "movex")      # โหลดเฉพาะ Movex (ประหยัดหน่วยความจำ)
    import assistant                                # noqa: F401  สร้างระบบแบบเดียวกับตอนใช้งานจริง
    from brands.movex import runtime as R
    inner = R._retriever_inner
    if inner is None:
        sys.exit("ตัวค้นของ Movex ไม่ถูกสร้าง (ไม่พบโมเดล Jina หรือ Qdrant ของ Movex) — ตรวจ log ตอนโหลด")

    rows = list(csv.DictReader(open(args.cases, encoding="utf-8-sig")))
    results, hit_new, hit_old, same_as_old = [], 0, 0, 0
    for r in rows:
        t0 = time.perf_counter()
        ranked = inner.rank(inner.search(query=r["query"], query_image=None, query_type="general"))
        top = [p.product_id for p in ranked.products[: args.top]]
        top1 = top[0] if top else ""
        new_hit = int(top1 == r["expected_pid"])
        old_hit = int(r.get("old_hit") or 0)
        hit_new += new_hit
        hit_old += old_hit
        same_as_old += int(top1 == r.get("old_top1", ""))
        results.append({
            "old_item": r["old_item"], "query": r["query"], "expected_pid": r["expected_pid"],
            "new_top1": top1, "new_hit": new_hit, "old_top1": r.get("old_top1", ""), "old_hit": old_hit,
            "same_top1_as_old": top1 == r.get("old_top1", ""), "new_top": top,
            "seconds": round(time.perf_counter() - t0, 2), "flag": r.get("flag", ""),
        })
        mark = "✅" if new_hit else "❌"
        diff = "" if top1 == r.get("old_top1", "") else f"  (เดิม {r.get('old_top1', '')})"
        print(f"{mark} {r['old_item']:<8} {top1}{diff}")

    summary = {"cases": args.cases, "total": len(rows), "new_hits": hit_new, "old_hits": hit_old,
               "same_top1_as_old": same_as_old, "results": results}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nระบบใหม่ {hit_new}/{len(rows)} · ระบบเดิม {hit_old}/{len(rows)} · "
          f"อันดับ 1 เหมือนเดิม {same_as_old}/{len(rows)} → {args.out}")


if __name__ == "__main__":
    main()
