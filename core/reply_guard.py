"""
core/reply_guard.py — ตรวจคำตอบของ LLM ก่อนถึงลูกค้า (ด้วยโค้ด ไม่ใช่ prompt)

ลูกค้าจำลอง sim4_llm (26 ต.ค. · โค้ด 0263f53) เจอสองแบบที่ prompt กันไม่อยู่
1) ช่องทางติดต่อปลอม (G02 ทั้งสองรอบ): ลูกค้าขอเบอร์พร้อมถามสเปก → LLM พิมพ์
   เบอร์ 02-123-4567 · อีเมล sales@<ชื่อแบรนด์>.co.th · LINE @<ชื่อแบรนด์>thailand ซึ่งไม่มีอยู่จริง
   แล้วโค้ดต่อท้ายด้วยช่องทางจริง (086-3451403) — ลูกค้าเห็นสองชุด
2) LLM เล่าเหตุผลภายในออกมาเป็นคำตอบ (G05): "ดูจาก context ที่ผ่านการคัดกรอง: slots_known: pitch_mm = 5.0 ..."

ตรวจจากคำตอบทั้งหมดที่เก็บไว้ 2,366 คำตอบ (conv_r1–r6 · lat_* · m136 · graph_apps · sim*):
ทั้งสองแบบเจอเฉพาะเคสข้างบน ไม่มีคำตอบปกติที่ถูกจับผิด

ไม่รู้จักชื่อแบรนด์ · ช่องทางจริงอ่านจาก sales_contact.py (ที่เดียวกับข้อความส่งฝ่ายขาย)
"""
from __future__ import annotations

import re

PHONE_RX = re.compile(r"(?<!\d)(?:\+?66[-\s]?|0)\d{1,2}[-\s]?\d{3}[-\s]?\d{3,4}(?!\d)")
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HANDLE_RX = re.compile(r"(?i)(?:line|ไลน์)[^\n@]{0,25}@[A-Za-z][\w.]+")

# ชื่อฟิลด์ภายใน (snake_case) หรือคำที่บอกว่ากำลังอ่าน Context — คำตอบลูกค้าไม่มีสิ่งเหล่านี้
LEAK_RX = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b|(?i:\bcontext\b)|ผ่านการคัดกรอง|ระบบ\s*parse")

LEAK_RETRY_TH = ("ข้อความก่อนหน้ามีเหตุผลภายในหรือชื่อฟิลด์ของระบบ ซึ่งลูกค้าไม่ควรเห็น "
                 "ช่วยเขียนคำตอบถึงลูกค้าใหม่ทั้งหมด เป็นภาษาไทยธรรมชาติ ไม่อ้างถึงระบบ Context หรือชื่อฟิลด์ใด ๆ")
LEAK_FALLBACK_TH = "ขออภัยครับ ระบบเรียบเรียงคำตอบไม่สำเร็จ รบกวนส่งคำถามเดิมอีกครั้งครับ"


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def official_contacts() -> tuple[set, set]:
    """(เบอร์จริงแบบตัวเลขล้วน, อีเมลจริงตัวพิมพ์เล็ก) จาก sales_contact.py"""
    try:
        import sales_contact as SC
    except Exception:                                    # noqa: BLE001 — ไม่มีไฟล์ = ไม่มีช่องทางจริง
        return set(), set()
    phones = {_digits(SC.SALES_PHONE)} - {""}
    emails = {SC.SALES_EMAIL.strip().lower()} - {""}
    return phones, emails


def scrub_contacts(reply: str, phones: set | None = None, emails: set | None = None) -> tuple[str, list]:
    """ลบบรรทัดที่มีเบอร์ · อีเมล · LINE ID ที่ไม่ใช่ช่องทางจริง → (คำตอบใหม่, รายการที่ลบ)
    ลบทั้งบรรทัด ไม่ใช่แค่ตัวเลข — ข้อความรอบ ๆ ("โทรศัพท์: ...") ไม่มีความหมายเมื่อไม่มีค่า"""
    if phones is None or emails is None:
        phones, emails = official_contacts()
    removed, keep = [], []
    for line in (reply or "").split("\n"):
        fake = [m for m in PHONE_RX.findall(line) if _digits(m) not in phones]
        fake += [m for m in EMAIL_RX.findall(line) if m.lower() not in emails]
        fake += HANDLE_RX.findall(line)
        if fake:
            removed += fake
            continue
        keep.append(line)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()
    return out, removed


def leaks(reply: str) -> list[str]:
    return LEAK_RX.findall(reply or "")
