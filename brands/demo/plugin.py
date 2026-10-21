"""
brands/demo/plugin.py
=====================
ปลั๊กอินแบรนด์ตัวอย่าง — เขียนจาก core/protocol.py อย่างเดียว ไม่ import แบรนด์อื่น

ตอบได้แค่สเปกของ 3 รุ่นในตาราง (products.json) · ราคาและการค้าส่งฝ่ายขายผ่าน core/sales.py
ไม่มีโมเดลรูป ไม่มี vector search — ตารางเล็กพอส่งทั้งแถวให้ LLM
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from core.llm import extract_text
from core.protocol import BrandInfo, BrandSignal, DecideInput, Decision, LLMTurn, TurnOutput
from core.sales import attach_handoff, escalation_gate
from core.text import norm_code

BRAND_WORDS = re.compile(r"\bdemo\b|เดโม", re.IGNORECASE)
EMPTY_REPLY_TH = "ขออภัยครับ ระบบไม่สามารถสร้างคำตอบได้ในขณะนี้ กรุณาลองถามใหม่อีกครั้ง"


class DemoPlugin:
    gate_chain = ("escalation", "code", "answer")
    image_reject_th = ""

    def __init__(self, info: BrandInfo, products: list[dict]):
        self.info = info
        self.products = {p["code"]: p for p in products}
        self._idx = {norm_code(c): c for c in self.products}
        self._code_rx = re.compile(r"DMX\s*-?\s*\d{3}", re.IGNORECASE)

    # ── 1 · รู้จักข้อความ ──
    def _codes(self, text: str) -> list[str]:
        out = []
        for m in self._code_rx.finditer(text or ""):
            c = self._idx.get(norm_code(m.group()))
            if c and c not in out:
                out.append(c)
        return out

    def detect(self, text: str) -> BrandSignal:
        codes = self._codes(text)
        if codes:
            return BrandSignal("strong", "รหัส Demo", True, codes)
        if BRAND_WORDS.search(text or ""):
            return BrandSignal("strong", "ชื่อแบรนด์ Demo", False, [])
        return BrandSignal("none", "", False, [])

    def domain_terms(self) -> list[str]:
        return ["demo", "เดโม"]

    # ── 5 · สถานะ ──
    def empty_state(self) -> dict:
        return {"codes": []}

    def has_focus(self, st: dict) -> bool:
        return bool(st.get("codes"))

    def on_brand_switch(self, st: dict) -> dict:
        return {**st, "codes": []}

    def sanitize_state(self, raw: dict) -> dict:
        codes = raw.get("codes")
        return {"codes": [c for c in codes if c in self.products] if isinstance(codes, list) else []}

    def resumable(self, st: dict) -> bool:
        return bool(st.get("codes"))

    # ── 3 · ตัดสิน ──
    def decide(self, inp: DecideInput, st: dict) -> Decision:
        key, text = self.info.key, inp.text
        if inp.signal.parsed:
            st["codes"] = list(inp.signal.parsed)
        code = (st["codes"] or [None])[0]
        esc = escalation_gate(text, belt_code=code)
        if esc and not esc.has_spec_question:
            return Decision("escalate", key, esc.reply_th, f"หัวข้อ {esc.topics}", topic="escalate",
                            effective_text=text, payload=dict(codes=st["codes"]))
        if st["codes"]:
            d = Decision("answer", key, reason="รหัสชัด", effective_text=text,
                         payload=dict(codes=list(st["codes"])))
        else:
            models = "\n".join(f"• {c} — {p['name']} กว้าง {p['width_mm']} มม." for c, p in self.products.items())
            d = Decision("ask", key, f"แบรนด์ Demo มี {len(self.products)} รุ่นครับ หมายถึงรุ่นไหนครับ\n{models}",
                         "ยังไม่รู้รุ่น", topic="code", effective_text=text, pending="demo_model")
        if esc:
            attach_handoff(d, esc.handoff_th, esc.topics)
        return d

    # ── ข้ามแบรนด์ ──
    def cross_brand_section(self, topic: str) -> Optional[list[str]]:
        if topic != "stainless":
            return None
        ss = [c for c, p in self.products.items() if "SS" in str(p.get("material", ""))]
        return [f"• รุ่นที่ใช้ SS: {', '.join(ss)}"] if ss else ["• ไม่มีรุ่นที่ใช้ชิ้นส่วนสแตนเลส (ข้อมูลสมมติ)"]

    # ── 2 + 4 · ค้นและ prompt ──
    def build_turn(self, decision: Decision, turn) -> LLMTurn:
        codes = decision.payload.get("codes") or []
        rows = [self.products[c] for c in codes if c in self.products]
        prompt = (
            "คุณคือผู้ช่วยฝ่ายขายของแบรนด์ตัวอย่าง Demo (ข้อมูลสมมติสำหรับทดสอบระบบ)\n"
            "ตอบภาษาไทย ตอบจากตารางนี้เท่านั้น ถ้าไม่มีในตารางให้บอกว่าไม่มีข้อมูล ห้ามเดา\n\n"
            f"[ตารางสินค้า]\n{json.dumps(rows, ensure_ascii=False, indent=2)}\n"
        )
        if decision.sales_topics:
            prompt += (f"\nเรื่อง {'/'.join(decision.sales_topics)} ระบบแนบข้อความฝ่ายขายเอง "
                       "ตอบเฉพาะส่วนสเปก")
        return LLMTurn(prompt, [decision.effective_text or turn.user_text], tools=(),
                       debug=[f"**Demo:** รุ่น {', '.join(codes) or '-'}\n\n"])

    def finish_turn(self, decision, turn, llm, result) -> TurnOutput:
        return TurnOutput(extract_text(result.response).strip() or EMPTY_REPLY_TH)

    # ── 6 · รูป ──
    def image_scorer(self):
        return None


def create(ctx):
    cfg = ctx.config
    path = os.path.join(ctx.brand_dir, cfg["data"]["products"])
    with open(path, encoding="utf-8") as f:
        products = json.load(f)["products"]
    i = cfg["info"]
    info = BrandInfo(key=cfg["key"], name=i["name"], order=i["order"], kind_th=i["kind_th"],
                     menu_line_th=i["menu_line_th"], offtopic_th=i["offtopic_th"],
                     category_th=i["category_th"], answer_patterns=tuple(i.get("answer_patterns") or ()))
    return DemoPlugin(info, products)
