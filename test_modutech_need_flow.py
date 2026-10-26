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
# 26 ต.ค. ผู้ใช้เลือกข้อ 2 ก: บอกงาน + ขอให้ช่วยเลือก → ข้ามคำถามงาน ถามพิทช์ต่อ (เดิมตอบรายชื่อทันที)
ok("บอกงานมาตั้งแต่แรก + ขอให้ช่วยเลือก → ถามพิทช์ต่อ (ข้ามคำถามงาน)", ds[0].action == "ask"
   and ds[0].reply_th == NF.ASK_PITCH_TH and slots_of(st).get(NF.FLOW_KEY) == "pitch", ds[0].reply_th)
ds, st = run(["สายพาน modutech สำหรับไก่ พิทช์ 2 นิ้ว รุ่นไหนดี"])
ok("บอกพิทช์แล้วแต่ยังไม่บอกอุณหภูมิ → ถามอุณหภูมิ", ds[0].reply_th == NF.ASK_TEMP_TH, ds[0].reply_th)
ds, st = run(["สายพาน modutech สำหรับไก่ พิทช์ 2 นิ้ว ห้องเย็น 5 องศา ไลน์เปียก รุ่นไหนดี"])
ok("บอกครบ (งาน พิทช์ อุณหภูมิ เปียก/แห้ง) → ตอบทันที", ds[0].action == "answer", (ds[0].action, ds[0].reason))
ds, st = run(["สายพานสำหรับงานเครื่องตรวจจับโลหะ ใช้รุ่นไหนได้บ้าง"])
ok("ถามรายชื่อตามเล่ม (\"ใช้รุ่นไหนได้บ้าง\") → ตอบรายชื่อ ไม่ถามพิทช์", ds[0].action == "answer", ds[0].action)

print("\n1b) พิทช์ที่ไม่มีในแคตตาล็อกแต่ใกล้ → ถามยืนยัน (ผู้ใช้เลือก 25 ต.ค.)")
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "50.6", "ใช่ครับ", "ไม่ทราบ"])
ok("50.6 → \"หมายถึง 50.8 มม. (2 นิ้ว) ไหมครับ\"", ds[2].reply_th ==
   "สายพาน Modutech ไม่มีพิทช์ 50.6 มม. ครับ หมายถึง 50.8 มม. (2 นิ้ว) ไหมครับ", ds[2].reply_th)
ok("ตอบใช่ → พิทช์ 50.8 แล้วถามอุณหภูมิต่อ", slots_of(ds[3].state).get("pitch_mm") == 50.8
   and ds[3].reply_th == NF.ASK_TEMP_TH)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "50.6", "ไม่ใช่", "63.5", "ไม่ทราบ"])
ok("ตอบไม่ใช่ → ถามว่าถ้าไม่ใช่ 50.8 แล้วคือเท่าไหร่ (ผู้ใช้ 25 ต.ค.)", ds[3].reply_th.startswith(
   "ถ้าไม่ใช่ 50.8 มม. (2 นิ้ว) ระยะพิทช์ที่ต้องการคือเท่าไหร่ครับ"), ds[3].reply_th)
ok("… ตอบ 63.5 → ใช้ 63.5 แล้วถามอุณหภูมิต่อ", slots_of(ds[4].state).get("pitch_mm") == 63.5
   and ds[4].reply_th == NF.ASK_TEMP_TH)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "50.6", "ไม่ใช่", "50.6", "ไม่ทราบ"])
ok("… ตอบ 50.6 ซ้ำ → ใช้ตามที่ลูกค้ายืนยัน ไม่ถามวนอีก", slots_of(ds[4].state).get("pitch_mm") == 50.6
   and ds[4].reply_th == NF.ASK_TEMP_TH)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "50.6", "ไม่ใช่", "ไม่ทราบ", "ไม่ทราบ"])
ok("… ตอบไม่ทราบ → ไม่กรองพิทช์", slots_of(ds[4].state).get("pitch_mm") == NF.UNKNOWN)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "25", "ไม่ใช่ทั้งหมด"])
ok("หลายตัวเลือก ตอบไม่ใช่ → \"ถ้าไม่ใช่ค่าเหล่านี้ …\"", ds[3].reply_th.startswith("ถ้าไม่ใช่ค่าเหล่านี้"), ds[3].reply_th)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "25", "25.4", "ไม่ทราบ"])
ok("25 → ถามเลือก 25.4 / 25.7 / 25.8 · ตอบ 25.4 → ใช้ 25.4", "หมายถึงค่าไหน" in ds[2].reply_th
   and slots_of(st).get("pitch_mm") == 25.4, ds[2].reply_th)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "25", "ใช่", "ไม่ทราบ"])
