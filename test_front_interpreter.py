#!/usr/bin/env python3
"""
test_front_interpreter.py — ตัวตีความด่านหน้า (core/front_interpreter · 2 พ.ย. · branch bot-qi-first)

LLM ปลอม (ไม่ใช้เน็ต ไม่ใช้โควตา) + ปลั๊กอินจริง (modutech_v30_3.json · extracted_data_v3)
    1. ตรวจ JSON: แบรนด์/หัวข้อ/ชนิดค่าที่ไม่อยู่ในรายการ → ไม่เชื่อทั้งก้อน
    2. ปิด (front=None) = บอทเดิม · เปิดแต่ LLM ล้ม = บอทเดิม
    3. แบรนด์: regex ไม่เจอสัญญาณ → ใช้ผล LLM · regex เจอ → ไม่เรียก LLM เลย · LLM บอก null → ถามแบรนด์เหมือนเดิม
    4. ด่านเปียก/แห้ง: ชื่องาน "ฟรีซเซอร์" ไม่ใช่คำถามอุณหภูมิ · ค่าเปียก = แห้ง ไม่ต้องถาม · ถามแล้วไม่ตอบ ไม่ถามซ้ำ
ข้อความทดสอบเขียนใหม่ทั้งหมด ไม่ใช้คำถามจากชุด blind
    python test_front_interpreter.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as DS                                     # noqa: E402
from core.decide import Dialogue                                # noqa: E402
from core.front_interpreter import FrontInterpreter, parse_front, build_system   # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


print("1) ตรวจ JSON")
K = ["movex", "modutech"]
good = '{"brand": "modutech", "topic": "application", "asks_temperature": false, "wet_or_dry": null, "note": "x"}'
r = parse_front(good, K)
ok("รูปแบบถูก", r is not None and r.brand == "modutech" and r.topic == "application" and r.asks_temperature is False)
ok("แบรนด์ที่ไม่มี → None", parse_front(good.replace('"modutech"', '"acme"'), K) is None)
ok("หัวข้อที่ไม่มี → None", parse_front(good.replace('"application"', '"weather"'), K) is None)
ok("asks_temperature ไม่ใช่ bool → None", parse_front(good.replace("false", '"no"'), K) is None)
ok("wet_or_dry แปลก → None", parse_front(good.replace('"wet_or_dry": null', '"wet_or_dry": "damp"'), K) is None)
ok("ไม่ใช่ JSON → None", parse_front("ไม่รู้ครับ", K) is None)
ok("brand null ได้", parse_front(good.replace('"modutech"', "null", 1), K).brand is None)


class FakeLLM:
    """ตอบตามคำในข้อความ · นับจำนวนครั้ง"""
    def __init__(self, rules, fail=False):
        self.rules, self.fail, self.calls, self.systems = rules, fail, [], []

    def __call__(self, system, user, json_mode=False, temperature=None):
        self.calls.append(user)
        self.systems.append(system)
        if self.fail:
            raise RuntimeError("503")
        for kw, out in self.rules:
            if kw in user:
                return json.dumps(out, ensure_ascii=False)
        return json.dumps({"brand": None, "topic": "other", "asks_temperature": False, "wet_or_dry": None, "note": ""})


data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))


def make(llm=None):
    mgr = DS.DialogueManager(real, cat)
    if llm is None:
        return mgr.core, None
    fi = FrontInterpreter(llm)
    plugins = [mgr.movex_plugin, mgr.modutech_plugin]
    for p in plugins:                     # ปลั๊กอินชุดเดียวใช้ร่วมกันสอง Dialogue ไม่ได้ — สร้างใหม่ทุกครั้ง
        p._front = None
    return Dialogue(plugins, mgr.core.state_cls, image_brands=mgr.core.image_brands, front=fi), fi


def play(core, *texts):
    st, d = None, None
    for t in texts:
        d = core.decide(t, state=st)
        st = d.state
    return d


def is_wet_ask(d):
    return d.action == "ask" and d.pending == "wet_or_dry"


MOD = {"brand": "modutech", "topic": "application", "asks_temperature": False, "wet_or_dry": None, "note": "งานอาหาร"}

print("2) ปิด = บอทเดิม · LLM ล้ม = บอทเดิม")
Q_NOSIG = "ร้านทำไส้กรอกอยากได้สายพานลำเลียงรุ่นไหนดี"
base, _ = make()
d0 = play(base, Q_NOSIG)
ok("ปิด: regex ไม่เจอสัญญาณ → ถามแบรนด์", d0.action == "ask" and d0.topic == "brand", (d0.action, d0.topic))
core_f, fi = make(FakeLLM([], fail=True))
d1 = play(core_f, Q_NOSIG)
ok("LLM ล้ม → ถามแบรนด์เหมือนเดิม", (d1.action, d1.topic, d1.reply_th) == (d0.action, d0.topic, d0.reply_th))
ok("นับความล้มเหลว", fi.failures == 1)

print("3) แบรนด์")
llm = FakeLLM([("ไส้กรอก", MOD)])
core_f, fi = make(llm)
d2 = play(core_f, Q_NOSIG)
ok("regex ไม่เจอ + LLM บอก modutech → ไปปลั๊กอิน Modutech", d2.brand == "modutech" and d2.topic != "brand",
   (d2.action, d2.brand, d2.topic, d2.reason))
ok("system prompt มีสัญญาณของทั้งสองแบรนด์จากปลั๊กอิน",
   "โซ่ท็อปเชนและสเตอร์" in llm.systems[0] and "พื้นที่เปิดหรือรู" in llm.systems[0])
ok("system prompt บอกว่า 'สายพาน' เฉย ๆ ไม่ใช่สัญญาณ", "\"สายพาน\" \"ลำเลียง\"" in llm.systems[0])
n_before = len(llm.calls)
d3 = play(core_f, "EC254 C พิทช์เท่าไหร่")
ok("มีรหัสรุ่น (regex strong) → ไม่เรียก LLM ด่านหน้า", len(llm.calls) == n_before and d3.brand == "modutech",
   (len(llm.calls) - n_before, d3.brand))
d4 = play(core_f, "มีสายพานความกว้าง 300 มิลไหม")
ok("LLM บอก null → ถามแบรนด์", d4.action == "ask" and d4.topic == "brand", (d4.action, d4.topic))
llm_bad = FakeLLM([("ไส้กรอก", {**MOD, "brand": "acme"})])
core_b, _ = make(llm_bad)
ok("LLM ตอบแบรนด์ที่ไม่มี → ไม่เชื่อ ถามแบรนด์", play(core_b, Q_NOSIG).topic == "brand")
d5 = play(core_f, "สายพานสแตนเลสมีอะไรบ้าง")
ok("สแตนเลสไม่ระบุแบรนด์ → ทางข้ามแบรนด์เดิม", d5.action == "cross_brand", d5.action)

print("4) ด่านเปียก/แห้ง")
Q_APP = "สายพาน Modutech สำหรับไลน์ฟรีซเซอร์ไก่มีรุ่นไหนบ้าง"
ok("ปิด: ชื่องานมีคำว่าฟรีซ → ถามเปียก/แห้ง (พฤติกรรมเดิม)", is_wet_ask(play(base, Q_APP)))
core_f, fi = make(FakeLLM([("ฟรีซเซอร์ไก่", MOD)]))
d6 = play(core_f, Q_APP)
ok("เปิด: LLM บอกไม่ได้ถามอุณหภูมิ → ไม่ถามเปียก/แห้ง", not is_wet_ask(d6), (d6.action, d6.reason))

TEMP_Q = {"brand": "modutech", "topic": "temperature", "asks_temperature": True, "wet_or_dry": None, "note": ""}
Q_SAME = "HC508 PR22 เกรด PE ทนเย็นได้กี่องศา"
ok("ปิด: รุ่นต้องรู้เปียก/แห้ง → ถาม", is_wet_ask(play(base, Q_SAME)))
core_f, _ = make(FakeLLM([("HC508 PR22", TEMP_Q)]))
d7 = play(core_f, Q_SAME)
ok("เปิด: เกรด PE ของรุ่นนี้ค่าเปียก = แห้ง → ไม่ต้องถาม", not is_wet_ask(d7), (d7.action, d7.reason))

Q_DIFF = "MP80 C เกรด POM ทนร้อนได้กี่องศา"
core_f, _ = make(FakeLLM([("MP80 C", TEMP_Q)]))
ok("เปิด: เกรด POM เปียกต่างจากแห้ง → ยังถาม", is_wet_ask(play(core_f, Q_DIFF)))

print("5) ถามเปียก/แห้งแล้วลูกค้าตอบเรื่องอื่น")
ANS = "ใช้ที่ประมาณ 70 องศาครับ"
d_base = play(base, Q_DIFF, ANS)
ok("ปิด: ถามเปียก/แห้งซ้ำ (พฤติกรรมเดิม)", is_wet_ask(d_base), (d_base.action, d_base.reason))
core_f, _ = make(FakeLLM([("MP80 C", TEMP_Q)]))
d8 = play(core_f, Q_DIFF, ANS)
mslots = d8.state.brands["modutech"]["slots"]
ok("เปิด: ไม่ถามซ้ำ", not is_wet_ask(d8), (d8.action, d8.reason))
ok("ใช้ค่าเปียกและติดป้ายว่าสมมติ", mslots.get("wet_or_dry") == "wet" and mslots.get("_wet_assumed") is True, mslots)
d9 = play(core_f, Q_DIFF, ANS, "จริง ๆ เป็นไลน์แห้งครับ")
s9 = d9.state.brands["modutech"]["slots"]
ok("ลูกค้าบอกแห้งทีหลัง → ใช้แห้ง ล้างป้ายสมมติ", s9.get("wet_or_dry") == "dry" and not s9.get("_wet_assumed"), s9)
d10 = play(core_f, Q_DIFF, "ไลน์เปียกครับ")
ok("ลูกค้าตอบเปียก/แห้งตามปกติ → ไม่สมมติ", d10.state.brands["modutech"]["slots"].get("wet_or_dry") == "wet"
   and not d10.state.brands["modutech"]["slots"].get("_wet_assumed"))
d11 = play(core_f, Q_DIFF)
ok("คำถามใหม่ (ไม่ใช่คำตอบ) ยังถามได้ตามปกติ", is_wet_ask(d11))

print("6) จำผลข้อความเดิม")
llm = FakeLLM([("ฟรีซเซอร์ไก่", MOD)])
fi = FrontInterpreter(llm, brands=[])
ok("ไม่มีรายชื่อแบรนด์ → ไม่เรียก", fi.read("x") is None and not llm.calls)
core_f, fi = make(llm)
fi.read(Q_APP)
fi.read(Q_APP)
ok("ข้อความเดิมเรียก LLM ครั้งเดียว", len(llm.calls) == 1, len(llm.calls))
ok("system prompt สร้างได้ไม่มีวงเล็บค้าง", "{" not in build_system(fi.brands).split("คืน JSON")[0])

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
