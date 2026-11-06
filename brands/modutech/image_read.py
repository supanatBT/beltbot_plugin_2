"""
brands/modutech/image_read.py — ลักษณะผิวที่ LLM อ่านจากรูป → รายชื่อรุ่น Modutech ที่ผิวตรง (คัดด้วยโค้ด) · 6 พ.ย.

ตัวอ่าน (core/image_interpreter) ให้แค่ "ผิวหน้าตาแบบไหน · ทึบหรือมีช่อง · พิทช์จากสเกล (ถ้ามี)"
ไฟล์นี้เป็นคนเดียวที่แปลงลักษณะเป็นรุ่น — ด้วย CatalogueSearch ตัวเดิม (ทางเดียวกับคำถามค้นทั้งฐาน)
    ผิวที่อ่านได้   → ExploratoryQuery(surface_any=ผิวหลัก + ผิวที่ยังแยกไม่ออก) → ทุกรุ่นที่ผิวตรง
    อ่านผิวไม่ได้ แต่รู้ว่าทึบ/มีช่อง → กลุ่มผิวทึบหรือกลุ่มผิวมีช่อง
    พิทช์จากสเกล   → ใช้เรียงลำดับ (ใกล้ก่อน) เท่านั้น ไม่ตัดรุ่นทิ้ง — ระยะจากรูปเป็นค่าประมาณ ต้องให้ลูกค้ายืนยัน

ไม่ใช้กรองเลย (คืน None = ทางเดิม):
    อ่านรูปไม่ได้ · ไม่ใช่สินค้า/ไม่ชัด · ความมั่นใจต่ำ · ไม่มีรุ่นที่ผิวตรง · ผิวตรงทุกรุ่น (ไม่ได้ลดอะไร)

สวิตช์: IMAGE_INTERPRETER=llm (assistant.py) · ค่าเริ่มต้นปิด = บอทเดิมทุกตัวอักษร
"""
from __future__ import annotations

from typing import Optional

from brands.modutech.router import SURFACE_GROUPS, ExploratoryQuery
from core.image_interpreter import ImageReading, ImageSpec

# คำอธิบายหน้าตาผิวให้ LLM อ่าน (ชื่อไทยมาจาก surface_type_vocabulary ในไฟล์ข้อมูล — ตรงนี้เติมแค่ลักษณะที่ตาเห็น)
LOOKS_TH = {
    "Flat Top": "ผิวบนเรียบทึบ มองไม่ทะลุ",
    "Flush Grid": "โครงตะแกรงซี่บาง ช่องเปิดกว้างกินพื้นที่ส่วนใหญ่ มองทะลุได้ทั่วแผ่น ผิวบนเสมอกัน",
    "Perforated Flat Top": "แผ่นผิวเรียบเนื้อทึบเป็นส่วนใหญ่ มีรูหรือร่องเล็ก (กลม หรือยาวรีเป็นขีด) เจาะเรียงเป็นแถว",
    "Grip Top": "มียางหรือปุ่มยางนิ่มหุ้มบนผิว มักเป็นสีต่างจากตัวโมดูล",
    "Flush Grid Grip Top": "ตะแกรงเปิดที่มีปุ่มยางกันลื่นบนผิว",
    "Non Slip": "ลายนูนพลาสติกกันลื่นทั่วผิว ไม่มียาง",
    "Nub Top": "ปุ่มกลมเล็กนูนเรียงทั่วผิว",
    "Flush Grid Nub Top": "ตะแกรงเปิดที่มีปุ่มนูนเล็กบนผิว",
    "Raised Rib": "สันนูนยาวเรียงขนานกัน",
    "Mini Rib": "สันนูนขนาดเล็กเรียงถี่",
    "Roller Top": "มีลูกกลิ้งทรงกระบอกฝังบนผิว",
    "Ball Top": "มีลูกบอลฝังบนผิว",
    "Diamond Top": "ลายนูนรูปข้าวหลามตัด",
    "Negative Pyramid": "ลายพีระมิดบุ๋มลงเรียงทั่วผิว",
    "Curve Top": "ผิวของสายพานวิ่งโค้ง โมดูลเป็นแถวแคบต่อกันเลี้ยวได้",
}
# ใช้เมื่ออ่านผิวไม่ได้แต่รู้ว่าทึบหรือมีช่อง — ผิวที่ทึบ/มีช่องไม่แน่นอน (ลูกกลิ้ง ลูกบอล ผิวโค้ง) ไม่อยู่ในกลุ่มไหน
OPEN_SURFACES = ("Flush Grid", "Perforated Flat Top", "Flush Grid Grip Top", "Flush Grid Nub Top")
CLOSED_SURFACES = ("Flat Top", "Grip Top", "Non Slip", "Nub Top", "Raised Rib", "Mini Rib",
                   "Diamond Top", "Negative Pyramid")
