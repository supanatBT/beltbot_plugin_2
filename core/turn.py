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

import re

import base64
import time
import traceback
from io import BytesIO
from typing import Any, Optional

from core.decide import Dialogue
from core.image_policy import ImageCarry, resolve as resolve_image_policy
from core.image_router import route_image
from core.llm import GeminiClient, is_transient
from core import templates as T
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


TRANSIENT_REPLY_TH = "❌ ตอนนี้ระบบตอบคำถามไม่ว่างชั่วคราว รบกวนส่งคำถามเดิมอีกครั้งในอีกสักครู่ครับ"


class TurnEngine:
    def __init__(self, dialogue: Dialogue, llm: GeminiClient, logger, tool_log: ToolLog,
                 image_scorers: Optional[dict] = None, image_gates: Optional[dict] = None):
        self.dialogue = dialogue
        self.plugins = dialogue.plugins
        self.llm = llm
        self.logger = logger
        self.tool_log = tool_log
        self.image_scorers = dict(image_scorers or {})
        self.image_gates = dict(image_gates or {})       # แบรนด์ → ImageGate (core/image_policy)
        self.dialog_states: dict[str, dict] = {}         # session_id → DialogState.to_dict()
        self.image_carry: dict[str, ImageCarry] = {}     # session_id → รูปของเทิร์นที่ถามแบรนด์ (ใช้เทิร์นเดียว)

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

        # ประตูรูปวัดจากรูปเต็ม (ปรับเกณฑ์ด้วยรูปเต็ม) · image_to_base64_html ย่อรูปตัวจริงเหลือ 400 px
        # ตัวให้คะแนนเดิมของแต่ละแบรนด์ได้รูปที่ย่อแล้วเหมือนเดิมทุกอย่าง — ไม่เปลี่ยนพฤติกรรมเดิม
        gate_src = img_input.copy() if (img_input is not None and self.image_gates) else None

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
        # รูปของเทิร์นที่ถามแบรนด์ใช้ได้เทิร์นเดียว · รูปใหม่ = ทิ้งของเก่า
        carry = self.image_carry.pop(session_id, None)
        if img_input is not None:
            carry = None
        try:
            # ── รูป: ถามทุกแบรนด์ที่รับรูปก่อนตัดสิน ──
            img_route, policy = None, None
            if img_input is not None:
                img_route = route_image(self.image_scorers, img_input, effective_text)
                policy = self._image_policy(img_route, gate_src, user_text)
                if policy is not None:
                    img_route = policy.route
                    raw_refs_html += f"**Image policy:** {policy.kind} · {policy.reason}\n"
                    print(f"🖼️ Image policy: {policy.kind} · {policy.reason}")
                self.dialogue.image_brands = tuple(img_route.image_brands)
            dstate = self.dialogue.state_cls.from_dict(self.dialog_states.get(session_id))
            decision = self.dialogue.decide(
                user_text, has_image=img_input is not None,
                image=img_route.best if img_route else None,
                image_rejected=bool(img_route and img_route.rejected), state=dstate,
                image_carry=carry)
            self.dialog_states[session_id] = decision.state.to_dict()
            raw_refs_html += (f"**Decision:** {decision.action} · brand={decision.brand} · "
                              f"{decision.reason}\n\n")
            if policy is not None and policy.asks_brand and decision.action == "ask" \
                    and decision.topic == "brand":
                orig = policy.original
                self.image_carry[session_id] = ImageCarry(img_input, orig.best, orig.rejected)
            carried = carry is not None and bool((decision.payload or {}).get("image_carried"))
            turn_image = carry.image if carried else img_input
            turn_score = carry.best if carried else (img_route.best if img_route else None)
            image_note = self._image_note(decision, policy, carry)

            if not decision.needs_llm:
                ai_reply = _prefix(image_note, decision.reply_th)
                self._log_finish(turn_log, ai_reply, [], t_start, error=None)
                chat_history += [{"role": "user", "content": display_content},
                                 {"role": "assistant", "content": ai_reply}]
                return (chat_history, chat_history, raw_refs_html,
                        last_pids, session_id, last_vit_signal, last_graph_result)

            plugin = self.plugins[decision.brand]
            turn = TurnInput(user_text=user_text, image=turn_image, history=chat_history,
                             session_id=session_id, effective_text=effective_text, followup=is_followup,
                             last_focus=last_pids, last_image=last_vit_signal,
                             last_context=last_graph_result,
                             image_score=turn_score, log=turn_log)
            llm_turn = plugin.build_turn(decision, turn)
            raw_refs_html += "".join(llm_turn.debug)

            if llm_turn.direct_reply is not None:
                ai_reply = _prefix(image_note, llm_turn.direct_reply)
                self._log_finish(turn_log, ai_reply, [], t_start, error=None)
                chat_history += [{"role": "user", "content": display_content},
                                 {"role": "assistant", "content": ai_reply}]
                return (chat_history, chat_history, raw_refs_html,
                        last_pids, session_id, last_vit_signal, last_graph_result)

            result = self.llm.run(llm_turn, chat_history, self.tool_log.calls)
            out = plugin.finish_turn(decision, turn, llm_turn, result)
            ai_reply = _prefix(image_note, out.reply)
            extra_messages = list(out.extra_messages)
            raw_refs_html += "".join(out.debug)
            new_carry = out.carry_fn
            if out.state_patch:
                st2 = self.dialogue.state_cls.from_dict(self.dialog_states.get(session_id))
                st2.brands[decision.brand].update(out.state_patch)
                self.dialog_states[session_id] = st2.to_dict()
                raw_refs_html += f"**State patch:** {decision.brand} {out.state_patch}\n"
        except Exception as e:
            # 13 ต.ค.: Google ไม่ว่างแม้ลองใหม่แล้ว (core/llm.py with_retry) → ข้อความที่ลูกค้าเข้าใจ ไม่ใช่ JSON ดิบ
            ai_reply = (TRANSIENT_REPLY_TH if is_transient(e) else f"❌ เกิดข้อผิดพลาด: {str(e)}")
            error_msg = str(e)
            extra_messages = []
            print(f"[ERROR] {e}")
            traceback.print_exc()

        if decision is not None and decision.sales_handoff_th and not error_msg \
                and not _already_has_contact(ai_reply, decision.sales_handoff_th):
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

    def _image_note(self, decision, policy, carry) -> str:
        """มีรูป (หรือรูปที่เก็บไว้) แต่ไปแบรนด์ที่ไม่มีตัวให้คะแนนรูป → บอกว่ายังระบุรุ่นจากรูปไม่ได้"""
        b = decision.brand
        if b is None or b in self.image_scorers or b not in self.plugins:
            return ""
        if decision.action in ("reject_image", "refuse_offtopic", "smalltalk", "escalate"):
            return ""
        if decision.action == "ask" and decision.topic == "brand":
            return ""
        if policy is not None and policy.kind in ("direct", "text_brand", "ask"):
            return T.image_no_model(self.plugins[b].info, from_image=policy.kind == "direct")
        if policy is None and carry is not None:
            return T.image_no_model(self.plugins[b].info, from_image=False)
        return ""

    def _image_policy(self, route, image, user_text: str):
        """core/image_policy — คืน None เมื่อทุกแบรนด์มีตัวให้คะแนนรูป (พฤติกรรมเดิม)"""
        brands = list(self.plugins)
        if all(b in self.image_scorers for b in brands):
            return None
        readings = {}
        for b, g in (self.image_gates.items() if image is not None else ()):
            try:
                readings[b] = g.read(image)
            except Exception as e:                       # noqa: BLE001 — ประตูพัง = ไม่มีประตู ไม่ล้มทั้งเทิร์น
                print(f"⚠️ ประตูรูป {b} ผิดพลาด ({type(e).__name__}: {e}) — ข้ามประตูนี้")
        strong = [b for b, p in self.plugins.items() if p.detect(user_text or "").strength == "strong"]
        return resolve_image_policy(route, brands, list(self.image_scorers), readings, strong)


_CONTACT_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\d[\d-]{6,}\d")


def _already_has_contact(reply: str, handoff: str) -> bool:
    """LLM ใส่ช่องทางติดต่อฝ่ายขายครบแล้ว → ไม่ต่อข้อความซ้ำ (ES-007 · ES-017 บอกให้ติดต่อสองรอบ · 10 ต.ค.)

    ตัดสินจากเบอร์/อีเมลในข้อความส่งต่อเท่านั้น ถ้าข้อความส่งต่อไม่มีช่องทางติดต่อ ถือว่ายังไม่มี
    """
    tokens = _CONTACT_RX.findall(handoff or "")
    return bool(tokens) and all(t in (reply or "") for t in tokens)


def _prefix(note: str, reply: str) -> str:
    return f"{note}\n\n{reply}" if note and reply else (reply if reply is not None else reply)
