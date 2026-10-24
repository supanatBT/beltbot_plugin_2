#!/usr/bin/env python3
"""เทียบคำตอบก่อน/หลังต่อชั้นงานใช้ของกราฟ (23 ต.ค. 2026)

ใช้ไฟล์ผลของ run_answer_eval.py สองไฟล์ที่รันชุดคำถามเดียวกัน — ไฟล์แรกปิดกราฟ (MODUTECH_GRAPH_APPS=0)
ไฟล์ที่สองเปิด แล้ววัดแต่ละข้อด้วยค่าที่ถูกจากกราฟ (ซึ่งตรวจกับ JSON ดิบแล้วใน test_modutech_kg_apps_full.py)

วัดต่อข้อ
  ผ่าน/ตก ตามเกณฑ์ของชุดทดสอบ
  รุ่นสายพานในคำตอบ: ถูก · เกิน (เล่มไม่ได้ผูกกับงาน/อุตสาหกรรมนี้) · ขาด
  รหัสเฟือง (ข้อสองขั้น): ถูก · ไม่มีในเล่ม · ขาด
  ถามกลับแทนตอบ · เวลา · token

รัน: python compare_graph_runs.py ก่อน.json หลัง.json [-o compare_graph.md]
"""
from __future__ import annotations

import csv
import json
import re
import sys

import run_answer_eval as rae
from brands.modutech.gates import Catalogue
from brands.modutech.kg import ModutechGraph

args = [a for a in sys.argv[1:] if not a.startswith("-")]
out_path = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else "compare_graph.md"
if "-o" in sys.argv:
    args = [a for a in args if a != out_path]
if len(args) != 2:
    sys.exit(__doc__)
before_f, after_f = args

cat = Catalogue("modutech_v30_3.json")
g = ModutechGraph.from_catalogue(cat)
codes_long = sorted(cat.by_code, key=len, reverse=True)
cases = {c["id"]: c for c in csv.DictReader(open("testcases_graph_apps.csv", encoding="utf-8-sig"))}
ind_by_th = {}
for p in cat.products:
    for i in p.get("industries") or []:
        ind_by_th[i.get("industry_th") or ""] = i["industry"]


def belts_in(text: str) -> set:
    """รหัสรุ่นในข้อความ — ยาวสุดก่อน กัน EC508 C นับซ้ำใน EC508 C-RT"""
    t, out = text, set()
    for c in codes_long:
        if c in t:
            out.add(c)
            t = t.replace(c, " ")
    return out


def sprockets_in(text: str) -> set:
    t = text.replace("\\*", "*")
    return set(re.findall(r"[A-Z][A-Z0-9\-]*S[QR]Z\d+(?:\*[A-Z]+)?", t))


def truth(case: dict):
    """รุ่นที่ถูก (หรือ None ถ้าข้อนั้นไม่ได้ถามหารายชื่อรุ่น) และรหัสเฟืองที่ถูก"""
    q = case["user_text"]
    apps = g.find_applications(q)
    ind = None
    for th, en in ind_by_th.items():
        if th and th in q:
            ind = en
    sub = case["subcategory"]
    if sub in ("application_to_belt", "application_in_industry", "application_to_sprocket", "pair_not_in_catalogue"):
        belts = sorted({b for a in apps for b in g.belts_for_application(a, ind)})
        spr = {c for b in belts for c in (cat.links.get(b) or {}).get("sprocket_codes") or []} \
            if sub == "application_to_sprocket" else None
        return set(belts), spr
    return None, None


def load(f):
    d = json.load(open(f, encoding="utf-8"))
    return d, {r["id"]: r for r in d["results"]}


bd, before = load(before_f)
ad, after = load(after_f)
ids = [i for i in cases if i in before and i in after]

rows, tot = [], {"b_pass": 0, "a_pass": 0, "b_extra": 0, "a_extra": 0, "b_miss": 0, "a_miss": 0,
                 "b_spr": 0, "a_spr": 0, "spr_want": 0, "b_ask": 0, "a_ask": 0, "b_sec": 0.0, "a_sec": 0.0}
