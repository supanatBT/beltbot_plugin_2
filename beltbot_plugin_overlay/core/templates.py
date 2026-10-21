"""
core/templates.py
=================
ข้อความที่พูดถึงหลายแบรนด์พร้อมกัน — ประกอบจาก BrandInfo (brands/<key>/brand.yaml › info)

เพิ่มแบรนด์ = ข้อความพวกนี้มีแบรนด์ใหม่เองโดยไม่ต้องแก้ไฟล์ไหน
กับสองแบรนด์เดิมต้องได้ข้อความเท่าเดิมทุกตัวอักษร (test_core_registry.py ตรวจ)
"""
from __future__ import annotations

from typing import Sequence

from core.protocol import BrandInfo


def _ordered(infos: Sequence[BrandInfo]) -> list[BrandInfo]:
    return sorted(infos, key=lambda i: i.order)


def ask_brand(infos: Sequence[BrandInfo]) -> str:
    """เมนูถามแบรนด์ — ตอบเลขในเมนูได้ (เลขคือ info.order)"""
    return ("ขอทราบก่อนนะครับว่าถามถึงสินค้าแบบไหน\n"
            + "\n".join(f"{i.order}. {i.menu_line_th}" for i in _ordered(infos))
            + "\nถ้ามีรหัสรุ่นหรือรูปสินค้า ส่งมาได้เลยครับ")


def clarify_conflict(infos: Sequence[BrandInfo]) -> str:
    """เจอสัญญาณแข็งของหลายแบรนด์ในข้อความเดียว"""
    return ("ขอยืนยันก่อนนะครับ ถามถึงสินค้า "
            + " หรือ ".join(f"{i.name} ({i.kind_th})" for i in _ordered(infos)) + " ครับ")


def offtopic(infos: Sequence[BrandInfo]) -> str:
    return (f"ขออภัยครับ ผมตอบได้เฉพาะเรื่องสินค้า{' และ'.join(i.offtopic_th for i in _ordered(infos))} "
            "เช่น สเปก การเลือกรุ่น หรืออะไหล่ที่ใช้คู่กัน มีเรื่องไหนให้ช่วยไหมครับ")


def smalltalk(infos: Sequence[BrandInfo]) -> str:
    return (f"ยินดีครับ มีเรื่อง{'หรือ'.join(i.category_th for i in _ordered(infos))}"
            "ให้ช่วยดูเพิ่มเติม บอกได้เลยครับ")


def brand_answer_patterns(info: BrandInfo) -> list[str]:
    """regex ที่แปลว่าลูกค้าตอบเลือกแบรนด์นี้ — ของใน brand.yaml + เลขในเมนู"""
    return list(info.answer_patterns) + [rf"^\s*{info.order}\s*$"]


def all_brands_th(n: int) -> str:
    """คำเรียกรวม — สองแบรนด์ใช้คำเดิม"""
    return "ทั้งสองแบรนด์" if n == 2 else "ทุกแบรนด์"
