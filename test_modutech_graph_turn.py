#!/usr/bin/env python3
"""ต่อชั้นงานใช้ของกราฟเข้าบอต (23 ต.ค. 2026) — ตรวจว่า LLM เห็นอะไร โดยไม่เรียก LLM

  1. load_modutech_kg คืน ModutechGraph (มีชั้นงานใช้) เสมอ ไม่ว่าไฟล์ .db จะมีหรือไม่
  2. ชื่องานตรงตัว → รายชื่อจากกราฟ ไม่ใช่ tag กว้างของ router (เครื่องชั่ง 6 รุ่น ไม่ใช่ 17)
  3. งาน × อุตสาหกรรม ใช้คู่ที่เล่มระบุจริง · คู่ที่เล่มไม่มี → application_pair_absent ไม่มีรุ่นปน
  4. ถามสองขั้นถึงเฟือง → sprockets_by_belt มีแต่รหัส ไม่มีขนาด · รุ่นไม่มีเฟือง → แยกรายการ ไม่เดา
  5. การ์ดสินค้าตัดงานที่เกรดไม่ตรง (MD254 GT × การลำเลียงกล่อง) ไว้ใน applications_excluded_th
     และไม่แก้ข้อมูลแคตตาล็อกในที่ (เรียกซ้ำได้ผลเดิม)
  6. ชื่องานที่ไม่ตรงตัว ถอยไปใช้ router เหมือนเดิม (AP-006 ลำเลียงกล่องลูกฟูก)

รัน: python test_modutech_graph_turn.py
"""
from __future__ import annotations

import json
import sys

import modutech_router as mr
import modutech_turn as mt
from brands.modutech.gates import Catalogue
from brands.modutech.kg import ModutechGraph, load_modutech_kg
from dialogue_state import DialogueManager

cat = Catalogue("modutech_v30_3.json")
search = mr.CatalogueSearch(cat)
kg = load_modutech_kg(cat, "./__ไม่มีไฟล์__.db", quiet=True)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(f"  {'✓' if cond else '✗'} {name}{'' if cond else '  — ' + str(detail)}")


def ctx(q):
    d = DialogueManager({}, cat, movex_materials={}).decide(q)
    return mt.build_modutech_turn(d, cat, search, vector_search=None, kg=kg).context


print("1) ตัวโหลด")
check("ได้ ModutechGraph", isinstance(kg, ModutechGraph), type(kg))
check("มีชั้นงานใช้", hasattr(kg, "find_applications") and kg.stats()["nodes"].get("Application") == 73)

print("2) ชื่องานตรงตัว")
c = ctx("สายพานสำหรับงานเครื่องชั่งน้ำหนักตรวจสอบ ใช้รุ่นไหนได้บ้าง")
am = c.get("application_match") or {}
check("Checkweighers 6 รุ่น จากกราฟ", am.get("source") == "graph" and am.get("belt_codes_complete") ==
      ["EC127 C", "EC127 FG", "HC152 C", "HC152 FG", "MP80 C", "SM127 C"], am.get("belt_codes_complete"))
check("ไม่ปนงานตรวจจับโลหะ", am.get("applications") == ["Checkweighers"], am.get("applications"))

print("3) งาน × อุตสาหกรรม")
c = ctx("สายพานสำหรับงานเครื่องตรวจจับโลหะในอุตสาหกรรมเบเกอรี่ ใช้รุ่นไหน")
got = set((c.get("application_match") or {}).get("belt_codes_complete") or [])
check("เฉพาะคู่ที่เล่มระบุ", got == set(kg.belts_for_application("Metal Detection", "Bakery Processing")), sorted(got))
check("ไม่มีรุ่นที่ทำงานนี้ในหมวดอื่น (MP80 C)", "MP80 C" not in got)
c = ctx("สายพานสำหรับงานการลำเลียงกล่องในอุตสาหกรรมกล่องลูกฟูก ใช้รุ่นไหน")
ab = c.get("application_pair_absent") or {}
check("คู่ที่เล่มไม่มี → application_pair_absent", ab.get("industry") == "Corrugated" and "ไม่ได้ระบุ" in ab.get("note_th", ""))
check("ไม่มีรุ่นปนเป็นคำตอบ", not c.get("products") and "application_match" not in c, [p["belt_code"] for p in c.get("products") or []])

print("4) สองขั้นถึงเฟือง")
c = ctx("งานเครื่องจัดเรียงพาเลทในอุตสาหกรรมกล่องลูกฟูก ใช้สายพานกับเฟืองตัวไหน")
sb = c.get("sprockets_by_belt") or {}
belts_with = {b: st["sprocket_codes"] for st in sb.get("sets") or [] for b in st["belt_codes"]}
check("มีรหัสเฟือง 6 รุ่น", len(belts_with) == 6, list(belts_with))
check("รุ่นที่ใช้ชุดเดียวกันรวมเป็นชุดเดียว (XP254 4 รุ่น)",
      any(len(st["belt_codes"]) == 4 for st in sb.get("sets") or []), [st["belt_codes"] for st in sb.get("sets") or []])
check("MD508 C · MD508 NS ไม่มีเฟือง แยกไว้", sb.get("no_sprocket_in_catalogue") == ["MD508 C", "MD508 NS"],
      sb.get("no_sprocket_in_catalogue"))
check("รหัสตรง belt_sprocket_links", all(v == sorted(cat.links[b]["sprocket_codes"]) for b, v in belts_with.items()))
check("ไม่มีขนาดเฟือง", not any(isinstance(x, (int, float)) for v in belts_with.values() for x in v)
      and "dimensions" not in json.dumps(sb))

print("5) การ์ดสินค้า")
first = ctx("MD254 GT ใช้กับงานอะไรได้บ้าง")["products"][0]
apps = [a["application_th"] for i in first["industries"] for a in i["applications"]]
check("ตัดการลำเลียงกล่องออกจากงาน", "การลำเลียงกล่อง" not in apps, apps)
check("ย้ายไป applications_excluded_th", (first.get("applications_excluded_th") or {}).get("applications") ==
      ["การลำเลียงกล่อง (ปลาและอาหารทะเล)"], first.get("applications_excluded_th"))
again = ctx("MD254 GT ใช้กับงานอะไรได้บ้าง")["products"][0]
check("เรียกซ้ำได้ผลเดิม (ไม่แก้แคตตาล็อกในที่)", again.get("applications_excluded_th") == first.get("applications_excluded_th"))
raw = [a["application"] for i in cat.by_code["MD254 GT"]["industries"] for a in i["applications"]]
check("ข้อมูลดิบในแคตตาล็อกยังครบ", "Box Handling" in raw)

print("6) ถอยไป router")
c = ctx("สายพานสำหรับลำเลียงกล่องลูกฟูก")
check("ชื่อไม่ตรงตัว → router เดิม", (c.get("application_match") or {}).get("source") is None and "application_match" in c)

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
