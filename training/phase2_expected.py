"""
phase2_expected.py — ความต่างที่ "ตั้งใจ" ระหว่างโค้ดเดิม (e261bf9) กับเฟส 2 สำหรับเทสต์เทียบของเดิม

เทสต์เทียบ (test_core_registry · test_core_router · test_core_decide · test_demo) ยังเทียบกับโค้ดเดิมทุกเทิร์น
แต่แปลงผลของเดิมด้วยการเปลี่ยนที่ตั้งใจข้างล่างก่อนเทียบ — อะไรที่ต่างนอกเหนือจากนี้ยังตก
ทุกข้อมีที่มาใน RESULTS_phase2_answer_review.md (10 ต.ค.)

  1 ท้ายเมนูถามแบรนด์  "ถ้ามีรหัสรุ่นหรือรูปสินค้า ส่งมาได้เลยครับ" → บอกว่าตอบเลขได้ก่อน (EX-004–006)
  2 ทักทาย             คำทัก (ไม่ใช่ขอบคุณ) ได้ "สวัสดีครับ …" แทน "ยินดีครับ …" (RT-003)
  3 เลือกแบรนด์         พื้นที่เปิด · kg/m² เป็นสัญญาณแข็งของ Modutech (EX-004 · EX-006)
  4 ค้นผิว             "ผิวกันลื่น" (คำกลาง) = Non Slip + Grip Top + Flush Grid Grip Top (EX-009)
  5 Movex ถามรุ่น       ถ้าคำถามบอกงาน (ขวด PET · กระป๋อง …) ยกรุ่นที่ usage เขียนถึงงานนั้นแทนข้อความถามรุ่น (RT-014 · 11 ต.ค. ค่ำ)
"""
from __future__ import annotations

import re

OLD_ASK_ENDING = "\nถ้ามีรหัสรุ่นหรือรูปสินค้า ส่งมาได้เลยครับ"
NEW_ASK_ENDING = "\nตอบเป็นเลขข้อหรือชื่อแบรนด์ได้เลยครับ ถ้ามีรหัสรุ่นหรือรูปสินค้าก็ส่งมาแทนได้"

_THANKS_RX = re.compile(r"ขอบคุณ|ขอบใจ|thank", re.IGNORECASE)
_GREET_RX = re.compile(r"สวัสดี|hello|hi |ดีครับ|ดีค่ะ", re.IGNORECASE)
_OLD_SMALLTALK_RX = re.compile(r"^ยินดีครับ มีเรื่อง(.*)ให้ช่วยดูเพิ่มเติม บอกได้เลยครับ$")

# ต้องตรงกับที่เพิ่มใน brands/modutech/detect.py MODUTECH_WORDS
MODUTECH_ATTR_RX = re.compile(r"พื้นที่เปิด|ช่องเปิด|open\s*area|kg\s*/\s*m\s*(?:2|²|\^2)|กก\.?\s*/\s*ตร\.?\s*ม",
                              re.IGNORECASE)


MOVEX_MODEL_ASK_HEAD = "ขอทราบรุ่นก่อนนะครับ เพื่อให้ตอบได้ตรง"


def expected_reply(old_reply: str, text: str, action: str = "", movex_products: dict | None = None) -> str:
    """ข้อความของเดิม → ข้อความที่เฟส 2 ตั้งใจให้เป็น"""
    r = (old_reply or "").replace(OLD_ASK_ENDING, NEW_ASK_ENDING)
    if movex_products is not None and r.startswith(MOVEX_MODEL_ASK_HEAD):
        from brands.movex.plugin import movex_application_block
        r = movex_application_block(text, movex_products) or r
    m = _OLD_SMALLTALK_RX.match(r)
    if m and _GREET_RX.search(text or "") and not _THANKS_RX.search(text or ""):
        r = f"สวัสดีครับ มีเรื่อง{m.group(1)}ให้ช่วยดู บอกได้เลยครับ"
    return r


def routing_changed(text: str) -> bool:
    """ข้อความที่ตั้งใจให้เลือกแบรนด์ต่างจากเดิม"""
    return bool(MODUTECH_ATTR_RX.search(text or ""))


NON_SLIP_GROUP = ["Non Slip", "Grip Top", "Flush Grid Grip Top"]


def expected_search_query(sq: dict, text: str) -> dict:
    """search_query ของเดิม → ที่เฟส 2 ตั้งใจ (เพิ่ม surface_any เมื่อลูกค้าพูด "กันลื่น" แบบกลาง ๆ)"""
    if not isinstance(sq, dict) or sq.get("surface") != "Non Slip":
        return sq
    if "กันลื่น" in (text or "") and not re.search(r"non\s*slip", text or "", re.IGNORECASE):
        return {**sq, "surface_any": list(NON_SLIP_GROUP)}
    return sq
