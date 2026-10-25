"""
core/image_policy.py — รูปเมื่อบางแบรนด์ยังไม่มีตัวให้คะแนนรูป (claude/PLAN_image_brand_ask.md)

ปัญหาเดิม: แบรนด์เดียวที่มีตัวให้คะแนนรูปรับทุกรูป → รูปของแบรนด์ที่ไม่มีตัวให้คะแนนได้คำตอบผิดแบรนด์ 53%
หรือถูกปฏิเสธ 47% (วัดจากรูปหน้างาน 247 ใบ · RESULTS_field_eval.md ข้อ 7)

ทำงานเฉพาะเมื่อมีรูป และมีบางแบรนด์ที่ไม่มีตัวให้คะแนนรูป · ทุกแบรนด์มีตัวให้คะแนน = คืนผลเดิมไม่แตะ

ลำดับ (route = ผลจาก core/image_router ที่ยังไม่แก้)
    1. ไม่ dominant + ประตูทุกตัวบอกว่าไม่ใช่สินค้า     → ปฏิเสธรูป (ข้อความกลาง)         not_product
    2. ข้อความระบุแบรนด์ที่ไม่มีตัวให้คะแนนแบรนด์เดียว   → แบรนด์นั้น รูปไม่ใช้               text_brand
       ข้อความระบุแบรนด์อื่น                           → ผลเดิม                          unchanged
    3. dominant                                       → ผลเดิม (แบรนด์ที่ให้คะแนน)        dominant
    4. ประตูของแบรนด์ที่ไม่มีตัวให้คะแนนบอกว่า "ของเรา" แบรนด์เดียว → แบรนด์นั้น            direct
    5. นอกนั้น                                        → ถามแบรนด์ เก็บผลรูปไว้หนึ่งเทิร์น   ask

ประตู (ImageGate) เป็นของปลั๊กอิน — แกนกลางเห็นแค่ GateReading
ไม่มีประตูเลย (ไฟล์ไม่ครบ/ปิด) → ข้อ 1 และ 4 ไม่ทำงาน · รูปที่แบรนด์ให้คะแนนปฏิเสธก็ถามแบรนด์ก่อน (ไม่เดา)
ไม่ import torch — เทสต์ด้วย python ล้วน
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence

from core.image_router import ImageRoute
from core.protocol import ImageScore


@dataclass
class GateReading:
    brand: str                    # แบรนด์เจ้าของประตู
    product_like: bool            # หน้าตาเป็นสินค้าในกลุ่มนี้ (สายพาน/โซ่/สเตอร์) หรือไม่
    direct: bool                  # มั่นใจพอให้ไปแบรนด์นี้โดยไม่ต้องถาม
    detail: dict = field(default_factory=dict)   # ตัวเลขลง debug


class ImageGate(Protocol):
    brand: str

    def read(self, image: Any) -> GateReading: ...


@dataclass
class ImageCarry:
    """ผลรูปของเทิร์นที่ถามแบรนด์ — ใช้ในเทิร์นถัดไปเทิร์นเดียว"""
    image: Any
    best: Optional[ImageScore]
    rejected: bool


@dataclass
class PolicyResult:
    route: ImageRoute
    kind: str                     # not_product · text_brand · unchanged · dominant · direct · ask · off
    reason: str = ""
    original: Optional[ImageRoute] = None

    @property
    def asks_brand(self) -> bool:
        return self.kind == "ask"


def resolve(route: ImageRoute, brands: Sequence[str], scored: Sequence[str],
            readings: dict, text_strong: Sequence[str]) -> PolicyResult:
    """brands = ทุกแบรนด์ตาม info.order · scored = แบรนด์ที่มีตัวให้คะแนนรูป
    readings = {brand: GateReading} · text_strong = แบรนด์ที่ข้อความเทิร์นนี้ให้สัญญาณ strong"""
    unscored = [b for b in brands if b not in scored]
    if not unscored:
        return PolicyResult(route, "off", "ทุกแบรนด์มีตัวให้คะแนนรูป")
    best = route.best
    dominant = bool(best is not None and best.accepted and best.dominant and not route.rejected)

    if readings and not dominant and not any(r.product_like for r in readings.values()):
        why = " · ".join(f"{r.brand} {_fmt(r.detail)}" for r in readings.values())
        return PolicyResult(ImageRoute(True, [], None, route.scores), "not_product",
                            f"ประตูรูปบอกว่าไม่ใช่สินค้า ({why})", route)

    strong = [b for b in text_strong if b in brands]
    if strong:
        if len(strong) == 1 and strong[0] in unscored:
            return PolicyResult(ImageRoute(False, [], None, route.scores), "text_brand",
                                f"ข้อความระบุ {strong[0]} → ไม่ใช้รูป", route)
        return PolicyResult(route, "unchanged", "ข้อความระบุแบรนด์ที่มีตัวให้คะแนนรูป", route)

    if dominant:
        return PolicyResult(route, "dominant", f"{best.brand} dominant {best.confidence:.2f}", route)

    direct = [b for b in unscored if b in readings and readings[b].direct]
    if len(direct) == 1:
        b = direct[0]
        return PolicyResult(ImageRoute(False, [b], None, route.scores), "direct",
                            f"ประตู {b} มั่นใจ ({_fmt(readings[b].detail)})", route)

    every = [b for b in brands]
    return PolicyResult(ImageRoute(False, every, route.best, route.scores), "ask",
                        "รูปไม่ระบุแบรนด์ → ถามแบรนด์", route)


def _fmt(detail: dict) -> str:
    return ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in detail.items())
