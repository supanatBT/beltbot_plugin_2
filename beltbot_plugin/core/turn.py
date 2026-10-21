"""
core/turn.py
============
หนึ่งเทิร์นของแชต — ย้ายมาจาก chat_interaction ใน chatbot_v5.py (ชั้น 5)
แกนกลางไม่รู้จักแบรนด์: ตัดสินด้วย core/decide · ค้นและประกอบ prompt ด้วยปลั๊กอิน · คุยกับ LLM ที่นี่ที่เดียว

สัญญาเดิมของ chat_interaction คงไว้ทุกตำแหน่ง (webapi/bot.py · run_answer_eval.py · Gradio ใช้อยู่)
    รับ  (user_text, img_input, chat_history, last_pids, session_id, last_vit_signal, last_graph_result)
    คืน  (chat_history, chat_state_out, refs, last_pids, session_id, last_vit_signal, last_graph_result)
สามช่องท้ายตอนนี้คือ "ของฝากข้ามเทิร์น" ที่ปลั๊กอินเป็นเจ้าของ (focus · image · context) แกนกลางแค่ส่งต่อ
"""
from __future__ import annotations

import base64
import time
import traceback
from io import BytesIO
from typing import Any, Optional

from core.decide import Dialogue
from core.image_router import route_image
from core.llm import GeminiClient
from core.protocol import TurnInput
from core.tools import ToolLog

# ขอแบบ/รูปของรุ่นที่อยู่ในโฟกัส → เติมรหัสรุ่นนั้นหน้าคำถาม (กฎเดิม)
ARTIFACT_WORDS = ["ขอรูป", "ขอดู", "drawing", "datasheet"]
EMPTY_INPUT_TH = "⚠️ กรุณาพิมพ์ข้อความหรืออัปโหลดรูปภาพ"
DEFAULT_IMAGE_TEXT = "ลูกค้าส่งรูปภาพมา"


def image_to_base64_html(pil_image) -> str:
    if pil_image is None:
        return ""
    buf = BytesIO()
    pil_image.thumbnail((400, 400))
    pil_image.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f'<img src="data:image/jpeg;base64,{b64}" style="max-width:250px;border-radius:10px;margin-bottom:10px;" />'


