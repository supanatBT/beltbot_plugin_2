"""
core/sales.py
=============
ส่งเรื่องฝ่ายขาย — ใช้ร่วมกันทุกแบรนด์ (ย้ายมาจากไฟล์เกตของแบรนด์ ชั้น 4 · เนื้อหาเท่าเดิม)

ข้อความฝ่ายขายสร้างในโค้ดเสมอ LLM ไม่ได้เขียนเอง
แต่ละแบรนด์เลือกหัวข้อที่ตัวเองตอบเองได้ผ่าน allowed_topics
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


# ═══════════════════════════════════════════════════════════════
# ESCALATE TO SALES — ตอบจาก template ไม่ผ่าน LLM
# ═══════════════════════════════════════════════════════════════

# หัวข้อ = ค่าใน answering.escalate_to_sales (เหมือนกันทั้ง 68 รุ่น)
# คำพ้อง: ระวัง "เท่าไหร่" คำเดียว — "กว้างเท่าไหร่" ไม่ใช่คำถามราคา
ESCALATE_PATTERNS: dict[str, list[str]] = {
    "ราคา": [r"ราคา", r"กี่บาท", r"\bprice\b", r"\bcost\b", r"quotation", r"ใบเสนอราคา",
             r"ส่วนลด", r"discount"],
    "lead time": [r"lead\s*time", r"กี่วัน(?:ได้|ส่ง|ถึง)", r"ส่งของ", r"ระยะเวลา(?:ส่ง|ผลิต)",
                  r"(?:ได้|ส่ง)(?:ของ)?(?:เมื่อไ(?:หร่|ร))", r"delivery"],
    "MOQ": [r"\bmoq\b", r"สั่งขั้นต่ำ", r"ขั้นต่ำกี่", r"minimum\s*order"],
    "สต็อก": [r"สต็อก", r"สต๊อก", r"\bstock\b", r"ของพร้อมส่ง", r"มีของ(?:ไหม|มั้ย|หรือเปล่า)"],
    "สเปกเฟือง": [r"สเปก(?:เฟือง|สเตอร์)", r"ขนาด(?:เฟือง|สเตอร์)", r"pitch\s*diameter",
                  r"เส้นผ่าน(?:ศูนย์กลาง)?(?:เฟือง|สเตอร์)", r"\bP\.?D\.?\b", r"\bO\.?D\.?\b"],
    "ขนาดเพลา": [r"เพลา", r"\bshaft\b", r"\bbore\b", r"รูเพลา", r"รูสเตอร์"],
    "ความกว้างสั่งทำพิเศษ": [r"สั่งทำ(?:พิเศษ)?", r"ทำพิเศษ", r"custom\s*width", r"กว้างพิเศษ"],
    "รัศมีวงเลี้ยว": [r"รัศมี", r"radius", r"วงเลี้ยว", r"turning"],
    "อะไหล่": [r"อะไหล่", r"spare\s*part", r"\bspare\b"],
    # เพิ่ม 2 ต.ค. — สองหัวข้อนี้เคยไม่มี คำถามจึงไปถึง LLM ซึ่งไม่มีเบอร์ในมือ
    # แล้ว LLM ตอบว่า "ยังไม่มีข้อมูลเบอร์โทรหรืออีเมลของทีมฝ่ายขาย" และขอให้ลูกค้า
    # ฝากเบอร์ไว้ในแชตแทน ทั้งที่ sales_contact.py มีเบอร์จริงอยู่
    # ช่องทางติดต่อต้องมาจากโค้ดเสมอ ไม่ใช่จาก LLM
    "ช่องทางติดต่อ": [r"ขอ(?:เบอร์|อีเมล|อีเมล์|ช่องทาง|ไลน์)", r"เบอร์(?:โทร|ติดต่อ)?",
                      r"โทรศัพท์", r"อีเมล", r"\bemail\b", r"\be-?mail\b",
                      r"line\s*id", r"ไลน์ไอดี", r"\bcontact\b",
                      r"ติดต่อ(?:ใคร|ยังไง|อย่างไร|ได้ที่ไหน|ที่ไหน|ฝ่ายขาย|เซลล์|ทาง)"],
    "สั่งซื้อ": [r"สั่งซื้อ", r"สั่งของ", r"สั่ง(?:ยังไง|อย่างไร|ที่ไหน)",
                 r"(?:อยาก|สนใจ|ต้องการ)(?:จะ)?(?:ซื้อ|สั่ง)", r"ซื้อ(?:ยังไง|อย่างไร|ที่ไหน|ได้ที่ไหน)",
                 r"ออเดอร์", r"\border\b", r"\bpurchase\b", r"เปิด\s*PO", r"\bPO\b"],
}
_ESC_RE = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in ESCALATE_PATTERNS.items()}

# คำที่ติดมากับหัวข้อส่งฝ่ายขาย — ลบทิ้งด้วยก่อนดูว่ายังเหลือคำถามสเปกไหม
# ("สั่งทำความกว้าง 700" ไม่ใช่คำถามสเปกความกว้าง · "สเตอร์รูเพลาขนาดเท่าไหร่" ไม่ใช่คำถามสเปกสเตอร์)
_ESC_COMPANION = {
    "ความกว้างสั่งทำพิเศษ": r"(?:ความ)?กว้าง",
    "รัศมีวงเลี้ยว": r"เลี้ยว|โค้ง",
    "สเปกเฟือง": r"สเตอร์|เฟือง|ขนาด",
    "ขนาดเพลา": r"สเตอร์|เฟือง|ขนาด",
}
# คำถามสเปกที่บอทตอบเองได้ (ทั้งสองแบรนด์) — ใช้ตัดสินว่าเป็นคำถามผสมหรือไม่
SPEC_QUESTION_RX = re.compile(
    r"กว้าง|ยาว|หนา|น้ำหนัก|หนัก|แรงดึง|รับแรง|โหลด|\bload\b|workload|strength|"
    r"อุณหภูมิ|องศา|ร้อน|เย็น|แช่แข็ง|°|วัสดุ|ทำจาก|เกรด|สเปก|\bspec|pitch|พิทช์|"
    r"ช่องเปิด|open\s*area|เลี้ยว|โค้ง|ผิว|เปียก|แห้ง|\bFDA\b|ใช้กับ|เหมาะ|ผลิตยังไง|สเตอร์ตัวไหน|ฟัน",
    re.IGNORECASE)

# ข้อความเฉพาะหัวข้อ — ใช้แทนข้อความกลางเมื่อข้อความกลางอ่านไม่เป็นธรรมชาติ
# "เรื่องช่องทางติดต่อของสายพาน HC127 C ต้องให้ฝ่ายขายยืนยันโดยตรง" ไม่ใช่คำตอบของคำถามนี้
# เรียงตามลำดับความสำคัญ เจอตัวแรกใช้ตัวนั้น
TOPIC_PRIORITY = ("ช่องทางติดต่อ", "สั่งซื้อ")

def order_steps_th(belt_code: Optional[str] = None) -> str:
    """ข้อความเรื่องการสั่งซื้อ — บอกว่าบอตทำอะไรได้แค่ไหน แล้วให้ลูกค้าติดต่อเอง"""
    what = f"สายพาน {belt_code}" if belt_code else "สินค้า"
    return (f"ถ้าสนใจสั่งซื้อ{what} ต้องติดต่อฝ่ายขายโดยตรงครับ ผมดูแลเฉพาะข้อมูลสเปก "
            f"เวลาติดต่อเตรียมข้อมูลสี่อย่างนี้ไปด้วยจะได้ใบเสนอราคาเร็วขึ้น "
            f"ความกว้างที่ต้องการ · ความยาวสายพาน · เกรดวัสดุ · "
            f"อุปกรณ์ประกอบถ้ามี เช่น สเตอร์")

SALES_CONTACT_TH = "ฝ่ายขาย"   # ช่องทางติดต่อจริงอยู่ใน sales_contact.py


@dataclass
class Escalation:
    topics: list[str]
    reply_th: str               # ข้อความเต็ม — ใช้เมื่อคำถามมีแต่เรื่องฝ่ายขาย (ไม่เรียก LLM)
    handoff_th: str = ""        # ข้อความสั้น — ต่อท้ายคำตอบสเปกเมื่อเป็นคำถามผสม
    has_spec_question: bool = False


def _spec_remainder(user_text: str, topics: list[str]) -> str:
    rest = user_text or ""
    for t in topics:
        rest = _ESC_RE[t].sub(" ", rest)
        if t in _ESC_COMPANION:
            rest = re.sub(_ESC_COMPANION[t], " ", rest, flags=re.IGNORECASE)
    return rest


def escalation_gate(user_text: str, belt_code: Optional[str] = None,
                    allowed_topics: Optional[Iterable[str]] = None) -> Optional[Escalation]:
    """
    คืน Escalation ถ้าคำถามแตะหัวข้อต้องส่งฝ่ายขาย
      has_spec_question = False → chatbot ตอบ reply_th ตรง ไม่เรียก LLM
      has_spec_question = True  → คำถามผสม: ตอบสเปกตามปกติ แล้วโค้ดต่อท้ายด้วย handoff_th
    ข้อความฝ่ายขายสร้างในโค้ดเสมอ LLM ไม่ได้เขียนเอง
    """
    from sales_contact import sales_contact_line_th
    allowed = set(allowed_topics) if allowed_topics else set(ESCALATE_PATTERNS)
    topics = [t for t, rx in _ESC_RE.items() if t in allowed and rx.search(user_text or "")]
    if not topics:
        return None
    contact = sales_contact_line_th()
    subject = f"สายพาน {belt_code} " if belt_code else ""
    topic_txt = "/".join(topics)
    topic_txt = (" " + topic_txt + " ") if topic_txt[0].isascii() else topic_txt
    lead = next((t for t in TOPIC_PRIORITY if t in topics), None)
    if lead == "ช่องทางติดต่อ":
        # คำถามนี้ "คำตอบคือช่องทาง" ไม่ใช่ "ต้องให้ฝ่ายขายยืนยัน"
        reply = "ติดต่อฝ่ายขายได้ตามนี้ครับ" if contact else \
                "ขออภัยครับ ระบบยังไม่ได้ตั้งช่องทางติดต่อฝ่ายขายไว้ รบกวนแจ้งผู้ดูแลระบบครับ"
    elif lead == "สั่งซื้อ":
        reply = order_steps_th(belt_code)
    else:
        # ห้ามรับปากว่าจะส่งเรื่องต่อหรือให้ฝ่ายขายติดต่อกลับ
        #
        # ข้อความเดิมลงท้ายว่า "ผมจะส่งเรื่องต่อให้ฝ่ายขายติดต่อกลับครับ" ซึ่งบอตทำไม่ได้
        # ไม่มีกลไกส่งต่อ ไม่มีใครได้รับเรื่อง ลูกค้าที่เชื่อแล้วรออยู่จะไม่มีใครโทรมา
        # หน้าที่ของบอตคือให้ข้อมูลสเปกกับบอกช่องทางติดต่อ ลูกค้าเป็นคนติดต่อเอง
        reply = (f"เรื่อง{topic_txt}ของ{subject}อยู่นอกข้อมูลที่ระบบมีครับ "
                 f"ต้องสอบถาม{SALES_CONTACT_TH}โดยตรง "
                 f"เวลาติดต่อ แจ้งรุ่นสายพาน ความกว้าง ความยาว และจำนวนที่ต้องการไปด้วย "
                 f"จะได้คำตอบเร็วขึ้นครับ")
    handoff = (f"ส่วนเรื่อง{topic_txt}{('ของ' + subject.strip()) if subject else ''} "
               f"ต้องสอบถาม{SALES_CONTACT_TH}โดยตรงครับ "
               f"เวลาติดต่อแจ้งความกว้าง ความยาว และจำนวนที่ต้องการไปด้วยนะครับ")
    if contact:
        reply += "\n" + contact
        handoff += "\n" + contact
    spec = bool(SPEC_QUESTION_RX.search(_spec_remainder(user_text, topics)))
    return Escalation(topics=topics, reply_th=reply, handoff_th=handoff, has_spec_question=spec)


def attach_handoff(d, handoff_th: str, topics: list) -> None:
    """
    คำถามผสม: ส่วนสเปกเดินตามปกติ ส่วนการค้าส่งฝ่ายขาย
      ask            → ต่อข้อความฝ่ายขายท้ายคำถามกลับเลย (ลูกค้าเห็นทันที)
      answer/search  → เก็บไว้ใน sales_handoff_th ให้ chatbot ต่อท้ายหลังคำตอบของ LLM
    (ย้ายมาจาก dialogue_state._attach_handoff ชั้น 4)
    """
    d.sales_topics = list(topics)
    d.reason = f"{d.reason} · คำถามผสม: {'/'.join(topics)} → ฝ่ายขาย".strip(" ·")
    if d.needs_llm:
        d.sales_handoff_th = handoff_th
    elif d.action == "ask":
        d.reply_th = f"{d.reply_th}\n\n{handoff_th}"
