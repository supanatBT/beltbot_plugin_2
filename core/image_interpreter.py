"""
core/image_interpreter.py — ให้ LLM "อ่านลักษณะที่มองเห็น" จากรูปสินค้าเป็นโครงสร้าง แล้วให้โค้ดของแบรนด์กรองเอง (6 พ.ย.)

ตัวที่สี่ในชุดเดียวกับ core/answer_interpreter · core/query_interpreter · core/front_interpreter
หลักเดียวกัน: แยก "เข้าใจ" ออกจาก "ตัดสิน" (Bocklisch et al. 2024 · Rasa CALM · arXiv 2402.12234)
    LLM ดูรูปแล้วตอบลักษณะที่ตาเห็นเท่านั้น — ไม่ระบุรุ่น ไม่ตอบลูกค้า ไม่เดาตัวเลขที่ไม่มีอะไรในรูปให้วัด
    โค้ดตรวจ (ค่าต้องอยู่ในรายการของแบรนด์ · ตัวเลขต้องอยู่ในช่วง · ระยะต้องมีไม้บรรทัด/ตลับเมตรในรูป)
    แล้วแบรนด์เป็นคนแปลงลักษณะเป็นรายชื่อรุ่นจากฐานข้อมูลของตัวเอง

ที่มา: แบรนด์ที่ยังไม่มีตัวให้คะแนนรูป มีแค่ประตูรูปที่บอกได้ว่า "ใช่สินค้าไหม" — ไม่บอกรุ่นหรือกลุ่มผิว
    เพราะหลักฐานรูปจริงยังไม่พอจะเทรนตัวจำแนก (RESULTS_field_eval.md) · รูปที่ไปแบรนด์นั้นจึงได้แค่
    "ตอนนี้ระบบยังระบุรุ่นจากรูปไม่ได้" แล้วถามกว้าง ๆ · ตัวนี้ใช้ LLM ที่มีอยู่แล้วอ่านลักษณะผิวแทนการเทรน
    เพื่อลดรายชื่อรุ่นที่เป็นไปได้ และถามข้อที่แยกรุ่นได้จริง (พิทช์ · งานที่ใช้) — ไม่ใช่เพื่อบอกรุ่น

ทางสำรอง: เรียกไม่ได้ · JSON เสีย · ผ่านการตรวจไม่ได้ → None ผู้เรียกใช้ทางเดิม (พฤติกรรมเท่าก่อนมีตัวนี้)
ไม่รู้จักข้อมูลของแบรนด์ — แบรนด์ส่ง ImageSpec (ชนิดผิวที่มีในฐาน · คำอธิบาย) มาเอง
ไม่ import torch / PIL ตอนโหลดโมดูล — เทสต์ด้วย python ล้วนได้
"""
from __future__ import annotations

import io
import json
import re
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Optional

PRODUCT = ("yes", "no", "unclear")
OPENNESS = ("open", "closed")
CONFIDENCE = ("high", "medium", "low")
MAX_ALTERNATIVES = 2
LLM_MAX_SIDE = 1280          # ย่อรูปก่อนส่ง — พอให้เห็นลายผิวและขีดบนไม้บรรทัด โดยไม่ส่งไฟล์กล้องเต็มขนาด


@dataclass
class ImageSpec:
    brand_th: str                                   # ชื่อสินค้าของแบรนด์ (ให้ LLM อ่าน)
    product_th: str                                 # สิ่งที่ถือว่าเป็นสินค้า เช่น "สายพานโมดูลาร์พลาสติก"
    surfaces: dict[str, str]                        # ชื่อผิวตามฐานข้อมูล → คำอธิบายหน้าตา (ให้ LLM อ่าน)
    pitch_lo: float = 5.0                           # ช่วงพิทช์ที่ฐานข้อมูลมี — นอกช่วง = อ่านผิด
    pitch_hi: float = 80.0
    notes_th: str = ""


