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
import json
import os
import threading
import time
import traceback
from io import BytesIO
from typing import Any, Optional

from core.decide import Dialogue
from core.image_policy import ImageCarry, resolve as resolve_image_policy
from core.image_router import route_image
from core.llm import GeminiClient, LLMTimeout, extract_text, is_transient
from core import reply_guard as RG
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


# ข้อความเมื่อตอบไม่สำเร็จ — ใช้ถ้อยคำทางการ ไม่มีรายละเอียดทางเทคนิค (ผู้ใช้เลือก 27 ต.ค.)
# คำว่า "ไม่ว่างชั่วคราว" · "ตอบช้ากว่าปกติ" · "เกิดข้อผิดพลาด" ต้องคงไว้ — leak_detectors.FALLBACK_RX ใช้นับเทิร์นที่ตอบไม่สำเร็จ
TRANSIENT_REPLY_TH = "ขออภัยครับ ขณะนี้ระบบไม่ว่างชั่วคราว กรุณาส่งคำถามเดิมอีกครั้งในอีกสักครู่ครับ"
TIMEOUT_REPLY_TH = "ขออภัยครับ ขณะนี้ระบบตอบช้ากว่าปกติ กรุณาส่งคำถามเดิมอีกครั้งครับ"
ERROR_REPLY_TH = ("ขออภัยครับ เกิดข้อผิดพลาดระหว่างประมวลผลคำถามนี้ กรุณาส่งคำถามอีกครั้ง "
                  "หากยังพบปัญหา กรุณาติดต่อฝ่ายขายโดยตรงครับ")


def error_reply_th() -> str:
    """error ที่ไม่รู้จัก — เดิมส่ง str(e) ดิบถึงลูกค้า (เช่น 400 INVALID_ARGUMENT {...}) · รายละเอียดอยู่ใน log แทน"""
    try:
        from sales_contact import sales_contact_line_th
        contact = sales_contact_line_th()
    except Exception:                                    # noqa: BLE001 — ไม่มีไฟล์ช่องทางติดต่อ = ข้อความอย่างเดียว
        contact = ""
    return f"{ERROR_REPLY_TH}\n{contact}" if contact else ERROR_REPLY_TH


# ── log ทดสอบรูป (27 ต.ค.) ──
# IMAGE_TEST_LOG=1 → หนึ่งบรรทัดต่อเทิร์นที่มีรูป "IMGLOG {json}" (คะแนนทุกตัวให้คะแนน · ประตู · policy · การตัดสิน)
#   เขียนต่อท้ายไฟล์ image_test.log (UTF-8) ในโฟลเดอร์ที่รัน + พิมพ์ลงหน้าต่างด้วย · ตั้งเป็น path แทน 1 ได้
#   เขียนไฟล์เอง ไม่พึ่ง Tee-Object ของ PowerShell ซึ่งทำภาษาไทยเพี้ยนได้
# อ่านด้วย image_test_log.py → CSV · ปิดไว้เป็นค่าเริ่มต้น เพราะมีข้อความลูกค้าและคำตอบบางส่วน (Space จริงไม่ต้องเก็บ)
_IMG_LOG_ENV = os.environ.get("IMAGE_TEST_LOG", "").strip()
IMAGE_TEST_LOG = bool(_IMG_LOG_ENV) and _IMG_LOG_ENV != "0"
IMAGE_TEST_LOG_FILE = "image_test.log" if _IMG_LOG_ENV == "1" else _IMG_LOG_ENV
_img_log_lock = threading.Lock()


def _round(v):
    return round(v, 4) if isinstance(v, float) else v


def _score_log(sc) -> dict:
    return {"conf": _round(getattr(sc, "confidence", None)), "accepted": bool(getattr(sc, "accepted", False)),
            "dominant": bool(getattr(sc, "dominant", False)), "group": getattr(sc, "group", None) or ""}


