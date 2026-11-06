"""ทดสอบการส่งรูป datasheet ของ agent (AGENT_DATASHEET_FILES · 4 พ.ย. 2026) แบบออฟไลน์ — ไม่เรียก Gemini

    python test_agent_datasheet.py          (venv ของ agent)

ตรวจ
  ปิดสวิตช์ (ค่าเริ่มต้น) = agent เดิมทุกตัวอักษร: ผลเครื่องมือเท่าฟังก์ชันเดิม · ไม่เขียนไฟล์ · ไม่แนบรูป
  เปิดสวิตช์: เครื่องมือเขียน PNG ลงไฟล์ · แชทใหม่ไม่ได้ข้อความ "แสดงบนหน้าจอเรียบร้อยแล้ว" ·
             agent_assistant แนบรูปท้ายบทสนทนาแบบเดียวกับบอท · run_answer_eval อ่านคำตอบเป็นข้อความ ไม่ใช่รูป ·
             หน้าเว็บแปลงเป็นข้อความรูป · รูปไม่ถูกส่งเข้า session ของ ADK (ไม่กินโทเคน) · ไฟล์เก่าไม่ถูกแนบ
ต้องมีรูป drawing ของจริง (ไม่ใช่ตัวชี้ LFS) และ movex_kg.db ของจริง — ไม่มี = ข้ามส่วนที่สร้างรูปพร้อมบอกเหตุ
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["AGENT_LAZY"] = "1"
os.environ["AGENT_DATASHEET_FILES"] = "0"   # ค่าเริ่มต้นเปิดตั้งแต่ 6 พ.ย.
os.environ["AGENT_DATASHEET_DIR"] = tempfile.mkdtemp(prefix="agent_ds_")

import importlib.util  # noqa: E402
import types  # noqa: E402


class _Any:
    """ตัวแทนชื่อใดก็ได้ในโมดูลที่ไม่มี (แบบเดียวกับ test_agent_movex.py) — ทางที่ทดสอบไม่ใช้โมเดล"""
    def __init__(self, *a, **k):
        pass

    def __call__(self, f=None, *a, **k):
        return f

    def __getattr__(self, attr):
        return _Any()


_MISSING = {top for top in ("torch", "transformers", "peft") if importlib.util.find_spec(top) is None}
for _name in ("torch", "torch.nn", "torch.nn.functional", "transformers", "peft"):
    if _name.split(".")[0] in _MISSING:
        _m = types.ModuleType(_name)
        _m.__getattr__ = lambda attr: _Any
        sys.modules[_name] = _m
if "torch" in _MISSING:
    sys.modules["torch"].nn = sys.modules["torch.nn"]
    sys.modules["torch.nn"].functional = sys.modules["torch.nn.functional"]
    sys.modules["torch"].cuda = types.SimpleNamespace(is_available=lambda: False)
from agent_baseline import movex_tools as M   # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


print("\n=== test_agent_datasheet ===")
R = M._data()[0]
PID = "movex_sprocket_54901"
drawing = next((im["image_path"] for im in R.product_db[PID].get("images", []) if im.get("type") == "drawing"), "")
real_png = os.path.isfile(drawing) and open(drawing, "rb").read(4) == b"\x89PNG"

print("1) ปิดสวิตช์ = agent เดิม")
check("ค่าเริ่มต้นปิด", not M.datasheet_files_on())
R._datasheet_cache.clear()
a = M.movex_datasheet("54901")
R._datasheet_cache.clear()
b = R.generate_datasheet(PID)
check("ผลเครื่องมือเท่าฟังก์ชันเดิมของ runtime.py", a == b, f"{a!r} vs {b!r}")
check("ไม่เขียนไฟล์", not os.listdir(M.DATASHEET_DIR))
import agent_assistant as A   # noqa: E402
calls = [{"tool": "movex_datasheet", "args": {"product_id": "54901"}}]
check("datasheet_messages คืน [] เมื่อปิด", A.datasheet_messages(calls, 0) == [])

print("2) เปิดสวิตช์")
os.environ["AGENT_DATASHEET_FILES"] = "1"
if not real_png:
    print(f"  (ข้าม — {drawing} เป็นตัวชี้ LFS หรือไม่มีไฟล์ · รันบนเครื่องที่มีรูปจริง)")
else:
    R._datasheet_cache.clear()
    t0 = time.time()
    out1 = M.movex_datasheet("54901")
    p = M.datasheet_path(PID)
    check("เขียน PNG ลงไฟล์", os.path.isfile(p) and open(p, "rb").read(4) == b"\x89PNG", p)
    check("ข้อความเครื่องมือสั้นเท่าเดิม (ไม่ใส่รูปหรือพาธใน context)",
          "base64" not in out1 and M.DATASHEET_DIR not in out1 and len(out1) < 120, out1)
    out2 = M.movex_datasheet("54901")          # แชทใหม่ ขอรุ่นเดิม
    check("แชทใหม่ไม่ได้ข้อความ 'แสดงบนหน้าจอเรียบร้อยแล้ว'", "แสดงบนหน้าจอ" not in out2, out2)

    msgs = A.datasheet_messages(calls + calls, t0)
    check("แนบรูปหนึ่งใบ (เรียกซ้ำรุ่นเดิมในเทิร์นเดียว = ใบเดียว)", len(msgs) == 1, len(msgs))
    check("รูปแบบเดียวกับบอท (<img src=data:image/png;base64,…>)",
          bool(msgs) and msgs[0]["role"] == "assistant"
          and msgs[0]["content"].startswith('<img src="data:image/png;base64,'))
    check("ไฟล์ที่เขียนก่อนเริ่มเทิร์นไม่ถูกแนบ", A.datasheet_messages(calls, time.time() + 10) == [])
    check("เครื่องมืออื่นไม่ถูกแนบรูป",
          A.datasheet_messages([{"tool": "movex_lookup", "args": {"product_id": "54901"}}], t0) == [])

    print("3) ต่อกับ run_answer_eval และหน้าเว็บ")

    class _Probe:
        sent = []

    eng = A._Engine.__new__(A._Engine)          # ไม่สร้าง ADK/MCP จริง — แทนการคุยกับ LLM ด้วยผลคงที่
    eng.llm = A._LLMInfo()
    eng.last_images = []

    def fake_call(coro):
        _Probe.sent.append(coro.cr_frame.f_locals.get("message") if coro.cr_frame else None)
        coro.close()
        return "นี่คือ Datasheet ของสเตอร์ 54901 ครับ", {"tool_calls": calls}, "fake"

    async def fake_new_session():
        return "s1"

    eng._call = lambda c: fake_call(c) if c.__name__ == "_turn" else (c.close(), "s1")[1]
    A.engine = eng
    h, _st, _refs, _p, sid, _v, _g = A.chat_interaction("ขอ datasheet 54901", None, [], [], "", None, None)
    check("ประวัติ = ผู้ใช้ · ข้อความตอบ · รูป", [m["role"] for m in h] == ["user", "assistant", "assistant"],
          [m["role"] for m in h])
    import run_answer_eval as RAE   # noqa: E402
    check("run_answer_eval อ่านคำตอบเป็นข้อความ ไม่ใช่รูป",
          RAE.extract_reply(h) == "นี่คือ Datasheet ของสเตอร์ 54901 ครับ", RAE.extract_reply(h)[:40])
    from webapi.bot import MediaRegistry, to_web_messages   # noqa: E402
    web = to_web_messages(h[1:], MediaRegistry(["image"], ROOT), scrub=False)
    check("หน้าเว็บได้ข้อความ + รูป", [w["type"] for w in web] == ["text", "image"], web and [w["type"] for w in web])
    msg = _Probe.sent[-1] if _Probe.sent else None
    parts_text = " ".join(getattr(pt, "text", "") or "" for pt in (getattr(msg, "parts", None) or []))
    check("รูป datasheet ไม่ถูกส่งเข้า session ของ ADK", "base64" not in parts_text and "<img" not in parts_text)

    os.environ["AGENT_DATASHEET_FILES"] = "0"
    eng2 = A._Engine.__new__(A._Engine); eng2.llm = A._LLMInfo(); eng2.last_images = []
    eng2._call = eng._call
    A.engine = eng2
    h2, *_ = A.chat_interaction("ขอ datasheet 54901", None, [], [], "", None, None)
    check("ปิดสวิตช์: ประวัติ = ผู้ใช้ · ข้อความตอบ (เท่าเดิม)", [m["role"] for m in h2] == ["user", "assistant"])

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
