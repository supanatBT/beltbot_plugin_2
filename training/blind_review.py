"""
training/blind_review.py — สำเนาสำหรับคนอ่าน transcript โดยไม่รู้ว่าบทไหนเป็นบอทหรือ agent (sim-fair · 4 พ.ย. 2026)

ใช้กรอก tactic_checked (ลูกค้าจำลองทำตามแผนไหม) และจด manual_check ก่อนดูคะแนน — ไฟล์ผลดิบไม่ถูกแก้

    python training/blind_review.py make sim_redteam_qi.json sim_redteam_agent.json --goals training/redteam_goals_v2_truth.json -o review
        → review/review.txt   บทสนทนาเรียงสุ่ม รหัสสุ่มแทนชื่อระบบ ("ระบบ" แทน "บอท") + tactic + manual_check
          review/sheet.csv    รหัส · เป้าหมาย · tactic_checked (ว่าง) · manual_ok (ว่าง) · หมายเหตุ  ← กรอกที่นี่
          review/key.json     รหัส → ไฟล์ผล · เป้าหมาย · รอบ  ← อย่าเปิดจนกรอก sheet.csv ครบ
    python training/blind_review.py merge review
        → <ไฟล์ผล>_checked.json  สำเนาที่มี tactic_checked / manual_ok / review_note จาก sheet.csv

ข้อจำกัด: ซ่อนได้แค่ชื่อ — สำนวนของแต่ละระบบยังต่างกัน คนที่คุ้นกับระบบอาจเดาได้ (เขียนในเล่ม)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import secrets

SHEET_COLS = ["code", "goal", "tactic_checked", "manual_ok", "note"]


def _bool(x: str):
    v = (x or "").strip().lower()
    if v in ("true", "t", "1", "y", "yes", "ใช่", "ผ่าน"):
        return True
    if v in ("false", "f", "0", "n", "no", "ไม่", "ไม่ผ่าน"):
        return False
    return None


def make(results: list[str], goals_path: str | None, out_dir: str) -> None:
    goals = {}
    if goals_path:
        goals = {g["id"]: g for g in json.load(open(goals_path, encoding="utf-8"))["goals"]}
    items = []
    for path in results:
        doc = json.load(open(path, encoding="utf-8"))
        for i, r in enumerate(doc["results"]):
            items.append({"file": os.path.abspath(path), "index": i, "goal": r["goal"], "run": r.get("run", 1),
                          "transcript": r["transcript"], "tactic": r.get("tactic") or goals.get(r["goal"], {}).get("tactic")})
    codes = set()
    for it in items:
        while True:
            c = secrets.token_hex(3).upper()
            if c not in codes:
                codes.add(c)
                it["code"] = c
                break
    order = sorted(items, key=lambda _: secrets.randbits(32))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "review.txt"), "w", encoding="utf-8") as f:
        for it in order:
            g = goals.get(it["goal"], {})
            f.write(f"\n=== {it['code']} · {it['goal']} · {g.get('application', '')} ===\n")
            f.write(f"tactic: {it['tactic'] or '(ไม่ระบุ)'}\n")
            for m in g.get("manual_check", []):
                f.write(f"ตรวจ: {m}\n")
            for t in it["transcript"]:
                f.write(f"{'🧑 ลูกค้า' if t['role'] == 'customer' else '🤖 ระบบ'}: {t['text']}\n")
    with open(os.path.join(out_dir, "sheet.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLS)
        for it in sorted(order, key=lambda x: (x["goal"], x["code"])):
            w.writerow([it["code"], it["goal"], "", "", ""])
    key = {it["code"]: {"file": it["file"], "index": it["index"], "goal": it["goal"], "run": it["run"]} for it in items}
    json.dump(key, open(os.path.join(out_dir, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(items)} บท → {out_dir}/review.txt · กรอก {out_dir}/sheet.csv · อย่าเปิด key.json จนกรอกครบ")


def merge(out_dir: str) -> list[str]:
    key = json.load(open(os.path.join(out_dir, "key.json"), encoding="utf-8"))
    rows = list(csv.DictReader(open(os.path.join(out_dir, "sheet.csv"), encoding="utf-8-sig")))
    blank = [r["code"] for r in rows if _bool(r["tactic_checked"]) is None]
    if blank:
        print(f"⚠ ยังไม่กรอก tactic_checked {len(blank)} บท: {blank[:10]}")
    by_file: dict[str, dict] = {}
    for r in rows:
        k = key[r["code"]]
        doc = by_file.setdefault(k["file"], json.load(open(k["file"], encoding="utf-8")))
        res = doc["results"][k["index"]]
        res["tactic_checked"] = _bool(r["tactic_checked"])
        res["manual_ok"] = _bool(r.get("manual_ok", ""))
        res["review_note"] = r.get("note", "")
    written = []
    for path, doc in by_file.items():
        dst = os.path.splitext(path)[0] + "_checked.json"
        json.dump(doc, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        written.append(dst)
        print(f"เขียนแล้ว: {dst}")
    return written


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("results", nargs="+")
    m.add_argument("--goals")
    m.add_argument("-o", "--out", default="review")
    g = sub.add_parser("merge")
    g.add_argument("dir")
    a = ap.parse_args()
    if a.cmd == "make":
        make(a.results, a.goals, a.out)
    else:
        merge(a.dir)


if __name__ == "__main__":
    main()
