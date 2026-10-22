#!/usr/bin/env python3
"""เทสต์ชั้นงานใช้/อุตสาหกรรมในกราฟ Modutech (22 ต.ค. 2026)

ยืนยันว่า
  1. จำนวนปมและเส้นตรงกับ JSON (อุตสาหกรรม 7 · งานใช้ 73 · สายพาน×อุตสาหกรรม 211)
  2. กราฟใช้ตัวกรองเกรดเดียวกับ router — ไม่ผูกงานที่รุ่นนั้นไม่มีเกรดตามเล่ม (AP-006 · MD254 GT)
  3. รายชื่อตามอุตสาหกรรมตรงกับ router.match_industry ทุกอุตสาหกรรม
  4. ถามสองขั้น งานใช้ → สายพาน → เฟือง ได้ และรุ่นที่เล่มไม่ผูกเฟืองคืนว่าง ไม่เดา
  5. ปมใหม่ไม่มีตัวเลข · กราฟยังปฏิเสธการเขียนไฟล์ของ Movex

รัน: python test_modutech_kg_apps.py [modutech_v30_3.json]
"""
from __future__ import annotations

import sys

from brands.modutech.gates import Catalogue
from brands.modutech.kg import (APPLICATION, INDUSTRY, USED_FOR, USED_IN, ModutechGraph,
                                _refuse_if_movex)
from brands.modutech.router import CatalogueSearch

PATH = sys.argv[1] if len(sys.argv) > 1 else "modutech_v30_3.json"
cat = Catalogue(PATH)
g = ModutechGraph(cat.data)
search = CatalogueSearch(cat)

ok = fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}{('  — ' + detail) if detail else ''}")


print("1) นับ")
st = g.stats()
pairs = sum(len(p.get("industries") or []) for p in cat.products)
check("อุตสาหกรรม 7 ปม", st["nodes"].get(INDUSTRY) == 7, str(st["nodes"]))
check("งานใช้ 73 ปม (= application_vocabulary)",
      st["nodes"].get(APPLICATION) == len(cat.data["application_vocabulary"]) == 73, str(st["nodes"]))
check(f"USED_IN = คู่สายพาน×อุตสาหกรรม ({pairs})", st["edges"].get(USED_IN) == pairs == 211, str(st["edges"]))
check("USED_FOR มีเส้น", st["edges"].get(USED_FOR, 0) > 0, str(st["edges"]))

print("2) ตัวกรองเกรด")
check("MD254 GT ไม่ผูก Box Handling (เล่มระบุแค่ POM ที่รุ่นนี้ไม่มี)",
      "Box Handling" not in g.applications_for_belt("MD254 GT"), str(g.applications_for_belt("MD254 GT")))
check("SM254 FG50% ผูกงานผ่าน PA → PA6 (base_polymer)", len(g.applications_for_belt("SM254 FG50%")) > 0)

print("3) ตรงกับ router.match_industry")
th = {}
for p in cat.products:
    for i in p.get("industries") or []:
        th[i["industry"]] = i.get("industry_th") or i["industry"]
from brands.modutech.router import INDUSTRY_KEYWORDS  # noqa: E402
for ind, kws in INDUSTRY_KEYWORDS.items():
    res = search.match_industry(kws[0])
    want = set(res[1]) if res and res[0] == ind else set()
    # รุ่นที่มีงานใช้ในอุตสาหกรรมนี้อย่างน้อยหนึ่งงาน (ผ่านตัวกรองเกรดแบบตรงตัว)
    got = set()
    for b in g.belts_in_industry(ind):
        apps = set(g.applications_for_belt(b))
        p = cat.by_code[b]
        made = {v.get("belt_material") for v in p["specifications"]["variants"]}
        for i in p.get("industries") or []:
            if i["industry"] == ind and any(a["application"] in apps and set(a.get("materials") or []) & made
                                            for a in i.get("applications") or []):
                got.add(b)
    check(f"{ind}: {len(want)} รุ่น", got == want, f"ขาด {sorted(want - got)} เกิน {sorted(got - want)}")

print("4) ถามสองขั้น")
spr = g.sprockets_for_application("Box Handling", "Corrugated")
check("Box Handling × Corrugated → 3 รุ่น", sorted(spr) == ["HC152 FG-GT", "MD254 C", "MD508 C"], str(sorted(spr)))
check("MD508 C เล่มไม่ผูกเฟือง → [] ไม่เดา", spr.get("MD508 C") == [], str(spr.get("MD508 C")))
check("HC152 FG-GT ได้รหัสเฟือง", len(spr.get("HC152 FG-GT") or []) > 0)
check("ค้นด้วยชื่อไทยได้", g.belts_for_application("เครื่องตรวจจับโลหะ") == g.belts_for_application("Metal Detection"))

print("5) ตัวกัน")
new = [n for n in g.nodes.values() if n.node_type in (INDUSTRY, APPLICATION)]
check("ปมใหม่ไม่มีตัวเลข", all(isinstance(v, str) for n in new for _, v in n.attrs))
try:
    _refuse_if_movex("movex_kg.db", "ทดสอบ")
    check("ปฏิเสธไฟล์ Movex", False)
except PermissionError:
    check("ปฏิเสธไฟล์ Movex", True)

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
