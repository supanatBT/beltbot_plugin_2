"""
core/router.py
==============
เลือกแบรนด์จาก N ตัว — แกนกลางเห็นแค่ BrandSignal ของแต่ละแบรนด์ ไม่รู้ว่าสัญญาณมาจากอะไร

ลำดับ (จากแข็งไปอ่อน) — เท่ากับของเดิมเมื่อมีสองแบรนด์
    strong มากกว่าหนึ่งแบรนด์    → ชนกัน ถามกลับ ห้ามเดา              conflict_strong
    strong แบรนด์เดียว           → แบรนด์นั้น                           strong
    weak มากกว่าหนึ่งแบรนด์      → ไม่ตัดสิน (ใช้แบรนด์เทิร์นก่อน ถ้ามี) conflict_weak
    weak แบรนด์เดียว             → แบรนด์นั้น                           weak
    ไม่มีสัญญาณ                  → แบรนด์ของเทิร์นก่อน                  previous
    ไม่มีอะไรเลย                 → ไม่รู้                                none

รูปภาพ: ถ้ามีรูป แบรนด์ใน image_brands นับเป็น strong (หลักฐาน "รูปภาพ")
ผู้เรียกเป็นคนตัดสินว่ารูปนี้ของแบรนด์ไหนได้บ้าง (ImageRouter) — ถ้ามีแบรนด์เดียวที่รับรูป
ก็คือแบรนด์นั้น ซึ่งตรงกับกฎเดิม "รูปเป็นของแบรนด์ที่มีโมเดลรูป"

ข้อความถามกลับสร้างจาก BrandInfo (brand.yaml) ด้วย core/templates.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

from core.protocol import BrandSignal

RouteKind = Literal["conflict_strong", "strong", "conflict_weak", "weak", "previous", "none"]
IMAGE_EVIDENCE = "รูปภาพ"


@dataclass
class RouteResult:
    brand: Optional[str]
    kind: RouteKind
    conflict: list = field(default_factory=list)      # key ที่ชนกัน (เรียงตาม order)
    evidence: dict = field(default_factory=dict)      # key → หลักฐานของแบรนด์ที่ถูกนับ
    signals: dict = field(default_factory=dict)       # key → BrandSignal (หลังรวมรูปแล้ว)

    @property
    def need_clarify(self) -> bool:
        return self.kind == "conflict_strong"


def apply_image(signals: dict[str, BrandSignal], has_image: bool,
                image_brands: Sequence[str]) -> dict[str, BrandSignal]:
    """คืนสำเนาที่ยกแบรนด์ซึ่งรับรูปเป็น strong เมื่อมีรูป (ไม่แก้ของที่ส่งมา)"""
    out = {}
    for key, sig in signals.items():
        if has_image and key in image_brands and sig.strength != "strong":
            out[key] = BrandSignal("strong", IMAGE_EVIDENCE, sig.has_code, sig.parsed)
        else:
            out[key] = sig
    return out


def choose(signals: dict[str, BrandSignal], prev_brand: Optional[str] = None,
           has_image: bool = False, image_brands: Sequence[str] = ()) -> RouteResult:
    """signals ต้องเรียงตาม info.order (ลำดับนี้คือลำดับในข้อความถามกลับ)"""
    sig = apply_image(signals, has_image, image_brands)
    strong = [k for k, s in sig.items() if s.strength == "strong"]
    weak = [k for k, s in sig.items() if s.strength == "weak"]

    if len(strong) > 1:
        return RouteResult(None, "conflict_strong", strong, {k: sig[k].evidence for k in strong}, sig)
    if strong:
        k = strong[0]
        return RouteResult(k, "strong", [], {k: sig[k].evidence}, sig)
    if len(weak) > 1:
        return RouteResult(None, "conflict_weak", weak, {k: sig[k].evidence for k in weak}, sig)
    if weak:
        k = weak[0]
        return RouteResult(k, "weak", [], {k: sig[k].evidence}, sig)
    if prev_brand:
        return RouteResult(prev_brand, "previous", [], {}, sig)
    return RouteResult(None, "none", [], {}, sig)