for i in ids:
    c = cases[i]
    want_b, want_s = truth(c)
    rec = {"id": i, "q": c["user_text"], "sub": c["subcategory"]}
    for side, r in (("b", before[i]), ("a", after[i])):
        rep = r.get("reply") or ""
        # ให้คะแนนใหม่ด้วยเกณฑ์ปัจจุบันทั้งสองฝั่ง — ไฟล์รอบเก่าอาจใช้ตัวให้คะแนนรุ่นก่อน
        rec[f"{side}_pass"] = rae.check_reply(c, rep, r.get("error"))["passed"]
        rec[f"{side}_ask"] = (r.get("llm_usage") is None and len(rep) < 400)
        rec[f"{side}_sec"] = r.get("seconds") or 0
        tot[f"{side}_pass"] += rec[f"{side}_pass"]
        tot[f"{side}_ask"] += rec[f"{side}_ask"]
        tot[f"{side}_sec"] += rec[f"{side}_sec"]
        if want_b is not None and not (c["subcategory"] == "pair_not_in_catalogue"):
            got = belts_in(rep)
            rec[f"{side}_extra"] = sorted(got - want_b)
            rec[f"{side}_miss"] = sorted(want_b - got)
            tot[f"{side}_extra"] += len(rec[f"{side}_extra"])
            tot[f"{side}_miss"] += len(rec[f"{side}_miss"])
        if want_s is not None:
            got_s = sprockets_in(rep)
            rec[f"{side}_spr_ok"] = len(got_s & want_s)
            rec[f"{side}_spr_bad"] = sorted(got_s - want_s)
            tot[f"{side}_spr"] += rec[f"{side}_spr_ok"]
    if want_s is not None:
        rec["spr_want"] = len(want_s)
        tot["spr_want"] += len(want_s)
    if want_b is not None:
        rec["want_n"] = len(want_b)
    rows.append(rec)


def mark(p):
    return "✓" if p else "✗"


def belts_cell(r, side):
    if f"{side}_extra" not in r:
        return ""
    e, m = r[f"{side}_extra"], r[f"{side}_miss"]
    s = f"เกิน {len(e)} · ขาด {len(m)}" if (e or m) else "ตรง"
    if e:
        s += f" ({', '.join(e[:4])}{'…' if len(e) > 4 else ''})"
    return s


lines = [f"# เทียบคำตอบก่อน/หลังต่อกราฟ · {len(ids)} ข้อ",
         "",
         f"- ก่อน: `{before_f}` · graph_apps = {bd.get('graph_apps', 'ไม่ได้บันทึก')} · {bd.get('model_versions')}",
         f"- หลัง: `{after_f}` · graph_apps = {ad.get('graph_apps', 'ไม่ได้บันทึก')} · {ad.get('model_versions')}",
         "",
         "| | ก่อน | หลัง |",
         "|---|---|---|",
         f"| ผ่านเกณฑ์ชุดทดสอบ | {tot['b_pass']}/{len(ids)} | {tot['a_pass']}/{len(ids)} |",
         f"| รุ่นเกิน (เล่มไม่ได้ผูกกับงาน/อุตสาหกรรมที่ถาม) รวม | {tot['b_extra']} | {tot['a_extra']} |",
         f"| รุ่นขาด รวม | {tot['b_miss']} | {tot['a_miss']} |",
         f"| รหัสเฟืองเต็มที่ถูก (ข้อสองขั้น) | {tot['b_spr']}/{tot['spr_want']} | {tot['a_spr']}/{tot['spr_want']} |",
         f"| ถามกลับแทนตอบ | {tot['b_ask']} | {tot['a_ask']} |",
         f"| เวลารวม (วินาที) | {tot['b_sec']:.0f} | {tot['a_sec']:.0f} |",
         "",
         "| ข้อ | คำถาม | ก่อน | หลัง | รุ่นก่อน | รุ่นหลัง | เฟืองก่อน | เฟืองหลัง |",
         "|---|---|---|---|---|---|---|---|"]
for r in rows:
    spr_b = f"{r.get('b_spr_ok', '')}/{r['spr_want']}" if "spr_want" in r else ""
    spr_a = f"{r.get('a_spr_ok', '')}/{r['spr_want']}" if "spr_want" in r else ""
    lines.append(f"| {r['id']} | {r['q']} | {mark(r['b_pass'])}{' ถามกลับ' if r['b_ask'] else ''} | "
                 f"{mark(r['a_pass'])}{' ถามกลับ' if r['a_ask'] else ''} | {belts_cell(r, 'b')} | {belts_cell(r, 'a')} | "
                 f"{spr_b} | {spr_a} |")
open(out_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
json.dump({"totals": tot, "rows": rows}, open(out_path.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n".join(lines[:14]))
print(f"\nเขียน {out_path}")
