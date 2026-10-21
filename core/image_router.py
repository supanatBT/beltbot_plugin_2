"""
core/image_router.py — รูปนี้เป็นของแบรนด์ไหน (HANDOFF ข้อ 4)

ทุกแบรนด์ที่เปิดรูป (brand.yaml › image + collection มีข้อมูล) ให้คะแนน แล้วเทียบกัน
    ไม่มีแบรนด์ไหนรับ          → ปฏิเสธรูป
    รับแบรนด์เดียว             → แบรนด์นั้น
    รับหลายแบรนด์ ห่างกันพอ    → แบรนด์ที่มั่นใจสุด
    รับหลายแบรนด์ สูสี         → ส่งทุกแบรนด์ที่สูสีเป็น image_brands → core/router ถามกลับ (ห้ามเดา)
ห้ามอนุมานเกรดวัสดุหรือสภาวะเปียก/แห้งจากรูป — ImageScore ไม่มีช่องให้ใส่
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.protocol import ImageScore

TIE_MARGIN = 0.05        # ต่างกันน้อยกว่านี้ถือว่าสูสี


@dataclass
class ImageRoute:
    rejected: bool
    image_brands: list = field(default_factory=list)   # แบรนด์ที่รูปอาจเป็นของมัน
    best: Optional[ImageScore] = None                    # ส่งเข้า decide (ช่อง image)
    scores: dict = field(default_factory=dict)


def route_image(scorers: dict, image: Any, text: str, tie_margin: float = TIE_MARGIN) -> ImageRoute:
    scores = {k: s.score(image, text) for k, s in scorers.items()}
    if not scores:
        return ImageRoute(True, [], None, scores)
    accepted = sorted((sc for sc in scores.values() if sc.accepted), key=lambda s: -s.confidence)
    if not accepted:
        # แบรนด์เดียว: ส่งคะแนนของมันไปด้วย (ข้อความปฏิเสธและเหตุผลมาจากแบรนด์นั้น)
        only = next(iter(scores.values())) if len(scores) == 1 else None
        return ImageRoute(True, list(scores) if only else [], only, scores)
    top = accepted[0]
    close = [s for s in accepted if top.confidence - s.confidence < tie_margin]
    return ImageRoute(False, [s.brand for s in close], top, scores)
