"""
test_simulate_customers.py — ท่อของ simulate_customers.py แบบไม่ใช้ LLM (ลูกค้าจำลองตามบท · บอทผ่าน TurnEngine จริง)

    python test_simulate_customers.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import simulate_customers as SC  # noqa: E402
import test_conversation_leaks as L  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


goals = {g["id"]: g for g in SC.load_goals(os.path.join(ROOT, "training", "sim_goals.json"))}
judge = SC.Judge()

print("1) ชุดรุ่นที่ถูก (โค้ด ไม่ใช่ LLM)")
acc = judge.acceptable(goals["G01"])
ok("G01 ไก่ตัดแต่ง 50.8 · 5 °C เปียก → มีรุ่น และทุกรุ่นพิทช์ 50.8", acc["ok"] and all(
    judge.cat.by_code[c]["specifications"]["pitch"]["mm"] == 50.8 for c in acc["ok"]), acc)
ok("G02 เตาอบ 25.4 · 120 °C แห้ง → ชุดว่าง (คาดว่าบอทต้องบอกว่าไม่มี)", judge.acceptable(goals["G02"])["ok"] == [])
ok("ทุกเป้าหมายมี id ไม่ซ้ำ และ Modutech มี application", len(goals) == len(SC.load_goals(
    os.path.join(ROOT, "training", "sim_goals.json"))) and all(g.get("application") for g in goals.values()))

print("\n2) ให้คะแนน")
tr = [{"role": "customer", "text": "x"}, {"role": "bot", "text": "แนะนำ MP80 C และ EC508 C ครับ"}]
s = SC.score(goals["G01"], tr, judge, "done")
ok("MP80 C (พิทช์ 8) ผิดเงื่อนไขพิทช์ 50.8 → violation · EC508 C ถูก → hit", s["violations"] == ["MP80 C"]
   and s["hit"], s)
tr = [{"role": "customer", "text": "x"}, {"role": "bot", "text": "ไม่มีรุ่นที่ตรงทุกเงื่อนไขครับ"}]
ok("ชุดว่าง + บอทบอกว่าไม่มี → hit", SC.score(goals["G02"], tr, judge, "done")["hit"])
tr = [{"role": "customer", "text": "a"}, {"role": "bot", "text": "ถามซ้ำ"}, {"role": "customer", "text": "b"},
      {"role": "bot", "text": "ถามซ้ำ"}, {"role": "customer", "text": "c"},
      {"role": "bot", "text": "ขออภัยครับ ผมตอบได้เฉพาะเรื่องสินค้า"}]
s = SC.score(goals["G01"], tr, judge, "giveup")
ok("นับข้อความซ้ำติดกัน + นอกเรื่อง", s["repeats"] == 1 and s["offtopic"] == 1 and not s["hit"], s)
ok("Movex: เจอ K450 → hit", SC.score(goals["G13"], [{"role": "bot", "text": "LF 880 TAB K450 กว้าง 114.3"}],
                                    judge, "done")["hit"])

print("\n3) วนคุยทั้งเส้น (ลูกค้าตามบท · บอทผ่าน TurnEngine จริง)")
rec = L.Recorder()
eng = L.new_engine(rec)
SCRIPT = ["modutech", "ไก่ ไลน์ตัดแต่ง", "ประมาณ 50 มิลครับ", "ใช่", "5 องศา", "เปียก", "โอเคครับ [จบ]"]
calls = {"i": 0}


def fake_complete(system, user, json_mode=False, temperature=None):
    assert "ห้ามคิดชื่อรุ่น" in system and "หัวหน้าไลน์" in system
    m = SCRIPT[calls["i"]]
    calls["i"] += 1
    return m


def chat_fn(text, image, history, last_pids, session_id, vit, graph):
    return eng.chat(text, image, history, last_pids, session_id or "s", vit, graph)


r = SC.run_goal(goals["G01"], chat_fn, fake_complete, judge, max_turns=10, temperature=1.0)
bot = [t["text"] for t in r["transcript"] if t["role"] == "bot"]
ok("ถามแบรนด์ → ถามงาน → พิทช์ → ยืนยัน 50.8 → อุณหภูมิ", "แบบไหน" in bot[0] and "ลำเลียงอะไร" in bot[1]
   and "พิทช์" in bot[2] and "หมายถึง 50.8" in bot[3] and "อุณหภูมิ" in bot[4], [b[:30] for b in bot])
ok("จบแบบ done · ได้รุ่นที่ถูก · ไม่มีรุ่นผิดเงื่อนไข", r["ended"] == "done" and r["hit"] and not r["violations"], r)
ok("ไม่ส่ง [จบ] ไปหาบอท", all("[จบ]" not in t["text"] for t in r["transcript"]))

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.txt")
    SC.write_txt(p, [dict(r, run=1)])
    txt = open(p, encoding="utf-8").read()
ok("ไฟล์ .txt เป็นแชท ลูกค้า/บอท", "🧑 ลูกค้า: ไก่ ไลน์ตัดแต่ง" in txt and "🤖 บอท:" in txt)
summ = SC.summarize([r])
ok("สรุป: hit 100% · ไม่มีผิดเงื่อนไข", summ["hit_pct"] == 100.0 and summ["with_violation_pct"] == 0.0, summ)
L.MOD.runtime = None

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