ok("หลายตัวเลือก ตอบแค่ \"ใช่\" → ไม่เดาแทน (unknown)", slots_of(st).get("pitch_mm") == NF.UNKNOWN)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่ pitch 50.6", "ครับ", "ไม่ทราบ"])
ok("พิทช์มากับคำตอบงานก็ถามยืนยันเหมือนกัน", NF.PITCH_SAID_KEY in slots_of(ds[1].state)
   and slots_of(st).get("pitch_mm") == 50.8)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "15.2", "ไม่ทราบ"])
ok("15.2 = 15.24 (ปัดทศนิยม) → ไม่ถามยืนยัน", ds[2].reply_th == NF.ASK_TEMP_TH)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "62", "ไม่ทราบ"])
ok("62 ไม่ใกล้ค่าไหน (≤ 1 มม.) → ไม่ถามยืนยัน", ds[2].reply_th == NF.ASK_TEMP_TH)

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

print("\n4) รุ่นที่คำตอบเสนอ → โฟกัสเทิร์นหน้า (เว็บ 25 ต.ค.: \"ขอดูสเปคทั้งสองตัวเทียบกัน\" ถูกตีเป็นนอกเรื่อง)")
from types import SimpleNamespace  # noqa: E402
from core.protocol import LLMTurn, TurnOutput  # noqa: E402
from core.turn import TurnEngine  # noqa: E402


class _Log:
    n = 0

    def new_session(self):
        return "s1"

    def start_turn(self, **kw):
        _Log.n += 1
        return SimpleNamespace(turn_id=f"t{_Log.n}", summary_top1_pid="", summary_tool_calls=0)

    def log_llm(self, *a, **k):
        pass

    def finish_turn(self, *a, **k):
        pass


class _Tools:
    calls = []

    def reset(self):
        pass


REPLY = ("จากข้อมูลพิทช์ 50.6 มม. ไม่มีรุ่นที่ตรง อย่างไรก็ตาม มีรุ่นพิทช์ใกล้เคียง 50.8 มม. ได้แก่\n"
         "• MD508 C\n• EC508 PR11")
seen = []


class _RT:
    def build_turn(self, decision, turn):
        seen.append(decision)
        return LLMTurn(system_prompt="", user_parts=[decision.effective_text])

    def finish_turn(self, decision, turn, llm_turn, result):
        return TurnOutput(REPLY if len(seen) == 1 else "ตารางเทียบสเปก")


class _LLM:
    def run(self, *a, **k):
        return None


plugin.runtime = _RT()
eng = TurnEngine(core, llm=_LLM(), logger=_Log(), tool_log=_Tools())
dst = core.state_cls()
dst.brand = "modutech"
dst.brands["modutech"]["slots"] = {"_flow": "temp", "pitch_mm": 50.6}
dst.pending, dst.pending_question = "modutech_temp", "สายพานนี้รุ่นอะไร ใช้ในโรงงานบรรจุ 50.6"
eng.dialog_states["s1"] = dst.to_dict()
h = eng.chat("ไม่แน่ใจ", None, [], session_id="s1")
st1 = core.state_cls.from_dict(eng.dialog_states["s1"])
ok("หลังคำตอบแนะนำ → จำรุ่นที่เสนอไว้ (_offered) ยังไม่ตั้งเป็นโฟกัสจนกว่าลูกค้าจะอ้างถึง",
   st1.brands["modutech"]["slots"].get("_offered") == ["MD508 C", "EC508 PR11"]
   and st1.brands["modutech"]["codes"] == [], st1.brands["modutech"])
h = eng.chat("ขอดูสเปคทั้งสองตัวเทียบกัน", None, h[0], session_id="s1")
ok("\"ขอดูสเปคทั้งสองตัวเทียบกัน\" → ตอบสองรุ่นนั้น ไม่ใช่นอกเรื่อง",
   h[0][-1]["content"] == "ตารางเทียบสเปก" and seen[-1].payload.get("codes") == ["MD508 C", "EC508 PR11"],
   (h[0][-1]["content"][:60], seen[-1].payload if seen else None))
t = build_modutech_turn(seen[-1], cat, plugin.search)
ok("รุ่นในโฟกัสไม่ถูกกรองด้วยพิทช์ที่ค้างใน slot (50.6) → products ครบสองรุ่น",
   sorted(p["belt_code"] for p in t.context["products"]) == ["EC508 PR11", "MD508 C"]
   and "need_filter" not in t.context, [p["belt_code"] for p in t.context["products"]])
d = core.decide("ขอสเปคหน่อย", state=None)
ok("สะกด \"สเปค\" นับเป็นเรื่องสินค้า", d.action != "refuse_offtopic", d.action)
plugin.runtime = None

