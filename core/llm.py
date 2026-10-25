"""
core/llm.py — แกนกลางเป็นคนเดียวที่คุยกับ LLM
ย้ายมาจาก chatbot_v5.py (ชั้น 5): สร้าง history · เปิด chat · ส่งข้อความ · ดึงข้อความตอบ

ไม่ import google.generativeai — ตัวเริ่มระบบส่งโมดูลเข้ามา (เทสต์ส่งของปลอมได้)

จำกัด thinking (13 ต.ค. 2026)
  gemini-flash-latest ใช้ token "thinking" ที่มองไม่เห็นราว 780 ต่อคำตอบ (≈3.7 เท่าของคำตอบ) — เป็นเวลาส่วนใหญ่
  แพ็กเกจเดิม google-generativeai (เลิกพัฒนาแล้ว) ส่งค่าคุม thinking ไม่ได้ จึงมี GenAIClient ที่ใช้แพ็กเกจใหม่ google-genai
  เปิดด้วย .env  GEMINI_THINKING=minimal | low | medium | high   (thinking_level — โมเดลรุ่น 3)
                 GEMINI_THINKING=0 | 512 | …                     (thinking_budget — โมเดลรุ่น 2.5)
  ไม่ตั้ง = GeminiClient เดิมทุกอย่าง (prompt snapshot ไม่เปลี่ยน)
  ⚠ venv ที่รันบอตเป็น Python 3.10.0 + gradio ที่ต้องการ pydantic < 2.12 → ติดตั้งได้แค่
      pip install "google-genai==2.8.0" "pydantic==2.11.10" "pydantic-core==2.33.2"
    google-genai ≥ 2.9 บังคับ pydantic ≥ 2.12.5 ซึ่งพังบน 3.10.0 (เจอจริง 11 ต.ค.)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from core.protocol import LLMTurn


def history_for_llm(chat_history: list) -> list:
    """ลบ HTML ทั้งหมด (รูป base64 สไตล์) · ข้ามข้อความที่เหลือว่าง (รูปล้วน)"""
    out = []
    for msg in chat_history:
        clean = re.sub(r'<[^>]+>', '', msg.get("content", "")).strip()
        if clean:
            out.append({"role": "model" if msg["role"] == "assistant" else "user", "parts": [clean]})
    return out


def extract_text(resp) -> str:
    """response.text พังด้วย ValueError เมื่อ Gemini ส่งแค่ tool call ไม่มี text part"""
    try:
        text = resp.text
        if text:
            return text
    except ValueError:
        pass
    try:
        for part in resp.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                return part.text
    except Exception:
        pass
    return ""


def usage_of(resp) -> dict | None:
    """token ที่ API รายงาน (รวม thinking) — ใช้ยืนยันว่าตั้ง GEMINI_THINKING แล้วได้ผลจริง (13 ต.ค.)"""
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return None
    out = {k: getattr(u, k, None) for k in ("prompt_token_count", "candidates_token_count",
                                            "thoughts_token_count", "total_token_count")}
    return {k: v for k, v in out.items() if isinstance(v, int)} or None


def model_version_of(resp) -> str | None:
    """ชื่อโมเดลจริงที่ Google ใช้ตอบ (เช่น gemini-3.6-flash) — ชื่อ alias อย่าง gemini-flash-latest
    ชี้ไปโมเดลใหม่ได้โดยไม่บอก จึงต้องบันทึกค่านี้ทุกเทิร์นเพื่อให้ผลทดสอบเทียบกันได้ (22 ต.ค.)"""
    v = getattr(resp, "model_version", None)
    return v if isinstance(v, str) and v else None


class _RetrySession:
    """session ของ SDK เดิม — send_message ต่อ (ขอให้ตอบซ้ำเมื่อคำตอบว่าง) ลองใหม่เมื่อ Google ไม่ว่างเหมือนกัน"""
    def __init__(self, session):
        self._s = session

    def send_message(self, message):
        return with_retry(lambda: self._s.send_message(message))

    def __getattr__(self, name):
        return getattr(self._s, name)


@dataclass
class LLMResult:
    response: Any
    session: Any                  # ส่งข้อความต่อได้ (เช่น ขอสรุปซ้ำเมื่อคำตอบว่าง)
    tool_calls: list


# ── ลองใหม่เมื่อ Google ไม่ว่าง (13 ต.ค.) ─────────────────────────────
# eval เจอ 429 (11 ต.ค.) และ 503 UNAVAILABLE (13 ต.ค.) — ลูกค้าเห็นข้อความ error ดิบทั้งที่ถามซ้ำก็ผ่าน
# ลองใหม่ 2 ครั้ง (รอ 2 และ 5 วินาที) เฉพาะ error ชั่วคราว · error อื่น (คีย์ผิด · prompt ผิด) ส่งต่อทันที
TRANSIENT_CODES = (429, 500, 502, 503, 504)
TRANSIENT_WORDS = ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded", "Deadline Exceeded", "DEADLINE_EXCEEDED")
RETRY_DELAYS = (2.0, 5.0)


def is_transient(e: BaseException) -> bool:
    """429/5xx ของทั้ง SDK เดิม (google.api_core.exceptions) และ google-genai (errors.APIError)"""
    for attr in ("code", "status_code"):
        c = getattr(e, attr, None)
        try:
            if c is not None and int(c) in TRANSIENT_CODES:
                return True
        except (TypeError, ValueError):
            pass
    s = str(e)
    return any(w in s for w in TRANSIENT_WORDS) or bool(re.match(r"^\s*(429|50[0234])\b", s))


def with_retry(fn, tool_calls: list | None = None, delays=None, sleep=time.sleep):
    """เรียก fn() ซ้ำเมื่อเจอ error ชั่วคราว · ลบบันทึก tool ของรอบที่ล้มเพื่อไม่ให้นับซ้ำ"""
    delays = RETRY_DELAYS if delays is None else delays
    start = len(tool_calls) if tool_calls is not None else 0
    for i in range(len(delays) + 1):
        try:
            return fn()
        except Exception as e:                       # noqa: BLE001
            if i == len(delays) or not is_transient(e):
                raise
            if tool_calls is not None:
                del tool_calls[start:]
            print(f"[WARN] Gemini ไม่ว่างชั่วคราว ({type(e).__name__}) — ลองใหม่ใน {delays[i]:g} วินาที")
            sleep(delays[i])


THINKING_LEVELS = ("minimal", "low", "medium", "high")


def parse_thinking(raw) -> dict | None:
    """ค่า GEMINI_THINKING → {"level": "low"} | {"budget": 0} | None (ไม่ตั้ง = ไม่แตะ)"""
    v = str(raw or "").strip().lower()
    if not v:
        return None
    if v.lstrip("-").isdigit():
        return {"budget": int(v)}
    if v in THINKING_LEVELS:
        return {"level": v}
    raise ValueError(f"GEMINI_THINKING={raw!r} ต้องเป็นตัวเลข (thinking budget) หรือหนึ่งใน {THINKING_LEVELS}")


class GeminiClient:
    def __init__(self, genai_module, model_name: str):
        self.genai = genai_module
        self.model_name = model_name
        self.last_usage = None
        self.last_model_version = None

    def describe(self) -> str:
        return f"google-generativeai · {self.model_name} · thinking ไม่จำกัด"

    def complete(self, system: str, user: str, json_mode: bool = False, temperature: float | None = None) -> str:
        """เรียกครั้งเดียว ไม่มี tool ไม่มีประวัติ — ใช้กับตัวตีความคำตอบ (core/answer_interpreter) และลูกค้าจำลอง"""
        cfg = {}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        if temperature is not None:
            cfg["temperature"] = temperature
        model = self.genai.GenerativeModel(model_name=self.model_name, system_instruction=system)
        resp = with_retry(lambda: model.generate_content(user, generation_config=cfg or None))
        return extract_text(resp)

    def run(self, turn: LLMTurn, chat_history: list, tool_calls: list) -> LLMResult:
        def attempt():
            model = self.genai.GenerativeModel(model_name=self.model_name,
                                               system_instruction=turn.system_prompt,
                                               tools=list(turn.tools))
            session = model.start_chat(history=history_for_llm(chat_history),
                                       enable_automatic_function_calling=True)
            return session, session.send_message(list(turn.user_parts))
        session, response = with_retry(attempt, tool_calls)
        self.last_usage = usage_of(response)
        self.last_model_version = model_version_of(response)
        return LLMResult(response, _RetrySession(session), tool_calls)


# ═══════════════════════════════════════════════════════════════
# google-genai (แพ็กเกจใหม่) — ใช้เมื่อตั้ง GEMINI_THINKING เท่านั้น
# หน้าตาที่ปลั๊กอินเห็นเหมือน GeminiClient: result.response (.text · .candidates) · result.session.send_message()
# ═══════════════════════════════════════════════════════════════

def _no_arg_tool(fn):
    """tool ที่ ToolLog.track ห่อไว้มีลายเซ็น (*args, **kwargs) — SDK เดิมจึงประกาศเป็นฟังก์ชันไม่มีพารามิเตอร์
    (ตรวจ 13 ต.ค.: function_declarations มีแค่ name + description) ห่ออีกชั้นให้ google-genai ประกาศแบบเดียวกัน
    พฤติกรรมเท่าเดิมทุกอย่าง — ถ้าจะให้ LLM ส่งพารามิเตอร์ได้ ต้องแก้ ToolLog.track ทั้งสองทาง (เรื่องแยก)"""
    def proxy() -> dict:
        return fn()
    proxy.__name__ = fn.__name__
    proxy.__doc__ = fn.__doc__
    return proxy


class _GenAISession:
    def __init__(self, chat, to_parts):
        self._chat, self._to_parts = chat, to_parts

    def send_message(self, message):
        return with_retry(lambda: self._chat.send_message(self._to_parts(message)))


class GenAIClient:
    def __init__(self, genai_new, model_name: str, api_key: str, thinking: dict):
        from google.genai import types           # มาพร้อม genai_new — import ที่นี่ให้เทสต์ส่งของปลอมได้
        self.types = types
        self.client = genai_new.Client(api_key=api_key)
        self.model_name = model_name
        self.thinking = dict(thinking or {})
        if "level" in self.thinking:
            self.thinking_config = types.ThinkingConfig(thinking_level=self.thinking["level"])
        elif "budget" in self.thinking:
            self.thinking_config = types.ThinkingConfig(thinking_budget=self.thinking["budget"])
        else:
            self.thinking_config = None
        self.last_usage = None
        self.last_model_version = None

    def describe(self) -> str:
        return f"google-genai · {self.model_name} · thinking {self.thinking or 'ไม่จำกัด'}"

    def _part(self, p):
        t = self.types
        if isinstance(p, str):
            return t.Part(text=p)
        if isinstance(p, dict) and "data" in p:          # รูปที่ปลั๊กอินแนบ: {"mime_type", "data"}
            return t.Part.from_bytes(data=p["data"], mime_type=p.get("mime_type") or "image/jpeg")
        return p

    def _parts(self, message):
        items = message if isinstance(message, (list, tuple)) else [message]
        return [self._part(p) for p in items]

    def complete(self, system: str, user: str, json_mode: bool = False, temperature: float | None = None) -> str:
        """เรียกครั้งเดียว ไม่มี tool ไม่มีประวัติ — ใช้กับตัวตีความคำตอบ (core/answer_interpreter) และลูกค้าจำลอง"""
        t = self.types
        cfg = t.GenerateContentConfig(system_instruction=system, thinking_config=self.thinking_config,
                                      **({"response_mime_type": "application/json"} if json_mode else {}),
                                      **({"temperature": temperature} if temperature is not None else {}))
        resp = with_retry(lambda: self.client.models.generate_content(model=self.model_name, contents=user,
                                                                      config=cfg))
        return extract_text(resp)

    def run(self, turn: LLMTurn, chat_history: list, tool_calls: list) -> LLMResult:
        t = self.types
        history = [t.Content(role=h["role"], parts=[t.Part(text=x) for x in h["parts"]])
                   for h in history_for_llm(chat_history)]
        cfg = t.GenerateContentConfig(system_instruction=turn.system_prompt,
                                      tools=[_no_arg_tool(f) for f in turn.tools] or None,
                                      thinking_config=self.thinking_config)
        def attempt():
            chat = self.client.chats.create(model=self.model_name, config=cfg, history=history)
            return chat, chat.send_message(self._parts(list(turn.user_parts)))
        chat, response = with_retry(attempt, tool_calls)
        self.last_usage = usage_of(response)
        self.last_model_version = model_version_of(response)
        return LLMResult(response, _GenAISession(chat, self._parts), tool_calls)
