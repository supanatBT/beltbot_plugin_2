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
    3a. dominant แต่ประตูของแบรนด์ที่ไม่มีตัวให้คะแนนก็มั่นใจ (direct) → ถามแบรนด์           conflict
        (ผู้ใช้เลือก 28 ต.ค. · ทดสอบรูปรอบ ① F03: ViT 0.851 dominant + ประตู 0.861 direct → บอทตอบซีรีส์ผิดแบรนด์
         สองฝั่งชี้คนละแบรนด์ = ไม่เดา · brand_calibration_rows: รูปของแบรนด์ที่ให้คะแนนไม่มีใบไหนผ่าน direct
         ทั้ง cal 0/49 · eval 0/57 → ไม่มีลูกค้าแบรนด์นั้นโดนถามเพิ่มในชุดวัด)
    4. ประตูของแบรนด์ที่ไม่มีตัวให้คะแนนบอกว่า "ของเรา" แบรนด์เดียว → แบรนด์นั้น            direct
    4a. แชตคุยแบรนด์ที่ไม่มีตัวให้คะแนนอยู่ + ประตูของมันบอกว่าเป็นสินค้า → แบรนด์นั้น        context
        (ผู้ใช้เลือก 27 ต.ค. เคส R5: คุย MP80 C ค้างคำถามเปียก/แห้ง ส่งรูปสายพาน → เดิมถามสองแบรนด์ คำถามค้างหาย)
    4b. ไม่มีตัวให้คะแนนตัวไหนระบุกลุ่มได้ + ประตูบอกว่าเป็นสินค้าแบรนด์เดียว → ถามยืนยันแบรนด์นั้น  confirm
        ("ใช่ไหม" แทนเมนูสองแบรนด์ · ตอบไม่ใช่ = แบรนด์ที่เหลือพร้อมผลรูปเดิม)
        ⚠ ยังไม่ได้วัดว่ารูปของแบรนด์ที่มีตัวให้คะแนนโดนปฏิเสธบ่อยแค่ไหน (ลูกค้าแบรนด์นั้นจะถูกถามผิดหนึ่งครั้ง)
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
    kind: str                     # not_product · text_brand · unchanged · dominant · conflict · direct · context · confirm · ask · off
    reason: str = ""
    original: Optional[ImageRoute] = None
    confirm: Optional[str] = None  # kind == confirm: แบรนด์ที่จะถามว่า "ใช่ไหม"
    readings: dict = field(default_factory=dict)   # GateReading ต่อแบรนด์ — ไว้ลง log ทดสอบรูป (core/turn IMGLOG)

    @property
    def asks_brand(self) -> bool:
        return self.kind in ("ask", "confirm", "conflict")


def resolve(route: ImageRoute, brands: Sequence[str], scored: Sequence[str],
            readings: dict, text_strong: Sequence[str], context_brand: Optional[str] = None) -> PolicyResult:
    """brands = ทุกแบรนด์ตาม info.order · scored = แบรนด์ที่มีตัวให้คะแนนรูป
    readings = {brand: GateReading} · text_strong = แบรนด์ที่ข้อความเทิร์นนี้ให้สัญญาณ strong
    context_brand = แบรนด์ที่แชตคุยอยู่ก่อนเทิร์นนี้ (None = ยังไม่รู้)"""
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
        clash = [b for b in unscored if b in readings and readings[b].direct]
        if clash:
            every = [b for b in brands]
            why = " · ".join(f"{b} {_fmt(readings[b].detail)}" for b in clash)
            return PolicyResult(ImageRoute(False, every, route.best, route.scores), "conflict",
                                f"{best.brand} dominant {best.confidence:.2f} แต่ประตู {why} มั่นใจด้วย → ถามแบรนด์",
                                route)
        return PolicyResult(route, "dominant", f"{best.brand} dominant {best.confidence:.2f}", route)

    direct = [b for b in unscored if b in readings and readings[b].direct]
    if len(direct) == 1:
        b = direct[0]
        return PolicyResult(ImageRoute(False, [b], None, route.scores), "direct",
                            f"ประตู {b} มั่นใจ ({_fmt(readings[b].detail)})", route)

    if context_brand in unscored and context_brand in readings and readings[context_brand].product_like:
        b = context_brand
        return PolicyResult(ImageRoute(False, [b], None, route.scores), "context",
                            f"แชตคุย {b} อยู่ + ประตูบอกว่าเป็นสินค้า ({_fmt(readings[b].detail)})", route)

    # "ตัวให้คะแนนไม่รับ" = ไม่มีตัวไหนระบุกลุ่ม/ซีรีส์ได้ (ViT ต่ำกว่าเกณฑ์กลุ่ม) — ไม่ใช่ accepted
    # accepted ของบางแบรนด์แปลว่า "ระบบค้นเจอสินค้าอะไรสักอย่าง" ซึ่งเกือบ true เสมอ (log 27 ต.ค.:
    # conf 0.4257 · group ว่าง · accepted true) → เดิมกฎนี้แทบไม่ทำงาน ไหลไปถามสองแบรนด์แทน
    like = [b for b in unscored if b in readings and readings[b].product_like]
    if len(like) == 1 and not any(_believed(sc) for sc in route.scores.values()):
        b = like[0]
        return PolicyResult(ImageRoute(False, [b], None, route.scores), "confirm",
                            f"ตัวให้คะแนนไม่รับ + ประตู {b} บอกว่าเป็นสินค้า → ถามยืนยัน {b}", route, confirm=b)

    every = [b for b in brands]
    return PolicyResult(ImageRoute(False, every, route.best, route.scores), "ask",
                        "รูปไม่ระบุแบรนด์ → ถามแบรนด์", route)


def _believed(sc: ImageScore) -> bool:
    """ตัวให้คะแนนเชื่อว่ารูปเป็นของแบรนด์ตัวเอง — ระบุกลุ่มได้ หรือ dominant"""
    return bool(sc.accepted and (sc.group or sc.dominant))


def _fmt(detail: dict) -> str:
    return ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in detail.items())
