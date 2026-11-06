"""
test_agent_web.py — หน้าเว็บเดิม (app.py · /api/chat) ใช้ agent เป็น backend ได้ (run_agent_app.ps1 · 6 พ.ย.)

ไม่เรียก Gemini: LLM ของ agent เป็นของปลอม (เห็นรูป → เรียก belts_by_surface · ไม่มีรูป → ทักทาย)
ADK · MCP server · ฐานข้อมูล · FastAPI = ของจริง

    .\\.venv-agent\\Scripts\\python.exe test_agent_web.py
    (venv ของ agent ต้องมี fastapi · uvicorn · python-multipart · httpx เพิ่มจาก requirements_agent.txt)
"""
from __future__ import annotations

import io
import json
import os
import sys
from typing import AsyncGenerator

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.update(BOT_MODULE="agent_assistant", AGENT_LAZY="1", AGENT_PROMPT="r3", AGENT_IMAGE_SURFACE="1",
                  AGENT_BRANDS="modutech", PROXY_SECRET="")
os.environ.setdefault("GEMINI_API_KEY", "offline-test")

from fastapi.testclient import TestClient                      # noqa: E402
from google.adk.models import BaseLlm, LlmResponse             # noqa: E402
from google.genai import types                                 # noqa: E402
from PIL import Image                                          # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


TOOL_RESULTS: list = []


class FakeLlm(BaseLlm):
    model: str = "fake"

    async def generate_content_async(self, req, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        u = types.GenerateContentResponseUsageMetadata(prompt_token_count=5, candidates_token_count=2, total_token_count=7)
        last = req.contents[-1]
        fr = [p.function_response for p in last.parts if p.function_response]
        if fr:
            TOOL_RESULTS.append(fr[0].response)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="จากรูปผิวน่าจะเป็นตะแกรงเปิด")]),
                              usage_metadata=u)
            return
        if any(p.inline_data for p in last.parts):
            call = types.FunctionCall(name="belts_by_surface", args={"surface": "Flush Grid", "confidence": "high"})
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]), usage_metadata=u)
            return
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="สวัสดีครับ")]), usage_metadata=u)


import agent_assistant as A                                    # noqa: E402

A.engine = A._Engine(model=FakeLlm())
import app as W                                                # noqa: E402
from webapi.settings import Settings                           # noqa: E402

with TestClient(W.create_app(Settings())) as c:
    h = c.get("/health").json()
    ok("/health: agent โหลดแล้ว", h.get("bot_ready") is True, h)
    r = c.post("/api/chat", data={"text": "สวัสดีครับ"})
    j = r.json()
    ok("ข้อความ → 200 + คำตอบของ agent", r.status_code == 200 and j["messages"][-1].get("text") == "สวัสดีครับ", j)
    sid = j.get("session_id", "")
    b = io.BytesIO()
    Image.new("RGB", (640, 480), (100, 100, 100)).save(b, "JPEG")
    r = c.post("/api/chat", data={"text": "", "session_id": sid},
               files={"image": ("belt.jpg", b.getvalue(), "image/jpeg")})
    j = r.json()
    ok("รูปเปล่า → 200 + คำตอบ", r.status_code == 200 and "ตะแกรง" in (j["messages"][-1].get("text") or ""), j)
    ok("session เดิมต่อได้", j.get("session_id") == sid)

body = TOOL_RESULTS[0] if TOOL_RESULTS else {}
raw = (body.get("content") or [{}])[0].get("text") if isinstance(body.get("content"), list) else body.get("result")
res = json.loads(raw) if isinstance(raw, str) else {}
ok("agent เรียก belts_by_surface ผ่านหน้าเว็บ", bool(TOOL_RESULTS), TOOL_RESULTS)
ok("ผลเครื่องมือ = รายชื่อที่โค้ดคัด", res.get("matched") is True and res.get("count", 0) > 0, res)
print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
