"""ตัวดำเนินการเทียบใน search_catalogue — เดิม ">" ตกไปเป็น "<=" (MDT-F2 probe_modutech_r2 ตอบผิดเพราะนี้)"""
import json, sys
from brands.modutech.router import CatalogueSearch, ExploratoryQuery, compare
from brands.modutech import turn as T

ok = fail = 0
def check(name, cond):
    global ok, fail
    ok += cond; fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name)

check("compare >", compare(31000, ">", 30000) and not compare(30000, ">", 30000))
check("compare <", compare(2.7, "<", 2.8) and not compare(2.8, "<", 2.8))
check("compare >=/<=", compare(30000, ">=", 30000) and compare(30000, "<=", 30000))
check("compare unknown op → False", not compare(1, "~", 0))

from modutech_gates import Catalogue  # noqa: E402
S = CatalogueSearch(Catalogue("modutech_v30_3.json"))
tool = T.make_search_tool(S)

# MDT-F2: EC508 C สูงสุด 30000 → "> 30000" ต้องได้ 13 รุ่น ทุกค่า > 30000
r = json.loads(tool(field="strength", op=">", value=30000))
vals = [h["value"] for m in r["matches"] for h in m["variants"]]
check(f"strength > 30000 → 13 รุ่น (ได้ {r['matched']})", r["matched"] == 13)
check("strength > 30000 ทุกค่า > 30000", all(v > 30000 for v in vals))
check("strength > 30000 ไม่มี EC508 C", all(m["belt_code"] != "EC508 C" for m in r["matches"]))
check("เรียงมากไปน้อย", r["matches"][0]["belt_code"] == "HD635 C")
# POM > 30000 (เดิมได้ 47 รุ่นที่ ≤ 30000)
r = json.loads(tool(field="strength", op=">", value=30000, belt_material="POM"))
check(f"POM > 30000 ทุกค่า > 30000 (matched {r['matched']})",
      r["matched"] > 0 and all(h["value"] > 30000 for m in r["matches"] for h in m["variants"]))
# MDT-F3 r1: open_area > 0 เดิมคืนรุ่นที่ 0%
r = json.loads(tool(field="open_area", op=">", value=0))
check(f"open_area > 0 ไม่มีรุ่น 0% (matched {r['matched']})",
      all(h["value"] > 0 for m in r["matches"] for h in m["variants"]))
# weight < 2.8 → ไม่มี
r = json.loads(tool(field="weight", op="<", value=2.8))
check("weight < 2.8 → 0 รุ่น", r["matched"] == 0)
# op แปลก → ข้อความผิดพลาด ไม่ใช่ผลกลับด้าน
check("op ผิด → ปฏิเสธ", tool(field="strength", op="~", value=1).startswith("op ไม่ถูกต้อง"))
check("op '=>' → >=", json.loads(tool(field="strength", op="=>", value=100000))["matched"] == 1)

# "น้ำหนัก" ไม่ใช่ "น้ำ" — QI-D2 ("น้ำหนักเบา ๆ") เดิมตั้ง wet_or_dry=wet ให้เองโดยลูกค้าไม่ได้พูด
from brands.modutech.plugin import extract_modutech_slots as X
check("น้ำหนักเบา ๆ → ไม่ตั้งเปียก", "wet_or_dry" not in X("Modutech มีสายพานรุ่นที่น้ำหนักเบา ๆ ไหม", []))
check("รับน้ำหนักได้เท่าไหร่ → ไม่ตั้งเปียก", "wet_or_dry" not in X("รับน้ำหนักได้เท่าไหร่", []))
check("ระบายน้ำ → เปียก", X("ระบายน้ำได้ดี", []).get("wet_or_dry") == "wet")
check("โดนน้ำตลอด → เปียก", X("ไลน์โดนน้ำตลอด", []).get("wet_or_dry") == "wet")
check("น้ำหนัก + ล้างน้ำ → เปียก", X("น้ำหนักเบา ล้างน้ำทุกวัน", []).get("wet_or_dry") == "wet")

print(f"\n{ok}/{ok+fail} ผ่าน")
sys.exit(1 if fail else 0)
