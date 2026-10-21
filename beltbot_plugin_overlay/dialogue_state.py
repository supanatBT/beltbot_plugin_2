"""
dialogue_state.py — ทางเข้าชื่อเดิม (ชั้น 4)
=================
ตรรกะทั้งหมดย้ายออกแล้ว
    ส่วนกลาง (ทักทาย นอกเรื่อง เลือกแบรนด์ ถามแบรนด์ ข้ามแบรนด์)   → core/decide.py
    Movex  (รหัส ซีรีส์ ความกว้าง ViT)                          → brands/movex/plugin.py
    Modutech (slot ค้นทั้งฐาน เปียก/แห้ง ตรง/โค้ง)               → brands/modutech/plugin.py
    ส่งฝ่ายขาย                                               → core/sales.py
    สถานะ                                                   → core/dialogue.py

ไฟล์นี้คงไว้เพราะชุดเกตและ chatbot_v5.py เรียกชื่อพวกนี้ตรง ๆ
    DialogueManager(movex_products, modutech_catalogue, movex_materials)
    DialogState · Decision (มี .movex / .modutech แบบเดิม) · VitInfo
แก้เทสต์ = เปลี่ยนเครื่องมือวัด จึงแปลงรูปที่นี่แทน
ระบุสองแบรนด์ตรง ๆ — แบรนด์ที่เพิ่มทีหลังไม่เปลี่ยนสิ่งที่ชุดเกตวัด

ไม่ import torch / qdrant / gradio / genai — เทสต์ด้วย python ล้วน
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from brands.modutech.detect import ModutechDetector
from brands.modutech.plugin import ModutechPlugin, extract_modutech_slots  # noqa: F401  (ชื่อเดิม)
from brands.movex import detect as _movex_detect
from brands.movex.plugin import MovexPlugin, load_thresholds, reject_text
from core import router as _core_router
from core import templates as _templates
from core.decide import Dialogue
from core.dialogue import state_class as _state_class
from core.protocol import Decision as _CoreDecision, ImageScore
from core.registry import discover as _discover_brands, state_schema as _state_schema
from modutech_gates import Catalogue
from modutech_router import CodeMatch

_LEGACY_BRANDS = ["movex", "modutech"]
_CFG = {b.key: b for b in _discover_brands(only=_LEGACY_BRANDS, resolve_images=False)}

# ═══════════════════════════════════════════════════════════════
# ชนิดข้อมูลชื่อเดิม
# ═══════════════════════════════════════════════════════════════


@dataclass
class VitInfo:
    """สรุปจาก ViTSignal ของ RetrieverV4 (ไม่ import ตัวจริง เพื่อให้เทสต์ได้)"""
    series: Optional[str] = None
    confidence: float = 0.0
    dominant: bool = False
    top_pid: str = ""


# สถานะอยู่ที่ core/dialogue.py — ช่องของแต่ละแบรนด์อ่านจาก brands/<key>/brand.yaml › state
DialogState = _state_class(_state_schema(list(_CFG.values())))


@dataclass
class Decision:
    """รูปเดิมที่ chatbot_v5 กับชุดเกตอ่าน — payload ของแบรนด์อยู่ใน .movex / .modutech"""
    action: str                # reject_image | smalltalk | refuse_offtopic | ask | escalate | cross_brand | search | answer
    brand: Optional[str]
    reply_th: str = ""         # มีค่าเมื่อเป็น template — ตอบได้โดยไม่เรียก LLM
    reason: str = ""
    topic: Optional[str] = None
    effective_text: str = ""   # คำถามที่รวมคำตอบของการถามกลับแล้ว
    movex: dict = field(default_factory=dict)      # pids, series, level
    modutech: dict = field(default_factory=dict)   # codes, slots, search_query
    state: DialogState = field(default_factory=DialogState)
    # คำถามผสม (สเปก + ราคา ฯลฯ): โค้ดต่อท้ายข้อความนี้หลังคำตอบ — LLM ไม่ได้เขียนส่วนนี้
    sales_handoff_th: str = ""
    sales_topics: list = field(default_factory=list)

    @property
    def needs_llm(self) -> bool:
        return self.action in ("answer", "search")

    @classmethod
    def from_core(cls, d: _CoreDecision) -> "Decision":
        payload = d.payload if isinstance(d.payload, dict) else {}
        return cls(action=d.action, brand=d.brand, reply_th=d.reply_th, reason=d.reason, topic=d.topic,
                   effective_text=d.effective_text,
                   movex=payload if d.brand == "movex" else {},
                   modutech=payload if d.brand == "modutech" else {},
                   state=d.state, sales_handoff_th=d.sales_handoff_th, sales_topics=list(d.sales_topics))


# ═══════════════════════════════════════════════════════════════
# DialogueManager — ประกอบสองปลั๊กอินเข้ากับ core/decide.py
# ═══════════════════════════════════════════════════════════════

IMAGE_BRANDS = ("movex",)             # แบรนด์ที่มีโมเดลรูป — กฎเดิม "รูปเป็นของ Movex"


class DialogueManager:
    def __init__(self, movex_products: dict, modutech: Catalogue, movex_materials: Optional[dict] = None):
        mx, md = _CFG["movex"], _CFG["modutech"]
        self.movex_plugin = MovexPlugin(mx.info, movex_products, movex_materials,
                                        thresholds=load_thresholds(mx.dir, mx.config),
                                        reject_th=reject_text(mx.config), state_defaults=mx.state)
        self.modutech_plugin = ModutechPlugin(md.info, modutech, state_defaults=md.state)
        self.core = Dialogue([self.movex_plugin, self.modutech_plugin], DialogState,
                             image_brands=IMAGE_BRANDS)
        # ชื่อเดิมที่โค้ดภายนอกอ่าน
        self.mx = movex_products
        self.mod = modutech
        self.search = self.modutech_plugin.search
        self.materials = self.modutech_plugin.materials
        self.VIT_ANSWER = self.movex_plugin.vit_answer
        self.VIT_SERIES = self.movex_plugin.vit_series

    def decide(self, text: str, has_image: bool = False, vit: Optional[VitInfo] = None,
               image_rejected: bool = False, state=None) -> Decision:
        image = None
        if vit is not None:
            image = ImageScore(brand="movex", confidence=vit.confidence,
                               accepted=vit.confidence >= self.VIT_SERIES, label=None,
                               group=vit.series, dominant=vit.dominant, product_ref=vit.top_pid or "")
        d = self.core.decide(text, has_image=has_image, image=image, image_rejected=image_rejected,
                             state=state)
        return Decision.from_core(d)

    def stainless_both_brands_th(self) -> str:
        return self.core.cross_brand_th("stainless")


# ═══════════════════════════════════════════════════════════════
# ตัวเลือกแบรนด์แบบสองแบรนด์ — คงไว้ให้ test_core_router.py เทียบกับของเดิม (ชั้น 3)
# ═══════════════════════════════════════════════════════════════
# การตัดสินจริงอยู่ที่ core/router.choose() ซึ่งไม่รู้จักแบรนด์ · decide ไม่ได้ใช้คลาสนี้แล้ว

NO_SIGNAL_POLICY = "legacy_movex"     # ค่าเดิมของ modutech_router — decide() ส่ง "ask" เสมอ
IMAGE_BRANDS = ("movex",)             # แบรนด์ที่มีโมเดลรูป — กฎเดิม "รูปเป็นของ Movex"


@dataclass
class Route:
    brand: Optional[str]
    reason: str
    need_clarify: bool = False
    clarify_th: str = ""
    codes: CodeMatch = field(default_factory=CodeMatch)


class BrandRouter:
    def __init__(self, cat: Catalogue):
        self._mod = ModutechDetector(cat)
        self.resolver = self._mod.resolver
        self.weak_terms = self._mod.weak_terms
        self.infos = {b.key: b.info for b in _discover_brands(only=["movex", "modutech"], resolve_images=False)}

    def route(self, text: str, has_image: bool = False, prev_brand: Optional[str] = None,
              no_signal_policy: Optional[str] = None) -> Route:
        signals = {"movex": _movex_detect.detect(text), "modutech": self._mod.detect(text)}
        codes = signals["modutech"].parsed
        r = _core_router.choose(signals, prev_brand=prev_brand, has_image=has_image,
                                image_brands=IMAGE_BRANDS)
        if r.kind == "conflict_strong":
            return Route(None, "สัญญาณทั้งสองแบรนด์", True,
                         _templates.clarify_conflict([self.infos[k] for k in r.conflict]), codes)
        if r.kind == "strong":
            return Route(r.brand, r.evidence[r.brand], codes=codes)
        if r.kind == "conflict_weak":
            return Route(None, f"สัญญาณอ่อนทั้งสองฝั่ง ({r.evidence['modutech']} / {r.evidence['movex']})", True,
                         "งานนี้ลำเลียงอะไรเป็นหลักครับ และต้องการโซ่ท็อปเชน (Movex) "
                         "หรือสายพานโมดูลาร์ (Modutech) ครับ", codes)
        if r.kind == "weak":
            label = "คำอุตสาหกรรม/งาน" if r.brand == "modutech" else "คำงานขวด/กระป๋อง"
            return Route(r.brand, f"{label}: {r.evidence[r.brand]}", codes=codes)
        if r.kind == "previous":
            return Route(prev_brand, "ต่อจากเทิร์นก่อน", codes=codes)
        if (no_signal_policy or NO_SIGNAL_POLICY) == "legacy_movex":
            return Route("movex", "ไม่มีสัญญาณแบรนด์ → pipeline เดิม", codes=codes)
        return Route(None, "ไม่มีสัญญาณแบรนด์", True,
                     "ขอทราบเพิ่มนิดนะครับ ต้องการโซ่ท็อปเชน (Movex) หรือสายพานโมดูลาร์ (Modutech) "
                     "และใช้กับงานแบบไหนครับ", codes)
