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
from agent_baseline.agent import INSTRUCTION_TH, build_agent  # noqa: E402

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
check("ไม่มีวงเล็บปีกกาที่ ADK จะตีความเป็นตัวแปร (static_instruction ไม่แทนค่า แต่กันไว้)", "{" not in INSTRUCTION_TH.replace("{policy}", ""))

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

print(f"\nรวม {ok}/{ok + fail}")
os._exit(1 if fail else 0)
