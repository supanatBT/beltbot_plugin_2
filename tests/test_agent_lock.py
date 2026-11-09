"""test_agent_lock.py — agent ที่จะ deploy ตรงกับตัวที่ทดสอบรูป (agent_lock.json) ไหม · ไม่เรียก Gemini

    python test_agent_lock.py
ไม่ผ่าน = prompt หรือสวิตช์ต่างจากตัวที่ทดสอบ → ทดสอบใหม่ก่อน แล้วค่อยอัปเดต agent_lock.json
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
for k in ("AGENT_PROMPT", "AGENT_REPLY_GUARD", "AGENT_RESOLVE_TAB", "AGENT_DATASHEET_FILES", "AGENT_IMAGE_SURFACE",
          "AGENT_IMAGE_MAX_SIDE", "AGENT_BRANDS", "GEMINI_MODEL", "GEMINI_THINKING"):
    os.environ.pop(k, None)

from agent import assistant as A        # noqa: E402
from webapi import versions as V   # noqa: E402

ok = n = 0


def check(name, cond, info=""):
    global ok, n
    n += 1
    ok += bool(cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {info}"))


print("=== test_agent_lock ===")
s = A.lock_status()
check("ค่าเริ่มต้น = ตัวที่ล็อก (agent_lock.json)", s["matches"] is True, s.get("diff") or s.get("error"))
check("ล็อกอ้าง commit ที่ทดสอบ", bool(s.get("tested_commit")), s)

os.environ["AGENT_IMAGE_SURFACE"] = "0"
s = A.lock_status()
check("ปิดผิวจากรูป → ไม่ตรงล็อก", s["matches"] is False and "image_surface" in s["diff"], s.get("diff"))
check("prompt เปลี่ยนตามไปด้วย (prompt_sha)", "prompt_sha" in s["diff"], s.get("diff"))
os.environ.pop("AGENT_IMAGE_SURFACE")
os.environ["GEMINI_THINKING"] = "high"
check("thinking ต่าง → ไม่ตรงล็อก", "thinking" in A.lock_status()["diff"])
os.environ.pop("GEMINI_THINKING")


class _Mod:                         # versions.collect กับโมดูล agent (ไม่มีแบรนด์แบบบอท)
    lock_status = staticmethod(A.lock_status)


v = V.collect(_Mod)
check("versions มีส่วน agent", v.get("agent", {}).get("matches") is True, v.get("agent"))
sm = V.summary(v)
check("/health สรุป agent_lock", sm.get("agent_lock", {}).get("matches") is True, sm)

print(f"\nรวม {ok}/{n}")
sys.exit(0 if ok == n else 1)