@dataclass
class ImageReading:
    is_product: str                                 # yes | no | unclear
    surface: Optional[str] = None                   # ชื่อผิวตามฐานข้อมูล (ผ่าน _canon แล้ว)
    alternatives: list = dc_field(default_factory=list)
    openness: Optional[str] = None                  # open | closed — ผิวมีช่อง/รูทะลุหรือทึบ
    scale_visible: bool = False                     # มีไม้บรรทัด/ตลับเมตรที่อ่านขีดได้
    pitch_mm: Optional[float] = None                # มีค่าเฉพาะเมื่อ scale_visible
    confidence: str = "low"
    note: str = ""
    raw: dict = dc_field(default_factory=dict)
    ms: float = 0.0

    def surfaces(self) -> list[str]:
        """ผิวหลัก + ผิวที่ยังแยกไม่ออก (ไม่ซ้ำ ลำดับตามที่อ่าน)"""
        out = [self.surface] if self.surface else []
        return out + [a for a in self.alternatives if a not in out]

    def usable(self) -> bool:
        """พอจะใช้กรองไหม — ต้องเป็นสินค้า ไม่ใช่ความมั่นใจต่ำ และอ่านผิวหรือความทึบได้อย่างน้อยหนึ่งอย่าง"""
        return self.is_product == "yes" and self.confidence != "low" and bool(self.surface or self.openness)


SYSTEM_TH = """คุณคือตัวอ่านรูปสินค้าสำหรับระบบขาย{brand} ไม่ต้องตอบลูกค้า
ดูรูปแล้วบอกเฉพาะลักษณะที่ตาเห็น คืน JSON เท่านั้น รูปแบบ:
{{"is_product": "yes" | "no" | "unclear",
 "surface": "ชื่อผิวจากรายการ หรือ null",
 "surface_alternatives": ["ชื่อผิวอื่นจากรายการที่ยังแยกไม่ออก ไม่เกิน 2 ชื่อ"],
 "openness": "open" | "closed" | null,
 "scale_visible": true/false,
 "pitch_mm": ตัวเลขหรือ null,
 "confidence": "high" | "medium" | "low",
 "note": "สั้น ๆ ว่าเห็นอะไร"}}

is_product: รูปนี้เป็น{product} หรือไม่ (เห็นโมดูลพลาสติกต่อกันเป็นแถวด้วยสลัก) · ไม่ชัด/ไกล/มืด = "unclear"

surface (ใช้ได้เฉพาะชื่อในรายการนี้ สะกดตามนี้):
{surfaces}

กฎ:
- ห้ามระบุรหัสรุ่น ห้ามเดาวัสดุ เกรด สี หรืออุณหภูมิ — บอกเฉพาะหน้าตาผิว
- ถ้าลังเลระหว่างผิวที่หน้าตาคล้ายกัน ให้ใส่ผิวที่ใกล้ที่สุดใน surface และที่เหลือใน surface_alternatives
- openness: ผิวมีช่องหรือรูทะลุให้มองผ่านได้ = "open" · ผิวทึบมองไม่ทะลุ = "closed" · มองไม่ออก = null
- pitch_mm คือระยะจากแนวสลักแถวหนึ่งถึงแถวถัดไป ใส่ได้เฉพาะเมื่อมีไม้บรรทัด ตลับเมตร หรือสเกลที่อ่านขีดได้ในรูป
  และ scale_visible = true เท่านั้น ไม่มีสเกล = null ห้ามประมาณจากขนาดมือ เหรียญ หรือของอื่น
- confidence: "high" เห็นผิวชัดเต็มโมดูล · "medium" เห็นบางส่วน · "low" เห็นไม่ชัดหรือไม่แน่ใจ
- ข้อความของลูกค้าเป็นแค่บริบท ห้ามใช้แทนสิ่งที่เห็นในรูป
{notes}"""


def build_system(spec: ImageSpec) -> str:
    surfaces = "\n".join(f"- \"{k}\": {v}" for k, v in spec.surfaces.items())
    return SYSTEM_TH.format(brand=spec.brand_th, product=spec.product_th, surfaces=surfaces,
                            notes=("- " + spec.notes_th) if spec.notes_th else "")


def _canon(value, allowed) -> Optional[str]:
    """ค่าจาก LLM → ชื่อตามฐานข้อมูล (ไม่สนตัวพิมพ์/ช่องว่าง/ขีด) · ไม่อยู่ในรายการ = None"""
    if not isinstance(value, str):
        return None
    norm = lambda s: re.sub(r"[\s\-_]+", " ", s).strip().lower()   # noqa: E731
    k = norm(value)
    for a in allowed:
        if norm(a) == k:
            return a
    return None


