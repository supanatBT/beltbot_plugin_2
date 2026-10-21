"""
brands/movex/detect.py
======================
Movex รู้จักข้อความนี้ไหม — ตอบเฉพาะของ Movex ไม่รู้จักแบรนด์อื่น
(ย้ายมาจาก BrandRouter ใน brands/modutech/router.py ชั้น 3 · regex เท่าเดิม)

    strong  LF### · K### · Art.Nr สเตอร์ 5xxxx · ซีรีส์ 820/821/880/882/103 · โซ่ · chain · workload
    weak    งานขวด/กระป๋อง single file
รูปภาพไม่ได้ตัดสินที่นี่ — core/router.py นับรูปเป็น strong ให้แบรนด์ที่รับรูป
"""
from __future__ import annotations

import re

from core.protocol import BrandSignal

MOVEX_PATTERNS = [
    r"\bLF\s*N?\s*\d{2,3}", r"\bK\s?\d{3,4}\b",   # TAB ไม่นับ: Modutech มี EC254 TR-TAB
    r"(?<!\d)5[4-9]\d{3}(?!\d)",                 # Art.Nr สเตอร์ Movex
    r"(?<![A-Za-z\d])(?:820|821|880|882|103)(?!\d)",  # ซีรีส์ Movex
    r"movex", r"โซ่", r"\bchain\b", r"top\s*chain", r"workload",
]
_MOVEX_RE = re.compile("|".join(MOVEX_PATTERNS), re.IGNORECASE)

# สัญญาณอ่อนของ Movex — งานขวด/กระป๋อง single file
MOVEX_WEAK = ["ขวด", "กระป๋อง", "PET", "bottle", "can ", "single file"]

STRONG_EVIDENCE = "รหัส/ซีรีส์ Movex"


def detect(text: str) -> BrandSignal:
    """has_code ยังไม่ตัดสินที่นี่ — การแยกรหัสรุ่น Movex อยู่ใน DialogueManager จนถึงชั้น 4"""
    text = text or ""
    if _MOVEX_RE.search(text):
        return BrandSignal("strong", STRONG_EVIDENCE)
    weak = next((t for t in MOVEX_WEAK if t.lower() in text.lower()), None)
    if weak:
        return BrandSignal("weak", weak)
    return BrandSignal("none")
