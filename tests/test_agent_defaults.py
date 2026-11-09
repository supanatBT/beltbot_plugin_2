"""test_agent_defaults.py — ค่าเริ่มต้นของ agent ที่ล็อก 6 พ.ย. 2026 (ไม่เรียก Gemini)

ไม่ตั้งตัวแปรใดเลย = ตัวที่ใช้ blind v2 + ผิวจากรูป
    AGENT_PROMPT=r3 · AGENT_REPLY_GUARD · AGENT_RESOLVE_TAB · AGENT_DATASHEET_FILES · AGENT_IMAGE_SURFACE เปิด
    GEMINI_MODEL=gemini-3.8-flash · GEMINI_THINKING=low
ตั้ง =0 = ปิดทีละตัว (ใช้รันซ้ำผลเดิม/ทดสอบ agent เดิม) · AGENT_PROMPT=r1/r2/r2m = prompt รุ่นก่อน

    python test_agent_defaults.py
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
SW = ("AGENT_PROMPT", "AGENT_REPLY_GUARD", "AGENT_RESOLVE_TAB", "AGENT_DATASHEET_FILES", "AGENT_IMAGE_SURFACE",
      "GEMINI_MODEL", "GEMINI_THINKING")
for k in SW:
    os.environ.pop(k, None)

from agent import assistant as A                 # noqa: E402
from agent import agent as AG       # noqa: E402
from agent import movex_tools as M  # noqa: E402

ok = n = 0


def check(name, cond, info=""):
    global ok, n
    n += 1
    ok += bool(cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {info}"))


def state():
    return {"prompt": AG.prompt_version(), "guard": A.reply_guard_on(), "surface": AG.image_surface_enabled(),
            "tab": M.resolve_tab_on(), "files": M.datasheet_files_on()}


print("=== test_agent_defaults ===")
s = state()
check("ไม่ตั้งอะไร = prompt r3", s["prompt"] == "r3", s)
for k in ("guard", "surface", "tab", "files"):
    check(f"ไม่ตั้งอะไร = {k} เปิด", s[k] is True, s)
check("prompt มีกฎผิวจากรูป", "belts_by_surface" in AG.instruction_text())

for k in SW[1:5]:
    os.environ[k] = "0"
s = state()
for k in ("guard", "surface", "tab", "files"):
    check(f"ตั้ง =0 = {k} ปิด", s[k] is False, s)
os.environ["AGENT_PROMPT"] = "r1"
check("AGENT_PROMPT=r1 ยังเลือกได้", AG.prompt_version() == "r1")
for k in SW:
    os.environ.pop(k, None)

print(f"\nรวม {ok}/{n}")
sys.exit(0 if ok == n else 1)
