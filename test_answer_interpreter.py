"""
test_answer_interpreter.py — core/answer_interpreter + ทางที่ปลั๊กอิน Modutech ใช้ (ไม่เรียก LLM จริง)

    python test_answer_interpreter.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as DS  # noqa: E402
from brands.modutech import need_flow as NF  # noqa: E402
from core.answer_interpreter import AnswerInterpreter, parse_reading  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


print("1) ตรวจผลจาก LLM")
r = parse_reading('{"kind":"value","value":2,"unit":"inch"}', "number_mm")
ok("2 นิ้ว → 50.8 มม. (โค้ดแปลง ไม่ให้ LLM คำนวณ)", r and r.number("number_mm") == 50.8)
ok("JSON ในข้อความอื่นก็อ่านได้", parse_reading('ผล: {"kind":"unknown"} จบ', "number_mm").kind == "unknown")
ok("kind แปลก → None", parse_reading('{"kind":"maybe"}', "number_mm") is None)
ok("JSON เสีย → None", parse_reading('{"kind":', "number_mm") is None)
ok("พิทช์ 900 มม. หลุดช่วง → None", parse_reading('{"kind":"value","value":900,"unit":"mm"}', "number_mm") is None)
ok("อุณหภูมิ -35 ในช่วง", parse_reading('{"kind":"value","value":-35,"unit":"c"}', "number_c").number("number_c") == -35)
ok("value ไม่ใช่ตัวเลข → None", parse_reading('{"kind":"value","value":"สองนิ้ว"}', "number_mm") is None)
ok("wet_dry แต่ไม่บอกเปียก/แห้ง → None", parse_reading('{"kind":"value"}', "wet_dry") is None)
ok("wet_or_dry ค่าแปลกถูกทิ้ง", parse_reading('{"kind":"other","wet_or_dry":"moist"}', "free").wet_or_dry is None)

print("\n2) ตัวตีความ: ล้ม = ใช้กฎ")
def boom(*a, **k):
    raise TimeoutError("ช้า")


interp = AnswerInterpreter(boom)
ok("เรียกไม่ได้ → None", interp.interpret("พิทช์?", "2 นิ้ว", "number_mm") is None and interp.failures == 1)
interp = AnswerInterpreter(lambda *a, **k: "ไม่รู้")
ok("ตอบไม่เป็น JSON → None", interp.interpret("พิทช์?", "2 นิ้ว", "number_mm") is None)
seen = {}


def capture(system, user, json_mode=False, temperature=None):
    seen.update(system=system, user=user, json_mode=json_mode, temperature=temperature)
    return '{"kind":"unknown"}'


AnswerInterpreter(capture).interpret("ต้องการระยะพิทช์เท่าไหร่", "ไม่รู้", "number_mm")
ok("ส่งคำถาม + คำตอบ + ชนิดที่คาด · JSON mode · temperature 0",
   "ต้องการระยะพิทช์เท่าไหร่" in seen["user"] and "number_mm" in seen["user"] and seen["json_mode"]
   and seen["temperature"] == 0)

print("\n3) ปลั๊กอิน Modutech ใช้ผลจาก LLM ปลอม")
cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
mgr = DS.DialogueManager({}, cat)
core, plugin = mgr.core, mgr.modutech_plugin

# คำตอบที่กฎ regex อ่านไม่ออก → LLM ปลอมตอบตามตาราง
TABLE = {
    "เท่าของเดิมแหละ สองนิ้วมั้ง": {"kind": "value", "value": 2, "unit": "inch"},
    "แล้วแต่เลย ไม่ซีเรียส": {"kind": "unknown"},
    "ห้องเย็นติดลบยี่สิบ": {"kind": "value", "value": -20, "unit": "c"},
    "อันนั้นแหละ": {"kind": "yes"},
    "ผิด ไม่ใช่อันนั้น": {"kind": "no"},
    "เดี๋ยวก่อน ขอเบอร์ฝ่ายขายหน่อย": {"kind": "other"},
    "หมายถึงอุณหภูมิตรงไหน": {"kind": "question"},
    "มีน้ำกระเด็นตลอด": {"kind": "value", "wet_or_dry": "wet"},
}


def fake(system, user, json_mode=False, temperature=None):
    ans = user.split("คำตอบของลูกค้า: ")[-1].strip()
    if ans in TABLE:
        return json.dumps(TABLE[ans], ensure_ascii=False)
    try:                                   # ตัวเลขเปล่า → ค่า ตามชนิดที่คาด
        unit = "c" if "number_c" in user else "mm"
        return json.dumps({"kind": "value", "value": float(ans.replace("นิ้ว", "")) * 1, "unit":
                           "inch" if "นิ้ว" in ans else unit})
    except ValueError:
        return json.dumps({"kind": "unknown"})


plugin._interpreter = AnswerInterpreter(fake)


def run(turns):
    st, out = None, []
    for t in turns:
        d = core.decide(t, state=st)
        st = d.state
        out.append(d)
    return out, st


def sl(st):
    return st.brands["modutech"]["slots"]


ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "เท่าของเดิมแหละ สองนิ้วมั้ง"])
ok("\"เท่าของเดิมแหละ สองนิ้วมั้ง\" → พิทช์ 50.8 · ถามอุณหภูมิต่อ", sl(st).get("pitch_mm") == 50.8
   and ds[-1].reply_th == NF.ASK_TEMP_TH and "ตีความ: LLM" in ds[-1].reason, (sl(st), ds[-1].reason))
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "แล้วแต่เลย ไม่ซีเรียส"])
ok("\"แล้วแต่เลย ไม่ซีเรียส\" → ไม่ทราบ", sl(st).get("pitch_mm") == NF.UNKNOWN)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว", "ห้องเย็นติดลบยี่สิบ"])
ok("\"ห้องเย็นติดลบยี่สิบ\" → -20 °C", sl(ds[-1].state).get("temp_c") == -20.0, sl(ds[-1].state))
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "50.6", "อันนั้นแหละ"])
ok("ยืนยันพิทช์ \"อันนั้นแหละ\" → 50.8", sl(ds[-1].state).get("pitch_mm") == 50.8)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "50.6", "ผิด ไม่ใช่อันนั้น"])
ok("\"ผิด ไม่ใช่อันนั้น\" → ถามพิทช์จริง", ds[-1].reply_th.startswith("ถ้าไม่ใช่ 50.8"), ds[-1].reply_th)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว", "หมายถึงอุณหภูมิตรงไหน"])
ok("ถามกลับเรื่องอุณหภูมิ → อธิบาย + ถามซ้ำ", ds[-1].reply_th.startswith(NF.EXPLAIN_TH["temp"]))
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "เดี๋ยวก่อน ขอเบอร์ฝ่ายขายหน่อย"])
ok("ขอเบอร์กลางการถาม → ส่งฝ่ายขาย (การถามค้างไว้ ลูกค้าตอบต่อได้ · C09)", ds[-1].action == "escalate", ds[-1].action)
TABLE["ขอดูสเปก EC508 C ก่อน"] = {"kind": "other"}
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "ขอดูสเปก EC508 C ก่อน"])
ok("เปลี่ยนเรื่องเป็นรหัส → ออกจากการถาม ตอบรหัส", ds[-1].action == "answer" and NF.FLOW_KEY not in sl(st)
   and ds[-1].payload.get("codes") == ["EC508 C"], (ds[-1].action, sl(st)))
TABLE["ว่าแต่มีแบบผิวกันลื่นไหม"] = {"kind": "other"}
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "ว่าแต่มีแบบผิวกันลื่นไหม"])
ok("LLM บอกเปลี่ยนเรื่อง (ไม่มีรหัส) → ออกจากการถาม ตอบเรื่องใหม่", NF.FLOW_KEY not in sl(st)
   and ds[-1].action in ("search", "answer"), (ds[-1].action, ds[-1].reason, sl(st)))
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว", "80", "มีน้ำกระเด็นตลอด"])
ok("\"มีน้ำกระเด็นตลอด\" → ไลน์เปียก · ตอบ", sl(st).get("wet_or_dry") == "wet" and ds[-1].action == "answer")

plugin._interpreter = AnswerInterpreter(boom)
ds, st = run(["สายพาน modutech รุ่นไหนดี", "ไก่", "2 นิ้ว"])
ok("LLM ล้ม → กฎเดิมอ่าน \"2 นิ้ว\" ได้ · เหตุผลบอกว่าใช้กฎ", sl(ds[-1].state).get("pitch_mm") == 50.8
   and "ตีความ: กฎ" in ds[-1].reason, ds[-1].reason)
plugin._interpreter = None

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
