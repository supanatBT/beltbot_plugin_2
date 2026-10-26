"""
brands/modutech/need_flow.py — ถามความต้องการทีละข้อ (25 ต.ค. · ผู้ใช้ทดสอบบนเว็บ)

เดิม: ลูกค้าถามแนะนำรุ่นแบบเปิด ("สายพานนี้รุ่นอะไร") → ได้ข้อความเดียวถามสามเรื่อง
(อุตสาหกรรม · จุดใช้งาน · เปียก/แห้ง+อุณหภูมิ) ผู้ใช้เห็นว่าทำให้ลูกค้าสับสน และขาดเรื่องพิทช์

ใหม่: ถามทีละข้อ ตามลำดับที่ผู้ใช้เลือก   งาน → พิทช์ → อุณหภูมิ → (เปียก/แห้ง เฉพาะตอนจำเป็น)
    · ข้อที่ลูกค้าบอกมาแล้วในข้อความก่อนหน้า ข้ามไป
    · พิทช์/อุณหภูมิ ตอบ "ไม่ทราบ" ได้ = ไม่กรองข้อนั้น
    · เปียก/แห้ง ถามเฉพาะเมื่อผลกรองอุณหภูมิของรุ่นที่เหลือต่างกันระหว่างเปียกกับแห้ง
    · พิทช์กับอุณหภูมิที่ได้ ใช้กรองรุ่นจริงในโค้ด (filter_by_need) ไม่ปล่อยให้ LLM เลือกเอง

ทำงานเฉพาะเมื่อบอทต้องถามงานก่อน (ลูกค้ายังไม่บอกงาน) — คำถามที่บอกงานมาแล้วตอบทันทีเหมือนเดิม
สถานะอยู่ใน slots: _flow (ขั้นที่ถามค้าง) · pitch_mm · temp_c (ตัวเลข หรือ "unknown")
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

UNKNOWN = "unknown"
FLOW_KEY = "_flow"

ASK_NEED_TH = "ขอทราบก่อนครับว่าสายพานนี้จะใช้ลำเลียงอะไร เช่น ชิ้นไก่ ขนมปังเข้าเตาอบ หรือกล่องสินค้า"
ASK_PITCH_TH = ("ต้องการระยะพิทช์ประมาณเท่าไหร่ครับ เช่น 12.7 มม. (½ นิ้ว) 25.4 มม. (1 นิ้ว) หรือ 50.8 มม. (2 นิ้ว) "
                "ถ้ายังไม่ทราบ ตอบว่าไม่ทราบได้เลยครับ")
ASK_TEMP_TH = "ไลน์นี้ใช้งานที่อุณหภูมิประมาณกี่องศาครับ ถ้าไม่แน่ใจ ตอบว่าไม่ทราบได้ครับ"
ASK_WET_TH = ("ไลน์นี้เป็นไลน์เปียก (มีน้ำ หรือฉีดล้างระหว่างใช้งาน) หรือไลน์แห้งครับ "
              "เพราะสายพานเกรดเดียวกันทนอุณหภูมิได้ไม่เท่ากันในสองแบบนี้")

_UNKNOWN_RX = re.compile(r"ไม่ทราบ|ไม่รู้|ไม่แน่ใจ|ไม่ระบุ|ไม่มีข้อมูล|ไม่ได้วัด|แล้วแต่|อะไรก็ได้|ข้าม|"
                         r"\bskip\b|don'?t\s*know|not\s*sure|n/?a\b", re.IGNORECASE)
_NUM = r"(-?\d+(?:[.,]\d+)?)"
_FRACTION_INCH = {"½": 0.5, "ครึ่ง": 0.5, "1/2": 0.5, "¼": 0.25, "1/4": 0.25, "3/4": 0.75, "¾": 0.75,
                  "half": 0.5, "quarter": 0.25}     # main_sim G07: "pitch half inch" (26 ต.ค.)
PITCH_TOL_MM = 0.05           # ตรงพิทช์ (ปัดทศนิยม เช่น 15.2 = 15.24) · 25.4 ไม่นับ 25.7 / 25.8 / 26.0 ซึ่งเป็นคนละพิทช์ ใช้สเตอร์ร่วมกันไม่ได้
PITCH_NEAR_MM = 1.0           # ใกล้เคียง — ไม่เสนอเป็นรุ่นที่ตรง แต่บอกลูกค้าว่ามี (เช่น ตระกูล 254 มีพิทช์ 25.4–26.0)
# ข้อสังเกต (รายงาน ไม่ตัดสินแทน): ชื่อรุ่น "254" ไม่ได้แปลว่าพิทช์ 25.4 เสมอ — EC254 TR พิทช์ 26.0 ·
# EC254 R พิทช์ 25.7 ตามตารางสเปกในเล่ม ลูกค้าที่บอก "1 นิ้ว" อาจหมายถึงตระกูลนี้ทั้งหมด จึงแนบรุ่นใกล้เคียงแยกไว้
ROOM_TEMP_C = 30.0


REJECTED = "rejected"            # ลูกค้าบอกว่าค่าใกล้เคียงที่บอทเสนอ "ไม่ใช่" แต่ไม่บอกค่าใหม่
PITCH_SAID_KEY = "_pitch_said"     # พิทช์ที่ลูกค้าพิมพ์แต่ไม่มีในแคตตาล็อก — รอยืนยันค่าใกล้เคียง
_NO_RX = re.compile(r"ไม่ใช่|ไม่ได้หมายถึง|ไม่เอา|^\s*ไม่\s*(?:ครับ|ค่ะ|คะ)?\s*$|\bno\b|\bnope\b", re.IGNORECASE)
_YES_RX = re.compile(r"ใช่|ถูก|โอเค|ตามนั้น|เอา|ครับ|ค่ะ|คะ|\bok\b|\byes\b|👍", re.IGNORECASE)
_INCH_TH = {12.7: "½ นิ้ว", 25.4: "1 นิ้ว", 38.1: "1½ นิ้ว", 50.8: "2 นิ้ว", 63.5: "2½ นิ้ว"}


def nearest_pitches(cat, said: float, limit: int = 3) -> list[float]:
    """พิทช์ในแคตตาล็อกที่ใกล้ค่าที่ลูกค้าพิมพ์ (≤ PITCH_NEAR_MM) — มีค่าตรงอยู่แล้ว = [] (ไม่ต้องถาม)"""
    vals = pitch_values(cat)
    if any(pitch_matches(v, said) for v in vals):
        return []
    near = sorted((v for v in vals if abs(v - said) <= PITCH_NEAR_MM), key=lambda v: (abs(v - said), v))
    return near[:limit]


def _pitch_label(v: float) -> str:
    inch = _INCH_TH.get(v)
    return f"{v:g} มม. ({inch})" if inch else f"{v:g} มม."


def ask_pitch_confirm_th(said: float, options: list[float]) -> str:
    if len(options) == 1:
        return (f"สายพาน Modutech ไม่มีพิทช์ {said:g} มม. ครับ "
                f"หมายถึง {_pitch_label(options[0])} ไหมครับ")
    opts = ", ".join(_pitch_label(v) for v in options[:-1]) + f" หรือ {_pitch_label(options[-1])}"
    return f"สายพาน Modutech ไม่มีพิทช์ {said:g} มม. ครับ ที่ใกล้ที่สุดคือ {opts} หมายถึงค่าไหนครับ"


def ask_pitch_again_th(options: list[float]) -> str:
    if len(options) == 1:
        head = f"ถ้าไม่ใช่ {_pitch_label(options[0])}"
    else:
        head = "ถ้าไม่ใช่ค่าเหล่านี้"
    return (f"{head} ระยะพิทช์ที่ต้องการคือเท่าไหร่ครับ วัดจากกึ่งกลางพินถึงกึ่งกลางพินถัดไปได้เลย "
            "ถ้าไม่ทราบ ตอบว่าไม่ทราบได้ครับ")


def resolve_pitch_confirm(cat, said: float, answer: str):
    """คำตอบของคำถามยืนยันพิทช์ → ค่าพิทช์ที่ใช้กรอง (ตัวเลข หรือ UNKNOWN)
    ตอบเลขใหม่ = ใช้เลขนั้น · ไม่ทราบ = UNKNOWN · ยืนยัน = ค่าใกล้เคียง (มีตัวเลือกเดียว)
    ปฏิเสธโดยไม่บอกเลข = REJECTED → บอทถามว่าถ้าไม่ใช่แล้วคือเท่าไหร่ (ผู้ใช้ 25 ต.ค.: เดิมใช้ค่าที่พิมพ์ตอนแรก
    แล้วข้ามไปถามอุณหภูมิ ทั้งที่ลูกค้าเพิ่งบอกว่าค่าที่บอทเดาไม่ใช่)
    หลายตัวเลือกแต่ไม่บอกเลข = UNKNOWN (ไม่เดาแทน)"""
    a = answer or ""
    if is_unknown(a):
        return UNKNOWN
    v = parse_pitch(a, bare_number=True)
    if v is not None:
        return v
    if _NO_RX.search(a):
        return REJECTED
    opts = nearest_pitches(cat, said)
    if _YES_RX.search(a) and len(opts) == 1:
        return opts[0]
    return UNKNOWN


_QUESTION_RX = re.compile(r"อะไร|ยังไง|อย่างไร|หมายถึง|หมายความ|คืออะไร|ทำไม|ดูยังไง|วัดยังไง|\?", re.IGNORECASE)

EXPLAIN_TH = {
    "pitch": ("พิทช์คือระยะห่างระหว่างแกนพินของสายพานสองแถวที่ติดกัน วัดจากกึ่งกลางพินถึงกึ่งกลางพินถัดไปครับ "
              "ถ้าใช้สเตอร์เดิมอยู่ ดูได้จากรหัสสเตอร์หรือสายพานเส้นเดิม"),
    "pitch_confirm": "พิทช์คือระยะห่างระหว่างแกนพินของสายพานสองแถวที่ติดกันครับ",
    "pitch_retry": "พิทช์คือระยะห่างระหว่างแกนพินของสายพานสองแถวที่ติดกันครับ",
    "temp": "หมายถึงอุณหภูมิของบริเวณที่สายพานวิ่ง หรือของที่วางบนสายพาน เช่น ห้องเย็น เตาอบ หรืออุณหภูมิห้องครับ",
    "wet": "ไลน์เปียกคือมีน้ำหรือของเหลวโดนสายพานระหว่างใช้งาน หรือฉีดน้ำล้างเป็นประจำครับ",
}


REASK_TH = "ขอโทษครับ ยังไม่แน่ใจว่าหมายถึงอะไร "
SIDE_INFO_TH = "รับทราบครับ "      # ลูกค้าตอบข้ออื่นมาแทน — เก็บไว้แล้ว ถามข้อเดิมต่อ (redteam R13)


def is_question(answer: str) -> bool:
    """ลูกค้าถามกลับแทนการตอบ ("พิทช์คืออะไร") — ต้องอธิบายแล้วถามข้อเดิมอีกรอบ ไม่ใช่นับเป็น "ไม่ทราบ"
    (test_conversation_leaks C03 · 25 ต.ค.)"""
    a = answer or ""
    return bool(_QUESTION_RX.search(a)) and not is_unknown(a) and parse_pitch(a) is None \
        and parse_temp(a) is None


def is_unknown(answer: str) -> bool:
    return bool(_UNKNOWN_RX.search(answer or ""))


def parse_pitch(text: str, bare_number: bool = False) -> Optional[float]:
    """พิทช์เป็นมม. · มีหน่วยนิ้ว/เซนติเมตร → แปลง · bare_number=True (ตอบคำถามพิทช์ตรง ๆ) รับเลขเปล่า = มม."""
    t = (text or "").replace(",", ".")
    # "5 เซน" = 50 มม. (sim4_llm G05 · 26 ต.ค.: เดิมอ่านเป็น 5 มม. → กรองเหลือ 0 รุ่น → LLM เล่าเหตุผลภายในออกมา)
    m = re.search(_NUM + r"\s*(?:เซนติเมตร|เซนต์|เซน|ซม\.?|cm\b)", t, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) * 10, 2)
    # redteam R06 (26 ต.ค.): "0.083 ฟุต" เดิมอ่านเป็น 0.083 มม. → กรองเหลือ 0 รุ่น · แปลงตรง ๆ ไม่ปัด (25.3 → ถามยืนยัน 25.4)
    m = re.search(_NUM + r"\s*(?:ฟุต|feet|foot|ft\b)", t, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) * 304.8, 2)
    for k, v in _FRACTION_INCH.items():
        if re.search(re.escape(k) + r"\s*(?:นิ้ว|inch|in(?![A-Za-z])|\")", t, re.IGNORECASE):
            return round(v * 25.4, 2)
    m = re.search(_NUM + r"\s*(?:นิ้ว|inch|in(?![A-Za-z])|\")", t, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) * 25.4, 2)
    m = re.search(r"(?:พิทช์|พิช|pitch|pich|picth)\D{0,12}" + _NUM, t, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(_NUM + r"\s*(?:มม|mm|มิล)", t, re.IGNORECASE)
    if m:
        return float(m.group(1))
    if bare_number:
        m = re.search(_NUM, t)
        if m:
            return float(m.group(1))
    return None


_PITCH_WORD = re.compile(r"พิทช์|พิทซ์|พิช|pitch|pich|picth", re.IGNORECASE)   # pich: redteam R07 พิมพ์ผิด
_RANGE_RX = re.compile(r"ไม่เกิน|อย่างน้อย|ไม่ต่ำกว่า|ขึ้นไป|มากกว่า|น้อยกว่า|ต่ำกว่า|สูงกว่า|เกินกว่า|ไม่ถึง|"
                       r"[<>≤≥]|at\s*least|at\s*most|minimum|maximum", re.IGNORECASE)


def stated_pitch(text: str) -> Optional[float]:
    """พิทช์ที่ลูกค้าพิมพ์มาเองในข้อความอิสระ (ไม่ใช่คำตอบของคำถามพิทช์)
    ต้องมีคำว่าพิทช์ แล้วอ่านเฉพาะช่วงหลังคำนั้น — กัน "กว้าง 24 นิ้ว" หรือ "120 องศา" ถูกอ่านเป็นพิทช์"""
    m = _PITCH_WORD.search(text or "")
    if not m:
        return None
    seg = (text or "")[m.start():m.start() + 30]
    # "พิทช์ไม่เกิน 10 มม." = ช่วงค้น ไม่ใช่พิทช์ที่ต้องการ (EX-005 · test_core_decide 26 ต.ค.)
    if _RANGE_RX.search(seg):
        return None
    seg = re.sub(r"-?\d+(?:[.,]\d+)?\s*(?:°\s*C|องศา|℃)", " ", seg)
    v = parse_pitch(seg)
    if v is None:
        # "1 inch pitch" / "2 นิ้ว พิทช์" — ค่าอยู่หน้าคำว่าพิทช์ (redteam R18 · 26 ต.ค.: เดิมอ่านไม่ได้ ไม่กรอง
        # LLM เสนอ MD254 GAP48% พิทช์ 25.7 แทนรุ่น 25.4) · ต้องมีหน่วยและติดกับคำว่าพิทช์
        before = re.search(_NUM + r"\s*(?:นิ้ว|inch(?:es)?|in|\"|มม\.?|mm|ซม\.?|cm)\s*$", (text or "")[:m.start()].rstrip(),
                           re.IGNORECASE)
        if before:
            v = parse_pitch(before.group(0))
    return v if v is not None and 1.0 <= v <= 200.0 else None


_F_RX = re.compile(r"(?<![A-Za-z\d.])" + _NUM + r"\s*(?:°\s*F\b|℉|(?:องศา\s*)?ฟาเรนไฮ[ต์ท]์?|(?:degrees?\s*)?fahrenheit|F\b)",
                   re.IGNORECASE)


def parse_fahrenheit(text: str) -> Optional[float]:
    """"176 องศาฟาเรนไฮต์" / "176 °F" / "176F" → °C (redteam R06 · 26 ต.ค.: เดิมอ่านเป็น 176 °C → ไม่มีรุ่นผ่าน)"""
    m = _F_RX.search((text or "").replace(",", "."))
    return round((float(m.group(1)) - 32) * 5 / 9, 1) if m else None


_NEG_RX = re.compile(r"(?:ติด\s*)?ลบ\s*(?:ประมาณ|ประมาน|ราว\s*ๆ?|สัก|ก็)?\s*(?=\d)|minus\s*(?=\d)", re.IGNORECASE)
# ตัว c เปล่า ("5 C" · "-30c") ต้องไม่ใช่เศษรหัสรุ่น: "EC254 C" (ติดตัวอักษร) · "MP8 0 C" (OCR แตก · CD-002 — มีเลขนำหน้า)
_C_RX = re.compile(r"(?<![A-Za-z\d.])" + _NUM + r"\s*(?:°\s*[cC]|องศา|℃)"
                   r"|(?<![A-Za-z\d.])(?<!\d\s)(?<![A-Z]{2}\s)" + _NUM + r"\s*[cC](?![A-Za-z])")   # "HC 508 C"


def parse_temp_unit(text: str) -> Optional[float]:
    """อุณหภูมิที่มีหน่วยกำกับเท่านั้น (°C · องศา · c · °F) — ใช้กับข้อความอิสระทุกเทิร์น (extract_modutech_slots)
    ไม่อ่าน "อุณหภูมิ … เลข" เพราะเลขอาจเป็นรหัสรุ่น · redteam R07: "tempลบ30c" เดิมไม่ได้ค่า → ไม่กรองอุณหภูมิ"""
    t = _NEG_RX.sub(" -", (text or "").replace(",", "."))   # " -": "tempลบ30c" → "temp -30c" (ไม่ติดตัวอักษร)
    f = parse_fahrenheit(t)
    if f is not None:
        return f
    m = _C_RX.search(t)
    return float(m.group(1) if m.group(1) is not None else m.group(2)) if m else None


def parse_temp(text: str, bare_number: bool = False) -> Optional[float]:
    t = (text or "").replace(",", ".")
    # "ลบ 35" / "ติดลบ 35" / "minus 35" = -35 (test_conversation_leaks C13 · เดิมได้ +35)
    # main_sim G04 (26 ต.ค.): "อุณภูมิติดลบประมาน 30" — มีคำขยายคั่นก่อนตัวเลข และไม่มีคำว่าองศา → เดิมอ่านไม่ออก ถามซ้ำ
    t = _NEG_RX.sub(" -", t)
    v = parse_temp_unit(t)               # "5 C" ตัวใหญ่ (R18) · °F (R06) · "EC254 C" ไม่ใช่ 254 °C
    if v is not None:
        return v
    m = re.search(r"(?:อุณหภูมิ|อุณภูมิ|อุนหภูมิ|temp(?:erature)?)(?!ห้อง)[^\d\n-]{0,15}" + _NUM, t, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "."))
    if re.search(r"อุณหภูมิห้อง|อุณหภูมิปกติ|ห้องปกติ|ห้องธรรมดา|room\s*temp|ambient", t, re.IGNORECASE):
        return ROOM_TEMP_C
    if bare_number:
        m = re.search(_NUM, t)
        if m:
            return float(m.group(1))
    return None


def pitch_values(cat) -> list[float]:
    return sorted({p["specifications"]["pitch"]["mm"] for p in cat.products
                   if (p["specifications"].get("pitch") or {}).get("mm") is not None})


def pitch_matches(belt_pitch: Optional[float], want: float) -> bool:
    return belt_pitch is not None and abs(belt_pitch - want) <= PITCH_TOL_MM + 1e-9


def _temp_range(variant: dict, cond: str) -> tuple[Optional[float], Optional[float]]:
    te = (variant.get("temperature_effective") or {}).get(cond) or {}
    lo, hi = te.get("min_c"), te.get("max_c")
    if lo is None or hi is None:
        t = variant.get("temperature") or {}
        lo = t.get(f"min_c_{cond}", t.get("min_c")) if lo is None else lo
        hi = t.get(f"max_c_{cond}", t.get("max_c")) if hi is None else hi
    return lo, hi


def variant_ok(variant: dict, temp_c: float, cond: str) -> bool:
    lo, hi = _temp_range(variant, cond)
    if lo is None or hi is None:
        return False                  # ไม่มีข้อมูล = ไม่ยืนยันว่าผ่าน (ไม่เดา)
    return lo <= temp_c <= hi


def filter_by_need(cat, belt_codes: Iterable[str], pitch_mm=None, temp_c=None,
                   wet_or_dry: Optional[str] = None) -> dict:
    """คืน {kept, removed: {code: เหตุผล}, grades: {code: [เกรดที่ผ่าน]}, cond, note_th}
    pitch_mm / temp_c เป็น None หรือ UNKNOWN = ไม่กรองข้อนั้น
    wet_or_dry ไม่รู้ = ใช้ค่าเปียก (ต่ำกว่า · ปลอดภัยกว่า) แล้วบอกใน note"""
    want_p = pitch_mm if isinstance(pitch_mm, (int, float)) else None
    want_t = temp_c if isinstance(temp_c, (int, float)) else None
    cond = wet_or_dry if wet_or_dry in ("wet", "dry") else "wet"
    belt_codes_list = list(belt_codes)
    kept, removed, grades, near, conflicts, near_grades = [], {}, {}, {}, {}, {}
    for code in belt_codes_list:
        p = cat.by_code.get(code)
        if p is None:
            continue
        sp = p["specifications"]
        bp = (sp.get("pitch") or {}).get("mm")
        if want_p is not None and not pitch_matches(bp, want_p):
            removed[code] = f"พิทช์ {bp:g} มม." if bp is not None else "ไม่มีข้อมูลพิทช์"
            # พิทช์ใกล้เคียงต้องผ่านอุณหภูมิด้วย ไม่งั้นบอทเสนอเป็นทางเลือกทั้งที่ทนไม่ได้ (OVEN-02 · MD254 GAP48%)
            if bp is not None and abs(bp - want_p) <= PITCH_NEAR_MM and \
                    (want_t is None or any(variant_ok(v, want_t, cond) for v in sp["variants"])):
                near[code] = bp
                if want_t is not None:     # เกรดที่ผ่านอุณหภูมิ — turn.py เทียบกับเกรดที่เล่มแนะนำสำหรับงาน
                    near_grades[code] = [f"{v['belt_material']}/{v['pin_material']}" for v in sp["variants"]
                                         if variant_ok(v, want_t, cond)]
            continue
        if want_t is not None:
            ok = [f"{v['belt_material']}/{v['pin_material']}" for v in sp["variants"] if variant_ok(v, want_t, cond)]
            if not ok:
                his = [_temp_range(v, cond)[1] for v in sp["variants"]]
                los = [_temp_range(v, cond)[0] for v in sp["variants"]]
                his, los = [h for h in his if h is not None], [lo for lo in los if lo is not None]
                rng = f"{min(los):g} ถึง {max(his):g} °C" if his and los else "ไม่มีข้อมูล"
                removed[code] = f"ทน{'เปียก' if cond == 'wet' else 'แห้ง'}ได้ {rng}"
                # ตัดตามค่าที่เข้มกว่าไว้ก่อน (ไม่เดา) แต่ถ้าเป็นข้อขัดแย้งจริงที่อีกค่าให้ผ่าน ต้องรายงาน ไม่ใช่เงียบ
                # (HC152 FG PA ที่ 130 °C: ตารางสเปก 150 · เนื้อวัสดุ 120) — SM254 FG50% 116 < 120 ไม่ใช่ข้อขัดแย้ง
                why = conflict_passing(sp["variants"], want_t, cond)
                if why:
                    conflicts[code] = why
                continue
            grades[code] = ok
        kept.append(code)
    same_both = False
    if want_t is not None and wet_or_dry not in ("wet", "dry"):
        dry = filter_by_need(cat, belt_codes_list, pitch_mm, temp_c, "dry")
        same_both = dry["kept"] == kept and dry["grades"] == grades
    parts = []
    if want_p is not None:
        parts.append(f"พิทช์ {want_p:g} มม.")
    if want_t is not None:
        if same_both:
            cond_th = "ลูกค้าไม่ได้บอกเปียก/แห้ง แต่ผลเท่ากันทั้งไลน์เปียกและไลน์แห้ง"
        elif wet_or_dry in ("wet", "dry"):
            cond_th = "ไลน์เปียก" if cond == "wet" else "ไลน์แห้ง"
        else:
            cond_th = "ลูกค้าไม่ได้บอกเปียก/แห้ง จึงใช้ค่าไลน์เปียกซึ่งต่ำกว่า ต้องบอกลูกค้าเรื่องนี้"
        parts.append(f"ใช้งานที่ {want_t:g} °C ({cond_th})")
    note = ""
    if parts:
        note = (f"กรองตามที่ลูกค้าบอก: {' · '.join(parts)} — เหลือ {len(kept)} รุ่น ตัดออก {len(removed)} รุ่น "
                "ห้ามเสนอรุ่นที่ถูกตัดออก ถ้าเหลือ 0 รุ่น ให้บอกตรง ๆ ว่าไม่มีรุ่นที่ตรงทุกเงื่อนไข "
                "และบอกว่าติดเงื่อนไขไหน")
    if conflicts:
        note += (" · รุ่นใน temperature_conflicts ถูกตัดตามค่าที่เข้มกว่าในเล่ม แต่เล่มอีกหน้าระบุค่าที่ผ่าน "
                 "ต้องบอกลูกค้าทั้งสองค่าตามข้อความนั้น ห้ามบอกว่าใช้ได้ ให้ยืนยันกับฝ่ายขายก่อน")
    if near:
        note += (f" · รุ่นใน pitch_near มีพิทช์ใกล้เคียง (ต่างไม่เกิน {PITCH_NEAR_MM:g} มม.) แต่ไม่ตรง "
                 "บอกลูกค้าได้ว่ามี และต้องยืนยันพิทช์จริงก่อน เพราะใช้สเตอร์คนละชุด")
    return dict(kept=kept, removed=removed, grades=grades, cond=cond, note_th=note,
                pitch_mm=want_p, temp_c=want_t, near=near, conflicts=conflicts, near_grades=near_grades)


def conflict_passing(variants: list, temp_c: float, cond: str) -> str:
    """ข้อความข้อขัดแย้งของเกรดที่ถูกตัดตามค่าเข้ม แต่ค่าอีกแหล่งในเล่มให้ผ่าน (ไม่งั้น "")

    ใช้กฎเดียวกับ gates.real_temperature_conflict — v30_3 pending_vendor_confirmation
    'spec-exceeds-material-limit': ข้อขัดแย้งจริงคือตารางสเปก *สูงกว่า* เนื้อวัสดุหน้า 347 เท่านั้น
    ตารางสเปกต่ำกว่า (เช่น SM254 FG50% 116 กับ PA6 120) = ข้อจำกัดของพื้นผิว/การขึ้นรูป ไม่ใช่ข้อขัดแย้ง
    ไม่อ่าน registry_conflict_th เพราะข้อความนั้นเขียนว่า "ยังไม่ยืนยัน" ทั้งสองทิศ (gates.py ก็ไม่ใช้)
    temperature_unconfirmed_th — ค่าที่ระบบเลือกค่าเข้มไว้ก่อนเพราะเล่มพิมพ์ขัดกันเอง (MD254 RR)"""
    from brands.modutech.gates import conflict_note, real_temperature_conflict
    out = []
    for v in variants:
        lo, hi = _temp_range(v, cond)
        spec = (((v.get("temperature_effective") or {}).get("source_layers") or {})
                .get("spec_table") or {}).get("max_c")
        if cond == "dry" and real_temperature_conflict(v) and isinstance(spec, (int, float)) \
                and (lo is None or lo <= temp_c) and hi is not None and hi < temp_c <= spec:
            out.append(conflict_note(v)[0])
        elif v.get("temperature_trust") == "unconfirmed" and v.get("temperature_unconfirmed_th") \
                and hi is not None and hi < temp_c <= (((((v.get("temperature_effective") or {})
                                                          .get("source_layers") or {}).get("belt_material") or {})
                                                        .get(cond) or [None, hi])[1] or hi):
            # เกินค่าเข้มแต่ไม่เกินเนื้อวัสดุ = ค่าที่ยังไม่ยืนยันมีผล · เกินเนื้อวัสดุด้วย = ตัดแน่นอน ไม่ต้องเตือน
            out.append(f"{v.get('belt_material')}/{v.get('pin_material')}: {v['temperature_unconfirmed_th']}")
    return " · ".join(dict.fromkeys(out))


def wet_dry_matters(cat, belt_codes: Iterable[str], pitch_mm, temp_c) -> bool:
    """ผลกรองอุณหภูมิต่างกันระหว่างเปียกกับแห้งไหม (ทั้งรายชื่อรุ่นและเกรดที่ผ่าน)"""
    if not isinstance(temp_c, (int, float)):
        return False
    codes = list(belt_codes)
    w = filter_by_need(cat, codes, pitch_mm, temp_c, "wet")
    d = filter_by_need(cat, codes, pitch_mm, temp_c, "dry")
    return w["kept"] != d["kept"] or w["grades"] != d["grades"]


def visible_slots(slots: dict) -> dict:
    """slot ที่ส่งให้ LLM เห็น — ไม่รวมสถานะภายในของการถาม"""
    return {k: v for k, v in (slots or {}).items() if not k.startswith("_") and v is not None}
