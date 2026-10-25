"""
test_modutech_need_flow.py — ถามความต้องการทีละข้อ (brands/modutech/need_flow.py · 25 ต.ค.)

    python test_modutech_need_flow.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as DS  # noqa: E402
from brands.modutech import need_flow as NF  # noqa: E402
from brands.modutech.turn import build_modutech_turn  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
mgr = DS.DialogueManager({}, cat)
core = mgr.core
plugin = mgr.modutech_plugin


def run(turns):
    st, out = None, []
    for t in turns:
        d = core.decide(t, state=st)
        st = d.state
        out.append(d)
    return out, st


def slots_of(st):
    return st.brands["modutech"]["slots"]


print("1) ลำดับคำถาม งาน → พิทช์ → อุณหภูมิ → เปียก/แห้ง (เฉพาะตอนจำเป็น)")
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว", "80", "เปียก"])
ok("ข้อ 1 ถามงาน (คำถามเดียว)", ds[0].reply_th == NF.ASK_NEED_TH and ds[0].action == "ask")
ok("ข้อ 2 ถามพิทช์", ds[1].reply_th == NF.ASK_PITCH_TH)
ok("ข้อ 3 ถามอุณหภูมิ · พิทช์ 2 นิ้ว = 50.8", ds[2].reply_th == NF.ASK_TEMP_TH and slots_of(ds[2].state)["pitch_mm"] == 50.8)
ok("ข้อ 4 ถามเปียก/แห้ง เพราะผลต่างกันที่ 80 °C", ds[3].reply_th == NF.ASK_WET_TH)
ok("ตอบครบ → answer · ไม่มีสถานะถามค้าง", ds[4].action == "answer" and NF.FLOW_KEY not in slots_of(st)
   and st.pending is None, (ds[4].action, slots_of(st)))
ok("ทุกคำถามเป็นประโยคเดียว ไม่มีรายการหัวข้อ", all("•" not in d.reply_th and "\n" not in d.reply_th for d in ds[:4]))

ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่ pitch 50.8", "-30"])
ok("บอกพิทช์มาแล้วในคำตอบงาน → ข้ามข้อพิทช์", ds[1].reply_th == NF.ASK_TEMP_TH
   and slots_of(ds[1].state)["pitch_mm"] == 50.8)
ok("-30 ไม่ต่างระหว่างเปียก/แห้ง → ไม่ถามเพิ่ม ตอบเลย", ds[2].action == "answer", ds[2].reason)

ds, st = run(["สายพาน modutech รุ่นไหนดี", "ขนมปังเข้าเตาอบ", "ไม่ทราบ", "ไม่แน่ใจ"])
ok("ตอบไม่ทราบทั้งพิทช์และอุณหภูมิ → ตอบได้ ไม่กรอง", ds[3].action == "answer"
   and slots_of(st)["pitch_mm"] == NF.UNKNOWN and slots_of(st)["temp_c"] == NF.UNKNOWN)

ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "25.4", "อุณหภูมิห้อง"])
ok("อุณหภูมิห้อง = 30 °C", slots_of(ds[3].state).get("temp_c") == 30.0, slots_of(ds[3].state))

ds, st = run(["สายพาน modutech รุ่นไหนดี", "ขอสเปก EC127 FG"])
ok("พิมพ์รหัสระหว่างถาม → ออกจากการถาม ตอบรหัส", ds[1].action == "answer" and ds[1].reason == "รหัสชัด"
   and NF.FLOW_KEY not in slots_of(st))

ds, st = run(["สายพาน modutech สำหรับไก่ รุ่นไหนดี"])
ok("บอกงานมาตั้งแต่แรก → ตอบทันทีเหมือนเดิม (ไม่เข้าการถามทีละข้อ)", ds[0].action == "answer"
   and NF.FLOW_KEY not in slots_of(st))

print("\n2) แปลงคำตอบ")
ok("พิทช์: 1 นิ้ว / ½ นิ้ว / 25.4 / 25 มม. / pitch 50.8",
   [NF.parse_pitch("1 นิ้ว"), NF.parse_pitch("½ นิ้ว"), NF.parse_pitch("25.4", True),
    NF.parse_pitch("25 มม."), NF.parse_pitch("ขอ pitch 50.8")] == [25.4, 12.7, 25.4, 25.0, 50.8])
ok("พิทช์: เลขเปล่าไม่นับถ้าไม่ได้ถามพิทช์", NF.parse_pitch("ไก่ 2 ตัน") is None)
ok("อุณหภูมิ: 80 องศา / -30°C / 90 (ตอบคำถามตรง)",
   [NF.parse_temp("80 องศา"), NF.parse_temp("-30°C"), NF.parse_temp("90", True)] == [80.0, -30.0, 90.0])
ok("ไม่ทราบ/ไม่รู้/ไม่แน่ใจ", all(NF.is_unknown(x) for x in ("ไม่ทราบ", "ไม่รู้ครับ", "ไม่แน่ใจ")))

print("\n3) กรองรุ่นจริง")
p254 = [p["belt_code"] for p in cat.products if p["specifications"]["pitch"]["mm"] == 25.4][0]
f = NF.filter_by_need(cat, ["MP80 C", "EC508 C", p254], 25.4, None, None)
ok(f"พิทช์ 25.4 → {p254} ผ่าน · 8 / 50.8 ตก", f["kept"] == [p254] and set(f["removed"]) == {"MP80 C", "EC508 C"}, f)
ok("EC254 TR พิทช์ 26.0 (ชื่อ 254 ไม่ได้แปลว่า 25.4) → ไม่ตรง แต่อยู่ใน near",
   NF.filter_by_need(cat, ["EC254 TR"], 25.4, None, None)["near"] == {"EC254 TR": 26.0})
codes_258 = [p["belt_code"] for p in cat.products if p["specifications"]["pitch"]["mm"] in (25.7, 25.8, 26.0)]
f = NF.filter_by_need(cat, codes_258, 25.4, None, None)
ok("พิทช์ 25.4 ไม่ปน 25.7/25.8/26.0 · แต่บอกเป็นรุ่นใกล้เคียง", f["kept"] == [] and set(f["near"]) == set(codes_258),
   f["kept"])
f_w = NF.filter_by_need(cat, ["MP80 C"], None, 80, "wet")
f_d = NF.filter_by_need(cat, ["MP80 C"], None, 80, "dry")
ok("MP80 C POM: 80 °C เปียกตก (60) แห้งผ่าน (93)", f_w["kept"] == [] and f_d["kept"] == ["MP80 C"])
ok("ไม่รู้เปียก/แห้ง → ใช้ค่าเปียก + บอกใน note",
   NF.filter_by_need(cat, ["MP80 C"], None, 80, None)["kept"] == [] and "ไลน์เปียก" in
   NF.filter_by_need(cat, ["MP80 C"], None, 80, None)["note_th"])
ok("UNKNOWN = ไม่กรอง", NF.filter_by_need(cat, ["MP80 C"], NF.UNKNOWN, NF.UNKNOWN, None)["kept"] == ["MP80 C"])

ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว", "80", "เปียก"])
t = build_modutech_turn(ds[-1], cat, plugin.search)
nf = t.context.get("need_filter") or {}
pitches = {cat.by_code[c]["specifications"]["pitch"]["mm"] for c in nf.get("kept", [])}
ok("build_turn: รุ่นที่ส่งให้ LLM พิทช์ 50.8 ทุกรุ่น", nf.get("kept") and pitches == {50.8}, pitches)
apps = t.context.get("industry_match") or t.context.get("application_match") or {}
ok("build_turn: รายชื่อครบ (belt_codes_complete) เป็นรายชื่อหลังกรอง", apps.get("belt_codes_complete") == nf["kept"])
ok("build_turn: products เฉพาะรุ่นที่ผ่าน", all(p["belt_code"] in nf["kept"] for p in t.context["products"]))
ok("build_turn: LLM ไม่เห็น _flow", NF.FLOW_KEY not in t.context["slots_known"])

ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "63.5", "80", "เปียก"])
t = build_modutech_turn(ds[-1], cat, plugin.search)
nf = t.context.get("need_filter") or {}
ok("ไม่มีรุ่นที่ตรง → kept ว่าง + แนบพิทช์ที่มีให้เลือก", nf.get("kept") == [] and nf.get("available_pitches_mm"),
   nf.get("kept"))

print("\n4) สถานะ")
raw = {"codes": [], "slots": {"_flow": "pitch", "pitch_mm": 25.4, "temp_c": "unknown", "junk": [1]}}
san = plugin.sanitize_state(raw)
ok("sanitize เก็บ _flow · pitch_mm · temp_c ทิ้งของแปลก", san["slots"] == {"_flow": "pitch", "pitch_mm": 25.4,
                                                                         "temp_c": "unknown"}, san)

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
