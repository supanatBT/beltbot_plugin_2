"""
brands/modutech/detect.py
=========================
Modutech รู้จักข้อความนี้ไหม — ตอบเฉพาะของ Modutech ไม่รู้จักแบรนด์อื่น
(ย้ายมาจาก BrandRouter ใน router.py ชั้น 3 · เนื้อหาเท่าเดิม)

    strong  รหัสสายพาน/สเตอร์ exact · พิมพ์แค่ซีรีส์ (candidates) · ชื่อแบรนด์ · หน่วย N/m
    weak    คำอุตสาหกรรม / สถานีงาน / ชื่อผิวสายพาน จาก v30 + คำเสริม
"""
from __future__ import annotations

import re

from brands.modutech.gates import Catalogue
from brands.modutech.router import CodeResolver
from core.protocol import BrandSignal

MODUTECH_WORDS = [r"modutech", r"โมดูเทค", r"modular", r"โมดูลาร์",
                  r"\bN\s*/\s*m\b", r"N/ม"]   # Movex ใช้ workload เป็น N ส่วน Modutech ใช้ N/m

# สัญญาณอ่อน — คำงานอาหาร/สถานีงานที่ Modutech ขาย (เสริมคำที่ดึงจาก v30 ซึ่งเป็นวลียาว)
MODUTECH_WEAK_EXTRA = [
    "เลาะกระดูก", "กระดูก", "ชำแหละ", "ไก่", "หมู", "เนื้อสัตว์", "เนื้อบด", "แล่ปลา", "กุ้ง", "อาหารทะเล",
    "เบเกอรี่", "ขนมปัง", "แป้ง", "โดว์", "ผัก", "ผลไม้", "เตาอบ", "สไปรัล", "แช่แข็ง", "ตู้แช่",
    "สะเด็ดน้ำ", "ล้างผัก", "กล่องลูกฟูก", "ลูกฟูก", "ตรวจจับโลหะ", "เครื่องชั่ง",
    "flush grid", "flat top", "ผิวตะแกรง", "ผิวเรียบ", "ผิวกันลื่น", "ผิวลูกกลิ้ง", "roller top",
]
# คำทั่วไปที่แบรนด์อื่นก็ใช้ ไม่นับเป็นสัญญาณ
GENERIC_TERMS = {"สายพาน", "บรรจุภัณฑ์", "Packaging", "Transfer Conveyors", "ลำเลียงจุดถ่ายโอน"}

STRONG_EVIDENCE = "รหัส/ชื่อแบรนด์ Modutech"


class ModutechDetector:
    def __init__(self, cat: Catalogue):
        self.resolver = CodeResolver(cat)
        terms = set()
        for v in cat.data.get("application_vocabulary", []):
            terms.add(v.get("application_th", ""))
            terms.add(v.get("application", ""))
        for p in cat.products:
            for i in p.get("industries", []):
                terms.add(i.get("industry_th", ""))
        for s in cat.data.get("surface_type_vocabulary", []):
            terms.add(s.get("surface_type_th", ""))
        terms |= set(MODUTECH_WEAK_EXTRA)
        self.weak_terms = sorted({t for t in terms if t and len(t) >= 3 and t not in GENERIC_TERMS},
                                 key=len, reverse=True)
        self._mod_word = re.compile("|".join(MODUTECH_WORDS), re.IGNORECASE)

    def detect(self, text: str) -> BrandSignal:
        """parsed = CodeMatch (รหัสที่จับได้ ใช้ต่อใน decide โดยไม่ต้องแยกซ้ำ)
        evidence ของ weak = คำที่จับได้"""
        text = text or ""
        codes = self.resolver.resolve(text)
        has_code = bool(codes.belt_codes or codes.sprocket_codes or codes.candidates)
        if has_code or self._mod_word.search(text):
            return BrandSignal("strong", STRONG_EVIDENCE, has_code, codes)
        weak = next((t for t in self.weak_terms if t.lower() in text.lower()), None)
        if weak:
            return BrandSignal("weak", weak, False, codes)
        return BrandSignal("none", "", False, codes)
