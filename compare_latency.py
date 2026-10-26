"""
compare_latency.py — เวลาตอบต่อเทิร์น แบบจับคู่ จากผล run_answer_eval.py สองรอบที่ใช้ชุดคำถามเดียวกัน

ใช้ตอบคำถามของผู้ใช้ (25 ต.ค.): ตัวตีความคำตอบด้วย LLM (ข้อ 1) ทำให้ตอบช้าลงต่อเทิร์นเท่าไร
ต่างจาก simulate_customers.py ตรงที่คำถามทุกเทิร์นเหมือนกันทั้งสองรอบ → เทียบรายเทิร์นได้ตรง ๆ (paired)

    $env:ANSWER_INTERPRETER="rules"; python run_answer_eval.py --module assistant --testcases testcases_conversation_leaks.csv -o lat_rules.json
    $env:ANSWER_INTERPRETER="llm";   python run_answer_eval.py --module assistant --testcases testcases_conversation_leaks.csv -o lat_llm.json
    python compare_latency.py lat_rules.json lat_llm.json

"เทิร์นตอบคำถาม" = เทิร์นก่อนหน้าบอทถามพิทช์ / ยืนยันพิทช์ / อุณหภูมิ / เปียก-แห้ง (เทิร์นที่ตัวตีความทำงาน)
"""
from __future__ import annotations

import json
import sys

ASK_MARKERS = ("ระยะพิทช์", "หมายถึง", "ถ้าไม่ใช่", "ใช้งานที่อุณหภูมิ", "ไลน์เปียก", "สภาวะเปียก")


def _stats(xs):
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(round(p * (len(s) - 1))))]  # noqa: E731
    return {"n": len(s), "mean": round(sum(s) / len(s), 2), "median": round(q(0.5), 2), "p90": round(q(0.9), 2)}


def turns(path):
    d = json.load(open(path, encoding="utf-8"))
    rows = [r for r in d["results"] if not r.get("skipped")]
    by = {(r["id"], int(r["turn"])): r for r in rows}
    out = {}
    for (cid, t), r in by.items():
        prev = by.get((cid, t - 1))
        answering = bool(prev and any(m in (prev.get("reply") or "") for m in ASK_MARKERS))
        out[(cid, t)] = dict(sec=float(r.get("seconds") or 0), answering=answering, passed=r.get("passed"))
    return d, out


def main(a_path, b_path):
    A, ta = turns(a_path)
    B, tb = turns(b_path)
    keys = sorted(set(ta) & set(tb))
    for name, pick in (("ทุกเทิร์น", lambda k: True),
                       ("เทิร์นตอบคำถามค้าง", lambda k: ta[k]["answering"] or tb[k]["answering"]),
                       ("เทิร์นอื่น", lambda k: not (ta[k]["answering"] or tb[k]["answering"]))):
        ks = [k for k in keys if pick(k)]
        sa, sb = _stats([ta[k]["sec"] for k in ks]), _stats([tb[k]["sec"] for k in ks])
        diff = _stats([tb[k]["sec"] - ta[k]["sec"] for k in ks])
        print(f"\n{name} ({len(ks)} คู่)")
        print(f"  {a_path}: {sa}")
        print(f"  {b_path}: {sb}")
        print(f"  ต่าง (B − A) ต่อเทิร์น: {diff}")
    pa = sum(1 for k in keys if ta[k]["passed"])
    pb = sum(1 for k in keys if tb[k]["passed"])
    print(f"\nผ่าน: A {pa}/{len(keys)} · B {pb}/{len(keys)}")
    print("หมายเหตุ: เวลาของ Gemini แกว่งรอบต่อรอบ — ควรรันอย่างละ 2 รอบขึ้นไปก่อนสรุป")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
