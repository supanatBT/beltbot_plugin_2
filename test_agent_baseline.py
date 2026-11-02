"""ทดสอบ agent เทียบแบบออฟไลน์ (ไม่เรียก Gemini) — รันด้วย venv ของ agent

    python test_agent_baseline.py

LLM ปลอม (BaseLlm ของ ADK) สั่งเรียกเครื่องมือจริงผ่าน MCP server จริง (stdio) แล้วตอบจากผลที่ได้
ตรวจ: เครื่องมือครบ 11 · ADK ↔ MCP ↔ ฐานข้อมูลจริงต่อกันได้ · session ข้ามเทิร์น · รูปถูกบันทึกและส่ง · ตัวเชื่อมคืน 7 ค่า
"""
from __future__ import annotations

import json
import os
import sys
from typing import AsyncGenerator

os.environ["AGENT_LAZY"] = "1"
from google.adk.models.base_llm import BaseLlm          # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types                          # noqa: E402

import agent_assistant as A                             # noqa: E402
from agent_baseline.agent import INSTRUCTION_TH, INSTRUCTION_TH_R2, build_agent  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


SEEN: list = []


class FakeLlm(BaseLlm):
    """เทิร์นที่ข้อความลูกค้ามีคำว่า 'สูงสุด' → เรียก search_catalogue · มีรูป → match_catalogue_image · อื่น ๆ → ตอบตรง"""
    model: str = "fake"

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        SEEN.append(llm_request)
        last = llm_request.contents[-1]
        fr = [p.function_response for p in last.parts if p.function_response]
        if fr:
            body = fr[0].response
            text = json.dumps(body, ensure_ascii=False)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"ผลจากเครื่องมือ: {text[:400]}")]),
                              usage_metadata=types.GenerateContentResponseUsageMetadata(
                                  prompt_token_count=10, candidates_token_count=5, total_token_count=15))
            return
        user_text = " ".join(p.text for p in last.parts if p.text)
        if "image_id=" in user_text:
            iid = user_text.split("image_id=")[1].split("]")[0]
            call = types.FunctionCall(name="match_catalogue_image", args={"image_id": iid})
        elif "สูงสุด" in user_text:
            call = types.FunctionCall(name="search_catalogue", args={"field": "strength", "rank": "max"})
        else:
            n_user = sum(1 for c in llm_request.contents if c.role == "user" and any(p.text for p in c.parts))
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"เทิร์นผู้ใช้ที่เห็น {n_user}")]),
                              usage_metadata=types.GenerateContentResponseUsageMetadata(
                                  prompt_token_count=3, candidates_token_count=2, total_token_count=5))
            return
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]),
                          usage_metadata=types.GenerateContentResponseUsageMetadata(
                              prompt_token_count=7, candidates_token_count=3, total_token_count=10))


print("1) system prompt")
ag = build_agent(model=FakeLlm())
txt = ag.static_instruction.parts[0].text
check("ไม่มี {policy} ค้าง", "{policy}" not in txt)
check("มีกฎ answering_policy จากฐานข้อมูล", "temperature_effective" in txt and "ถามลูกค้าว่าไลน์เปียกหรือแห้ง" in txt)
check("ไม่มีวงเล็บปีกกาที่ ADK จะตีความเป็นตัวแปร (static_instruction ไม่แทนค่า แต่กันไว้)", "{" not in INSTRUCTION_TH.replace("{policy}", "") and "{" not in INSTRUCTION_TH_R2.replace("{policy}", ""))

print("2) ADK ↔ MCP ↔ ฐานข้อมูลจริง")
A.engine = A._Engine(model=FakeLlm())
h, st, refs, pids, sid, v, g = A.chat_interaction("Modutech รุ่นไหนรับแรงดึงสูงสุด", None, [], [], "", None, None)
reply = h[-1]["content"]
check("ตัวเชื่อมคืน 7 ค่า และ history 2 ข้อความ", len(h) == 2 and sid, h)
check("เรียก search_catalogue ผ่าน MCP จริง", [c["tool"] for c in refs["tool_calls"]] == ["search_catalogue"], refs)
check("ผลมาจากฐานข้อมูลจริง (HD635 C อันดับ 1)", "HD635 C" in reply, reply[:200])
u = A.engine.llm.last_usage
check("นับการเรียก LLM 2 ครั้ง (เรียกเครื่องมือ + ตอบ) และโทเคนรวม", u["llm_calls"] == 2 and u["total_token_count"] == 25, u)

