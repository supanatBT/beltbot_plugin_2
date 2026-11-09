"""ทดสอบตัวตรวจคำตอบของ agent (AGENT_REPLY_GUARD · 4 พ.ย. 2026) แบบออฟไลน์ — ไม่เรียก Gemini

    python test_agent_reply_guard.py          (venv ของ agent)

ข้อความทดสอบเขียนเอง ไม่ใช่คำถามหรือคำตอบจากชุด blind
ตรวจ
  ปิดสวิตช์ (ค่าเริ่มต้น) = agent เดิม: คำตอบเท่าเดิมทุกตัวอักษร · ไม่เรียก LLM เพิ่ม
  เปิดสวิตช์: ชื่อฟิลด์หลุด → ขอเขียนใหม่หนึ่งครั้งใน session เดิม · เขียนใหม่ยังหลุด → ข้อความสำรอง ·
             เขียนใหม่ล้ม → ข้อความสำรอง · คำตอบปกติ → ไม่เรียกเพิ่ม · เบอร์ปลอม → ลบแล้วแนบช่องทางจริง ·
             โทเคนและเครื่องมือของการเขียนใหม่ถูกนับรวม · บันทึกเหตุการณ์ไว้ใน llm_usage
"""
from __future__ import annotations
import os as _os, sys as _sys  # รากของ repo: import แพ็กเกจได้ และพาธข้อมูลนับจากราก
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["AGENT_LAZY"] = "1"
for _k in ("AGENT_REPLY_GUARD", "AGENT_DATASHEET_FILES", "AGENT_RESOLVE_TAB", "AGENT_IMAGE_SURFACE"):
    os.environ[_k] = "0"                     # สวิตช์เปิดเป็นค่าเริ่มต้นตั้งแต่ 6 พ.ย. — ไฟล์นี้เริ่มจาก agent เดิม
os.environ.setdefault("AGENT_PROMPT", "r1")

from agent import assistant as A            # noqa: E402
from engine.core import reply_guard as RG     # noqa: E402
from engine.shared.sales_contact import sales_contact_line_th  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


def usage(p=100, c=10, tools=None):
    return {"prompt_token_count": p, "candidates_token_count": c, "total_token_count": p + c,
            "llm_calls": 1, "tool_calls": list(tools or [])}


def make_engine(replies):
    """replies = ลำดับผลของ _turn (ข้อความ, usage) หรือ Exception · เก็บข้อความที่ส่งเข้า session"""
    eng = A._Engine.__new__(A._Engine)
    eng.llm = A._LLMInfo()
    eng.last_images = []
    eng.sent = []
    queue = list(replies)

    def fake_call(coro):
        if coro.__name__ != "_turn":
            coro.close()
            return "s1"
        msg = coro.cr_frame.f_locals.get("message") if coro.cr_frame else None
        eng.sent.append(" ".join(getattr(p, "text", "") or "" for p in (msg.parts or [])) if msg else "")
        coro.close()
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        text, u = item
        return text, u, "fake"

    eng._call = fake_call
    return eng


LEAKY = "สเตอร์รุ่นนี้ใช้กับโซ่ได้ครับ (temperature_trust: unconfirmed)"
CLEAN = "สเตอร์รุ่นนี้ใช้กับโซ่ได้ครับ แต่ยังยืนยันอุณหภูมิใช้งานไม่ได้ แนะนำสอบถามฝ่ายขายครับ"
FAKE = "สนใจสั่งซื้อติดต่อได้ครับ\nโทร 02-111-2222\nขอบคุณครับ"

print("\n=== test_agent_reply_guard ===")
print("1) ปิดสวิตช์ = agent เดิม")
check("ค่าเริ่มต้นปิด", not A.reply_guard_on())
eng = make_engine([(LEAKY, usage())])
r, _ = eng.chat("ถามเอง", None, "s1")
check("คำตอบที่มีชื่อฟิลด์ผ่านไปเท่าเดิม", r == LEAKY, r)
check("เรียก LLM ครั้งเดียว", len(eng.sent) == 1, eng.sent)
check("ไม่มีบันทึก reply_guard", "reply_guard" not in eng.llm.last_usage)
eng = make_engine([(FAKE, usage())])
r, _ = eng.chat("ถามเอง", None, "s1")
check("เบอร์ปลอมไม่ถูกแตะเมื่อปิด", r == FAKE, r)