class TurnEngine:
    def __init__(self, dialogue: Dialogue, llm: GeminiClient, logger, tool_log: ToolLog,
                 image_scorers: Optional[dict] = None):
        self.dialogue = dialogue
        self.plugins = dialogue.plugins
        self.llm = llm
        self.logger = logger
        self.tool_log = tool_log
        self.image_scorers = dict(image_scorers or {})
        self.dialog_states: dict[str, dict] = {}         # session_id → DialogState.to_dict()

    def _log_finish(self, turn_log, ai_reply: str, tool_calls: list, t_start: float, error=None):
        latency_ms = (time.perf_counter() - t_start) * 1000
        self.logger.log_llm(turn_log, ai_reply=ai_reply, tool_calls=tool_calls, latency_ms=latency_ms)
        self.logger.finish_turn(turn_log, error=error)
        print(f"📋 Logged {turn_log.turn_id}  latency={latency_ms:.0f}ms  "
              f"top1={turn_log.summary_top1_pid}  tools={turn_log.summary_tool_calls}")

    def chat(self, user_text: str, img_input, chat_history: list, last_pids: list = None,
             session_id: str = "", last_vit_signal=None, last_graph_result=None):
        if last_pids is None:
            last_pids = []
        if not user_text.strip() and img_input is None:
            return (chat_history, chat_history, EMPTY_INPUT_TH,
                    last_pids, session_id, last_vit_signal, last_graph_result)
        if not session_id:
            session_id = self.logger.new_session()

        self.tool_log.reset()
        t_start = time.perf_counter()

        display_content = ""
        if img_input:
            display_content += image_to_base64_html(img_input) + "<br>"
        if user_text:
            display_content += user_text
        if not display_content:
            display_content = "[แนบรูปภาพ]"

        raw_refs_html = "### 🔍 ข้อมูลอ้างอิง (Debug v4)\n\n"
        ai_reply = ""
        error_msg = None
        extra_messages: list = []
        new_carry = None

        # follow-up = ไม่มีรูปใหม่ + พิมพ์สั้น + มีของฝากจากเทิร์นก่อน (นิพจน์เดิม — ค่าอาจเป็น "")
        is_followup = (
            img_input is None and
            user_text.strip() and
            len(user_text.split()) <= 6 and
            bool(last_pids or last_vit_signal or last_graph_result)
        )
        effective_text = user_text or DEFAULT_IMAGE_TEXT
        if is_followup and last_pids and any(w in user_text for w in ARTIFACT_WORDS):
            effective_text = f"{' '.join(last_pids[:1])} {user_text}"
        query_type = "image" if img_input is not None else "general"
        raw_refs_html += f"**follow-up:** {is_followup} | **last_pids:** {last_pids}\n"

        turn_log = self.logger.start_turn(
            session_id=session_id, user_text=user_text, has_image=img_input is not None,
            last_pid=" ".join(last_pids) if last_pids else "",
            effective_query=effective_text, query_type=query_type)
        raw_refs_html += f"**Turn:** `{turn_log.turn_id}`\n"
        raw_refs_html += f"**Effective query:** {effective_text}\n\n"

        decision = None
        try:
            # ── รูป: ถามทุกแบรนด์ที่รับรูปก่อนตัดสิน ──
            img_route = None
            if img_input is not None:
                img_route = route_image(self.image_scorers, img_input, effective_text)
                self.dialogue.image_brands = tuple(img_route.image_brands)
            dstate = self.dialogue.state_cls.from_dict(self.dialog_states.get(session_id))
            decision = self.dialogue.decide(
                user_text, has_image=img_input is not None,
                image=img_route.best if img_route else None,
                image_rejected=bool(img_route and img_route.rejected), state=dstate)
            self.dialog_states[session_id] = decision.state.to_dict()
            raw_refs_html += (f"**Decision:** {decision.action} · brand={decision.brand} · "
                              f"{decision.reason}\n\n")

            if not decision.needs_llm:
                ai_reply = decision.reply_th
                self._log_finish(turn_log, ai_reply, [], t_start, error=None)
                chat_history += [{"role": "user", "content": display_content},
                                 {"role": "assistant", "content": ai_reply}]
                return (chat_history, chat_history, raw_refs_html,
                        last_pids, session_id, last_vit_signal, last_graph_result)

            plugin = self.plugins[decision.brand]
            turn = TurnInput(user_text=user_text, image=img_input, history=chat_history,
                             session_id=session_id, effective_text=effective_text, followup=is_followup,
                             last_focus=last_pids, last_image=last_vit_signal,
                             last_context=last_graph_result,
                             image_score=img_route.best if img_route else None, log=turn_log)
            llm_turn = plugin.build_turn(decision, turn)
            raw_refs_html += "".join(llm_turn.debug)

            if llm_turn.direct_reply is not None:
                ai_reply = llm_turn.direct_reply
                self._log_finish(turn_log, ai_reply, [], t_start, error=None)
                chat_history += [{"role": "user", "content": display_content},
                                 {"role": "assistant", "content": ai_reply}]
                return (chat_history, chat_history, raw_refs_html,
                        last_pids, session_id, last_vit_signal, last_graph_result)

            result = self.llm.run(llm_turn, chat_history, self.tool_log.calls)
            out = plugin.finish_turn(decision, turn, llm_turn, result)
            ai_reply = out.reply
            extra_messages = list(out.extra_messages)
            raw_refs_html += "".join(out.debug)
            new_carry = out.carry_fn
        except Exception as e:
            ai_reply = f"❌ เกิดข้อผิดพลาด: {str(e)}"
            error_msg = str(e)
            extra_messages = []
            print(f"[ERROR] {e}")
            traceback.print_exc()

        if decision is not None and decision.sales_handoff_th and not error_msg:
            ai_reply = f"{ai_reply}\n\n{decision.sales_handoff_th}"   # คำถามผสม: ส่วนฝ่ายขายมาจากโค้ด

        self._log_finish(turn_log, ai_reply, self.tool_log.calls, t_start, error=error_msg)

        chat_history += [{"role": "user", "content": display_content},
                         {"role": "assistant", "content": ai_reply}]
        chat_history += extra_messages

        carry = new_carry(ai_reply) if new_carry else None
        if carry is None:
            carry = (last_pids, last_vit_signal, last_graph_result)
        new_last_pids, new_vit, new_graph = carry

        # ข้อความรูปที่โค้ดแนบ (datasheet) ไม่ส่งกลับเป็น state ให้ LLM เห็นซ้ำ
        chat_state_out = [m for m in chat_history
                          if not (m["role"] == "assistant" and m.get("content", "").startswith('<img'))]
        return (chat_history, chat_state_out, raw_refs_html,
                new_last_pids, session_id, new_vit, new_graph)