MAX_PITCHES_LISTED = 8


def image_spec(cat) -> ImageSpec:
    """ผิวที่มีในฐานข้อมูล (vocabulary) + ชื่อไทย + หน้าตา · ผิวที่ไม่มีคำอธิบายหน้าตาใช้ชื่อไทยอย่างเดียว"""
    surfaces = {}
    for s in cat.data.get("surface_type_vocabulary") or []:
        en, th = s["surface_type"], s.get("surface_type_th") or ""
        look = LOOKS_TH.get(en, "")
        surfaces[en] = f"{th} — {look}" if look else th
    return ImageSpec(brand_th="สายพานโมดูลาร์ Modutech", product_th="สายพานโมดูลาร์พลาสติก",
                     surfaces=surfaces, pitch_lo=5.0, pitch_hi=80.0)


def _pitch(cat, code: str) -> Optional[float]:
    p = cat.by_code.get(code) if hasattr(cat, "by_code") else None
    if p is None:
        p = next((x for x in cat.products if x["belt_code"] == code), None)
    if p is None:
        return None
    v = (p.get("specifications", {}).get("pitch") or {}).get("mm")
    if v is None:
        v = (p.get("code_parts") or {}).get("pitch_mm")
    return float(v) if isinstance(v, (int, float)) else None


def image_match(reading: Optional[ImageReading], search, cat, spec: ImageSpec) -> tuple[Optional[dict], str]:
    """(context สำหรับ build_modutech_turn หรือ None, เหตุผลสั้น ๆ ลง debug)"""
    if reading is None:
        return None, "อ่านรูปไม่ได้ — ทางเดิม"
    if not reading.usable():
        return None, (f"ไม่ใช้กรอง (is_product={reading.is_product} · confidence={reading.confidence} · "
                      f"surface={reading.surface} · openness={reading.openness})")
    surfaces, basis = reading.surfaces(), "surface"
    if not surfaces:
        group = OPEN_SURFACES if reading.openness == "open" else CLOSED_SURFACES
        surfaces, basis = [s for s in group if s in spec.surfaces], "openness"
    wanted: list[str] = []
    for s in surfaces:
        for x in (s, *SURFACE_GROUPS.get(s, ())):
            if x not in wanted:
                wanted.append(x)
    sr = search.search(ExploratoryQuery(surface=wanted[0], surface_any=tuple(wanted)))
    codes = [m["belt_code"] for m in sr.get("matches") or []]
    total = len(cat.products)
    if not codes:
        return None, f"ไม่มีรุ่นที่ผิว {wanted} — ทางเดิม"
    if len(codes) >= total:
        return None, f"ผิว {wanted} ตรงทุกรุ่น ไม่ช่วยคัด — ทางเดิม"

    pitches = {c: _pitch(cat, c) for c in codes}
    if reading.pitch_mm is not None:
        far = 1e9
        codes = sorted(codes, key=lambda c: abs((pitches[c] if pitches[c] is not None else far) - reading.pitch_mm))
    listed = sorted({p for p in pitches.values() if p is not None})

    names_th = {s["surface_type"]: s.get("surface_type_th") or s["surface_type"]
                for s in cat.data.get("surface_type_vocabulary") or []}
    ctx = {
        "basis": basis,
        "surface_read": surfaces[0] if basis == "surface" else None,
        "surface_read_th": names_th.get(surfaces[0]) if basis == "surface" else None,
        **({"also_possible": surfaces[1:]} if basis == "surface" and len(surfaces) > 1 else {}),
        **({"openness": "มีช่องหรือรูทะลุ" if reading.openness == "open" else "ผิวทึบ"}
           if basis == "openness" else {}),
        "belt_codes_complete": codes,
        "count": len(codes),
        "total_in_catalogue": total,
        **({"pitches_mm_in_list": listed[:MAX_PITCHES_LISTED]} if listed else {}),
        **({"pitch_estimate_mm": reading.pitch_mm} if reading.pitch_mm is not None else {}),
        "note_th": ("ลักษณะผิวนี้ระบบอ่านจากรูป ไม่ใช่การระบุรุ่น รายชื่อนี้คือทุกรุ่นในแคตตาล็อกที่ผิวตรงกับที่เห็น "
                    "รุ่นในรายการเดียวกันหน้าตาคล้ายกันแต่พิทช์ วัสดุ และสเปกต่างกัน"
                    + (" พิทช์ประมาณจากสเกลในรูป ต้องให้ลูกค้ายืนยัน" if reading.pitch_mm is not None else "")),
    }
    why = (f"{basis}: {wanted} → {len(codes)}/{total} รุ่น"
           + (f" · เรียงตามพิทช์ใกล้ {reading.pitch_mm} มม." if reading.pitch_mm is not None else "")
           + f" · conf={reading.confidence} · {reading.ms:.0f} ms")
    return ctx, why