print("\n5) สถานะ")
raw = {"codes": [], "slots": {"_flow": "pitch", "pitch_mm": 25.4, "temp_c": "unknown", "junk": [1]}}
san = plugin.sanitize_state(raw)
ok("sanitize เก็บ _flow · pitch_mm · temp_c ทิ้งของแปลก", san["slots"] == {"_flow": "pitch", "pitch_mm": 25.4,
                                                                         "temp_c": "unknown"}, san)

print("\n6) ลูกค้าบอกงาน + อุณหภูมิ + พิทช์ในข้อความเดียว (ลูกค้าจำลอง G02 · OVEN-01/02 · 26 ต.ค.)")
OVEN = "สายพาน modutech เข้าเตาอบ ร้อน 120 องศา แห้ง พิทช์ 1 นิ้ว รุ่นไหนดี"
d = core.decide(OVEN, state=None)
ok("ไม่ตีเป็นค้นทั้งฐาน \"พิทช์ ≥ 120\" → ทางงานใช้", d.action == "answer", (d.action, d.reason))
t = build_modutech_turn(d, cat, plugin.search)
nf = t.context.get("need_filter") or {}
ok("โค้ดกรอง: 120 °C แห้ง พิทช์ 25.4 → ไม่เหลือรุ่น · SM254 FG50% ถูกตัด (ทนแห้ง 116)",
   nf.get("kept") == [] and "116" in (nf.get("removed") or {}).get("SM254 FG50%", "")
   and t.context["products"] == [], nf.get("removed"))
ok("SM254 FG50% 116 < หน้า 347 120 ไม่นับเป็นข้อขัดแย้ง (v30_3 spec-exceeds-material-limit · ตรงกับ gates)",
   "SM254 FG50%" not in (nf.get("temperature_conflicts") or {}), nf.get("temperature_conflicts"))
r = NF.filter_by_need(cat, ["HC152 FG", "MP80 FG", "SM254 FG50%"], None, 130, "dry")
ok("ข้อขัดแย้งจริง (ตารางสเปก 150 > เนื้อวัสดุ 120) ที่ 130 °C → ตัดตามค่าเข้ม + รายงาน",
   r["kept"] == [] and "150" in r["conflicts"].get("HC152 FG", "") and "SM254 FG50%" not in r["conflicts"], r["conflicts"])
r = NF.filter_by_need(cat, ["MD254 RR"], None, 110, "dry")
ok("ค่ายังไม่ยืนยัน (MD254 RR PPH 93 · เนื้อวัสดุ 115) ที่ 110 °C → ตัดทั้งรุ่น + รายงาน",
   r["kept"] == [] and "MD254 RR" in r["conflicts"], r)
r = NF.filter_by_need(cat, ["MD254 RR"], None, 160, "dry")
ok("160 °C เกินเนื้อวัสดุด้วย → ตัดเฉย ๆ ไม่เตือน", r["conflicts"] == {} and r["kept"] == [], r["conflicts"])
ok("พิทช์ใกล้เคียงที่เสนอได้ต้องทน 120 °C ด้วย (MD254 GAP48% เกรด PA/PA 120)",
   nf.get("pitch_near") == {"MD254 GAP48%": 25.7}, nf.get("pitch_near"))
d = core.decide(OVEN.replace("120", "110"), state=None)
nf = build_modutech_turn(d, cat, plugin.search).context.get("need_filter") or {}
ok("110 °C → SM254 FG50% ผ่าน ไม่มีข้อขัดแย้ง", nf.get("kept") == ["SM254 FG50%"]
   and not nf.get("temperature_conflicts"), nf)
d = core.decide("สายพาน modutech ไลน์ขนมปัง ร้อน 100 องศา แห้ง รุ่นไหนดี", state=None)
t = build_modutech_turn(d, cat, plugin.search)
nf = t.context.get("need_filter") or {}
ok("บอกแค่อุณหภูมิ (ไม่ผ่านการถามทีละข้อ) → โค้ดกรองรายชื่อครบ ไม่ปล่อยให้ LLM เลือกเอง",
   nf and all(c in nf["kept"] for c in t.context.get("application_match", t.context.get("industry_match", {}))
              .get("belt_codes_complete", [])) and nf["removed"], (d.action, list(t.context)))
print("\n7) ค้นพิทช์ทั้งฐาน")
s = plugin.search
q = s.parse("มีสายพาน modutech พิทช์ 50.8 ไหม")
ok("\"มีพิทช์ 50.8 ไหม\" = เท่ากับ ไม่ใช่ ≥ (เดิมได้ 63.5 ปน)", q.op == "==" and q.value == 50.8
   and all(m["value"] == 50.8 for m in [h for x in s.search(q)["matches"] for h in x.get("hits", [x])]
           if "value" in m), q)
