"""ชื่อโมดูลแบบแบนก่อนจัดโฟลเดอร์ (9 พ.ย. 2026) — ใช้เฉพาะเทสต์ที่รันโค้ดเก่าจาก git (e261bf9) เทียบกับโค้ดปัจจุบัน

โค้ดเก่าเขียน `from modutech_gates import ...` · `from dialogue_state import ...` ซึ่งไม่มีที่รากแล้ว
install() ชี้ชื่อเดิมไปที่โมดูลปัจจุบัน (วัตถุเดียวกัน ไม่ใช่สำเนา) ก่อน exec โค้ดเก่า
"""
import importlib
import sys

LEGACY = {
    "modutech_gates": "engine.brands.modutech.gates",
    "modutech_router": "engine.brands.modutech.router",
    "modutech_kg": "engine.brands.modutech.kg",
    "modutech_turn": "engine.brands.modutech.turn",
    "dialogue_state": "bot.dialogue_state",
    "sales_contact": "engine.shared.sales_contact",
}


def install(*names: str) -> None:
    for old in names or LEGACY:
        sys.modules.setdefault(old, importlib.import_module(LEGACY[old]))
