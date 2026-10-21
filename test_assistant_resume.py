"""
test_assistant_resume.py — กู้บทสนทนากับบอตตัวจริง (assistant.py) ผ่าน webapi (ชั้น 6)
test_resume.py / test_api_resume.py ใช้ fakebot เท่านั้น — ไฟล์นี้ต่อสายจริง: BotAdapter → assistant →
ปลั๊กอิน (sanitize) → core/turn โดยใช้โมเดลปลอมชุดเดียวกับ prompt snapshot (ไม่มีเน็ต ไม่มี GPU)

    python test_assistant_resume.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "training", "prompt_snapshot"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("GEMINI_API_KEY", "fake-key-for-test")

import fakes                                                  # noqa: E402
fakes.install_all()
import retriever_v4                                           # noqa: E402
fakes.patch_retriever(retriever_v4.RetrieverV4, {})

from webapi.bot import BotAdapter, BotSession                 # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


a = BotAdapter("assistant")
a.load()
import assistant                                              # noqa: E402

print("1) seed_session ผ่านปลั๊กอินจริง")
s = BotSession(id="s1")
raw = {"brand": "modutech", "modutech_codes": ["HC508 C", "ไม่มีรุ่นนี้"],
       "modutech_slots": {"wet_or_dry": "wet", "ราคาลับ": 1},
       "movex_pids": ["movex_chain_LF820_K325", "ปลอม"], "pending": "x"}
info = a.seed_session(s, {"messages": [{"role": "user", "text": "HC508 C กว้างเท่าไหร่"},
                                       {"role": "assistant", "text": "กว้าง ..."}], "dialog_state": raw})
st = assistant._dialog_states.get(s.bot_session_id) or {}
ok("กู้สถานะได้", info["state"] is True, info)
ok("รหัสที่ไม่มีจริงถูกตัด (ถามแคตตาล็อกของปลั๊กอิน)", st.get("modutech_codes") == ["HC508 C"], st)
ok("pid ที่ไม่มีจริงถูกตัด", st.get("movex_pids") == ["movex_chain_LF820_K325"], st)
ok("slot ที่ไม่รู้จักถูกตัด", st.get("modutech_slots") == {"wet_or_dry": "wet"}, st)
ok("ไม่กู้ pending", st.get("pending") is None)

print("\n2) ถามต่อหลังกู้ — บอตจำรุ่นได้")
new, dec = a.turn(s, "ทนอุณหภูมิได้กี่องศา", None)
st2 = a.current_state(s)
ok("ตอบผ่านเส้นของแบรนด์ที่กู้มา", dec == "answer", dec)
ok("รุ่นยังอยู่ในสถานะ", st2.get("modutech_codes") == ["HC508 C"], st2)
ok("current_state เป็นชื่อแบนแบบเดิม", list(st2)[:2] == ["brand", "movex_pids"], list(st2))

print("\n3) สถานะเปล่า / แบรนด์ปลอม ไม่กู้")
s2 = BotSession(id="s2")
ok("brand ปลอม + รหัสปลอม → ไม่กู้", a.seed_session(s2, {"dialog_state": {"brand": "acme",
                                                                       "modutech_codes": ["x"]}})["state"] is False)
ok("ซีรีส์อย่างเดียว → ไม่กู้ (เงื่อนไขเดิม)",
   a.seed_session(BotSession(id="s3"), {"dialog_state": {"movex_series": "820"}})["state"] is False)

print(f"\nรวม {passed}/{passed + failed}")
for p in assistant.plugins.values():
    if hasattr(p, "close"):        # close() ไม่บังคับในสัญญา — พบตอนเพิ่ม brands/demo
        p.close()
sys.exit(1 if failed else 0)
