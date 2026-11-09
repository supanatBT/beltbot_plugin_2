"""
core/front_interpreter.py — ตัวตีความด่านหน้า (2 พ.ย. 2026 ค่ำ · branch bot-qi-first)

ให้ LLM อ่านคำถามก่อนด่านที่ตัดสินด้วย regex แล้วคืนโครงสร้างสั้น ๆ ให้โค้ดตัดสินต่อ
หลักเดียวกับ query_interpreter / answer_interpreter: LLM "เข้าใจ" · โค้ด "ตัดสิน"
    LLM ไม่ตอบลูกค้า ไม่เลือกรุ่น ไม่เติมค่าที่ลูกค้าไม่ได้พูด
    โค้ดตรวจ JSON (แบรนด์ต้องอยู่ในรายการ · หัวข้อต้องอยู่ในรายการ) ผิดรูป = None → ใช้ทางเดิม (regex)

ใช้ตอบ 3 คำถามที่ regex ตอบผิดบ่อย
    brand            ข้อความนี้เป็นของแบรนด์ไหน (ใช้เมื่อ regex ไม่เจอสัญญาณเลยเท่านั้น)
    asks_temperature ลูกค้าถามเรื่องอุณหภูมิที่ทนได้จริงไหม (ชื่องานอย่าง "สไปรัลฟรีซเซอร์" ไม่ใช่)
    wet_or_dry       ลูกค้าบอกสภาพไลน์มาหรือยัง

เปิดด้วย FRONT_INTERPRETER=llm (ค่าเริ่มต้นปิด = บอทเดิมทุกตัวอักษร)
ที่มาของงานนี้: ชุด blind v1.1 (RESULTS_blind_v1_1.md) — แก้หลังเห็นผล blind จึงรายงานเป็นผล blind ไม่ได้
"""
from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field as dc_field
from typing import Callable, Optional, Sequence

TOPICS = ("temperature", "strength", "width", "material", "pitch", "open_area", "weight",
          "application", "sprocket", "compare", "overview", "price_stock", "other")


@dataclass
class BrandHint:
    key: str
    name: str
    kind_th: str
    hint_th: str          # สัญญาณที่บอกว่าเป็นแบรนด์นี้ (แบรนด์เขียนเอง)


@dataclass
class FrontReading:
    brand: Optional[str] = None
    topic: str = "other"
    asks_temperature: bool = False
    wet_or_dry: Optional[str] = None
    note: str = ""
    raw: dict = dc_field(default_factory=dict)
    ms: float = 0.0


SYSTEM_TH = """คุณคือตัวแปลงข้อความของลูกค้าเป็น JSON สำหรับระบบขายสินค้าลำเลียง ไม่ต้องตอบลูกค้า
ระบบขาย {n} แบรนด์:
{brands}

คืน JSON เท่านั้น:
{{"brand": {brand_keys} | null, "topic": "...", "asks_temperature": true/false,
 "wet_or_dry": "wet" | "dry" | null, "note": "สั้น ๆ ว่าเห็นสัญญาณอะไร"}}

brand — ใส่เมื่อข้อความมีสัญญาณของแบรนด์นั้นชัดเจนเท่านั้น ไม่แน่ใจ = null
- คำว่า "สายพาน" "ลำเลียง" "conveyor" เฉย ๆ ไม่ใช่สัญญาณ ลูกค้าเรียกสินค้าทุกแบรนด์ว่าสายพาน
- คุณสมบัติที่ทุกแบรนด์มี (ระยะพิทช์ ความกว้าง อุณหภูมิ วัสดุ เลี้ยวได้ ราคา) ไม่ใช่สัญญาณด้วยตัวเอง
- ถ้ามีสัญญาณของหลายแบรนด์ หรือไม่มีเลย = null

topic — เรื่องหลักที่ลูกค้าถาม เลือกหนึ่งค่า: {topics}
- "application" = ถามหารุ่นตามงาน อุตสาหกรรม หรือจุดใช้งาน

asks_temperature — true เฉพาะเมื่อลูกค้าถามว่าทนอุณหภูมิได้เท่าไร หรือใช้ที่อุณหภูมิหนึ่งได้ไหม
- ชื่องานหรือชื่อเครื่องที่มีคำว่า ฟรีซ แช่แข็ง เย็น เตาอบ แต่ไม่ได้ถามเรื่องอุณหภูมิ = false
- บอกตัวเลขอุณหภูมิมาเป็นเงื่อนไขให้หารุ่น (เช่น ใช้ที่ -40 องศา มีรุ่นไหน) = true

wet_or_dry — ใส่เมื่อลูกค้าบอกสภาพไลน์เท่านั้น (มีน้ำ ฉีดล้าง ชื้น = wet · แห้ง ไม่โดนน้ำ = dry) ห้ามเดาจากชื่องาน"""


