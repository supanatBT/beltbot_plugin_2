"""
core/protocol.py
================
สัญญาที่ปลั๊กอินแบรนด์ต้องตอบ — แกนกลางรู้จักแบรนด์ผ่านไฟล์นี้เท่านั้น

หนึ่งแบรนด์ = หนึ่งโฟลเดอร์ brands/<key>/ ที่มี brand.yaml + plugin.py
plugin.py ต้องมีฟังก์ชัน  create(ctx: PluginContext) -> BrandPlugin

ข้อห้ามของไฟล์นี้และทุกไฟล์ใน core/
  · ไม่มีชื่อแบรนด์สักคำ (ตรวจด้วย grep ใน training/run_gates.py)
  · ไม่ import torch / qdrant / genai — เทสต์ด้วย python ล้วนได้

คำถามหกข้อจาก HANDOFF ข้อ 3 → เมธอดที่ตอบ
  1. รู้จักรหัสในข้อความนี้ไหม มั่นใจแค่ไหน      detect · domain_terms
  2. ค้นข้อมูลอย่างไร                          build_turn          (ปลั๊กอินเลือกวิธีค้นเอง)
  3. มีเกตอะไร เรียงลำดับไหน                   gate_chain · decide
  4. ใส่กฎอะไรลง prompt                        build_turn → LLMTurn.system_prompt
  5. เก็บสถานะอะไรข้ามเทิร์น                    empty_state · has_focus · on_brand_switch · sanitize_state
  6. มีโมเดลรูปไหม collection ชื่ออะไร          brand.yaml › image  +  image_scorer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Protocol, Sequence, runtime_checkable

PROTOCOL_VERSION = 1          # brand.yaml ต้องประกาศ protocol: 1 — ไม่ตรงให้ registry หยุดพร้อมบอกค่า

Strength = Literal["none", "weak", "strong"]
Action = Literal["reject_image", "smalltalk", "refuse_offtopic", "ask",
                 "escalate", "cross_brand", "search", "answer"]


# ═══════════════════════════════════════════════════════════════
# ข้อมูลประจำแบรนด์ — อ่านจาก brand.yaml (ไม่ใช่โค้ด)
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BrandInfo:
    """ข้อความที่แกนกลางใช้ประกอบเทมเพลตรวมหลายแบรนด์ ทุกช่องมาจาก brand.yaml

    ตัวอย่างการใช้ในแกนกลาง (สองแบรนด์ต้องได้ข้อความเดิมทุกตัวอักษร)
      ถามแบรนด์      "{order}. {menu_line_th}"                      ทีละบรรทัด
      สัญญาณชนกัน    "{name} ({kind_th})" ต่อกันด้วย " หรือ "
      นอกเรื่อง       "{offtopic_th}" ต่อกันด้วย " และ"   (ไม่มีช่องว่างหลัง และ — ตามข้อความเดิม)
      ทักทาย         "{category_th}" ต่อกันด้วย "หรือ"
    """
    key: str                      # ชื่อโฟลเดอร์ ใช้เป็น prefix ตอนแปลงสถานะเป็น dict แบน
    name: str                     # ชื่อที่ลูกค้าเห็น
    order: int                    # ลำดับในเมนูถามแบรนด์ — ตอบเลขนี้ = เลือกแบรนด์นี้
    kind_th: str                  # "โซ่ท็อปเชน"
    menu_line_th: str             # บรรทัดในเมนูถามแบรนด์
    offtopic_th: str              # ชื่อในข้อความปฏิเสธนอกเรื่อง
    category_th: str              # คำกว้าง ๆ ในข้อความทักทาย
    answer_patterns: tuple[str, ...] = ()   # regex ที่แปลว่าลูกค้าตอบเลือกแบรนด์นี้


# ═══════════════════════════════════════════════════════════════
# 1 · รู้จักข้อความนี้ไหม
# ═══════════════════════════════════════════════════════════════

@dataclass
class BrandSignal:
    """ผลของ detect() — แกนกลางเอาไปเทียบข้ามแบรนด์ใน core/router.py

    strength  strong = รหัส/ชื่อแบรนด์/รูปที่โมเดลของแบรนด์นี้รับ · weak = คำอุตสาหกรรม/งาน · none
    has_code  เจอรหัสสินค้าจริงในข้อความ (ใช้ตัดสินว่าเป็นคำถามเรื่องสินค้า แยกจาก strength
              เพราะชื่อแบรนด์เป็น strong แต่ไม่ใช่รหัส)
    parsed    ของที่ปลั๊กอินแยกได้ แกนกลางไม่เปิดดู ส่งคืนเข้า decide() ตัวเดิม
              ไม่ต้องแยกรหัสซ้ำสองรอบ และไม่มีชนิดข้อมูลของแบรนด์รั่วเข้าแกน
    """
    strength: Strength = "none"
    evidence: str = ""            # เหตุผลสั้น ๆ ลง debug เช่น "รหัส/ซีรีส์" หรือคำที่จับได้
    has_code: bool = False
    parsed: Any = None


# ═══════════════════════════════════════════════════════════════
# 5 · สถานะบทสนทนา (ตัวคลาสอยู่ core/dialogue.py — ที่นี่คือส่วนที่ปลั๊กอินต้องรู้)
# ═══════════════════════════════════════════════════════════════
#
# ในหน่วยความจำ   state.brands[key] = dict ที่ปลั๊กอินถือเอง แกนกลางไม่เปิดดู
# ตอนส่งออก        แบนเป็น "<key>_<field>"  เช่น brands["x"]["codes"] → "x_codes"
#                  รูปแบบนี้ตรงกับ dict ที่เบราว์เซอร์เก็บไว้อยู่แล้ว แชตเก่ากู้ได้โดยไม่ต้องแปลง
#                  และไม่ต้องมีชื่อแบรนด์ในโค้ดแปลง
# key ของแบรนด์ห้ามมี _ (registry ตรวจ) — แยก "<key>_<field>" กลับได้ที่ _ ตัวแรกเสมอ ไม่กำกวม


# ═══════════════════════════════════════════════════════════════
# 3 · ผลการตัดสินหนึ่งเทิร์น
# ═══════════════════════════════════════════════════════════════

@dataclass
class DecideInput:
    """สิ่งที่แกนกลางส่งให้ decide() หลังเลือกแบรนด์แล้ว"""
    text: str                     # คำถามที่รวมคำตอบของการถามกลับแล้ว (effective)
    signal: BrandSignal           # ผล detect() ของแบรนด์นี้ในเทิร์นนี้
    has_image: bool = False
    image: Optional["ImageScore"] = None   # มีเมื่อ ImageRouter เลือกแบรนด์นี้จากรูป
    answer: str = ""              # ข้อความดิบของเทิร์นนี้ เมื่อเป็นคำตอบของการถามกลับรอบก่อน ("" = ไม่ใช่)


@dataclass
class Decision:
    """ผลการตัดสิน — สร้างโดยแกนกลาง (ก่อนเลือกแบรนด์) หรือโดยปลั๊กอิน (หลังเลือก)

    payload   ข้อมูลของแบรนด์ที่ตัดสิน (รหัส slot คำค้น) ปลั๊กอินอ่านกลับใน build_turn
    reply_th  มีค่าเมื่อเป็นเทมเพลต — ตอบได้โดยไม่เรียก LLM
    """
    action: Action
    brand: Optional[str]
    reply_th: str = ""
    reason: str = ""
    topic: Optional[str] = None
    effective_text: str = ""
    payload: dict = field(default_factory=dict)
    state: Any = None                                # core.dialogue.DialogState
    sales_handoff_th: str = ""                       # คำถามผสม: โค้ดต่อท้ายหลังคำตอบ LLM
    sales_topics: list = field(default_factory=list)
    pending: Optional[str] = None    # ปลั๊กอินถามกลับค้างไว้ — แกนกลางเก็บลงสถานะพร้อมคำถามเดิม

    @property
    def needs_llm(self) -> bool:
        return self.action in ("answer", "search")


# ═══════════════════════════════════════════════════════════════
# 2 + 4 · ค้นข้อมูล และประกอบ prompt
# ═══════════════════════════════════════════════════════════════

@dataclass
class TurnInput:
    """หนึ่งเทิร์นที่แกนกลางส่งเข้าปลั๊กอินตอนต้องเรียก LLM

    ของที่ฝากข้ามเทิร์นมีสามช่อง (ตำแหน่งเดิมใน tuple ของ chat_interaction) แกนกลางไม่เปิดดู
      last_focus    รหัสที่พูดถึงในเทิร์น LLM ล่าสุด (list)
      last_image    สัญญาณรูปล่าสุดที่ปลั๊กอินฝากไว้
      last_context  บริบทค้น/กราฟล่าสุดที่ปลั๊กอินฝากไว้
    """
    user_text: str
    image: Any                    # PIL.Image หรือ None
    history: list                 # [{"role", "content"}] แบบเดียวกับที่หน้าเว็บส่งมา
    session_id: str
    effective_text: str = ""      # ข้อความหลังเติมรหัสในโฟกัส (ก่อนตัดสิน)
    followup: Any = False         # คำถามต่อเนื่องสั้น ๆ (ค่าเดิมอาจเป็น "" — คงไว้ให้ debug เหมือนเดิม)
    last_focus: list = field(default_factory=list)
    last_image: Any = None
    last_context: Any = None
    image_score: Optional["ImageScore"] = None   # ผลจาก ImageRouter ถ้าเทิร์นนี้มีรูป
    log: Any = None               # turn log ของ PipelineLogger (ปลั๊กอินบันทึกขั้นค้นของตัวเอง)


@dataclass
class LLMTurn:
    """สิ่งที่ปลั๊กอินขอให้แกนกลางส่งเข้า LLM — แกนกลางเป็นคนเดียวที่คุยกับ LLM"""
    system_prompt: str
    user_parts: list              # [str] หรือ [image_part, str]
    tools: Sequence[Callable] = ()
    debug: list = field(default_factory=list)       # บรรทัดลงช่อง "ข้อมูลอ้างอิง"
    state: Any = None             # ของภายในปลั๊กอินที่ต้องใช้ต่อใน finish_turn (ผลค้น ranking ฯลฯ)
    direct_reply: Optional[str] = None   # มีค่า = ตอบเลยโดยไม่เรียก LLM (ค้นแล้วไม่เจออะไร)


@dataclass
class TurnOutput:
    reply: str
    extra_messages: list = field(default_factory=list)   # เช่น รูป datasheet แยกเป็นข้อความต่างหาก
    debug: list = field(default_factory=list)
    # ของฝากเทิร์นหน้า — คำนวณหลังแกนกลางต่อข้อความฝ่ายขายแล้ว (ใช้คำตอบสุดท้าย)
    # คืน (last_focus, last_image, last_context) · None = คงของเดิมไว้
    carry_fn: Optional[Callable[[str], tuple]] = None


# ═══════════════════════════════════════════════════════════════
# 6 · รูปภาพ
# ═══════════════════════════════════════════════════════════════

@dataclass
class ImageScore:
    """คะแนนจากโมเดลรูปของหนึ่งแบรนด์ — core/image_router.py เทียบข้ามแบรนด์

    แกนกลางใช้แค่ confidence กับ accepted ตัดสิน ที่เหลือส่งคืนปลั๊กอิน
    accepted = ระบบรูปของแบรนด์นี้หาสินค้าเจอ (ไม่เจอ = ถือว่ารูปไม่ใช่ของแบรนด์นี้)
    เกณฑ์ความมั่นใจระดับรุ่น/ซีรีส์ ปลั๊กอินใช้เองใน decide (thresholds.json)
    ห้ามใส่เกรดวัสดุหรือสภาวะเปียก/แห้งในนี้ — อนุมานจากรูปไม่ได้ (HANDOFF ข้อ 4)
    """
    brand: str
    confidence: float             # 0..1
    accepted: bool                # ผ่านเกณฑ์ขั้นต่ำของแบรนด์ตัวเอง (thresholds.json)
    label: Optional[str] = None   # คลาสจาก labels.json
    group: Optional[str] = None   # กลุ่มที่มองด้วยตาแยกไม่ออก (visual_groups.json) เช่น ซีรีส์
    dominant: bool = False
    product_ref: str = ""
    raw: Any = None               # ผลค้นเต็มของปลั๊กอิน ใช้ต่อใน build_turn โดยไม่ต้องค้นซ้ำ


@runtime_checkable
class ImageScorer(Protocol):
    def score(self, image: Any, text: str) -> ImageScore: ...


# ═══════════════════════════════════════════════════════════════
# สิ่งที่แกนกลางให้ปลั๊กอินตอนสร้าง
# ═══════════════════════════════════════════════════════════════

@dataclass
class PluginContext:
    """registry สร้างแล้วส่งให้ create() ของปลั๊กอิน

    shared  ของที่โหลดครั้งเดียวใช้ร่วมกันทุกแบรนด์ (embedding model, device, logger)
            ใส่โดยตัวเริ่มระบบ ไม่ใช่โดยแกนกลาง — เทสต์ส่ง {} ได้ ปลั๊กอินต้องทำงานได้
            ในโหมดไม่มีโมเดล (ตัดสินอย่างเดียว) ไม่งั้นชุดเกตรันไม่ได้
    """
    brand_dir: str
    config: dict                  # brand.yaml ทั้งไฟล์
    image_model: Any = None       # core.models.ImageModelSpec ที่ตรวจแล้ว หรือ None ถ้าปิด
    shared: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# ตัวสัญญา
# ═══════════════════════════════════════════════════════════════

@runtime_checkable
class BrandPlugin(Protocol):
    info: BrandInfo
    gate_chain: tuple[str, ...]   # ชื่อเกตตามลำดับที่รันจริง — ใช้ในเทสต์และ debug
    image_reject_th: str          # ข้อความปฏิเสธรูปของแบรนด์นี้ ("" = ไม่รับรูป)

    # ── 1 · รู้จักข้อความนี้ไหม ──────────────────────────────────
    def detect(self, text: str) -> BrandSignal:
        """อ่านข้อความอย่างเดียว ไม่ดูรูป (รูปผ่าน image_scorer) · ห้ามมี side effect"""
        ...

    def domain_terms(self) -> Sequence[str]:
        """คำที่แปลว่าเป็นคำถามเรื่องสินค้าของแบรนด์นี้ (รวมกับคำกลางใน core เพื่อกันนอกเรื่อง)"""
        ...

    # ── 5 · สถานะข้ามเทิร์น ───────────────────────────────────
    def empty_state(self) -> dict: ...

    def has_focus(self, st: dict) -> bool:
        """มีรุ่นค้างอยู่ในบทสนทนาไหม — ใช้ตัดสินว่าข้อความสั้นเป็นคำถามต่อเนื่อง"""
        ...

    def on_brand_switch(self, st: dict) -> dict:
        """ลูกค้าเปลี่ยนแบรนด์กลางบทสนทนา — คืนสถานะที่ล้างแล้ว (ปลั๊กอินเลือกว่าล้างอะไร)"""
        ...

    def sanitize_state(self, raw: dict) -> dict:
        """กรองสถานะที่เบราว์เซอร์ส่งกลับมา เก็บเฉพาะรหัสที่มีจริงในฐานข้อมูลของแบรนด์นี้
        raw คือฟิลด์ของแบรนด์นี้ที่ตัด prefix แล้ว (webapi ตัดความยาว list/dict ให้ก่อน)
        ค่าที่ไม่รู้จักต้องทิ้ง ไม่ใช่ raise"""
        ...

    def resumable(self, st: dict) -> bool:
        """สถานะนี้มีของพอให้กู้บทสนทนาไหม (ใช้ตอนเบราว์เซอร์ส่งประวัติกลับมา)"""
        ...

    # ── 3 · ตัดสินและเกต ─────────────────────────────────────
    def decide(self, inp: DecideInput, st: dict) -> Decision:
        """ตัดสินหลังเลือกแบรนด์แล้ว: ask / escalate / search / answer / reject_image
        แก้ st ได้ (แกนกลางส่งสำเนามา) · ห้ามเรียก LLM · ห้ามเข้าเน็ต
        ถามกลับแล้วรอคำตอบ → ตั้ง Decision.pending (แกนกลางเก็บคำถามเดิมให้เอง)"""
        ...

    # ── 2 + 4 · ค้นและประกอบ prompt ───────────────────────────
    def build_turn(self, decision: Decision, turn: TurnInput) -> LLMTurn:
        """เรียกเฉพาะเมื่อ decision.needs_llm · ค้นข้อมูลด้วยวิธีของแบรนด์ แล้วคืน prompt + tools"""
        ...

    def finish_turn(self, decision: Decision, turn: TurnInput, llm: LLMTurn, result: Any) -> TurnOutput:
        """หลัง LLM ตอบ — result คือ core.llm.LLMResult (response · session · tool_calls)
        ดึงข้อความ ต่อของที่โค้ดต้องเขียนเอง (รูป datasheet) และคืน carry_fn ของเทิร์นหน้า"""
        ...

    # ── ข้ามแบรนด์ ──────────────────────────────────────────
    def cross_brand_section(self, topic: str) -> Optional[list[str]]:
        """ส่วนของแบรนด์นี้ในคำตอบรวมทุกแบรนด์ (เช่น "สแตนเลส" ไม่ระบุแบรนด์)
        คืน None = แบรนด์นี้ไม่ตอบหัวข้อนี้ · สร้างจากข้อมูลจริงทุกครั้ง ไม่ฮาร์ดโค้ดรายชื่อรุ่น"""
        ...

    # ── 6 · รูป ─────────────────────────────────────────────
    def image_scorer(self) -> Optional[ImageScorer]:
        """None = แบรนด์นี้ไม่รับรูป (หรือ enabled: auto แล้วยังไม่มีโมเดล/collection)"""
        ...