print("3) session ข้ามเทิร์น")
h2, *_rest = A.chat_interaction("แล้วสีอะไรบ้าง", None, h, [], sid, None, None)
check("เทิร์นที่ 2 ใช้ session เดิม (LLM เห็นข้อความผู้ใช้ 2 เทิร์น)", "เทิร์นผู้ใช้ที่เห็น 2" in h2[-1]["content"], h2[-1])
h3, _s, _r, _p, sid3, *_x = A.chat_interaction("สวัสดี", None, [], [], sid, None, None)
check("history ว่าง = บทสนทนาใหม่ (session ใหม่)", sid3 != sid and "เทิร์นผู้ใช้ที่เห็น 1" in h3[-1]["content"], h3[-1])

print("4) รูป")
from PIL import Image                                   # noqa: E402
im = Image.new("RGB", (64, 48), (200, 30, 30))
h4, _s, refs4, *_x = A.chat_interaction("", im, [], [], "", None, None)
calls = refs4["tool_calls"]
check("ส่ง image_id ให้ LLM และ LLM เรียก match_catalogue_image ได้", calls and calls[0]["tool"] == "match_catalogue_image", calls)
iid = calls[0]["args"]["image_id"] if calls else ""
check("ไฟล์รูปถูกบันทึกให้ MCP server อ่าน", os.path.isfile(os.path.join(A.IMAGE_DIR, iid)))
req = SEEN[-2] if len(SEEN) >= 2 else None
has_blob = any(p.inline_data for c in (req.contents if req else []) for p in c.parts)
check("รูปส่งให้ LLM ดูโดยตรงด้วย (inline image)", has_blob)
check("เครื่องมือเทียบรูปตอบกลับ (ไม่มีโมเดลในเครื่องนี้ = ข้อความเหตุผล ไม่ล้ม)", "ผลจากเครื่องมือ" in h4[-1]["content"], h4[-1])

print("5) ค้นทั้งฐานตัวเดียวกับบอท (Qdrant Range Filter · 2 พ.ย.)")
from agent_baseline import tools_impl as _T   # noqa: E402
_s = _T._state()[1]
check("search_catalogue ของ agent ใช้ QdrantCatalogueSearch เหมือนบอท",
      type(_s).__name__ == "QdrantCatalogueSearch" or os.environ.get("MODUTECH_SEARCH_ENGINE") == "python", type(_s).__name__)

print("6) prompt r3 (2 พ.ย.) = r2m + แก้ 4 จุดเท่านั้น · ข้อขัดแย้งอุณหภูมิส่งเฉพาะ r3")
import difflib  # noqa: E402
from agent_baseline import agent as _AG  # noqa: E402
_r2m, _r3 = _AG.instruction_r2m(), _AG.instruction_r3()
_added = [l[1:] for l in difflib.unified_diff(_r2m.splitlines(), _r3.splitlines(), lineterm="", n=0)
          if l.startswith("+") and not l.startswith("+++")]
_removed = [l for l in difflib.unified_diff(_r2m.splitlines(), _r3.splitlines(), lineterm="", n=0)
            if l.startswith("-") and not l.startswith("---")]
check("r3 ลบจาก r2m 2 บรรทัด (สัญญาณแบรนด์ · ถามแบรนด์) ที่เหลือเหมือนเดิม", len(_removed) == 2, _removed)
check("r3 เพิ่มกฎ 'สายพาน' ไม่ใช่สัญญาณแบรนด์ · ถามก่อนเรียกเครื่องมือ · เลขลำดับ · ข้อขัดแย้งอุณหภูมิ",
      any("ไม่ใช่สัญญาณแบรนด์" in l for l in _added) and any("ก่อนเรียกเครื่องมือ" in l for l in _added)
      and any("ถามยืนยันว่าหมายถึงข้อไหน" in l for l in _added) and any("temperature_conflict" in l for l in _added))
_codes = {p["belt_code"] for p in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "modutech_v30_3.json"), encoding="utf-8"))["products"]}
check("บรรทัดที่เพิ่มใน r3 ไม่มีรหัสรุ่น Modutech", not [c for c in _codes for l in _added if c in l])
check("r3 ไม่มีวงเล็บปีกกาค้าง", "{" not in _r3.replace("{policy}", ""))
_old = os.environ.get("AGENT_PROMPT")
for _v, _want in (("r2m", False), ("r3", True)):
    os.environ["AGENT_PROMPT"] = _v
    _rows = json.loads(_T.temperature("MD254 GAP48%-EHT"))["variants"]
    check(f"AGENT_PROMPT={_v}: temperature ส่ง temperature_conflict = {_want}",
          any("temperature_conflict" in r for r in _rows) == _want
          and (not _want or "ตารางสเปกระบุสูงกว่า" in (_rows[0].get("temperature_conflict_note_th") or "")), _rows[:1])
if _old is None:
    os.environ.pop("AGENT_PROMPT", None)
else:
    os.environ["AGENT_PROMPT"] = _old

print(f"\nรวม {ok}/{ok + fail}")
os._exit(1 if fail else 0)
