"""
audit_replies.py — ตรวจคำตอบเพิ่มจากเกณฑ์หลัก (ใช้กับผลของบอทหลักและ agent ด้วยเกณฑ์เดียวกัน)

    python audit_replies.py results\\probe_tools\\probe_modutech_r3.json ..\\agent_probe_mdt_r1.json

ไม่ตัดสินผ่าน/ตก แค่ชี้ข้อที่คนต้องอ่าน:
  hidden_inc  บอกค่าเพิ่มทีละของรุ่นที่ประตูความกว้างซ่อนไว้ (ค่าในตารางไม่ตรงหมายเหตุในเล่ม) — ผิด
  no_produce  ถ้อยคำว่าไม่ผลิต/ไม่มีการผลิต (กฎวัสดุ: ต้องพูดว่าแคตตาล็อกไม่มีข้อมูล ให้ยืนยันกับฝ่ายขาย)
  ask_back    ปิดท้ายด้วยคำถาม (นับไว้เทียบความถี่ ไม่ได้แปลว่าผิด)
  ask_use     ถามกลับว่าจะใช้ลำเลียงอะไร ทั้งที่คำถามไม่ได้ต้องใช้ข้อมูลนี้ (ดูประกอบกับคำถาม)
  list_missing  ข้อที่เป็นคำถามรายชื่อ (หมวดในตาราง LIST_EXPECT) แต่เอ่ยรหัสไม่ครบ
"""
from __future__ import annotations
import os as _os, sys as _sys  # รากของ repo: import แพ็กเกจได้ และพาธข้อมูลนับจากราก
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import json
import re
import sys
from collections import Counter

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NO_PRODUCE = re.compile(r"ไม่(?:มีการ)?ผลิต|ผลิตไม่ได้")
ASK_TAIL = re.compile(r"[?？]|ไม่ทราบว่า|รบกวนแจ้ง|(?:อะไร|ใด|ไหม|หรือไม่|หรือเปล่า)\s*(?:อยู่)?\s*ครับ")
ASK_USE = re.compile(r"ลำเลียง(?:สินค้า|วัตถุ|อะไร)|ใช้(?:งาน)?ลำเลียง|ประเภทใด")


def hidden_increments() -> dict[str, float]:
    """รุ่นที่ประตูความกว้างซ่อนค่าเพิ่มทีละ (ตรรกะเดียวกับ gates.width_gate)"""
    from engine.brands.modutech.gates import catalogue_increment_status
    here = os.path.dirname(os.path.abspath(__file__))
    out = {}
    for p in json.load(open(os.path.join(os.path.dirname(here), "data/modutech_v30_3.json"), encoding="utf-8"))["products"]:
        inc = (p["specifications"].get("width_effective") or {}).get("increment_mm")
        st, cat = catalogue_increment_status(p)
        ok = inc is not None and (st == "not_printed" or (st == "found" and abs(cat - inc) < 0.05))
        if inc is not None and not ok:
            out[p["belt_code"]] = inc
    return out


HIDDEN = hidden_increments()


def _inc_positions(rep: str, val: str) -> list[int]:
    """ตำแหน่ง "ทีละ <val>" ที่เป็นค่าเพิ่มทีละมาตรฐาน
    ไม่นับ "ขนาดนอกมาตรฐาน…เพิ่มทีละ" (ประตูอนุญาต) และ "ยังยืนยัน…ไม่ได้" ในประโยคเดียวกัน"""
    out = []
    for k in re.finditer(r"ทีละ\s*\**\s*" + re.escape(val) + r"(?!\d)", rep):
        start = max(rep.rfind("\n", 0, k.start()), rep.rfind("* ", 0, k.start()), k.start() - 120)
        before = rep[start: k.start()]
        if re.search(r"นอก(?:เหนือจาก)?มาตรฐาน|non-?standard|ยืนยัน\S*ไม่ได้|ยังไม่สามารถ", before, re.I):
            continue
        out.append(k.start())
    return out


def hidden_inc_hits(rep: str, query: str = "") -> list[str]:
    """รหัสที่ประตูซ่อนค่าเพิ่มทีละ แต่คำตอบเอ่ย "ทีละ <ค่านั้น>"
    ภายใน 400 ตัวอักษรหลังชื่อรุ่น (หยุดที่หัวข้อรุ่นถัดไป) หรือทั้งคำตอบเมื่อคำถามถามถึงรุ่นนั้น"""
    hits = []
    for code, inc in HIDDEN.items():
        pos = _inc_positions(rep, f"{inc:g}")
        if not pos:
            continue
        pat = re.escape(code) + r"(?![\w\-%])"
        if re.search(pat, query or ""):
            hits.append(code)
            continue
        for m in re.finditer(pat, rep):
            end = m.end() + 400
            nxt = re.search(r"\*\*[A-Z]{2}\d{3}", rep[m.end(): end])
            end = m.end() + nxt.start() if nxt else end
            if any(m.end() <= p < end for p in pos):
                hits.append(code)
                break
    return hits

# id ข้อ → รหัสที่ต้องเอ่ยครบ (เติมเมื่อมีคำถามรายชื่อเพิ่ม)
LIST_EXPECT = {
    "MDT-F2": ["MD508 C-RT", "XP254 EVO CR", "MD508 PR25", "EC381 R", "EC508 GT"],
}


def norm(s: str) -> str:
    return re.sub(r"[\s_\-]", "", (s or "").upper())


def audit(path: str) -> dict:
    d = json.load(open(path, encoding="utf-8"))
    rows, cnt = [], Counter()
    for r in d["results"]:
        rep = r.get("reply") or ""
        flags = []
        h = hidden_inc_hits(rep, r.get("query") or "")
        if h:
            flags.append("hidden_inc:" + ",".join(h))
        if NO_PRODUCE.search(rep):
            flags.append("no_produce")
        tail = rep.strip()[-220:]
        if ASK_TAIL.search(tail):
            flags.append("ask_back")
            if ASK_USE.search(tail):
                flags.append("ask_use")
        exp = LIST_EXPECT.get(r.get("id"))
        if exp:
            miss = [c for c in exp if norm(c) not in norm(rep)]
            if miss:
                flags.append("list_missing:" + ",".join(miss))
        for f in flags:
            cnt[f.split(":")[0]] += 1
        rows.append({"id": r.get("id"), "turn": r.get("turn"), "passed": r.get("passed"), "flags": flags})
    return {"file": path, "module": d.get("module"), "n": len(rows), "count": dict(cnt), "rows": rows}


def main() -> int:
    for p in sys.argv[1:]:
        a = audit(p)
        print(f"\n== {a['file']} ({a['module']}) {a['n']} ข้อ · {a['count']}")
        for r in a["rows"]:
            if r["flags"]:
                print(f"  {r['id']} t{r['turn']} {'ผ่าน' if r['passed'] else 'ตก'}  {r['flags']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
