"""
training/compare_truth.py — ตารางเทียบเฉลยใหม่ (redteam_truth.py) กับรุ่นที่ need_flow ของบอทคำนวณ (sim-fair · 4 พ.ย.)

รายงานทุกข้อที่ต่าง ไม่ตัดสินว่าฝ่ายไหนถูก · ไฟล์นี้ import โค้ดบอทได้ (เป็นตัวเทียบ ไม่ใช่ตัวตัดสิน)

    python training/compare_truth.py training/redteam_goals_v2_truth.json
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TRUTH_KEYS = ("accept_codes", "hard_ok_codes", "hard_ok_by_stated", "truth_note")


def rows(truth_path: str) -> list[dict]:
    import simulate_customers as SC
    judge = SC.Judge()
    out = []
    for g in json.load(open(truth_path, encoding="utf-8"))["goals"]:
        if g.get("brand") == "movex" or "accept_codes" not in g:
            continue
        plain = {k: v for k, v in g.items() if k not in TRUTH_KEYS}
        try:
            bot = judge.acceptable(plain)
        except Exception as e:                       # noqa: BLE001 — เช่น need_flow ไม่รับ wet_or_dry = null
            bot = {"ok": None, "hard_ok": None, "source": f"error: {type(e).__name__}: {e}"}
        new_a, new_h = set(g["accept_codes"]), set(g["hard_ok_codes"])
        row = {"id": g["id"], "application": g.get("application"), "truth_note": g.get("truth_note", ""),
               "bot_source": bot["source"]}
        for name, new, old in (("accept", new_a, bot["ok"]), ("hard_ok", new_h, bot["hard_ok"])):
            if old is None:
                row[name] = {"new": len(new), "bot": None}
                continue
            old = set(old)
            row[name] = {"new": len(new), "bot": len(old), "only_new": sorted(new - old), "only_bot": sorted(old - new)}
        out.append(row)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "training", "redteam_goals_v2_truth.json")
    rs = rows(path)
    diff = 0
    for r in rs:
        same = all(r[k].get("bot") is not None and not r[k]["only_new"] and not r[k]["only_bot"]
                   for k in ("accept", "hard_ok"))
        diff += not same
        print(f"{'=' if same else '≠'} {r['id']:4} {r['application'] or '':22} bot={r['bot_source']}"
              + (f" · {r['truth_note']}" if r["truth_note"] else ""))
        if same:
            continue
        for k in ("accept", "hard_ok"):
            x = r[k]
            if x.get("bot") is None:
                print(f"     {k:7} ใหม่ {x['new']} · บอท คำนวณไม่ได้")
                continue
            if x["only_new"] or x["only_bot"]:
                print(f"     {k:7} ใหม่ {x['new']} · บอท {x['bot']}"
                      + (f" · เฉพาะใหม่ {x['only_new']}" if x["only_new"] else "")
                      + (f" · เฉพาะบอท {x['only_bot']}" if x["only_bot"] else ""))
    print(f"\nต่างกัน {diff}/{len(rs)} เป้าหมาย — รายงานเจ้าของทุกข้อ ไม่ตัดสินว่าฝ่ายไหนถูก")


if __name__ == "__main__":
    main()