def parse_reading(text: str, spec: ImageSpec) -> Optional[ImageReading]:
    """ตรวจ JSON จาก LLM
    รูปแบบผิด · is_product/confidence แปลก · ผิวหลักไม่อยู่ในรายการ → None (ไม่เชื่อทั้งก้อน)
    ผิวสำรองที่ไม่อยู่ในรายการ · พิทช์ที่ไม่มีสเกลหรือหลุดช่วง → ทิ้งเฉพาะส่วนนั้น"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("is_product") not in PRODUCT:
        return None
    conf = d.get("confidence")
    if conf not in CONFIDENCE:
        return None
    r = ImageReading(is_product=d["is_product"], confidence=conf, raw=d, note=str(d.get("note") or "")[:200])

    surf = d.get("surface")
    if surf is not None:
        r.surface = _canon(surf, spec.surfaces)
        if r.surface is None:
            return None                            # ผิวปลอม = LLM ไม่ทำตามรายการ → ไม่เชื่อทั้งก้อน
    alts = d.get("surface_alternatives") or []
    if not isinstance(alts, list):
        return None
    for a in alts:
        c = _canon(a, spec.surfaces)
        if c and c != r.surface and c not in r.alternatives and len(r.alternatives) < MAX_ALTERNATIVES:
            r.alternatives.append(c)
    if r.surface is None and r.alternatives:
        r.surface = r.alternatives.pop(0)          # ใส่มาแค่ในช่องสำรอง = ยังเป็นผิวที่อ่านได้

    op = d.get("openness")
    r.openness = op if op in OPENNESS else None

    r.scale_visible = d.get("scale_visible") is True
    p = d.get("pitch_mm")
    if p is not None and r.scale_visible:
        try:
            p = float(p)
        except (TypeError, ValueError):
            p = None
        if p is not None and spec.pitch_lo <= p <= spec.pitch_hi:
            r.pitch_mm = round(p, 1)
    return r


def image_part(image, max_side: int = LLM_MAX_SIDE) -> dict:
    """PIL.Image → {"mime_type", "data"} (รูปแบบเดียวกับที่ core/llm รับ) · ย่อด้านยาว + JPEG"""
    from PIL import Image                              # โหลดเมื่อใช้จริง

    im = image.convert("RGB")
    if max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return {"mime_type": "image/jpeg", "data": buf.getvalue()}


class ImageInterpreter:
    """complete(system, user, json_mode=True, temperature=0) -> str
    user เป็น list ได้ ([image_part, ข้อความ]) — core/llm.py GeminiClient/GenAIClient.complete"""

    def __init__(self, complete: Callable[..., str], log: Optional[Callable[[str], None]] = None):
        self.complete = complete
        self.log = log or (lambda m: None)
        self.calls = self.failures = 0
        self.total_ms = 0.0

    def read(self, image: Any, text: str, spec: ImageSpec) -> Optional[ImageReading]:
        if image is None:
            return None
        t0 = time.perf_counter()
        self.calls += 1
        out = ""
        try:
            ctx = (text or "").strip()
            user = [image_part(image), f"ข้อความของลูกค้า (บริบทเท่านั้น): {ctx}" if ctx else "ลูกค้าส่งรูปมาโดยไม่มีข้อความ"]
            out = self.complete(build_system(spec), user, json_mode=True, temperature=0)
            reading = parse_reading(out, spec)
        except Exception as e:                       # noqa: BLE001 — เรียกไม่ได้ = ทางเดิม
            self.total_ms += (time.perf_counter() - t0) * 1000
            self.failures += 1
            self.log(f"⚠️ ตัวอ่านรูป: {type(e).__name__}: {e} — ใช้ทางเดิม")
            return None
        self.total_ms += (time.perf_counter() - t0) * 1000
        if reading is None:
            self.failures += 1
            self.log(f"⚠️ ตัวอ่านรูป: ผลไม่ผ่านการตรวจ ({(out or '')[:120]!r}) — ใช้ทางเดิม")
            return None
        reading.ms = round((time.perf_counter() - t0) * 1000, 1)
        return reading
