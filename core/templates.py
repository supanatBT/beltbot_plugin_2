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
            + "\nตอบเป็นเลขข้อหรือชื่อแบรนด์ได้เลยครับ ถ้ามีรหัสรุ่นหรือรูปสินค้าก็ส่งมาแทนได้")
# เฟส 2 (10 ต.ค.): ท้ายเมนูเดิม "ถ้ามีรหัสรุ่นหรือรูปสินค้า ส่งมาได้เลยครับ" ไม่เข้ากับคำถามแบบค้นหา (EX-004–006)
# — บอกก่อนว่าตอบเลขได้ แล้วค่อยเสนอรหัส/รูปเป็นทางเลือก


def clarify_conflict(infos: Sequence[BrandInfo]) -> str:
    """เจอสัญญาณแข็งของหลายแบรนด์ในข้อความเดียว"""
    return ("ขอยืนยันก่อนนะครับ ถามถึงสินค้า "
            + " หรือ ".join(f"{i.name} ({i.kind_th})" for i in _ordered(infos)) + " ครับ")


def offtopic(infos: Sequence[BrandInfo]) -> str:
    return (f"ขออภัยครับ ผมตอบได้เฉพาะเรื่องสินค้า{' และ'.join(i.offtopic_th for i in _ordered(infos))} "
            "เช่น สเปก การเลือกรุ่น หรืออะไหล่ที่ใช้คู่กัน มีเรื่องไหนให้ช่วยไหมครับ")


def smalltalk(infos: Sequence[BrandInfo]) -> str:
    """ตอบคำขอบคุณ"""
    return (f"ยินดีครับ มีเรื่อง{'หรือ'.join(i.category_th for i in _ordered(infos))}"
            "ให้ช่วยดูเพิ่มเติม บอกได้เลยครับ")


def greeting(infos: Sequence[BrandInfo]) -> str:
    """ตอบคำทักทาย — เดิมใช้ข้อความเดียวกับคำขอบคุณ ("ยินดีครับ…") อ่านแปลกเมื่อลูกค้าแค่ทัก (RT-003 · 10 ต.ค.)"""
    return (f"สวัสดีครับ มีเรื่อง{'หรือ'.join(i.category_th for i in _ordered(infos))}"
            "ให้ช่วยดู บอกได้เลยครับ")


def brand_answer_patterns(info: BrandInfo) -> list[str]:
    """regex ที่แปลว่าลูกค้าตอบเลือกแบรนด์นี้ — ของใน brand.yaml + เลขในเมนู"""
    return list(info.answer_patterns) + [rf"^\s*{info.order}\s*$"]


def all_brands_th(n: int) -> str:
    """คำเรียกรวม — สองแบรนด์ใช้คำเดิม"""
    return "ทั้งสองแบรนด์" if n == 2 else "ทุกแบรนด์"


def image_no_model(info: BrandInfo, from_image: bool) -> str:
    """รูปไปแบรนด์ที่ยังไม่มีตัวให้คะแนนรูป — บอกตรง ๆ ว่ายังระบุรุ่นจากรูปไม่ได้ (ไม่ปล่อยให้ลูกค้าคิดว่ารูปถูกอ่านแล้ว)
    from_image = แบรนด์มาจากรูปเอง (ประตูรูปมั่นใจ) ไม่ใช่จากข้อความหรือคำตอบของลูกค้า"""
    if from_image:
        return f"จากรูปน่าจะเป็น{info.kind_th} {info.name} ครับ แต่ตอนนี้ระบบยังระบุรุ่นจากรูปไม่ได้"
    return f"ตอนนี้ระบบยังระบุรุ่น{info.kind_th} {info.name} จากรูปไม่ได้ครับ"


def image_need_question(info: BrandInfo) -> str:
    """ส่งรูปมาเฉย ๆ (ไม่มีข้อความ) ไปแบรนด์ที่อ่านรูปไม่ได้ — ไม่มีคำถามให้ตอบ จึงขอคำถามแทนการเดา (27 ต.ค.)
    ไม่อ้างรุ่นที่คุยค้างอยู่ — รูปใหม่อาจเป็นคนละรุ่น"""
    return (f"ถ้าต้องการถามเกี่ยวกับรูปนี้ รบกวนพิมพ์คำถามมาด้วยครับ เช่น รหัสรุ่นที่ปั๊มบน{info.kind_th} "
            "ใช้ลำเลียงอะไร หรืออยากทราบสเปกเรื่องไหน")
