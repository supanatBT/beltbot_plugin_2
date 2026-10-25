"""
core/answer_interpreter.py — ให้ LLM ตีความ "คำตอบของลูกค้าต่อคำถามที่บอทเพิ่งถาม" (ผู้ใช้เลือก 25 ต.ค. · ข้อ 1)

ที่มา: แนวทางแยก "เข้าใจ" ออกจาก "ตัดสิน" (Bocklisch et al. 2024 · Rasa CALM · arXiv 2402.12234)
    LLM ทำแค่แปลงข้อความภาษาพูดเป็นโครงสร้าง — ไม่ตอบลูกค้า ไม่เลือกรุ่น ไม่เติมตัวเลขที่ลูกค้าไม่ได้พูด
    โค้ดตรวจโครงสร้างนั้น (ชนิด · ช่วงค่า) แล้วเดินขั้นตอนเดิมทุกอย่าง

ทำไม: กฎ regex ตีความภาษาพูดได้ไม่ครบ ทุกแบบที่กฎไม่รู้จักคือรูรั่วใหม่ (test_conversation_leaks · 25 ต.ค.:
"ไม่ใช่" · "ลบ 35" · "พิทช์คืออะไร" · "ระยะ 50 มิล" ต้องอุดทีละจุด)

ขอบเขต: เฉพาะเทิร์นที่ลูกค้ากำลังตอบคำถามที่บอทถาม (รู้ว่าถามอะไร คาดคำตอบชนิดไหน)
ทางสำรอง: เรียกไม่ได้ · JSON เสีย · ค่าหลุดช่วง → คืน None ผู้เรียกใช้กฎเดิม (พฤติกรรมเท่าก่อนมีตัวนี้)
ไม่รู้จักชื่อแบรนด์ — ผู้เรียกส่งคำถามและชนิดคำตอบที่คาดมา
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

KINDS = ("value", "yes", "no", "unknown", "question", "other")
EXPECT = ("number_mm", "number_c", "yes_no", "wet_dry", "free")

# ช่วงที่รับได้ต่อชนิด — นอกช่วง = ไม่เชื่อ LLM ใช้กฎเดิม
RANGES = {"number_mm": (1.0, 200.0), "number_c": (-80.0, 400.0)}

SYSTEM_TH = """คุณคือตัวแปลงคำตอบของลูกค้าเป็น JSON สำหรับระบบขายสายพาน ไม่ต้องตอบลูกค้า
อ่าน "คำถามของบอท" และ "คำตอบของลูกค้า" แล้วคืน JSON เท่านั้น รูปแบบ:
{"kind": "...", "value": ตัวเลขหรือ null, "unit": "...หรือ null", "wet_or_dry": "wet" | "dry" | null, "note": "สั้น ๆ"}

kind:
- "value"    ลูกค้าให้ค่าตัวเลขที่ถูกถาม (ใส่ value และ unit)
- "yes"      ลูกค้ายืนยันสิ่งที่บอทเสนอ (ใช่ ถูกต้อง ครับ โอเค ตามนั้น)
- "no"       ลูกค้าปฏิเสธสิ่งที่บอทเสนอ โดยไม่ได้บอกค่าใหม่
- "unknown"  ลูกค้าไม่ทราบ ไม่แน่ใจ ข้าม ไม่มีข้อมูล
- "question" ลูกค้าถามกลับ หรือไม่เข้าใจคำถาม (เช่น คืออะไร หมายถึงอะไร วัดยังไง)
- "other"    ลูกค้าพูดเรื่องอื่น เปลี่ยนเรื่อง หรือถามสินค้าอื่น

