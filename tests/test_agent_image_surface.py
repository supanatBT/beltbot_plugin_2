"""
test_agent_image_surface.py — เครื่องมือ belts_by_surface ของ agent (AGENT_IMAGE_SURFACE=1 · 6 พ.ย.)

ยืนยัน 3 อย่าง (ไม่เรียก Gemini)
    1. ผลเท่ากับตัวคัดของบอท (brands/modutech/image_read.image_match) ทุกตัวอักษร — ต่างกันแค่ใครอ่านรูป
    2. ค่าที่ LLM ส่งมาผ่านตัวตรวจเดียวกับบอท (ผิวปลอม · พิทช์ไม่มีสเกล · มั่นใจต่ำ)
    3. สวิตช์ปิด = เครื่องมือและ prompt เท่าเดิม (ผลบทที่ 4 เทียบได้)

    python test_agent_image_surface.py      (ต้องมี google-adk · mcp ตาม requirements ของ agent)
"""
from __future__ import annotations
import os as _os, sys as _sys  # รากของ repo: import แพ็กเกจได้ และพาธข้อมูลนับจากราก
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import asyncio
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["AGENT_IMAGE_SURFACE"] = "0"

from agent import agent as A                          # noqa: E402
from agent import tools_impl as T                     # noqa: E402
from brands.modutech.image_read import image_match, image_spec  # noqa: E402
from core.image_interpreter import parse_reading               # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


cat, search, *_ = T._state()
spec = image_spec(cat)
call = lambda **k: json.loads(T.belts_by_surface(**k))   # noqa: E731


def bot(**k):
    base = {"is_product": "yes", "surface": None, "surface_alternatives": [], "openness": None,
            "scale_visible": False, "pitch_mm": None, "confidence": "medium"}
    base.update(k)
    return image_match(parse_reading(json.dumps(base), spec), search, cat, spec)[0]


print("1 · ผลเท่ากับตัวคัดของบอท")
for name, kw, bk in [
    ("Flush Grid", dict(surface="Flush Grid"), dict(surface="Flush Grid")),
    ("ผิว + ผิวสำรอง", dict(surface="Flat Top", alternatives="Perforated Flat Top, Nub Top"),
     dict(surface="Flat Top", surface_alternatives=["Perforated Flat Top", "Nub Top"])),
    ("ผิวทึบอย่างเดียว", dict(surface="", openness="closed"), dict(openness="closed")),
    ("พิทช์ + สเกล", dict(surface="Flush Grid", pitch_mm=50.8, scale_visible=True),
     dict(surface="Flush Grid", pitch_mm=50.8, scale_visible=True)),
]:
    a, b = call(**kw), bot(**bk)
    ok(f"{name}: รายชื่อตรงกัน", a.get("matched") and b and a["belt_codes_complete"] == b["belt_codes_complete"],
       (a.get("count"), b and b["count"]))
fg = call(surface="Flush Grid")
ok("ลดรุ่นได้จริง + มีพิทช์ไว้ถาม + บอกว่าไม่ใช่การระบุรุ่น",
   0 < fg["count"] < len(cat.products) and fg.get("pitches_mm_in_list") and "ไม่ใช่การระบุรุ่น" in fg["note_th"])

print("\n2 · ตัวตรวจเดียวกับบอท")
bad = call(surface="Mesh Magic")
ok("ผิวที่ไม่มีในรายการ → error + รายชื่อที่รับได้", "error" in bad and "Flush Grid" in bad["allowed_surfaces"])
ok("confidence แปลก → error", "error" in call(surface="Flat Top", confidence="sure"))
ok("ชื่อผิวไม่สนตัวพิมพ์", call(surface="flush grid")["count"] == fg["count"])
ok("พิทช์ไม่มีสเกล → ทิ้ง (ไม่มี pitch_estimate_mm)", "pitch_estimate_mm" not in call(surface="Flush Grid", pitch_mm=25.4))
low = call(surface="Flush Grid", confidence="low")
ok("มั่นใจต่ำ → ไม่คัดรุ่น + ให้ถามเพิ่ม", low["matched"] is False and "ถาม" in low["note_th"])
ok("ไม่มีผิว ไม่มีความทึบ → ไม่คัดรุ่น", call(surface="")["matched"] is False)

print("\n3 · สวิตช์")


def tools_and_prompt(on: bool):
    if on:
        os.environ["AGENT_IMAGE_SURFACE"] = "1"
    else:
        os.environ["AGENT_IMAGE_SURFACE"] = "0"
    from agent import mcp_server
    S = importlib.reload(mcp_server)
    tools = asyncio.run(S.app.list_tools())
    return {t.name: t for t in tools}, A.instruction_text()


off_tools, off_prompt = tools_and_prompt(False)
on_tools, on_prompt = tools_and_prompt(True)
ok("ปิด = ไม่มี belts_by_surface", "belts_by_surface" not in off_tools)
ok("ปิด = prompt ไม่มีกฎผิวจากรูป", "belts_by_surface" not in off_prompt)
ok("เปิด = เครื่องมือเพิ่มตัวเดียว", set(on_tools) - set(off_tools) == {"belts_by_surface"})
desc = on_tools["belts_by_surface"].description
ok("คำอธิบายเครื่องมือมีผิวครบทุกชื่อ", all(f'"{s}"' in desc for s in spec.surfaces))
ok("เปิด = prompt เดิม + กฎผิวจากรูปต่อท้าย", on_prompt.startswith(off_prompt) and "belts_by_surface" in on_prompt)
os.environ["AGENT_IMAGE_SURFACE"] = "0"

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
