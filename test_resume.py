"""test_resume.py — เทสต์เส้นทางกู้บทสนทนาใน webapi/bot.py โดยไม่โหลดโมเดลจริง

รัน:  python test_resume.py        (ในโฟลเดอร์นี้ ซึ่งมี fakebot.py · dialogue_state.py · webapi/)

เทสต์สี่กลุ่ม
  1. rebuild_history        ประวัติจาก localStorage → history ของ chat_interaction
  2. sanitize_dialog_state  ตัดรหัส/slot/brand ปลอมที่ client ส่งมา
  3. seed_session           ใส่ประวัติ+สถานะเข้า session ใหม่ แล้วถามต่อได้
  4. ไม่มี resume            ต้องทำงานเหมือนเดิมทุกอย่าง
"""
import sys

sys.path.insert(0, ".")

from webapi.bot import (BotAdapter, BotSession, RESUME_MAX_CHARS,  # noqa: E402
                        rebuild_history, sanitize_dialog_state)
import fakebot  # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  — {detail}")


def head(t):
    print(f"\n{t}")


def adapter():
    a = BotAdapter("fakebot")
    a.load()
    return a


# ───────────────────────────── 1
head("1) rebuild_history")

msgs = [
    {"id": "a", "role": "user", "text": "HC508 C กว้างเท่าไหร่"},
    {"id": "b", "role": "bot", "text": "508.0 มม."},
    {"id": "c", "role": "assistant", "text": "ตอบแล้ว"},
    {"id": "d", "role": "bot-image", "url": "/media/xyz", "alt": "แบบ"},
    {"id": "e", "role": "notice", "text": "ส่งไม่สำเร็จ"},
    {"id": "f", "role": "user", "text": "   "},
    "ไม่ใช่ dict",
    {"id": "g", "role": "user", "text": 123},
]
h = rebuild_history(msgs)
ok("เก็บเฉพาะ user/assistant", [m["role"] for m in h] == ["user", "assistant"], h)
ok("ไม่มีคีย์ path หลุดมา", all(set(m) == {"role", "content"} for m in h), h)
ok("ข้ามรูป · notice · ข้อความว่าง · ชนิดผิด", len(h) == 2, h)
ok("ตัดข้อความยาวเกิน",
   len(rebuild_history([{"role": "user", "text": "ก" * 5000}])[0]["content"]) == RESUME_MAX_CHARS)
ok("input ไม่ใช่ list → []", rebuild_history(None) == [] and rebuild_history("x") == [])
ok("จำกัดจำนวนเทิร์น",
   len(rebuild_history([{"role": "user", "text": f"q{i}"} for i in range(100)])) == 16)

# ───────────────────────────── 2
head("2) sanitize_dialog_state")

raw = {
    "brand": "modutech",
    "modutech_codes": ["HC508 C", "ไม่มีรุ่นนี้", 42],
    "modutech_slots": {"wet_or_dry": "wet", "ราคาลับ": 1, "material": "ไก่"},
    "movex_pids": ["movex_chain_LF820_K325", "movex_chain_ปลอม"],
    "movex_series": "LF820",
    "pending": "ask_width",
    "role_admin": True,
}
st = sanitize_dialog_state(raw, fakebot)
ok("เก็บรหัสที่มีจริง", st["modutech_codes"] == ["HC508 C"], st["modutech_codes"])
ok("เก็บ pid ที่มีจริง", st["movex_pids"] == ["movex_chain_LF820_K325"], st["movex_pids"])
ok("ตัด slot ที่ไม่รู้จัก", set(st["modutech_slots"]) == {"wet_or_dry", "material"}, st["modutech_slots"])
ok("ไม่กู้ pending", st["pending"] is None)
ok("ตัดคีย์ที่คลาสไม่รู้จัก", "role_admin" not in st, list(st))
ok("brand ปลอมถูกตัด", sanitize_dialog_state({"brand": "acme"}, fakebot)["brand"] is None)
ok("input ไม่ใช่ dict → {}", sanitize_dialog_state(None, fakebot) == {} and
   sanitize_dialog_state("x", fakebot) == {})

# ───────────────────────────── 3
head("3) seed_session แล้วถามต่อ")

a = adapter()
s = BotSession(id="s1")
info = a.seed_session(s, {"messages": msgs, "dialog_state": raw})
ok("รายงานจำนวนข้อความ", info["messages"] == 2, info)
ok("รายงานว่ากู้สถานะได้", info["state"] is True, info)
ok("ได้ bot_session_id", bool(s.bot_session_id), s.bot_session_id)
ok("สถานะอยู่ใน _dialog_states",
   fakebot._dialog_states.get(s.bot_session_id, {}).get("modutech_codes") == ["HC508 C"],
   fakebot._dialog_states.get(s.bot_session_id))

new, _dec = a.turn(s, "แล้วหนาเท่าไหร่", None)
reply = new[-1]["content"]
ok("บอทเห็นประวัติเดิม", "เห็นประวัติ 2 ข้อความ" in reply, reply)
ok("บอทเห็นรหัสในบริบท", "HC508 C" in reply, reply)
ok("current_state คืนของจริง", a.current_state(s).get("brand") == "modutech", a.current_state(s))

# ───────────────────────────── 4
head("4) ไม่มี resume ก็ต้องทำงานเหมือนเดิม")

a2 = adapter()
s2 = BotSession(id="s2")
ok("resume ว่าง → ไม่กู้สถานะ",
   a2.seed_session(s2, {}) == {"messages": 0, "state": False} and not s2.bot_session_id)

new2, _ = a2.turn(s2, "สวัสดี", None)
# fakebot ต่อข้อความของผู้ใช้เข้า history ก่อนนับ แล้วรายงาน len(history)-1
# ดังนั้น session ที่เริ่มจากศูนย์ต้องรายงาน 0 ไม่ใช่ 1
ok("เริ่มจากศูนย์ได้", "เห็นประวัติ 0 ข้อความ" in new2[-1]["content"], new2[-1]["content"])

print(f"\n{'─' * 46}\n{PASS}/{PASS + FAIL} ผ่าน")
sys.exit(1 if FAIL else 0)