def build_system(brands: Sequence[BrandHint]) -> str:
    lines = "\n".join(f"- \"{b.key}\" = {b.name} ({b.kind_th}) · สัญญาณ: {b.hint_th}" for b in brands)
    keys = " | ".join(f"\"{b.key}\"" for b in brands)
    return SYSTEM_TH.format(n=len(brands), brands=lines, brand_keys=keys, topics=", ".join(TOPICS))


def parse_front(text: str, brand_keys: Sequence[str]) -> Optional[FrontReading]:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    brand = d.get("brand")
    if brand is not None and brand not in brand_keys:
        return None                                   # แบรนด์ที่ไม่มี = ไม่ทำตามรูปแบบ → ไม่เชื่อทั้งก้อน
    topic = d.get("topic")
    if topic not in TOPICS:
        return None
    wd = d.get("wet_or_dry")
    if wd not in ("wet", "dry", None):
        return None
    at = d.get("asks_temperature")
    if not isinstance(at, bool):
        return None
    return FrontReading(brand=brand, topic=topic, asks_temperature=at, wet_or_dry=wd,
                        note=str(d.get("note") or "")[:200], raw=d)


class FrontInterpreter:
    """complete(system, user, json_mode=True, temperature=0) -> str  (core/llm.py)
    จำผลของข้อความเดิมไว้ — ด่านกลางกับปลั๊กอินถามข้อความเดียวกันในเทิร์นเดียว เรียก LLM ครั้งเดียว"""

    CACHE = 64

    def __init__(self, complete: Callable[..., str], brands: Sequence[BrandHint] = (),
                 log: Optional[Callable[[str], None]] = None):
        self.complete = complete
        self.brands = list(brands)
        self.log = log or (lambda m: None)
        self.calls = self.failures = 0
        self._cache: OrderedDict[str, Optional[FrontReading]] = OrderedDict()

    def read(self, text: str) -> Optional[FrontReading]:
        t = (text or "").strip()
        if not t or not self.brands:
            return None
        if t in self._cache:
            self._cache.move_to_end(t)
            return self._cache[t]
        t0 = time.perf_counter()
        self.calls += 1
        try:
            out = self.complete(build_system(self.brands), f"ข้อความของลูกค้า: {t}", json_mode=True, temperature=0)
            r = parse_front(out, [b.key for b in self.brands])
        except Exception as e:                        # noqa: BLE001 — เรียกไม่ได้ = ทางเดิม
            self.failures += 1
            self.log(f"⚠️ ตัวตีความด่านหน้า: {type(e).__name__}: {e} — ใช้ทางเดิม")
            r = None
        else:
            if r is None:
                self.failures += 1
                self.log(f"⚠️ ตัวตีความด่านหน้า: ผลไม่ผ่านการตรวจ ({(out or '')[:120]!r}) — ใช้ทางเดิม")
            else:
                r.ms = round((time.perf_counter() - t0) * 1000, 1)
                self.log(f"🔎 ด่านหน้า: brand={r.brand} topic={r.topic} temp={r.asks_temperature} "
                         f"wet={r.wet_or_dry} · {r.ms:.0f} ms · {r.note}")
        self._cache[t] = r
        while len(self._cache) > self.CACHE:
            self._cache.popitem(last=False)
        return r
