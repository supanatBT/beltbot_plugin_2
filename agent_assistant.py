"""
agent_assistant.py — ตัวเชื่อม agent เทียบเข้ากับ run_answer_eval.py (สัญญาเดียวกับ assistant.py)

    python run_answer_eval.py --module agent_assistant --testcases testcases_modutech_136.csv -o agent_136_r1.json

รันด้วย venv ของ agent (requirements_agent.txt) ไม่ใช่ venv ของบอทหลัก — ADK ต้องใช้ google-genai คนละรุ่น
history == [] = บทสนทนาใหม่ → เปิด session ใหม่ของ ADK (สถานะข้ามเทิร์นอยู่ใน session ของ agent เอง)
llm.last_usage เก็บโทเคนรวม · จำนวนครั้งที่เรียก LLM · รายชื่อเครื่องมือที่ถูกเรียก (ลงในผลของ run_answer_eval)
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import threading
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:                                            # noqa: BLE001
    pass
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from google.adk.runners import Runner                         # noqa: E402
from google.adk.sessions import InMemorySessionService        # noqa: E402
from google.genai import types                                # noqa: E402

from agent_baseline.agent import build_agent                  # noqa: E402
from agent_baseline.tools_impl import IMAGE_DIR               # noqa: E402

APP, USER = "modutech_agent_baseline", "eval"


class _LLMInfo:
    def __init__(self):
        self.last_usage = None
        self.last_model_version = None

    def describe(self) -> str:
        return (f"ADK agent · {os.environ.get('GEMINI_MODEL') or 'gemini-3.8-flash'} · "
                f"thinking {os.environ.get('GEMINI_THINKING') or 'low'} · เครื่องมือผ่าน MCP (stdio)")


class _Engine:
    def __init__(self, model=None, toolset=None):
        self.llm = _LLMInfo()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self.agent = build_agent(model=model, toolset=toolset)
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name=APP, agent=self.agent, session_service=self.sessions)

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
            timeout=float(os.environ.get("AGENT_TURN_TIMEOUT", "240")))

    async def _new_session(self) -> str:
        s = await self.sessions.create_session(app_name=APP, user_id=USER)
        return s.id

    async def _turn(self, session_id: str, message: types.Content) -> tuple[str, dict, str | None]:
        text_parts, calls = [], []
        usage = {"prompt_token_count": 0, "candidates_token_count": 0, "total_token_count": 0, "llm_calls": 0}
        model_version = None
        async for ev in self.runner.run_async(user_id=USER, session_id=session_id, new_message=message):
            um = getattr(ev, "usage_metadata", None)
            if um is not None:
                usage["llm_calls"] += 1
                for k in ("prompt_token_count", "candidates_token_count", "total_token_count"):
                    usage[k] += getattr(um, k, 0) or 0
            model_version = getattr(ev, "model_version", None) or model_version
            for fc in ev.get_function_calls() or []:
                calls.append({"tool": fc.name, "args": dict(fc.args or {})})
            if ev.is_final_response() and ev.content and ev.content.parts:
                text_parts += [p.text for p in ev.content.parts if getattr(p, "text", None) and not getattr(p, "thought", False)]
        usage["tool_calls"] = calls
        return "".join(text_parts).strip(), usage, model_version

    def chat(self, query: str, image, session_id: str) -> tuple[str, str]:
        if not session_id:
            session_id = self._call(self._new_session())
        parts = []
        if image is not None:
            os.makedirs(IMAGE_DIR, exist_ok=True)
            image_id = f"{uuid.uuid4().hex[:12]}.png"
            image.convert("RGB").save(os.path.join(IMAGE_DIR, image_id))
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="PNG")
            parts.append(types.Part(text=f"[ลูกค้าแนบรูป image_id={image_id}]"))
            parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"))
        if query:
            parts.append(types.Part(text=query))
        reply, usage, mv = self._call(self._turn(session_id, types.Content(role="user", parts=parts)))
        self.llm.last_usage, self.llm.last_model_version = usage, mv
        return reply, session_id


engine: _Engine | None = None


def _engine() -> _Engine:
    global engine
    if engine is None:
        engine = _Engine()
    return engine


def chat_interaction(user_text, image, history, last_pids, session_id, vit_signal, graph_result):
    """สัญญาเดียวกับ assistant.chat_interaction — คืน 7 ค่า"""
    eng = _engine()
    if not history:                         # บทสนทนาใหม่ (run_answer_eval รีเซ็ต history ทุกเคส)
        session_id = ""
    reply, session_id = eng.chat(user_text or "", image, session_id)
    history = list(history or []) + [{"role": "user", "content": user_text or "[รูป]"},
                                     {"role": "assistant", "content": reply}]
    refs = {"tool_calls": (eng.llm.last_usage or {}).get("tool_calls", [])}
    return history, None, refs, [], session_id, None, None


# run_answer_eval อ่าน getattr(bot, "engine").llm ก่อนเรียกเทิร์นแรก → สร้างตอน import
engine = _Engine() if os.environ.get("AGENT_LAZY") != "1" else None
