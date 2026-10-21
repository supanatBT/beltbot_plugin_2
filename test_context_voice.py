#!/usr/bin/env python3
"""
test_context_voice.py — Context ที่ส่งให้ LLM ต้องไม่มีคำสั่งถึง LLM ปนอยู่ (เฟส 2 · 10 ต.ค. 2026)

ทำไมต้องมี
  ข้อความใน Context ถูก LLM เล่าต่อให้ลูกค้า (\"ระบบจึงใช้ค่า 93 °C\" · \"ห้ามคำนวณค่าเพิ่มทีละ\")
  ส่วนกฎท้าย prompt ไม่เคยหลุด — จึงแยก: ข้อเท็จจริงอยู่ใน Context · คำสั่งอยู่ในส่วนกฎ
  ดู FINDING_prompt_leak_sources.md

ตรวจอะไร
  ทุกเทิร์นของชุดเคส Modutech → build_modutech_turn → ทุกสตริงใน Context
  ต้องไม่มี  ห้าม · ให้บอกเฉพาะ · ระบบจึง · ระบบใช้ · ระบบเลือกใช้ · ระบบไม่ใช้
  และต้องไม่มีกุญแจ forbidden_th / gate_rules_th เหลือใน Context
  ส่วนกฎเฉพาะรุ่นต้องยังมีอยู่ (ย้ายที่ ไม่ใช่ทิ้ง)

ไม่เรียก LLM · ไม่ใช้เวกเตอร์ (vector_search=None)
    python test_context_voice.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict

import modutech_gates as mg
import modutech_router as mr
import modutech_turn as mt
from dialogue_state import DialogueManager
from modutech_kg import ModutechGraph

CASES = ["testcases_modutech_136.csv", "testcases_graph_relations.csv"]
VOICE_RX = re.compile(r"ห้าม|ให้บอกเฉพาะ|ระบบ(?:จึง|ใช้|เลือกใช้|ไม่ใช้)"
                      # รอบ 2 (10 ต.ค.): ศัพท์ภายใน · ถ้อยคำที่ทำให้ LLM อธิบายผิด (RESULTS_phase2_answer_review.md)
                      r"|ชั้นที่มีข้อมูล|คนละค่ากับค่าเพิ่มทีละ|สั่งได้ตั้งแต่\s*([\d.]+)\s*ถึง\s*\1\s*มม")
RULE_KEYS = ('"forbidden_th"', '"gate_rules_th"', '"_gate_rules_th"')

cat = mg.Catalogue("modutech_v30_3.json")
search = mr.CatalogueSearch(cat)
kg = ModutechGraph.from_catalogue(cat)


def strings(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from strings(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o


convs = defaultdict(list)
for f in CASES:
    for r in csv.DictReader(open(f, encoding="utf-8-sig")):
        convs[(f, r["id"])].append(r)

turns = bad_voice = bad_keys = with_rules = industry_turns = 0
bad_grades: list[str] = []
examples: list[str] = []
for (f, cid), rows in sorted(convs.items()):
    rows.sort(key=lambda r: int(r.get("turn_number") or 1))
    dm = DialogueManager({}, cat, movex_materials={})
    st = None
    for r in rows:
        d = dm.decide(r["user_text"], state=st)
        st = d.state
        if d.brand != "modutech" or d.action not in ("answer", "search"):
            continue
        t = mt.build_modutech_turn(d, cat, search, vector_search=None, kg=kg)
        turns += 1
        blob = json.dumps(t.context, ensure_ascii=False)
        if any(k in blob for k in RULE_KEYS):
            bad_keys += 1
        hits = [(p, s) for p, s in strings(t.context) if VOICE_RX.search(s)]
        if hits:
            bad_voice += 1
            if len(examples) < 8:
                p, s = hits[0]
                m = VOICE_RX.search(s)
                examples.append(f"{cid} t{r['turn_number']} {p}: …{s[max(0, m.start() - 40):m.end() + 30]}…")
        if "กฎเฉพาะรุ่น" in t.system_prompt:
            with_rules += 1
        # รอบ 2: เกรดในรายชื่องานใช้/อุตสาหกรรม ต้องเป็นเกรดที่รุ่นนั้นผลิตจริง (AP-006 · AP-007)
        grade_lists = list(((t.context.get("application_match") or {}).get("materials_by_belt") or {}).items())
        for code, apps in ((t.context.get("industry_match") or {}).get("applications_by_belt") or {}).items():
            # รอบ 3: "งาน (เกรด, เกรด) · งาน (เกรด)" — ดึงเกรดในวงเล็บทุกงาน
            grade_lists.append((code, [g.strip() for grp in re.findall(r"\(([^)]*)\)", apps)
                                       for g in grp.split(",")]))
        for code, ms in grade_lists:
            made = {v["belt_material"] for v in cat.by_code[code]["specifications"]["variants"]}
            if not set(ms) <= made:
                bad_grades.append(f"{cid} {code} {ms} ผลิตจริง {sorted(made)}")
        if t.context.get("industry_match"):
            industry_turns += 1

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


print(f"ตรวจ {turns} เทิร์นที่ไปถึง LLM ฝั่ง Modutech")
ok("Context ไม่มีคำสั่งถึง LLM หรือศัพท์ภายใน (ห้าม · ระบบจึง/ใช้ · ชั้นที่มีข้อมูล …)", bad_voice == 0,
   f"{bad_voice} เทิร์น\n      " + "\n      ".join(examples))
ok("ไม่มีกุญแจ forbidden_th / gate_rules_th ค้างใน Context", bad_keys == 0, f"{bad_keys} เทิร์น")
ok(f"กฎเฉพาะรุ่นยังอยู่ในส่วนกฎ ({with_rules} เทิร์น)", with_rules > 0)
ok("รายชื่องานใช้/อุตสาหกรรม บอกเฉพาะเกรดที่ผลิตจริง", not bad_grades, "; ".join(bad_grades[:5]))
ok(f"คำถามงานที่เล่มไม่มี ตอบจากรายชื่ออุตสาหกรรม ({industry_turns} เทิร์น)", industry_turns > 0)

# งานที่เล่มไม่มี + ถามเรื่องตัด → รุ่นที่เล่มระบุเกรดทนการบาด ต้องอยู่ในรายละเอียดเต็ม (AP-004 · รอบ 3)
t04 = mt.build_modutech_turn(DialogueManager({}, cat, movex_materials={}).decide("สายพานสำหรับไลน์แล่ปลา"),
                             cat, search, vector_search=None, kg=kg)
im04 = t04.context.get("industry_match") or {}
ok("AP-004: HC508 C-MTW (เกรด CR) อยู่ในรายละเอียด · มีชื่อเกรด Cut Resistant · ส่วนกฎไม่สั่งให้บอกว่าแคตตาล็อกไม่มี",
   "HC508 C-MTW" in [p["belt_code"] for p in t04.context.get("products") or []]
   and (im04.get("grade_names") or {}).get("CR") == "Cut Resistant"
   and "ห้ามบอกว่าแคตตาล็อกไม่มีข้อมูลเรื่องนั้น" in t04.system_prompt,
   str([p["belt_code"] for p in t04.context.get("products") or []]))

# รอบ 4 (11 ต.ค.): หัวข้อเกรดทนการบาดต้องมีแค่รุ่นที่ผลิตเกรดนั้นจริง — HC508 C ผลิตแค่ PE/PP/POM (AP-004)
gm = im04.get("grade_match") or {}
ok("AP-004: grade_match มีแค่ HC508 C-MTW (CR · ICR) · HC508 C ไม่อยู่ · กฎสั่งห้ามจัดรุ่นอื่นไว้ใต้หัวข้อเกรด",
   set(gm.get("belts") or {}) == {"HC508 C-MTW"}
   and any(g.startswith("CR ") for g in gm["belts"]["HC508 C-MTW"])
   and "ห้ามจัดรุ่นอื่นไว้ใต้หัวข้อ" in t04.system_prompt, json.dumps(gm, ensure_ascii=False)[:200])
tpo = mt.build_modutech_turn(DialogueManager({}, cat, movex_materials={}).decide("สายพานสำหรับไลน์หั่นไก่"),
                             cat, search, vector_search=None, kg=kg)
gmp = ((tpo.context.get("industry_match") or {}).get("grade_match") or {})
ok("ไม่มีรุ่นในอุตสาหกรรมที่ผลิตเกรดนั้น → belts ว่าง แต่บอกรุ่นที่ผลิตเกรดนั้นในอุตสาหกรรมอื่น",
   gmp.get("belts") == {} and "HC508 C-MTW" in (gmp.get("other_industry_belts") or []), str(gmp)[:200])

# เกรดที่ค่ายังไม่ยืนยันแล้วถูกตัด ต้องถูกเอ่ยถึง (TP-014 · MD254 RR PPH 93 °C ที่ 100 °C แห้ง)
t14 = mt.build_modutech_turn(DialogueManager({}, cat, movex_materials={}).decide(
    "MD254 RR ใช้ที่ 100 องศา ไลน์แห้ง ได้ไหม"), cat, search, vector_search=None, kg=kg)
n14 = " ".join((t14.context.get("products") or [{}])[0].get("gate_notes_th") or [])
ok("TP-014: หมายเหตุบอกว่า PPH ไม่อยู่ในรายการเพราะ 93 °C ที่ยังไม่ยืนยัน · กฎสั่งให้เอ่ยถึง PPH เสมอ",
   "เกรด PPH ไม่อยู่ในรายการที่รองรับ 100 °C" in n14 and "93 °C" in n14
   and "ต้องเอ่ยถึงเกรด PPH ในคำตอบเสมอ" in t14.system_prompt, n14[:200])

# รุ่นที่ไม่มีเกรดไหนผ่านอุณหภูมิ ต้องยังอยู่ใน Context พร้อมค่าสูงสุดจริง (TP-016)
dm = DialogueManager({}, cat, movex_materials={})
t16 = mt.build_modutech_turn(dm.decide("MP80 C ใช้ที่ 80 องศา ไลน์เปียก ได้ไหม"), cat, search,
                             vector_search=None, kg=kg)
p16 = (t16.context.get("products") or [{}])[0]
ok("TP-016: MP80 C ยังอยู่ใน Context · ไม่มีเกรดผ่าน · บอก 60 °C",
   p16.get("belt_code") == "MP80 C" and not p16.get("variants")
   and any("60 °C" in n for n in p16.get("gate_notes_th") or []), str(p16)[:200])
# ── รอบ 5 (11 ต.ค. ค่ำ) ──
# ไม่มี "ฝ่ายเทคนิค" ใน Context หรือ prompt ของเทิร์นไหนเลย (เจ้าของตัดสิน: ยืนยันกับพนักงานฝ่ายขาย · v30_3)
tech = []
for (f, cid), rows in sorted(convs.items()):
    dm = DialogueManager({}, cat, movex_materials={})
    st = None
    for r in sorted(rows, key=lambda r: int(r.get("turn_number") or 1)):
        d = dm.decide(r["user_text"], state=st)
        st = d.state
        if d.brand == "modutech" and d.action in ("answer", "search"):
            t = mt.build_modutech_turn(d, cat, search, vector_search=None, kg=kg)
            if "ฝ่ายเทคนิค" in t.system_prompt:
                tech.append(cid)
ok("ไม่มี 'ฝ่ายเทคนิค' ใน prompt ทุกเทิร์น (v30_3 + โค้ด)", not tech, str(sorted(set(tech))[:5]))

# WD-M: ประโยค "ไม่ได้ระบุเงื่อนไข" ต้องจบที่ช่วงความกว้าง ก่อนพูดถึงขนาดนอกมาตรฐาน (เดิม LLM ขยายไปถึงขนาดนอกมาตรฐาน)
tm = mt.build_modutech_turn(DialogueManager({}, cat, movex_materials={}).decide("EC254 R-TABE กว้างเท่าไหร่"),
                            cat, search, vector_search=None, kg=kg)
wn = tm.context["products"][0]["width_note_th"]
ok("WD-M05: ช่วงที่ไม่ได้ระบุมาก่อน · ขนาดนอกมาตรฐานแยกประโยคว่าเล่มระบุไว้",
   wn.find("ไม่ได้ระบุเงื่อนไขการสั่งเฉพาะช่วง 100–200") < wn.find("ส่วนขนาดนอกมาตรฐาน เล่มระบุไว้ชัดเจน") != -1, wn)

# TP-013: รุ่นที่ไม่ต้องถามเปียก/แห้ง และค่าเปียกเท่าค่าแห้ง → บอกว่าเป็นค่าของทั้งสองสภาวะ
t13 = mt.build_modutech_turn(DialogueManager({}, cat, movex_materials={}).decide("EC127 GT ทนร้อนกี่องศา"),
                             cat, search, vector_search=None, kg=kg)
conds = {(v.get("temperature_answer") or {}).get("condition") for v in t13.context["products"][0]["variants"]}
ok("TP-013: EC127 GT ได้ condition = dry_and_wet · กฎอธิบายค่านี้", conds == {"dry_and_wet"}
   and '"dry_and_wet"' in t13.system_prompt, str(conds))

# EX-004: ผลค้นบอกแบรนด์
t4 = mt.build_modutech_turn(DialogueManager({}, cat, movex_materials={}).decide("มีสายพานพื้นที่เปิดอย่างน้อย 45% ไหม"),
                            cat, search, vector_search=None, kg=kg)
ok("EX-004: search_result มี scope_th ที่เอ่ย Modutech", "Modutech" in (t4.context.get("search_result") or {}).get(
    "scope_th", ""), str((t4.context.get("search_result") or {}).get("scope_th")))

# RT-014: ลูกค้าบอกงานแต่ไม่รู้รุ่น → ยกรุ่น Movex ที่ usage เขียนถึงงานนั้น (ข้อความตายตัว)
from brands.movex.plugin import movex_application_block  # noqa: E402
_mx = {x["product_id"]: x for x in json.load(open("extracted_data_v3_machine_ready.json", encoding="utf-8"))["products"]}
blk = movex_application_block("โซ่ลำเลียงขวด PET", _mx) or ""
ok("RT-014: ขวด PET → LF 820 K325 · LF 880 TAB K325 · LFN 83 MFM · ไม่มีรุ่นที่ usage ไม่พูดถึง PET",
   all(c in blk for c in ("LF 820 K325", "LF 880 TAB K325", "LFN 83 MFM")) and "LF 821" not in blk
   and movex_application_block("โซ่ลำเลียง", _mx) is None, blk[:200])

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
