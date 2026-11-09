"""
core/text.py — ตัวช่วยข้อความที่ใช้ร่วมกันทุกแบรนด์ (ไม่มีความรู้เรื่องสินค้า)
"""
from __future__ import annotations

import re
from typing import Iterable, Optional


def norm_code(s: str) -> str:
    """MP8 0 C / MP80-C / mp80c → MP80C  (& ในรหัสที่ OCR อ่านผิดก็ตัดทิ้ง)"""
    return re.sub(r"[^A-Z0-9%]", "", (s or "").upper())


def has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text or "", re.IGNORECASE))


def any_word(words: Iterable[str], text: str) -> Optional[str]:
    low = (text or "").lower()
    return next((w for w in words if w.lower() in low), None)
