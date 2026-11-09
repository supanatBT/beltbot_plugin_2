"""
core/query_interpreter.py — ให้ LLM ตีความ "คำถามหารุ่น" ของลูกค้าเป็นโครงสร้าง แล้วให้โค้ดค้นเอง (30 ต.ค.)

คู่กับ core/answer_interpreter.py (ตีความคำตอบต่อคำถามที่บอทถาม) · หลักเดียวกัน:
แยก "เข้าใจ" ออกจาก "ตัดสิน" (Bocklisch et al. 2024 · Rasa CALM · arXiv 2402.12234)
    LLM แปลงข้อความเป็นโครงสร้างอย่างเดียว — ไม่ตอบลูกค้า ไม่เลือกรุ่น ไม่เติมตัวเลขที่ลูกค้าไม่ได้พูด
    โค้ดตรวจโครงสร้าง (ชื่อช่อง · ช่วงค่า · ค่าที่อนุญาต) แล้วค้นด้วยโค้ดของแบรนด์เอง

ที่มา: probe_tools (30 ต.ค.) — กฎ regex จับรูปประโยคได้จำกัด ("รูเยอะ ระบายน้ำดี" · "<แบรนด์> รุ่นไหนรับโหลดสูงสุด")
    คำถามที่กฎไม่รู้จักตกไปทางถามงาน/ถามรุ่น/ค้นเวกเตอร์ 5 รุ่น · tool ของ LLM ช่วยได้บางครั้ง (เรียกหรือไม่ก็ได้)

ขอบเขต: เรียกเฉพาะจุดที่ระบบต้องเดา (แบรนด์เป็นคนเลือกจุด) · ไม่ใช่ทุกเทิร์น
ทางสำรอง: เรียกไม่ได้ · JSON เสีย · ผ่านการตรวจไม่ได้ → None ผู้เรียกใช้ทางเดิม (พฤติกรรมเท่าก่อนมีตัวนี้)
ไม่รู้จักข้อมูลของแบรนด์ — แบรนด์ส่ง QuerySpec (ช่องที่ค้นได้ · ค่าที่อนุญาต) มาเอง
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field as dc_field
from typing import Callable, Optional

INTENTS = ("search", "overview", "need_help", "other")
OPS = (">=", "<=", "==")
RANKS = ("max", "min")


@dataclass
class QueryField:
    desc_th: str                 # ให้ LLM อ่าน เช่น "แรงดึงของสายพาน (N/m)"
    lo: float                    # ช่วงค่าที่รับได้ — นอกช่วง = ไม่เชื่อ
    hi: float
    allow_eq: bool = False       # "==" ใช้ได้กับช่องนี้ (เช่น พิทช์ที่ต้องการ)


@dataclass
class QuerySpec:
    brand_th: str                                   # ชื่อสินค้าของแบรนด์ เช่น "สายพานโมดูลาร์ ..."
    fields: dict[str, QueryField]                   # ช่องตัวเลขที่ค้นได้
    enums: dict[str, list[str]] = dc_field(default_factory=dict)   # ตัวกรองแบบเลือกค่า (ค่าตามฐานข้อมูล)
    enum_desc_th: dict[str, str] = dc_field(default_factory=dict)
    notes_th: str = ""                              # กฎเฉพาะแบรนด์ (เช่น อุณหภูมิไม่ค้นที่นี่)


@dataclass
class QueryReading:
    intent: str
    field: Optional[str] = None
    op: Optional[str] = None
    value: Optional[float] = None
    rank: Optional[str] = None
    filters: dict = dc_field(default_factory=dict)
    mentions_temperature: bool = False
    mentions_width: bool = False
    note: str = ""
    raw: dict = dc_field(default_factory=dict)
    ms: float = 0.0

    def is_search(self) -> bool:
        return self.intent == "search" and bool(
            (self.field and (self.rank or self.value is not None)) or self.filters)


SYSTEM_TH = """คุณคือตัวแปลงคำถามของลูกค้าเป็น JSON สำหรับระบบขาย{brand} ไม่ต้องตอบลูกค้า
คืน JSON เท่านั้น รูปแบบ:
{{"intent": "...", "field": "...หรือ null", "op": ">=" | "<=" | "==" | null, "value": ตัวเลขหรือ null,
 "rank": "max" | "min" | null, "filters": {{{filter_keys}}},
 "mentions_temperature": true/false, "mentions_width": true/false, "note": "สั้น ๆ"}}