ok("\"พิทช์ 2 นิ้ว\" → 50.8", s.parse("สายพาน modutech พิทช์ 2 นิ้ว มีรุ่นไหนบ้าง").value == 50.8)
ok("\"พิทช์ไม่เกิน 10 มม.\" ยังเป็นช่วง ≤ 10 (EX-005)", (lambda q: q.op == "<=" and q.value == 10)(
   s.parse("มีสายพานพิทช์ไม่เกิน 10 มม. ไหม")))
ok("เลของศาไม่ถูกใช้เป็นค่าค้น", s.parse("มีสายพานแรงดึงอย่างน้อย 30000 N/m ทน 80 องศาไหม").value == 30000)
ok("stated_pitch ไม่อ่านความกว้างเป็นพิทช์", NF.stated_pitch("กว้าง 24 นิ้ว ไลน์ไก่") is None
   and NF.stated_pitch("pitch 1 นิ้ว ร้อน 120 องศา") == 25.4)
ok("stated_pitch ไม่อ่านช่วงค้นเป็นพิทช์ที่ต้องการ", NF.stated_pitch("มีสายพานพิทช์ไม่เกิน 10 มม. ไหม") is None
   and NF.stated_pitch("พิทช์อย่างน้อย 25 มม.") is None)

print("\n8) คำถามต่อที่เปลี่ยนแค่พิทช์/อุณหภูมิ ใช้งานเดิม (c16_*.json · CONV-16 t5 · 26 ต.ค.)")
st = None
for t in ["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว", "ไม่ทราบ", "ถ้าเป็นพิทช์ 1 นิ้วล่ะ"]:
    d = core.decide(t, state=st)
    st = d.state
t5 = build_modutech_turn(d, cat, plugin.search)
nf = t5.context.get("need_filter") or {}
ok("\"ถ้าเป็นพิทช์ 1 นิ้วล่ะ\" → ยังเป็นงานสัตว์ปีก + พิทช์ 25.4 (ไม่ค้นทั้งฐาน 18 รุ่น)",
   d.action == "answer" and t5.context.get("industry_match", {}).get("industry") == "Poultry"
   and nf.get("kept") and all(cat.by_code[c]["specifications"]["pitch"]["mm"] == 25.4 for c in nf["kept"])
   and "search_result" not in t5.context, (d.action, list(t5.context), nf.get("kept")))
ok("ไม่มีสายพานเลี้ยว EC254 R ปน (ไม่ใช่งานสัตว์ปีกพิทช์ 25.4 ที่ผ่าน)", "EC254 R" not in (nf.get("kept") or []))
d = core.decide("มีสายพาน modutech พิทช์ 50.8 ไหม", state=None)
ok("ไม่มีงานก่อนหน้า → ค้นทั้งฐานเหมือนเดิม", d.action == "search", d.action)
st = None
for t in ["สายพาน modutech ไลน์ปลา พิทช์ 1 นิ้ว ห้องเย็น 5 องศา ไลน์เปียก รุ่นไหนดี", "ถ้าพิทช์ 2 นิ้วล่ะ"]:
    d = core.decide(t, state=st)
    st = d.state
nf = build_modutech_turn(d, cat, plugin.search).context.get("need_filter") or {}
ok("ไลน์ปลา → \"ถ้าพิทช์ 2 นิ้วล่ะ\" กรองในงานปลา", nf.get("kept") and "MD508 C" in nf["kept"], nf.get("kept"))
d = core.decide("EC508 C ถ้าพิทช์ 1 นิ้วล่ะ", state=st)
ok("มีรหัสในประโยค → ไม่เอางานเดิมมาปน", "ไลน์ปลา" not in d.effective_text and d.payload.get("codes") == ["EC508 C"],
   d.effective_text)

print("\n9) ตัดการ์ดเหลืออุตสาหกรรมที่ถาม (prompt 54k → ~46k ตัวอักษร · 26 ต.ค.)")
card = next(p for p in t5.context["products"] if p["belt_code"] == "EC254 C")
ok("การ์ดเหลือเฉพาะสัตว์ปีก + รายชื่ออุตสาหกรรมอื่นยังอยู่ (ไม่ลบเงียบ)",
   [i["industry_th"] for i in card["industries"]] == ["สัตว์ปีก"] and len(card.get("other_industries", [])) >= 3,
   ([i["industry_th"] for i in card["industries"]], card.get("other_industries")))
d = core.decide("EC508 C ใช้กับงานอะไรบ้าง", state=None)
card = build_modutech_turn(d, cat, plugin.search).context["products"][0]
ok("ถามรหัสตรง ๆ → การ์ดครบทุกอุตสาหกรรม", len(card["industries"]) >= 6 and "other_industries" not in card,
   len(card["industries"]))

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
