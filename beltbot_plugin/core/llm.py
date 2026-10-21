"""
core/llm.py — แกนกลางเป็นคนเดียวที่คุยกับ LLM
ย้ายมาจาก chatbot_v5.py (ชั้น 5): สร้าง history · เปิด chat · ส่งข้อความ · ดึงข้อความตอบ

ไม่ import google.generativeai — ตัวเริ่มระบบส่งโมดูลเข้ามา (เทสต์ส่งของปลอมได้)
"""
from __future__ import annotations

import re
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
        return resp.text
    except ValueError:
        pass
    try:
        for part in resp.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                return part.text
    except Exception:
        pass
    return ""


@dataclass
class LLMResult:
    response: Any
    session: Any                  # ส่งข้อความต่อได้ (เช่น ขอสรุปซ้ำเมื่อคำตอบว่าง)
    tool_calls: list


class GeminiClient:
    def __init__(self, genai_module, model_name: str):
        self.genai = genai_module
        self.model_name = model_name

    def run(self, turn: LLMTurn, chat_history: list, tool_calls: list) -> LLMResult:
        model = self.genai.GenerativeModel(model_name=self.model_name,
                                           system_instruction=turn.system_prompt,
                                           tools=list(turn.tools))
        session = model.start_chat(history=history_for_llm(chat_history),
                                   enable_automatic_function_calling=True)
        response = session.send_message(list(turn.user_parts))
        return LLMResult(response, session, tool_calls)