intent:
- "search"    ลูกค้าต้องการหารุ่นตามคุณสมบัติที่วัดได้หรือตามประเภท (มากกว่า/น้อยกว่า/สูงสุด/ต่ำสุด/ชนิด/วัสดุ)
- "overview"  ลูกค้าถามภาพรวม เช่น มีกี่รุ่น มีอะไรบ้าง
- "need_help" ลูกค้าเล่างานหรือการใช้งาน (ลำเลียงอะไร อุตสาหกรรมไหน) โดยไม่ได้ให้เกณฑ์ที่วัดได้
- "other"     อย่างอื่น

field (ช่องตัวเลข ใช้ได้เฉพาะชื่อในรายการนี้):
{fields}

filters (ใส่เฉพาะที่ลูกค้าพูดถึง ค่าต้องอยู่ในรายการเท่านั้น ไม่พูดถึง = null):
{enums}

กฎ:
- ห้ามเดาตัวเลขที่ลูกค้าไม่ได้พูด · "ห้าหมื่น" = 50000 · "5 พัน" = 5000 · "ครึ่งนิ้ว" = 12.7 มม. · "1 นิ้ว" = 25.4 มม.
- "ไม่ต่ำกว่า/อย่างน้อย/ขึ้นไป/เกิน" = ">=" · "ไม่เกิน/ไม่มากกว่า/ต่ำกว่า/น้อยกว่า" = "<="
- ถามหาค่าที่ดีที่สุด (สูงสุด แข็งแรงที่สุด เบาที่สุด รูเยอะสุด) = ใส่ rank และ value = null
- คำบรรยายเชิงคุณภาพให้แปลงเป็นช่องที่ตรงที่สุด เช่น "รูเยอะ ระบายน้ำดี" = ช่องพื้นที่เปิด rank max · "เบา ๆ" = น้ำหนัก rank min
- ถ้าเลือกช่องที่ตรงไม่ได้ ให้ field = null
- mentions_temperature: คำถามพูดถึงอุณหภูมิ ร้อน เย็น แช่แข็ง องศา · mentions_width: พูดถึงความกว้างหรือหน้ากว้างของสายพาน/โซ่
{notes}"""


# ── ด่านก่อนเรียก LLM: ต้องดูเป็น "คำถามหารุ่นตามคุณสมบัติ" ก่อน (กันค่าใช้จ่ายและการตีความคำถามต่อเนื่องผิด) ──
# conv_leaks (จำลอง 30 ต.ค.): ไม่มีด่านนี้ "ตัวแรกพิทช์เท่าไหร่" · "สองตัวนี้ต่างกันยังไง" · "รุ่นไหนดี" ก็ถูกส่งไปตีความ
_SUPER = r"ที่สุด|สูงสุด|ต่ำสุด|มากสุด|น้อยสุด|เยอะสุด|เบาสุด|หนักสุด|แข็งแรงสุด|กว้างสุด|แคบสุด|ดีที่สุด"
_COMPARE = r"มากกว่า|น้อยกว่า|สูงกว่า|ต่ำกว่า|เกิน|ไม่ถึง|อย่างน้อย|ขึ้นไป|ลงไป|>=|<=|>|<"
_COUNT = r"กี่รุ่น|กี่แบบ|กี่ชนิด|กี่ตัว|กี่รายการ|ทั้งหมดกี่|how many"
_PROPERTY = (r"แรงดึง|แข็งแรง|รับโหลด|โหลด|รับแรง|ทนแรง|เบา|น้ำหนัก|ช่องเปิด|พื้นที่เปิด|รูเยอะ|รู|ระบาย|กว้าง|แคบ|"
             r"พิทช์|pitch|วัสดุ|POM|PP|PE|สแตนเลส|สลัก|พิน|ผิว|กันลื่น|เลี้ยว|โค้ง|ฟัน|รูเพลา|strength|weight|load")
_ASKS = r"ไหม|มั้ย|หรือเปล่า|บ้าง|รุ่นไหน|ตัวไหน|อันไหน|มีรุ่น|หา|อยากได้|ต้องการ|ขอ|which"
_REFERS = r"ตัวแรก|ตัวที่\s*\d|ตัวที่สอง|สองตัว|ตัวนี้|รุ่นนี้|อันนี้|ตัวนั้น|รุ่นนั้น|อันนั้น|ตัวเมื่อกี้|ที่บอกมา"


def looks_like_search(text: str) -> bool:
    """คำถามหารุ่นตามคุณสมบัติ (ขั้นสุด · เปรียบเทียบตัวเลข · นับ · คุณสมบัติ + คำถาม) และไม่ได้อ้างรุ่นที่คุยอยู่"""
    t = text or ""
    if re.search(_REFERS, t):
        return False
    if re.search(_SUPER + "|" + _COUNT, t, re.IGNORECASE):
        return True
    has_prop = re.search(_PROPERTY, t, re.IGNORECASE) is not None
    return has_prop and (re.search(_COMPARE, t) is not None or re.search(_ASKS, t, re.IGNORECASE) is not None)


class QueryInterpreter:
    """complete(system, user, json_mode=True, temperature=0) -> str  (core/llm.py GeminiClient/GenAIClient.complete)"""

    def __init__(self, complete: Callable[..., str], log: Optional[Callable[[str], None]] = None):
        self.complete = complete
        self.log = log or (lambda m: None)
        self.calls = self.failures = 0
        self.total_ms = 0.0

    def interpret(self, text: str, spec: QuerySpec) -> Optional[QueryReading]:
        if not (text or "").strip():
            return None
        t0 = time.perf_counter()
        self.calls += 1
        try:
            out = self.complete(build_system(spec), f"คำถามของลูกค้า: {text.strip()}", json_mode=True, temperature=0)
            reading = parse_query(out, spec)
        except Exception as e:                       # noqa: BLE001 — เรียกไม่ได้ = ทางเดิม
            self.total_ms += (time.perf_counter() - t0) * 1000
            self.failures += 1
            self.log(f"⚠️ ตัวตีความคำถาม: {type(e).__name__}: {e} — ใช้ทางเดิม")
            return None
        self.total_ms += (time.perf_counter() - t0) * 1000
        if reading is None:
            self.failures += 1
            self.log(f"⚠️ ตัวตีความคำถาม: ผลไม่ผ่านการตรวจ ({(out or '')[:120]!r}) — ใช้ทางเดิม")
            return None
        reading.ms = round((time.perf_counter() - t0) * 1000, 1)
        return reading


def build_system(spec: QuerySpec) -> str:
    fields = "\n".join(f"- \"{k}\": {f.desc_th}" + (" (ใช้ \"==\" ได้)" if f.allow_eq else "")
                       for k, f in spec.fields.items())
    enums = "\n".join(f"- \"{k}\": {spec.enum_desc_th.get(k, '')} ค่าที่ใช้ได้ {json.dumps(v, ensure_ascii=False)}"
                      for k, v in spec.enums.items()) or "- (ไม่มี)"
    keys = ", ".join(f"\"{k}\": ...หรือ null" for k in spec.enums)
    return SYSTEM_TH.format(brand=spec.brand_th, fields=fields, enums=enums, filter_keys=keys,
                            notes=("- " + spec.notes_th) if spec.notes_th else "")


def _canon(value, allowed: list[str]) -> Optional[str]:
    """ค่าจาก LLM → ค่าตามฐานข้อมูล (ไม่สนตัวพิมพ์/ช่องว่าง) · ไม่อยู่ในรายการ = None"""
    if not isinstance(value, str):
        return None
    k = re.sub(r"\s+", " ", value).strip().lower()
    for a in allowed:
        if a.lower() == k:
            return a
    return None


def parse_query(text: str, spec: QuerySpec) -> Optional[QueryReading]:
    """ตรวจ JSON จาก LLM — ผิดรูป · intent แปลก · ช่อง/ค่าไม่อยู่ในรายการ · ค่าหลุดช่วง → None หรือทิ้งเฉพาะส่วนนั้น"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("intent") not in INTENTS:
        return None
    r = QueryReading(intent=d["intent"], raw=d, note=str(d.get("note") or "")[:200],
                     mentions_temperature=d.get("mentions_temperature") is True,
                     mentions_width=d.get("mentions_width") is True)

    fld = d.get("field")
    if fld is not None:
        if fld not in spec.fields:
            return None                            # ชื่อช่องที่ไม่มี = LLM ไม่ทำตามรูปแบบ → ไม่เชื่อทั้งก้อน
        r.field = fld
    rank = d.get("rank")
    if rank is not None and rank not in RANKS:
        return None
    op, val = d.get("op"), d.get("value")
    if val is not None:
        try:
            val = float(val)
        except (TypeError, ValueError):
            return None
    if r.field:
        f = spec.fields[r.field]
        if rank:
            r.rank = rank                          # จัดอันดับ — ไม่ใช้ค่า
        elif val is not None:
            if op not in OPS or (op == "==" and not f.allow_eq):
                return None
            if not (f.lo <= val <= f.hi):
                return None                        # ค่าหลุดช่วง = อ่านหน่วยผิด/เดา
            r.op, r.value = op, val
        else:
            r.field = None                         # มีช่องแต่ไม่มีเกณฑ์ = ไม่ใช่การค้น

    filters = d.get("filters") or {}
    if not isinstance(filters, dict):
        return None
    for k, v in filters.items():
        if v is None or k not in spec.enums:
            continue
        c = _canon(v, spec.enums[k])
        if c is None:
            return None                            # ค่านอกรายการ (ผิวปลอม วัสดุปลอม) → ไม่เชื่อ
        r.filters[k] = c
    return r