os.environ["AGENT_REPLY_GUARD"] = "1"
print("2) เปิดสวิตช์")
eng = make_engine([(CLEAN, usage())])
r, _ = eng.chat("ถามเอง", None, "s1")
check("คำตอบปกติ → เท่าเดิม", r == CLEAN, r)
check("คำตอบปกติ → ไม่เรียก LLM เพิ่ม", len(eng.sent) == 1, eng.sent)
check("คำตอบปกติ → ไม่มีบันทึก", "reply_guard" not in eng.llm.last_usage)

tc1 = [{"tool": "movex_lookup", "args": {"product_id": "x"}}]
tc2 = [{"tool": "movex_lookup", "args": {"product_id": "y"}}]
eng = make_engine([(LEAKY, usage(100, 10, tc1)), (CLEAN, usage(150, 20, tc2))])
r, _ = eng.chat("ถามเอง", None, "s1")
check("หลุด → ใช้คำตอบที่เขียนใหม่", r == CLEAN, r)
check("ข้อความที่สองเป็นคำขอเขียนใหม่ของบอท", len(eng.sent) == 2 and eng.sent[1] == RG.LEAK_RETRY_TH, eng.sent)
u = eng.llm.last_usage
check("โทเคนรวมสองครั้ง", u["prompt_token_count"] == 250 and u["candidates_token_count"] == 30
      and u["llm_calls"] == 2, u)
check("เครื่องมือรวมสองครั้ง", u["tool_calls"] == tc1 + tc2, u["tool_calls"])
check("บันทึกว่าเขียนใหม่", {"action": "rewritten"} in u.get("reply_guard", []), u.get("reply_guard"))

eng = make_engine([(LEAKY, usage()), ("ยังมี slot_value อยู่ครับ", usage())])
r, _ = eng.chat("ถามเอง", None, "s1")
check("เขียนใหม่ยังหลุด → ข้อความสำรอง", r == RG.LEAK_FALLBACK_TH, r)

eng = make_engine([(LEAKY, usage()), TimeoutError()])
r, _ = eng.chat("ถามเอง", None, "s1")
check("เขียนใหม่ล้ม → ข้อความสำรอง ไม่ทำแชทล้ม", r == RG.LEAK_FALLBACK_TH, r)
check("บันทึกสาเหตุที่ล้ม", {"retry_error": "TimeoutError"} in eng.llm.last_usage.get("reply_guard", []))

eng = make_engine([(FAKE, usage())])
r, _ = eng.chat("ถามเอง", None, "s1")
check("เบอร์ปลอมถูกลบ", "02-111-2222" not in r, r)
line = sales_contact_line_th()
check("แนบช่องทางจริง", (not line) or r.endswith(line), r)
check("ไม่เรียก LLM เพิ่มสำหรับเบอร์ปลอม", len(eng.sent) == 1)

real = f"ติดต่อฝ่ายขายได้ครับ\n{line}" if line else "ติดต่อฝ่ายขายได้ครับ"
eng = make_engine([(real, usage())])
r, _ = eng.chat("ถามเอง", None, "s1")
check("ช่องทางจริงไม่ถูกลบหรือแนบซ้ำ", r == real, r)

print("3) ต่อกับ chat_interaction")
eng = make_engine([(LEAKY, usage()), (CLEAN, usage())])
A.engine = eng
h, *_rest = A.chat_interaction("ถามเอง", None, [], [], "", None, None)
check("ประวัติได้คำตอบที่ผ่านตัวตรวจ", h[-1]["content"] == CLEAN, h[-1])

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