def _emit_image_log(img: Optional[dict], ai_reply: str) -> None:
    if not (IMAGE_TEST_LOG and img):
        return
    img["reply_head"] = re.sub(r"\s+", " ", ai_reply or "")[:120]
    img["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    line = "IMGLOG " + json.dumps(img, ensure_ascii=False)
    print(line, flush=True)
    try:
        with _img_log_lock, open(IMAGE_TEST_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:                                  # เขียนไม่ได้ = ไม่ล้มเทิร์น แค่เตือน
        print(f"⚠️ เขียน {IMAGE_TEST_LOG_FILE} ไม่ได้: {e}")


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

    def _log_finish(self, turn_log, ai_reply: str, tool_calls: list, t_start: float, error=None, img=None):
        _emit_image_log(img, ai_reply)
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
        img_log = None                                   # IMGLOG (ถ้าเปิด) — เติมหลังตัดสิน
        img_size = list(img_input.size) if img_input is not None else None

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
                policy = self._image_policy(img_route, gate_src, user_text, session_id)
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
                image_carry=carry, image_confirm=policy.confirm if policy is not None else None)
            self.dialog_states[session_id] = decision.state.to_dict()
            if img_input is not None and IMAGE_TEST_LOG:
                raw = policy.original if (policy is not None and policy.original is not None) else img_route
                img_log = {
                    "turn": turn_log.turn_id, "session": session_id, "size": img_size,
                    "text": (user_text or "")[:60],
                    "scores": {b: _score_log(sc) for b, sc in ((raw.scores if raw else {}) or {}).items()},
                    "gates": {b: {"product_like": r.product_like, "direct": r.direct,
                                  **{k: _round(v) for k, v in (r.detail or {}).items()}}
                              for b, r in ((policy.readings if policy is not None else {}) or {}).items()},
                    "policy": policy.kind if policy is not None else "off",
                    "policy_reason": policy.reason if policy is not None else "",
                    "action": decision.action, "brand": decision.brand, "reason": decision.reason,
                }
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
                self._log_finish(turn_log, ai_reply, [], t_start, error=None, img=img_log)
                chat_history += [{"role": "user", "content": display_content},
                                 {"role": "assistant", "content": ai_reply}]
                return (chat_history, chat_history, raw_refs_html,
                        last_pids, session_id, last_vit_signal, last_graph_result)

            # ── รูปเปล่าไปแบรนด์ที่อ่านรูปไม่ได้ (27 ต.ค.) ──
            # ส่งรูปโดยไม่พิมพ์ (แชตใหม่หรือกลางแชต) + ประตูรูปมั่นใจว่าเป็นแบรนด์ที่อ่านรุ่นจากรูปไม่ได้ → ปลั๊กอินตัดสินว่า "ตอบ" ด้วยข้อความว่าง
            # แบรนด์ที่ไม่มีตัวให้คะแนนรูปไม่ส่งรูปให้ LLM (ปลั๊กอินแบบนี้ส่ง user_parts = [effective_text] ล้วน)
            # ผลเดิม: Gemini ได้ประวัติที่จบด้วยคำตอบบอท → 400 "Requests ending with a model turn"
            # และต่อให้ไม่ error ก็จะตอบเรื่องรุ่นเดิมโดยไม่ได้ดูรูป (เดาแทนลูกค้า) → ขอคำถามแทน
            if turn_image is not None and not (user_text or "").strip() \
                    and decision.brand not in self.image_scorers:
                ai_reply = _prefix(image_note, T.image_need_question(self.plugins[decision.brand].info))
                raw_refs_html += (f"**Image-only:** {decision.brand} อ่านรูปไม่ได้ + ไม่มีข้อความ "
                                  f"→ ขอคำถาม (เดิม {decision.action} · {decision.reason})\n")
                if img_log is not None:
                    img_log["guard"] = "รูปเปล่า → ขอคำถาม (ไม่เรียก LLM)"
                self._log_finish(turn_log, ai_reply, [], t_start, error=None, img=img_log)
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

            # กันชั้นสุดท้าย: ห้ามส่งเทิร์นผู้ใช้ที่ว่างให้ LLM (ทางไหนก็ตามที่ยังไม่รู้) — ขอคำถามแทน error ดิบ
            if llm_turn.direct_reply is None and not _has_content(llm_turn.user_parts):
                llm_turn.direct_reply = T.image_need_question(plugin.info) if turn_image is not None \
                    else EMPTY_INPUT_TH
                raw_refs_html += "**Empty turn:** user_parts ว่าง → ไม่เรียก LLM\n"
                if img_log is not None:
                    img_log["guard"] = "เทิร์นว่าง → ไม่เรียก LLM"

            if llm_turn.direct_reply is not None:
                ai_reply = _prefix(image_note, llm_turn.direct_reply)
                self._log_finish(turn_log, ai_reply, [], t_start, error=None, img=img_log)
                chat_history += [{"role": "user", "content": display_content},
                                 {"role": "assistant", "content": ai_reply}]
                return (chat_history, chat_history, raw_refs_html,
                        last_pids, session_id, last_vit_signal, last_graph_result)

            result = self.llm.run(llm_turn, chat_history, self.tool_log.calls)
            out = plugin.finish_turn(decision, turn, llm_turn, result)
            guarded, notes = guard_reply(out.reply, result, decision)
            raw_refs_html += "".join(notes)
            ai_reply = _prefix(image_note, guarded)
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
            # 26 ต.ค.: เกินเวลา (core/llm.py run_with_deadline) → บอกให้ส่งใหม่ แทนที่ลูกค้ารอเป็นสิบนาที
            ai_reply = (TIMEOUT_REPLY_TH if isinstance(e, LLMTimeout) else
                        TRANSIENT_REPLY_TH if is_transient(e) else error_reply_th())
            error_msg = str(e)
            extra_messages = []
            print(f"[ERROR] {e}")
            traceback.print_exc()

        if decision is not None and decision.sales_handoff_th and not error_msg \
                and not _already_has_contact(ai_reply, decision.sales_handoff_th):
            ai_reply = f"{ai_reply}\n\n{decision.sales_handoff_th}"   # คำถามผสม: ส่วนฝ่ายขายมาจากโค้ด

        self._log_finish(turn_log, ai_reply, self.tool_log.calls, t_start, error=error_msg, img=img_log)

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
        if policy is not None and policy.kind == "context":
            return T.image_from_context(self.plugins[b].info)
        if policy is not None and policy.kind in ("direct", "text_brand", "ask", "confirm"):
            return T.image_no_model(self.plugins[b].info, from_image=policy.kind == "direct")
        if policy is None and carry is not None:
            return T.image_no_model(self.plugins[b].info, from_image=False)
        return ""

    def _image_policy(self, route, image, user_text: str, session_id: str = ""):
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
        context = (self.dialog_states.get(session_id) or {}).get("brand")   # แบรนด์ที่แชตคุยอยู่ก่อนเทิร์นนี้
        pol = resolve_image_policy(route, brands, list(self.image_scorers), readings, strong, context)
        pol.readings = readings
        return pol


def _has_content(parts) -> bool:
    """มีอะไรให้ LLM อ่านไหม — ข้อความที่ไม่ว่าง หรือส่วนที่ไม่ใช่ข้อความ (รูป)"""
    return any((p.strip() if isinstance(p, str) else p is not None) for p in (parts or []))


_CONTACT_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\d[\d-]{6,}\d")


def guard_reply(reply: str, result, decision) -> tuple[str, list]:
    """ตรวจคำตอบด้วยโค้ดก่อนถึงลูกค้า (core/reply_guard.py · sim4_llm 26 ต.ค.)
    1) เหตุผลภายใน/ชื่อฟิลด์หลุด → ขอให้ LLM เขียนใหม่หนึ่งครั้ง · ยังหลุด → ข้อความขอให้ถามใหม่
    2) เบอร์ · อีเมล · LINE ที่ไม่ใช่ช่องทางจริง → ลบบรรทัดนั้น แล้วแนบช่องทางจริงแทน (ถ้าไม่มีข้อความส่งต่ออยู่แล้ว)"""
    notes = []
    leak = RG.leaks(reply)
    if leak:
        notes.append(f"**Reply guard:** เหตุผลภายในหลุด {leak[:5]} → ขอเขียนใหม่\n")
        new = ""
        try:
            new = extract_text(result.session.send_message(RG.LEAK_RETRY_TH))
        except Exception as e:                           # noqa: BLE001 — เขียนใหม่ไม่ได้ = ใช้ข้อความสำรอง
            notes.append(f"**Reply guard:** เขียนใหม่ไม่สำเร็จ ({type(e).__name__})\n")
        if new and not RG.leaks(new):
            reply = new
        else:
            reply = RG.LEAK_FALLBACK_TH
            notes.append("**Reply guard:** ยังหลุด → ข้อความสำรอง\n")
    reply, fake = RG.scrub_contacts(reply)
    if fake:
        notes.append(f"**Reply guard:** ลบช่องทางติดต่อที่ไม่ใช่ของจริง {fake[:5]}\n")
        if not getattr(decision, "sales_handoff_th", ""):
            from sales_contact import sales_contact_line_th
            line = sales_contact_line_th()
            if line and line not in reply:
                reply = f"{reply}\n\n{line}".strip()
    return reply, notes


def _already_has_contact(reply: str, handoff: str) -> bool:
    """LLM ใส่ช่องทางติดต่อฝ่ายขายครบแล้ว → ไม่ต่อข้อความซ้ำ (ES-007 · ES-017 บอกให้ติดต่อสองรอบ · 10 ต.ค.)

    ตัดสินจากเบอร์/อีเมลในข้อความส่งต่อเท่านั้น ถ้าข้อความส่งต่อไม่มีช่องทางติดต่อ ถือว่ายังไม่มี
    """
    tokens = _CONTACT_RX.findall(handoff or "")
    return bool(tokens) and all(t in (reply or "") for t in tokens)


def _prefix(note: str, reply: str) -> str:
    return f"{note}\n\n{reply}" if note and reply else (reply if reply is not None else reply)
