"""
brands/movex/search.py — ค้นสินค้า Movex ทั้งฐาน (23 รายการ) ตามเงื่อนไข ด้วยโค้ดล้วน (30 ต.ค.)

ใช้กับผลของตัวตีความคำถาม (core/query_interpreter) ในจุดที่เดิมระบบถาม "ขอทราบรุ่นก่อน"
(probe_movex_r1 MXT-U1–U3: "Movex รุ่นไหนรับโหลดสูงสุด" · "กว้างไม่เกิน 100 มม." · "มีกี่รุ่น" ไปไม่ถึงคำตอบ)

ไม่แตะ Qdrant / retriever_v4 — อ่าน extracted_data (product_db) ตรง ๆ จึงทดสอบได้โดยไม่มีโมเดล
ค่าที่ไม่มีในรายการ (เช่น รัศมีเลี้ยวของ 880/882 อยู่ในข้อความ ไม่อยู่ในช่องตัวเลข) = ไม่นับ และบอกใน note
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from core.query_interpreter import QueryField, QuerySpec

# ช่อง → (ชื่อช่องในข้อมูล ตามลำดับที่ลอง, หน่วย)
FIELDS = {
    "width":  (("Plate_Width_mm",), "มม."),
    "load":   (("Max_Working_Load_N",), "N"),
    "weight": (("Weight_kg_m",), "kg/m"),
    "radius": (("Min_curve_radius_mm", "Radius_min_mm"), "มม."),
    "teeth":  (("Z_Teeth",), "ฟัน"),
    "bore":   (("Bore_mm",), "มม."),
}
RANK_TOP = 5


def _value(p: dict, fld: str) -> Optional[float]:
    for k in FIELDS[fld][0]:
        v = p.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


class MovexSearch:
    def __init__(self, products: dict):
        self.mx = products
        self.types = sorted({p.get("product_type") for p in products.values() if p.get("product_type")})
        self.series = sorted({p.get("series") for p in products.values() if p.get("series")})

    def spec(self) -> QuerySpec:
        return QuerySpec(
            brand_th="โซ่ท็อปเชน Movex",
            fields={"width": QueryField("ความกว้างหน้าโซ่ หน่วย มม.", 10, 1000),
                    "load": QueryField("แรงดึง/โหลดใช้งานสูงสุด หน่วย N", 10, 100_000),
                    "weight": QueryField("น้ำหนักโซ่ หน่วย kg/m", 0.05, 50),
                    "radius": QueryField("รัศมีเลี้ยวต่ำสุด หน่วย มม.", 10, 5000),
                    "teeth": QueryField("จำนวนฟันสเตอร์", 3, 100, allow_eq=True),
                    "bore": QueryField("ขนาดรูเพลาสเตอร์ หน่วย มม.", 3, 300, allow_eq=True)},
            enums={"product_type": self.types, "series": self.series},
            enum_desc_th={"product_type": "ชนิดสินค้า (Sideflexing = เลี้ยวได้ · Straight Running = วิ่งตรง)",
                          "series": "ซีรีส์"},
            notes_th="ความกว้างของโซ่ Movex เป็นช่องค้นได้ (width) ให้ใช้ field แทน mentions_width")

    def search(self, field: Optional[str] = None, op: Optional[str] = None, value: Optional[float] = None,
               rank: Optional[str] = None, product_type: Optional[str] = None,
               series: Optional[str] = None, overview: bool = False) -> dict:
        pool = {pid: p for pid, p in self.mx.items()
                if (not product_type or p.get("product_type") == product_type)
                and (not series or p.get("series") == series)}
        if overview:
            return {"query": {"overview": True, "product_type": product_type, "series": series},
                    "scanned": len(self.mx), "matched": len(pool),
                    "overview": {"total": len(pool),
                                 "by_type": dict(Counter(p.get("product_type") for p in pool.values()).most_common()),
                                 "by_series": dict(Counter(p.get("series") for p in pool.values()).most_common())},
                    "matches": [], "note_th": f"นับจากฐานข้อมูล Movex ทั้ง {len(self.mx)} รายการ ตัวเลขนี้สมบูรณ์"}
        rows, missing = [], 0
        for pid, p in pool.items():
            v = _value(p, field) if field else None
            if field and v is None:
                missing += 1
                continue
            if field and not rank and value is not None:
                ok = (v >= value if op == ">=" else v <= value if op == "<=" else abs(v - value) < 1e-6)
                if not ok:
                    continue
            rows.append({"product_id": pid, "ref": p.get("Ref") or p.get("Art_Nr") or pid,
                         "product_type": p.get("product_type"), "series": p.get("series"),
                         **({"value": v} if field else {})})
        matched = len(rows)
        if field:
            rows.sort(key=lambda r: r["value"], reverse=(rank == "max" or (not rank and op == ">=")))
        if rank:
            best = rows[0]["value"] if rows else None
            top = [r for r in rows if r["value"] == best]           # ค่าเท่ากันหลายรุ่น = อันดับ 1 ร่วม
            rows = rows[:max(RANK_TOP, len(top))]
        unit = FIELDS[field][1] if field else ""
        note = f"ค้นครบทั้ง {len(self.mx)} รายการในฐานข้อมูล Movex ผลนี้สมบูรณ์"
        if rank:
            note += f" · เรียง{'มากไปน้อย' if rank == 'max' else 'น้อยไปมาก'} แสดง {len(rows)} อันดับแรก (หน่วย {unit})"
        if missing:
            note += f" · {missing} รายการไม่มีค่าช่องนี้ในข้อมูล จึงไม่ได้นับ"
        if not rows:
            note += " · ไม่มีรายการที่ตรงเงื่อนไขจริง"
        return {"query": {"field": field, "op": op, "value": value, "rank": rank,
                          "product_type": product_type, "series": series},
                "scanned": len(self.mx), "matched": matched, "matches": rows, "note_th": note}