กฎ:
- ห้ามเดาตัวเลขที่ลูกค้าไม่ได้พูด ถ้าไม่มีตัวเลขในคำตอบ value = null
- unit: "mm" "inch" "c" ตามที่ลูกค้าพูดหรือบริบทของคำถาม (คำถามเรื่องพิทช์ไม่บอกหน่วย = "mm" · เรื่องอุณหภูมิ = "c")
- "ลบ 35" "ติดลบ 35" "-35" = -35 · "ครึ่งนิ้ว" = 0.5 inch · "สองนิ้ว" = 2 inch · "50 มิล" = 50 mm
- ถ้าลูกค้าตอบว่าไม่ใช่และบอกค่าใหม่ในประโยคเดียว ให้ kind = "value"
- wet_or_dry: ใส่เมื่อคำตอบบอกสภาพไลน์ (มีน้ำ ฉีดล้าง ชื้น = wet · แห้ง ไม่โดนน้ำ = dry) ไม่งั้น null
"""


@dataclass
class AnswerReading:
    kind: str
    value: Optional[float] = None
    unit: Optional[str] = None
    wet_or_dry: Optional[str] = None
    note: str = ""
    raw: dict = field(default_factory=dict)
    ms: float = 0.0

    def number(self, expect: str) -> Optional[float]:
        """ค่าในหน่วยที่ผู้เรียกต้องการ (มม. หรือ °C) — แปลงนิ้วเป็นมม. ที่นี่ (ไม่ให้ LLM คำนวณ)"""
        if self.value is None:
            return None
        v = float(self.value)
        if expect == "number_mm" and (self.unit or "").lower() in ("inch", "in", "นิ้ว", '"'):
            v = round(v * 25.4, 2)
        return v


class AnswerInterpreter:
    """complete(system, user, json_mode=True, temperature=0) -> str  (core/llm.py GeminiClient/GenAIClient.complete)"""

    def __init__(self, complete: Callable[..., str], log: Optional[Callable[[str], None]] = None):
        self.complete = complete
        self.log = log or (lambda m: None)
        self.calls = self.failures = 0
        self.total_ms = 0.0          # เวลารวมที่ใช้เรียก LLM (simulate_customers วัดเวลาต่อเทิร์น)

    def interpret(self, question_th: str, answer: str, expect: str) -> Optional[AnswerReading]:
        if expect not in EXPECT or not (answer or "").strip():
            return None
        user = (f"ชนิดคำตอบที่คาด: {expect}\n"
                f"คำถามของบอท: {question_th}\n"
                f"คำตอบของลูกค้า: {answer.strip()}")
        t0 = time.perf_counter()
        self.calls += 1
        try:
            text = self.complete(SYSTEM_TH, user, json_mode=True, temperature=0)
            reading = parse_reading(text, expect)
        except Exception as e:                       # noqa: BLE001 — เรียกไม่ได้ = ใช้กฎเดิม
            self.total_ms += (time.perf_counter() - t0) * 1000
            self.failures += 1
            self.log(f"⚠️ ตัวตีความคำตอบ: {type(e).__name__}: {e} — ใช้กฎเดิม")
            return None
        self.total_ms += (time.perf_counter() - t0) * 1000
        if reading is None:
            self.failures += 1
            self.log(f"⚠️ ตัวตีความคำตอบ: ผลไม่ผ่านการตรวจ ({(text or '')[:120]!r}) — ใช้กฎเดิม")
            return None
        reading.ms = round((time.perf_counter() - t0) * 1000, 1)
        return reading


def parse_reading(text: str, expect: str) -> Optional[AnswerReading]:
    """ตรวจ JSON จาก LLM — ผิดรูป · kind แปลก · ค่าหลุดช่วง → None (ผู้เรียกใช้กฎเดิม)"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("kind") not in KINDS:
        return None
    val = d.get("value")
    if val is not None:
        try:
            val = float(val)
        except (TypeError, ValueError):
            return None
    wd = d.get("wet_or_dry")
    if wd not in (None, "wet", "dry"):
        wd = None
    r = AnswerReading(kind=d["kind"], value=val, unit=d.get("unit"), wet_or_dry=wd,
                      note=str(d.get("note") or "")[:200], raw=d)
    if r.kind == "value":
        if expect in RANGES:
            n = r.number(expect)
            lo, hi = RANGES[expect]
            if n is None or not (lo <= n <= hi):
                return None
        elif expect == "wet_dry" and r.wet_or_dry is None:
            return None
    return r
