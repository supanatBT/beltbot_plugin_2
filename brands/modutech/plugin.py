"""
brands/modutech/plugin.py
=========================
ปลั๊กอิน Modutech — ย้ายมาจาก DialogueManager (dialogue_state.py) ชั้น 4 · ตรรกะเท่าเดิม

ลำดับ: ส่งฝ่ายขาย → ค้นทั้งฐาน → รหัสกำกวม → เปียก/แห้ง → ตรง/โค้ง → ความต้องการ → answer

สิ่งที่เปลี่ยนตอนย้าย
  st.modutech_codes/slots/sprocket_codes → st["codes"/"slots"/"sprocket_codes"]
  route.codes → inp.signal.parsed (CodeMatch จาก detect ตัวเดียวกัน)
  pending ส่งคืนทาง Decision.pending

ค้นข้อมูลและประกอบ prompt อยู่ใน runtime.py (ต้องใช้โมเดล) — ชุดเกตสร้างปลั๊กอินแบบไม่มี runtime ได้
"""
from __future__ import annotations

import re
from typing import Optional

from brands.modutech.detect import ModutechDetector
from brands.modutech.gates import Catalogue
from brands.modutech.router import CatalogueSearch, ExploratoryQuery
from core.protocol import BrandInfo, BrandSignal, DecideInput, Decision
from core.sales import attach_handoff, escalation_again_th, escalation_gate
from core.text import any_word, has
from brands.modutech import need_flow as NF

MOD_TEMP_TOPIC = r"อุณหภูมิ|องศา|°\s*[cC]|ร้อน|เย็น|แช่แข็ง|ฟรีซ|freez|temp|ทนความร้อน|ทนเย็น"
MOD_STRENGTH_TOPIC = r"แรงดึง|ความแข็งแรง|รับแรง|strength|N\s*/\s*m|รับน้ำหนัก|โหลด"
REFER_RX = (r"ตัวนี้|อันนี้|รุ่นนี้|ตัวนั้น|อันนั้น|รุ่นนั้น|ตัวแรก|อันแรก|ตัวหลัง|อันหลัง|ตัวที่|อันที่|รุ่นที่|"
            r"สองตัว|2\s*ตัว|ทั้งสอง|ทั้ง\s*2|เทียบ|ต่างกัน|อันไหน|ตัวไหน|ที่แนะนำ|เมื่อกี้|ข้างบน")
OTHER_RX = r"รุ่นอื่น|แบบอื่น|ตัวอื่น|อันอื่น|อีกไหม|อีกมั้ย|อีกบ้าง|นอกจากนี้"
EXCLUDE_KEY = "_exclude"          # รุ่นที่ลูกค้าขอให้ตัดออก ("ขอรุ่นอื่น") — ส่งไป build_turn เทิร์นเดียว
FOLLOWUP_CHARS = 40
MOD_RECOMMEND = r"แนะนำ|ใช้รุ่นไหน|ใช้อะไรดี|ตัวไหนดี|รุ่นไหนดี|เหมาะกับ|มีอะไรบ้าง|สายพานอะไร"
# ขอให้ช่วยเลือก (ไม่ใช่ถามรายชื่อ) — บอกงานแล้วแต่ยังไม่รู้พิทช์ → ถามทีละข้อต่อ (ผู้ใช้เลือก 26 ต.ค. ข้อ 2 ก)
# "ใช้รุ่นไหน(ได้)บ้าง" "มีงานอะไรบ้าง" = ถามรายชื่อตามเล่ม → ตอบรายชื่อเหมือนเดิม (graph_apps)
MOD_PICK = (r"แนะนำ|รุ่นไหนดี|ตัวไหนดี|อันไหนดี|ใช้อะไรดี|หาสายพาน|อยากได้สายพาน|ต้องการสายพาน|กำลังหา|ช่วยเลือก|"
            r"recommend|suggest|looking for")     # อังกฤษ: redteam R18 (26 ต.ค.) · "which model" = "รุ่นไหน" ไม่ใช่ขอให้เลือก (C11)
MOD_LIST = r"บ้าง|ทั้งหมด|ทุกรุ่น|\ball\b|\blist\b"

ASK_WET_DRY_TH = ("ขอทราบก่อนครับว่าไลน์นี้เป็นสภาวะเปียก (มีน้ำ ล้างบ่อย) หรือแห้ง "
                  "เพราะค่าอุณหภูมิที่ทนได้ต่างกันมาก บางเกรดต่างกันถึง 33 °C")
ASK_LINE_SHAPE_TH = ("รุ่นนี้วิ่งโค้งได้ครับ ขอทราบก่อนว่าไลน์เป็นแบบตรงอย่างเดียว หรือมีช่วงโค้ง "
                     "เพราะค่าความแข็งแรงตอนวิ่งโค้งต่ำกว่าตอนวิ่งตรงมาก")
ASK_MODUTECH_NEED_TH = ("ขอข้อมูลเพิ่มนิดนะครับ เพื่อแนะนำรุ่นได้ตรง\n"
                        "• อุตสาหกรรม: เนื้อสัตว์ / สัตว์ปีก / อาหารทะเล / เบเกอรี่ / ผักผลไม้ / บรรจุภัณฑ์ / กล่องลูกฟูก\n"
                        "• จุดที่ใช้งาน: เช่น ไลน์ตัดแต่ง เข้าเตาอบ เครื่องตรวจจับโลหะ\n"
                        "• ไลน์เปียกหรือแห้ง และอุณหภูมิใช้งานโดยประมาณ")


def extract_modutech_slots(text: str, materials: list[str], mask_codes: tuple = ()) -> dict:
    """ดึง slot จากข้อความ — mask_codes คือรหัสสินค้าที่ต้องลบออกก่อนหา slot

    ทำไมต้อง mask: รหัสสเตอร์มีวัสดุต่อท้าย เช่น EC127SQZ24*PA ตัว regex ของวัสดุ
    ใช้ (?<![A-Za-z])PA(?![A-Za-z]) ซึ่ง * ไม่ใช่ตัวอักษร จึงจับ PA ในรหัสได้
    ผลคือระบบคิดว่าลูกค้าต้องการเกรด PA ทั้งที่แค่พิมพ์รหัสสเตอร์มาถาม
    แล้วไปกรองสายพานผิดโดยไม่มีใครเห็น
    """
    t = text or ""
    for code in mask_codes:
        if code:
            t = re.sub(re.escape(code), " ", t, flags=re.IGNORECASE)
    out: dict = {}
    if has(r"เปียก|ล้าง|ฉีดน้ำ|น้ำ|wet|washdown|ชื้น", t) and not has(r"ไม่เปียก|ไม่โดนน้ำ", t):
        out["wet_or_dry"] = "wet"
    if has(r"แห้ง|\bdry\b|ไม่เปียก|ไม่โดนน้ำ", t):
        out["wet_or_dry"] = "dry"
    if has(r"ไลน์ตรง|วิ่งตรง|ทางตรง|straight|ไม่มีโค้ง|ไม่เลี้ยว", t):      # ทางตรง: redteam R17 r2
        out["line_shape"] = "straight"
    elif has(r"มีโค้ง|วิ่งโค้ง|เลี้ยว|โค้ง|curve|radius", t):
        out["line_shape"] = "curve"
    for m in materials:                                 # ยาวก่อน: POM-NL ก่อน POM
        if re.search(rf"(?<![A-Za-z]){re.escape(m)}(?![A-Za-z])", t, re.IGNORECASE):
            out["material"] = m.upper()
            break
    # มีหน่วยกำกับ: °C · องศา · c · ลบ30c (R07) · ฟาเรนไฮต์ → เซลเซียส (R06) — redteam 26 ต.ค.
    v = NF.parse_temp_unit(t)
    if v is not None:
        out["operating_temp_c"] = v
    return out


class ModutechPlugin:
    gate_chain = ("escalation", "explore_search", "ambiguous_code", "wet_or_dry",
                  "line_shape", "need", "answer")
    image_reject_th = ""                 # ยังไม่มีรูปจริงสักใบ — brand.yaml › image.enabled: auto ปิดเอง

    def __init__(self, info: BrandInfo, cat: Catalogue, state_defaults: Optional[dict] = None):
        self.info = info
        self.mod = cat
        self.detector = ModutechDetector(cat)
        self.search = CatalogueSearch(cat)
        self.materials = self.search.materials
        self._state_defaults = dict(state_defaults or {"codes": [], "slots": {}, "sprocket_codes": []})
        self.runtime = None             # brands.modutech.runtime.ModutechRuntime — ตั้งใน create()

    # ─────────────────────────── 1 · รู้จักข้อความ ───────────────────────────

    def detect(self, text: str) -> BrandSignal:
        return self.detector.detect(text)

    def domain_terms(self) -> list[str]:
        # คำอังกฤษของคำตอบในการถาม (redteam R18: "wet, washed daily" เดิมถูกปฏิเสธว่านอกเรื่อง)
        return ["modutech", "โมดูล", "pitch", "wet", "washdown", "washed"] + list(self.detector.weak_terms)

    def _names_industry(self, text: str) -> bool:
        """ข้อความระบุอุตสาหกรรมแล้ว (ตามคีย์เวิร์ดของตัวค้น) — นับว่าบอกงานมาแล้ว ไม่ต้องถามกลับ

        "บรรจุภัณฑ์" ถูกตัดออกจาก weak_terms โดยตั้งใจ (GENERIC_TERMS) เพราะ Movex ก็ใช้คำนี้
        จึงห้ามใช้เป็นสัญญาณเลือกแบรนด์ แต่เมื่อเลือก Modutech แล้ว คำนี้บอกงานได้ชัดพอ
        เดิม "อุตสาหกรรมบรรจุภัณฑ์มีงานอะไรบ้าง" ถูกถามกลับว่าอุตสาหกรรมอะไร
        ทั้งที่ match_industry จับ Packaging ได้ (GI-A06 · graph_apps_r1/r2 · 23 ต.ค.)
        """
        try:
            return bool(self.search.match_industry(text))
        except Exception:                                    # noqa: BLE001
            return False

    def _need_in(self, text: str) -> bool:
        """ข้อความบอกงานหรืออุตสาหกรรม (ตัวค้นจับได้)"""
        return self.search.match_application(text) is not None or self._names_industry(text)

    def _job_sig(self, text: str) -> tuple:
        """(คำงานที่จับได้, อุตสาหกรรม) — ใช้แยก "บอกงานเดิมซ้ำ" กับ "เปลี่ยนงาน" """
        from brands.modutech.router import APPLICATION_KEYWORDS, INDUSTRY_KEYWORDS
        low = (text or "").lower()
        tags = frozenset(t for t, kws in APPLICATION_KEYWORDS.items() if any(k.lower() in low for k in kws))
        ind = next((i for i, kws in INDUSTRY_KEYWORDS.items() if any(k.lower() in low for k in kws)), None)
        return tags, ind

    def _same_job(self, answer: str, text: str) -> bool:
        """คำตอบพูดถึงงานเดิมซ้ำ ("ก็บอกว่าห้องแห้ง ๆ ไง ตัวตรวจจับโลหะอะ") — ไม่ใช่งานใหม่
        redteam R13 r2 (27 ต.ค.): เดิมนับเป็นงานใหม่ → เริ่มถามพิทช์ใหม่ทั้งที่เพิ่งถาม → ลูกค้าเลิกคุย
        "ไม่ใช่ไลน์ไก่ … เป็นขนมปัง" มีงานใหม่ (ขนมปัง) ที่ข้อความก่อนไม่มี → ไม่ใช่งานเดิม"""
        before = (text or "").replace(answer or "", " ")
        a_tags, a_ind = self._job_sig(self.NEGATED_JOB_RX.sub(" ", answer or ""))
        b_tags, b_ind = self._job_sig(before)
        if not (a_tags or a_ind) or not (b_tags or b_ind):
            return False
        return a_tags <= b_tags and (a_ind is None or a_ind == b_ind)

    def _remember_need(self, text: str, st: dict) -> None:
        """จำข้อความที่บอกงาน (ไม่มีรุ่นในโฟกัส) ไว้ให้คำถามต่อที่เปลี่ยนแค่พิทช์/อุณหภูมิ"""
        if not st["codes"] and self._need_in(text):
            st["slots"][self.NEED_TEXT_KEY] = text[-self.NEED_TEXT_MAX:]

    @property
    def weak_terms(self) -> list[str]:
        return self.detector.weak_terms

    # ─────────────────────────── 5 · สถานะ ───────────────────────────

    def empty_state(self) -> dict:
        return {k: (type(v)() if isinstance(v, (list, dict)) else v) for k, v in self._state_defaults.items()}

    def has_focus(self, st: dict) -> bool:
        return bool(st.get("codes")) or bool((st.get("slots") or {}).get(self.OFFERED_KEY))

    def on_brand_switch(self, st: dict) -> dict:
        # ล้างรุ่นกับ slot · sprocket_codes ไม่ล้าง (ของเดิมก็ไม่ล้าง — เทิร์นถัดไปเขียนทับเอง)
        return {**st, "codes": [], "slots": {}}

    # slot ที่ decide รู้จัก — ค่าอื่นทิ้ง (ย้ายมาจาก webapi/bot.py _SLOT_KEYS ชั้น 6)
    SLOT_KEYS = ("wet_or_dry", "material", "line_shape", "operating_temp_c",
                 "pitch_mm", "temp_c", NF.FLOW_KEY, NF.PITCH_SAID_KEY,   # สี่ตัวนี้: ถามทีละข้อ (need_flow.py)
                 "_need_text", "_reask", "_esc_last")
    ESC_LAST_KEY = "_esc_last"    # หัวข้อส่งฝ่ายขายของเทิร์นก่อน — ถามซ้ำทันทีได้ข้อความอีกแบบ (redteam r4 R09#2)
    REASK_KEY = "_reask"          # ขั้นที่ถามซ้ำไปแล้วหนึ่งครั้งเพราะอ่านคำตอบไม่ออก (กันวน)
    NEED_TEXT_KEY = "_need_text"  # ข้อความที่บอกงาน/อุตสาหกรรมล่าสุด — ใช้กับคำถามต่อที่เปลี่ยนแค่พิทช์/อุณหภูมิ
    NEED_TEXT_MAX = 300
    OFFERED_KEY = "_offered"      # รุ่นที่คำตอบล่าสุดเสนอ (list) — ใช้เมื่อลูกค้าอ้างถึง ไม่ใช่โฟกัสทันที

    def sanitize_state(self, raw: dict) -> dict:
        """เก็บเฉพาะรหัสที่มีจริงในแคตตาล็อก · slot ที่รู้จักและเป็นค่าธรรมดา
        รหัสสเตอร์เป็นของเทิร์นเดียว ไม่กู้"""
        codes = raw.get("codes")
        slots_in = raw.get("slots")
        slots: dict = {}
        if isinstance(slots_in, dict):
            for k, v in slots_in.items():
                if k in self.SLOT_KEYS and isinstance(v, (str, int, float)) and not isinstance(v, bool):
                    slots[k] = v
                elif k == self.OFFERED_KEY and isinstance(v, list):
                    ok = [c for c in v if isinstance(c, str) and c in self.mod.by_code]
                    if ok:
                        slots[k] = ok
        return {"codes": [c for c in codes if c in self.mod.by_code] if isinstance(codes, list) else [],
                "slots": slots, "sprocket_codes": []}

    def resumable(self, st: dict) -> bool:
        return bool(st.get("codes"))

    # ─────────────────────────── 3 · ตัดสิน ───────────────────────────

    def decide(self, inp: DecideInput, st: dict) -> Decision:
        text, codes = inp.text, inp.signal.parsed
        # ลบรหัสที่ router จับได้ออกก่อนหา slot ไม่งั้นวัสดุที่ต่อท้ายรหัสสเตอร์
        # จะถูกอ่านเป็นความต้องการของลูกค้า (EC127SQZ24*PA → material=PA)
        st["slots"].update(extract_modutech_slots(
            text, self.materials,
            mask_codes=tuple(codes.belt_codes) + tuple(codes.sprocket_codes)))
        slots = st["slots"]
        slots.pop(EXCLUDE_KEY, None)                       # "ขอรุ่นอื่น" ใช้ได้เทิร์นเดียว
        last_esc = slots.pop(self.ESC_LAST_KEY, None)      # หัวข้อส่งฝ่ายขายของเทิร์นก่อน (ใช้ได้เทิร์นเดียว)
        if not codes.belt_codes:
            self._use_offered(inp.answer or text, st)
        if codes.belt_codes:
            st["codes"] = list(codes.belt_codes)
            slots.pop(self.OFFERED_KEY, None)
        # รหัสสเตอร์ไม่เก็บลง state เพราะไม่ใช่ "รุ่นที่อยู่ในความสนใจ" แต่ต้องส่งต่อ
        # ให้ turn แปลงกลับเป็นสายพานด้วยกราฟ ไม่งั้นรหัสที่ลูกค้าพิมพ์หายทั้งตัว
        st["sprocket_codes"] = list(codes.sprocket_codes)

        # กลางการถามทีละข้อ ตัดสิน "คำถามผสม" จากข้อความของเทิร์นนี้ ไม่ใช่ข้อความรวม
        # 26 ต.ค. (ลูกค้าจำลอง G11): ข้อความรวม "…ใช้กับไก่… ขอเบอร์ฝ่ายขาย" มีคำว่า "ใช้กับ" จากเทิร์นก่อน
        # → นับเป็นคำถามผสม → ตัวตีความบอก "เปลี่ยนเรื่อง" → เลิกถาม → เทิร์นหน้า "พิทช์ 2 นิ้ว" ลืมว่าเป็นงานไก่
        flow = slots.get(NF.FLOW_KEY)
        in_flow = bool(flow) and not (codes.belt_codes or codes.sprocket_codes or codes.candidates or st["codes"])
        esc = escalation_gate(inp.answer if in_flow and inp.answer else text,
                              belt_code=(st["codes"] or [None])[0])
        if esc and not esc.has_spec_question and in_flow:
            # ให้ช่องทางติดต่อแล้วถามข้อเดิมต่อ (ยังรอคำตอบอยู่) — เดิมส่งฝ่ายขายแล้วล้างการรอคำตอบ
            # เทิร์นหน้า "2 นิ้ว" จึงไม่ถูกอ่านเป็นคำตอบ และถูกบันทึกเป็น "ไม่ทราบ" (C09)
            return Decision("ask", self.info.key, f"{esc.reply_th}\n\n{self._step_question(flow, slots)}",
                            f"ขอ{'/'.join(esc.topics)}กลางการถาม ({flow}) → ให้ช่องทาง แล้วถามข้อเดิมต่อ",
                            topic="escalate", effective_text=text,
                            payload=dict(codes=[], slots=dict(slots)), pending=self.STEP_PENDING[flow])
        # "wet … ลบ30c pich1in มีของมั้ย" — ถามสต็อกพร้อมบอกสเปกครบ = ยังต้องการรุ่น (redteam R07 r2 · 27 ต.ค.)
        # เดิมส่งฝ่ายขายอย่างเดียว ไม่ตอบรุ่น → ตอบรุ่นแล้วแนบช่องทางฝ่ายขาย
        raw = inp.answer or text
        spec_info = NF.stated_pitch(raw) is not None or NF.parse_temp_unit(raw) is not None
        if esc and not esc.has_spec_question and spec_info and not st["codes"]:
            d = self._decide_core(text, st, codes, answer=inp.answer)
            attach_handoff(d, esc.handoff_th, esc.topics)
            return d
        if esc and not esc.has_spec_question:
            again = last_esc == "/".join(esc.topics)
            slots[self.ESC_LAST_KEY] = "/".join(esc.topics)
            return Decision("escalate", self.info.key, escalation_again_th(esc) if again else esc.reply_th,
                            f"หัวข้อ {esc.topics}" + (" (ถามซ้ำ)" if again else ""),
                            topic="escalate", effective_text=text,
                            payload=dict(codes=st["codes"], slots=dict(slots)))
        d = self._decide_core(text, st, codes, answer=inp.answer)
        if esc:
            attach_handoff(d, esc.handoff_th, esc.topics)
        # แนบรหัสสเตอร์ที่จุดเดียว แทนการแก้ทุก return ใน _decide_core
        # ซึ่งมี 7 ทางออกและเพิ่มได้เรื่อย ๆ ถ้าแก้ทีละที่จะมีทางที่ลืม
        if codes.sprocket_codes and isinstance(d.payload, dict):
            d.payload["sprocket_codes"] = list(codes.sprocket_codes)
        return d

    def _decide_core(self, text: str, st: dict, codes, answer: str = "") -> Decision:
        slots = st["slots"]
        key = self.info.key

        # ── ถามความต้องการทีละข้อ (need_flow.py) — ลูกค้าพิมพ์รหัสหรือเปลี่ยนเรื่อง = ออกจากการถาม ──
        flow = slots.get(NF.FLOW_KEY)
        if flow and (codes.belt_codes or codes.sprocket_codes or codes.candidates or st["codes"]):
            slots.pop(NF.FLOW_KEY, None)
            flow = None
        # ลูกค้าบอกงานใหม่แทนการตอบ ("แล้วถ้าเป็นขนมปังเข้าเตาอบล่ะ" ตอนถามพิทช์) → เริ่มคำขอใหม่จากข้อความนี้
        # 26 ต.ค. (C07): เดิมกฎอ่านไม่ออก = "ไม่ทราบพิทช์" แล้วถามอุณหภูมิต่อของงานเดิม
        # ต้องไม่ใช่คำตอบของข้อที่ถาม — "ฉีดน้ำล้างทุกวัน" ตอบเปียก/แห้ง แม้คำว่า "ล้าง" จับเป็นงานได้ (CONV-26)
        # redteam R02 (26 ต.ค.): "ขอโทษ ไม่ใช่ไลน์ไก่ จริง ๆ เป็นไลน์ขนมปังเข้าเตาอบ ส่วนพิทช์เอา 1 นิ้ว" — แก้งานพร้อมตอบพิทช์
        # เดิมกฎอ่านพิทช์ได้จึงไม่เริ่มใหม่ ข้อความรวมมีทั้งไก่และขนมปัง → จับอุตสาหกรรมไม่ได้ · มีคำบอกว่าแก้ = เริ่มจากข้อความนี้
        # ค่าที่บอกพร้อมกัน (พิทช์ 1 นิ้ว) อ่านต่อจากข้อความนี้ในขั้น need
        if flow and flow != "need" and answer and self._need_in(answer) and (
                (not re.search(r"\d", answer) and self._read_rules_sure(flow, answer) is None)
                or self.CORRECTION_RX.search(answer)) and not self._same_job(answer, text):
            slots.pop(NF.FLOW_KEY, None)
            slots.pop(NF.PITCH_SAID_KEY, None)
            slots.pop(self.NEED_TEXT_KEY, None)
            # "ไม่ใช่ไลน์ไก่" ยังมีคำว่าไก่ → ตัดส่วนที่ปฏิเสธออกก่อนจับงาน
            flow, text = "need", (self.NEGATED_JOB_RX.sub(" ", answer).strip() or answer)                # ยังอยู่ในการช่วยเลือก → ถามพิทช์ของงานใหม่ต่อ
        if flow:
            d = self._need_flow(text, st, flow, answer)
            if d is not None:
                return d
            # ลูกค้าเปลี่ยนเรื่อง → ตัดสินจากข้อความเทิร์นนี้อย่างเดียว (ไม่รวมคำถามเดิม)
            text = answer or text

        # ── คำถามต่อที่เปลี่ยนแค่พิทช์/อุณหภูมิ ("ถ้าเป็นพิทช์ 1 นิ้วล่ะ") → ใช้งานเดิมจากเทิร์นก่อน ──
        # 26 ต.ค. (c16_*.json · CONV-16 t5): เดิมค้นพิทช์ทั้งฐาน ไม่สนว่าเป็นงานไก่ — 2 ใน 6 รอบ LLM ลืมงานไก่
        # แล้วไล่ 18 รุ่น · บางรอบใส่ EC254 R (สายพานเลี้ยว) ปน · จะจำงานได้หรือไม่ขึ้นกับ LLM อ่านประวัติ
        stated = NF.stated_pitch(text)
        if stated is None and slots.get(self.NEED_TEXT_KEY) and self.REMEASURE_RX.search(text) \
                and not re.search(r"กว้าง|ยาว|หนา|width|length", text, re.IGNORECASE):
            # "เดี๋ยวนะ วัดใหม่แล้วเป็น 2 นิ้ว" — ไม่มีคำว่าพิทช์ แต่แก้ค่าหลังเพิ่งถามพิทช์ (redteam R01 r2 · 27 ต.ค.)
            v = NF.parse_pitch(text)
            stated = v if v is not None and 1.0 <= v <= 200.0 else None
        if stated is not None:
            slots["pitch_mm"] = stated                     # ลูกค้าบอกพิทช์ใหม่ = แทนค่าเดิม
        need_prev = slots.get(self.NEED_TEXT_KEY)
        new_temp = extract_modutech_slots(text, ()).get("operating_temp_c") is not None
        if need_prev and not codes.belt_codes and not st["codes"] and not self._need_in(text) \
                and (stated is not None or new_temp or self.COMPLAINT_RX.search(text) or self.CONTINUE_RX.search(text)
                     or set(extract_modutech_slots(text, ())) & {"line_shape", "wet_or_dry"}):
            # บ่นว่าถามซ้ำ/ไม่เข้าใจ → ยังเป็นงานเดิม ตอบจากงานเดิม (redteam R13 r2)
            text = f"{need_prev} {text}"

        q = self.search.parse(text)
        if q is not None and q.op == "==" and not (q.surface or q.pin_material or q.belt_material) and \
                self._need_in(text):
            # "เข้าเตาอบ … พิทช์ 1 นิ้ว" = บอกงานพร้อมพิทช์ → ทางงานใช้ แล้วกรองพิทช์/อุณหภูมิด้วยโค้ด (turn.py)
            # ไม่ใช่ค้นพิทช์ทั้งฐานซึ่งไม่สนงานที่ลูกค้าบอก (26 ต.ค. · OVEN-01/02)
            q = None
        if q is not None and not codes.belt_codes:
            return Decision("search", key, reason="คำถามเชิงสำรวจ → ค้นทั้งฐาน", topic="explore",
                            effective_text=text,
                            payload=dict(codes=[], slots=dict(slots), search_query=q.as_dict()))

        if codes.candidates and not codes.belt_codes:
            shown = codes.candidates[:10]
            reply = ("รหัสนี้มีหลายรุ่นครับ หมายถึงรุ่นไหนครับ\n"
                     + "\n".join(f"• {c} — {self.mod.by_code[c]['retrieval_card'].get('surface_type', '')}"
                                 for c in shown))
            return Decision("ask", key, reply, "รหัสกำกวม", topic="code", effective_text=text,
                            payload=dict(codes=[], candidates=codes.candidates, slots=dict(slots)),
                            pending="modutech_code")

        focus = self.mod.records(st["codes"])
        # อุณหภูมิค้างใน slot นับเป็นเรื่องอุณหภูมิ — ยกเว้นข้อความปิดท้าย ("…ไปคุยกับช่างก่อน ขอบคุณมากครับ")
        # redteam R02 (26 ต.ค.): เดิมลูกค้าขอบคุณแล้วบอทถามเปียก/แห้งต่อ
        closing = bool(re.search(r"ขอบคุณ|ขอบใจ|thank", text, re.IGNORECASE)) and not NF._QUESTION_RX.search(text) \
            and not re.search(r"ไหม|มั้ย|หรือเปล่า|บ้าง", text)
        temp_topic = has(MOD_TEMP_TOPIC, text) or ("operating_temp_c" in slots and not st["codes"] and not closing)
        if temp_topic and not slots.get("wet_or_dry"):
            needs = (not focus) or any("wet_or_dry" in (p["answering"].get("required_slots") or []) for p in focus)
            if needs:
                return Decision("ask", key, ASK_WET_DRY_TH, "ต้องรู้เปียก/แห้งก่อนตอบอุณหภูมิ",
                                topic="temperature", effective_text=text,
                                payload=dict(codes=st["codes"], slots=dict(slots)), pending="wet_or_dry")

        if has(MOD_STRENGTH_TOPIC, text) and not slots.get("line_shape") \
                and any(p["specifications"].get("has_curve_rating") for p in focus):
            return Decision("ask", key, ASK_LINE_SHAPE_TH, "รุ่นวิ่งโค้งได้ ต้องรู้ไลน์ตรง/โค้ง",
                            topic="strength", effective_text=text,
                            payload=dict(codes=st["codes"], slots=dict(slots)), pending="line_shape")

        # รหัสสเตอร์นับเป็น "รู้พอจะตอบ" แล้ว ไม่ต้องถามกลับว่าทำงานอะไร
        #
        # "EC127SQZ19*PA ใช้กับสายพานรุ่นไหน" มีคำว่า "สายพาน" จึงเข้าเงื่อนไขขอบล่าง
        # แล้วถูกตีเป็นคำถามแนะนำรุ่นแบบเปิด ทั้งที่ลูกค้าระบุของมาชัดเจนที่สุดแล้ว
        # ก่อน 1 ต.ค. มันรอดมาได้เพราะบั๊กอีกตัว — วัสดุต่อท้ายรหัส (*PA) ถูกอ่านเป็น
        # slot ของลูกค้า ทำให้ has_need เป็นจริง พอแก้บั๊กนั้นอาการนี้จึงโผล่
        # กล่าวคือมันเคย "ทำงานได้ด้วยเหตุผลที่ผิด" ไม่ใช่เคยถูกแล้วเพิ่งเสีย
        # slot ภายใน (ขึ้นต้นด้วย _ เช่น _need_text) ไม่นับเป็น "ลูกค้าบอกความต้องการในเทิร์นนี้" (CONV-15 · 26 ต.ค.)
        has_need = bool(any_word(self.detector.weak_terms, text)) or bool(NF.visible_slots(slots)) \
            or bool(codes.sprocket_codes) or self._names_industry(text)
        if not focus and not has_need and has(MOD_RECOMMEND + r"|สายพาน", text):
            # 25 ต.ค.: ถามทีละข้อ งาน → พิทช์ → อุณหภูมิ (เดิม ASK_MODUTECH_NEED_TH ถามสามเรื่องในข้อความเดียว)
            slots[NF.FLOW_KEY] = "need"
            return Decision("ask", key, NF.ASK_NEED_TH, "ยังไม่รู้งานของลูกค้า",
                            topic="recommend", effective_text=text,
                            payload=dict(codes=[], slots=dict(slots)), pending="modutech_need")

        # ── บอกงานมาแล้ว + ขอให้ช่วยเลือก แต่ยังไม่รู้พิทช์ → ถามทีละข้อต่อ (ข้ามคำถามงาน) ──
        # ลูกค้าจำลอง 26 ต.ค.: ลูกค้าบอกงานตั้งแต่ข้อความแรกแทบทุกบท บอทส่งรายการ 27–41 รุ่นทันที
        # ขั้นตอนถามพิทช์/อุณหภูมิจึงแทบไม่ได้ทำงาน (เรียกตัวตีความ 1 ครั้งใน 28 บท)
        need_known = "pitch_mm" in slots and ("temp_c" in slots or "operating_temp_c" in slots)
        if not focus and not codes.sprocket_codes and not need_known \
                and has(MOD_PICK, text) and not has(MOD_LIST, text) and self._need_in(text):
            d = self._need_flow(text, st, "need", "")
            if d is not None:
                return d

        self._remember_need(text, st)
        return Decision("answer", key, reason="รหัสชัด" if focus else "ค้นตามการใช้งาน",
                        topic="temperature" if temp_topic else None, effective_text=text,
                        payload=dict(codes=st["codes"], slots=dict(slots)))

    def _need_candidates(self, text: str) -> list[str]:
        """รุ่นที่งานนี้น่าจะใช้ — ไว้ตัดสินว่าต้องถามเปียก/แห้งไหม (ไม่ใช่รายชื่อที่ตอบลูกค้า)"""
        am = self.search.match_application(text)
        if am is not None:
            return list(am.belt_codes)
        im = self.search.match_industry(text)
        if im is not None:
            return list(im[1])
        return [p["belt_code"] for p in self.mod.products]

    # ── ตีความคำตอบของลูกค้าต่อคำถามที่ถามค้าง: LLM ก่อน (core/answer_interpreter) · ไม่ได้ = กฎเดิม ──
    STEP_EXPECT = {"pitch": "number_mm", "pitch_confirm": "number_mm", "pitch_retry": "number_mm",
                   "temp": "number_c", "wet": "wet_dry", "need": "free"}
    REMEASURE_RX = re.compile(r"วัดใหม่|วัดอีกที|แก้เป็น|เปลี่ยนเป็น|ที่จริง(?:เป็น)?|จริง\s*ๆ\s*(?:แล้ว)?เป็น|เดี๋ยวนะ|ขอแก้")
    # คุยต่อ/ตอบข้อที่ LLM ถามท้ายคำตอบ ("เป็นทางตรงครับ … เดี๋ยวขอเอาไปปรึกษาทีม") — ยังเป็นงานเดิม (redteam R17 r2)
    CONTINUE_RX = re.compile(r"ปรึกษา|คุยกับ|หัวหน้า|ไว้ก่อน|เข้าใจแล้ว|ทางตรง|ทางโค้ง")
    COMPLAINT_RX = re.compile(r"ถามซ้ำ|บอกไปแล้ว|ตอบไปแล้ว|ไม่รู้เรื่อง|ไม่เข้าใจ|งง")
    NEGATED_JOB_RX = re.compile(r"(?:ไม่ใช่|not)\s*(?:ไลน์|งาน|สาย|line\s*)?[^\s,]{0,20}", re.IGNORECASE)
    CORRECTION_RX = re.compile(r"ไม่ใช่|ที่จริง|จริง\s*ๆ|ขอโทษ|เปลี่ยนเป็น|แก้เป็น|actually|sorry", re.IGNORECASE)
    STEP_PENDING = {"pitch": "modutech_pitch", "pitch_confirm": "modutech_pitch", "pitch_retry": "modutech_pitch",
                    "temp": "modutech_temp", "wet": "wet_or_dry", "need": "modutech_need"}

    def _step_question(self, flow: str, slots: dict) -> str:
        said = slots.get(NF.PITCH_SAID_KEY)
        opts = NF.nearest_pitches(self.mod, said) if isinstance(said, (int, float)) else []
        if flow == "pitch_confirm" and opts:
            return NF.ask_pitch_confirm_th(said, opts)
        if flow == "pitch_retry" and opts:
            return NF.ask_pitch_again_th(opts)
        return {"pitch": NF.ASK_PITCH_TH, "pitch_confirm": NF.ASK_PITCH_TH, "pitch_retry": NF.ASK_PITCH_TH,
                "temp": NF.ASK_TEMP_TH, "wet": NF.ASK_WET_TH, "need": NF.ASK_NEED_TH}[flow]

    def _read_rules(self, flow: str, ans: str):
        """กฎเดิม (regex) — ผลรูปเดียวกับตัวตีความ LLM"""
        from core.answer_interpreter import AnswerReading
        if flow in ("pitch", "temp", "wet", "pitch_confirm", "pitch_retry") and NF.is_question(ans):
            return AnswerReading("question")
        if NF.is_unknown(ans):
            return AnswerReading("unknown")
        if flow in ("pitch", "pitch_retry", "pitch_confirm"):
            v = NF.parse_pitch(ans, bare_number=True)
            if v is not None:
                return AnswerReading("value", v, "mm")
            if flow == "pitch_confirm":
                if NF._NO_RX.search(ans):
                    return AnswerReading("no")
                if NF._YES_RX.search(ans):
                    return AnswerReading("yes")
            return AnswerReading("unknown")
        if flow == "temp":
            v = NF.parse_temp(ans, bare_number=True)
            return AnswerReading("value", v, "c") if v is not None else AnswerReading("unknown")
        return AnswerReading("other")

    def pending_reask(self, st: dict) -> Optional[str]:
        """คำถามที่ถามค้างอยู่ (ถามทีละข้อ) — แกนกลางใช้ถามซ้ำหลังตอบเรื่องอื่นสั้น ๆ เช่นขอเบอร์ (core/decide.py)"""
        slots = (st or {}).get("slots") or {}
        flow = slots.get(NF.FLOW_KEY)
        return self._step_question(flow, slots) if flow in self.STEP_PENDING and not (st or {}).get("codes") else None

    def _read_rules_sure(self, flow: str, ans: str):
        """ผลของกฎเมื่อมั่นใจ (คืน None = กฎไม่แน่ใจ ให้ LLM อ่าน)

        26 ต.ค.: เรียก LLM ทุกคำตอบทำให้เทิร์นตอบคำถามช้าลง 1.3–1.7 วินาที (lat_rules/lat_llm · 115 คู่)
        ทั้งที่คำตอบส่วนใหญ่สั้นและชัด ("2 นิ้ว" "ใช่" "5 องศา" "ไม่ทราบ") — กฎอ่านถูกอยู่แล้ว
        มั่นใจ = อ่านได้ค่าเดียวโดยไม่มีอะไรขัด · กฎเดิมคืน "unknown" เมื่ออ่านไม่ออกด้วย ซึ่งแยกไม่ได้จาก
        "ลูกค้าบอกว่าไม่ทราบ" จึงนับเฉพาะเมื่อเจอคำว่าไม่ทราบจริงและไม่มีตัวเลข"""
        from core.answer_interpreter import AnswerReading
        a = ans or ""
        nums = re.findall(r"\d+(?:[.,]\d+)?", a)
        if flow in ("pitch", "temp", "wet", "pitch_confirm", "pitch_retry") and NF.is_question(a) and not nums:
            return AnswerReading("question")
        if NF.is_unknown(a) and not nums:
            return AnswerReading("unknown")
        # ตัวเลขเดียว หรือคำที่แปลงเป็นค่าได้เอง ("ครึ่งนิ้ว" "อุณหภูมิห้อง") — สองตัวขึ้นไปไม่แน่ใจ
        # หลายตัวเลขแต่มีค่าติดคำว่าพิทช์ ("1 inch pitch … 5 C") — อ่านเฉพาะค่าที่ติดคำนั้น (redteam R18)
        if flow in ("pitch", "pitch_retry") and len(nums) > 1:
            sp = NF.stated_pitch(a)
            if sp is not None:
                return AnswerReading("value", sp, "mm")
        if flow in ("pitch", "pitch_retry", "pitch_confirm") and len(nums) <= 1:
            v = NF.parse_pitch(a, bare_number=True)
            if v is not None and not (flow == "pitch_confirm" and NF._NO_RX.search(a)):
                return AnswerReading("value", v, "mm")
        if flow == "pitch_confirm" and not nums:
            # "ไม่ใช่" มีคำว่า "ใช่" อยู่ข้างใน — ตัดคำปฏิเสธออกก่อนหาคำรับ (lat2 26 ต.ค.: "ไม่ใช่" ไป LLM +2.1 วิ)
            no = bool(NF._NO_RX.search(a))
            rest = NF._NO_RX.sub(" ", a)
            if no:                                   # "ไม่ใช่ครับ" — หางเสียงไม่ใช่คำรับ
                rest = re.sub(r"ครับ|ค่ะ|คะ|นะ|จ้า", " ", rest)
            yes = bool(NF._YES_RX.search(rest))
            if yes != no:
                return AnswerReading("yes" if yes else "no")
        if flow == "temp" and len(nums) <= 1:
            v = NF.parse_temp(a, bare_number=True)
            if v is not None:
                return AnswerReading("value", v, "c")
        if flow == "wet" and not nums:
            wd = extract_modutech_slots(a, ()).get("wet_or_dry")
            if wd:
                return AnswerReading("value", None, None, wet_or_dry=wd)
        return None

    def _read_answer(self, flow: str, ans: str, slots: dict):
        """คืน (reading, ที่มา) · ที่มา = "LLM" หรือ "กฎ"
        กฎก่อน (มั่นใจ = ไม่เรียก LLM) → LLM → กฎเดิมเป็นทางสำรองเมื่อ LLM ล้ม"""
        sure = self._read_rules_sure(flow, ans)
        if sure is not None:
            return sure, "กฎ"
        interp = getattr(self, "_interpreter", None)
        expect = self.STEP_EXPECT.get(flow)
        if interp is not None and expect and ans.strip():
            r = interp.interpret(self._step_question(flow, slots), ans, expect)
            if r is not None:
                return r, "LLM"
        return self._read_rules(flow, ans), "กฎ (เดา)"

    def _need_flow(self, text: str, st: dict, flow: str, answer: str) -> Optional[Decision]:
        """ขั้นต่อไปของการถามทีละข้อ · text = ข้อความรวมทุกคำตอบ · answer = คำตอบดิบของเทิร์นนี้
        คืน None = ลูกค้าเปลี่ยนเรื่อง (ตัวตีความ LLM บอก "other") → ออกจากการถาม ให้ทางปกติตัดสินต่อ"""
        slots, key = st["slots"], self.info.key
        ans = answer or ""
        reading, src = (None, "")
        if ans and flow in self.STEP_EXPECT and flow != "need":
            reading, src = self._read_answer(flow, ans, slots)
        tag = f" · ตีความ: {src}" if src else ""

        def ask(step: str, reply: str, why: str, pending: str) -> Decision:
            slots[NF.FLOW_KEY] = step
            if slots.get(self.REASK_KEY) not in (None, step):
                slots.pop(self.REASK_KEY, None)
            return Decision("ask", key, reply, why + tag, topic="recommend", effective_text=text,
                            payload=dict(codes=[], slots=dict(slots)), pending=pending)

        pend = self.STEP_PENDING
        # บอกค่าพร้อมถามยืนยัน ("ห่างกันประมาณ 5 เซน น่าจะตรงกับ 2 นิ้วมั้ยครับ") — มีค่าที่มีหน่วยชัด = คำตอบ
        # sim5 G05 (26 ต.ค.): ตัวตีความอ่านเป็นคำถาม บอทอธิบายพิทช์ซ้ำ ลูกค้า "บอกไปแล้วไง ถามซ้ำทำไม"
        if reading is not None and reading.kind == "question" and ans:
            from core.answer_interpreter import AnswerReading
            v = (NF.parse_pitch(ans) if flow in ("pitch", "pitch_retry", "pitch_confirm") else
                 NF.parse_temp(ans) if flow == "temp" else None)
            if v is not None:
                reading = AnswerReading("value", v, "mm" if flow != "temp" else "c")
        if reading is not None and reading.kind == "question":
            return ask(flow, f"{NF.EXPLAIN_TH[flow]}\n\n{self._step_question(flow, slots)}",
                       f"ถามทีละข้อ: ลูกค้าถามกลับ ({flow}) → อธิบาย", pend[flow])
        # ตอบข้ออื่นมาแทน ("ห้องปกติ แห้ง" ตอนถามพิทช์) → เก็บค่าที่ได้ แล้วถามข้อเดิมอีกครั้ง
        # redteam R13 (26 ต.ค.): ตัวตีความ LLM บอก "เปลี่ยนเรื่อง" → เลิกถาม → ตอบจากข้อความนี้อย่างเดียว ไม่รู้งาน
        # เสนอรุ่นพิทช์ 2 นิ้วรุ่นเดียว (ในเล่มมี 17 รุ่นสำหรับงานตรวจจับโลหะ) แล้วลูกค้าขอครึ่งนิ้ว
        # เฉพาะอ่านไม่ออก/เปลี่ยนเรื่อง — "ไม่ทราบ แต่ไลน์เปียก" เป็นคำตอบ (ไม่ทราบพิทช์) ไม่ต้องถามซ้ำ
        not_value = reading is None or reading.kind == "other" or src == "กฎ (เดา)"
        if ans and flow in ("pitch", "pitch_retry") and not_value and slots.get(self.REASK_KEY) != flow \
                and NF.parse_pitch(ans) is None and NF.stated_pitch(ans) is None:
            side_temp = NF.parse_temp(ans)
            side_wet = extract_modutech_slots(ans, ()).get("wet_or_dry")
            if side_temp is not None or side_wet:
                if side_temp is not None and "temp_c" not in slots:
                    slots["temp_c"] = side_temp
                slots[self.REASK_KEY] = flow
                return ask(flow, f"{NF.SIDE_INFO_TH}{self._step_question(flow, slots)}",
                           f"ถามทีละข้อ: ตอบข้ออื่นมาแทน ({flow}) → เก็บไว้ แล้วถามข้อเดิม", pend[flow])
        # กฎอ่านไม่ออก (และไม่มี LLM หรือ LLM ล้ม) → ถามข้อเดิมซ้ำหนึ่งครั้ง ครั้งที่สองค่อยนับว่าไม่ทราบ
        # 26 ต.ค. (CONV-20): ลูกค้าพิมพ์ "modutech" ตอนถามพิทช์ เดิมบันทึกว่า "ไม่ทราบพิทช์" ทันที
        if src == "กฎ (เดา)" and flow in pend and slots.get(self.REASK_KEY) != flow:
            slots[self.REASK_KEY] = flow
            return ask(flow, f"{NF.REASK_TH}{self._step_question(flow, slots)}",
                       f"ถามทีละข้อ: อ่านคำตอบไม่ออก ({flow}) → ถามซ้ำหนึ่งครั้ง", pend[flow])
        if reading is not None and reading.kind == "other" and src == "LLM" and slots.get(self.REASK_KEY) == flow \
                and flow in pend and not self._need_in(ans):
            # ถามซ้ำไปแล้วหนึ่งครั้งยังไม่ได้ค่า ("ถามซ้ำอยู่ได้ ไม่คุยละ") → นับว่าไม่ทราบข้อนี้ แล้วไปต่อ
            # redteam R13 r2 (27 ต.ค.): เดิมเลิกถาม → ตอบจากข้อความบ่นอย่างเดียว ไม่รู้งาน → "ไม่ได้ระบุงานนี้" (ไม่จริง)
            reading = None
        if reading is not None and reading.kind == "other" and src == "LLM":
            # ลูกค้าเปลี่ยนเรื่องกลางการถาม — เลิกถาม (ค่าที่ได้แล้วยังเก็บไว้)
            slots.pop(NF.FLOW_KEY, None)
            slots.pop(NF.PITCH_SAID_KEY, None)
            return None
        # แก้อุณหภูมิระหว่างตอบข้ออื่น ("ขอโทษ ลบ 40 ต่างหาก ส่วนพิทช์เอา 50.6") — redteam R17 r2 (27 ต.ค.)
        # เดิมเก็บแค่พิทช์ อุณหภูมิยังเป็น -20 ตามที่บอกครั้งแรก
        # ค่าล่าสุดชนะ — เดิมขั้นอุณหภูมิอ่านจากข้อความรวม ได้ค่าแรก (-20) แทนค่าที่แก้ (-40)
        if ans and flow != "temp":
            t_new = NF.parse_temp(ans)
            if t_new is not None and t_new != slots.get("temp_c"):
                slots["temp_c"] = t_new
                if "operating_temp_c" in slots:
                    slots["operating_temp_c"] = t_new
        if reading is not None and reading.wet_or_dry and not slots.get("wet_or_dry"):
            slots["wet_or_dry"] = reading.wet_or_dry

        def take_pitch(v):
            """พิทช์ที่ไม่มีในแคตตาล็อกแต่ใกล้ค่าที่มี → ถามยืนยันก่อน (ผู้ใช้เลือก 25 ต.ค.: 50.6 → หมายถึง 50.8 ไหม)"""
            if isinstance(v, (int, float)):
                opts = NF.nearest_pitches(self.mod, v)
                if opts:
                    slots[NF.PITCH_SAID_KEY] = v
                    return ask("pitch_confirm", NF.ask_pitch_confirm_th(v, opts),
                               f"ถามทีละข้อ: ยืนยันพิทช์ ({v:g} ไม่มีในแคตตาล็อก)", "modutech_pitch")
            slots["pitch_mm"] = v
            return None

        def number(expect):
            return reading.number(expect) if (reading is not None and reading.kind == "value") else None

        if flow == "pitch_confirm" and "pitch_mm" not in slots:
            said = slots.get(NF.PITCH_SAID_KEY)
            opts = NF.nearest_pitches(self.mod, said) if isinstance(said, (int, float)) else []
            v = number("number_mm")
            if reading is not None and reading.kind == "no":
                # "ไม่ใช่" → ถามค่าจริง (ผู้ใช้ 25 ต.ค.) · เก็บค่าที่พิมพ์ตอนแรกไว้ใช้ในคำถาม
                return ask("pitch_retry", NF.ask_pitch_again_th(opts),
                           f"ถามทีละข้อ: ลูกค้าบอกว่าไม่ใช่ {opts} → ถามพิทช์จริง", "modutech_pitch")
            slots.pop(NF.PITCH_SAID_KEY, None)
            if v is not None:
                slots["pitch_mm"] = v
            elif reading is not None and reading.kind == "yes" and len(opts) == 1:
                slots["pitch_mm"] = opts[0]
            else:
                slots["pitch_mm"] = NF.UNKNOWN            # หลายตัวเลือกแต่ไม่บอกเลข / ไม่ทราบ = ไม่เดาแทน
        if flow == "pitch_retry" and "pitch_mm" not in slots:
            # ถามซ้ำได้รอบเดียว — ตอบเลขอะไรมาก็ใช้เลขนั้น (ไม่มีในแคตตาล็อก บอทจะบอกตรง ๆ ตอนตอบ) กันวนไม่จบ
            slots.pop(NF.PITCH_SAID_KEY, None)
            v = number("number_mm")
            slots["pitch_mm"] = v if v is not None else NF.UNKNOWN
        if flow == "pitch" and "pitch_mm" not in slots:
            v = number("number_mm")
            d = take_pitch(v if v is not None else NF.UNKNOWN)
            if d is not None:
                return d
        if flow == "temp" and "temp_c" not in slots:
            v = number("number_c")
            slots["temp_c"] = v if v is not None else NF.UNKNOWN

        if "pitch_mm" not in slots:
            v = NF.parse_pitch(text)                      # บอกมาแล้วพร้อมหน่วย/คำว่าพิทช์ → ไม่ถาม
            if v is None:
                return ask("pitch", NF.ASK_PITCH_TH, "ถามทีละข้อ: พิทช์", "modutech_pitch")
            d = take_pitch(v)
            if d is not None:
                return d
        if "temp_c" not in slots:
            v = slots.get("operating_temp_c")
            if v is None:
                # บอกอุณหภูมิเป็นคำมาก่อน ("อุณหภูมิ room temp ปกติ" ตอนตอบว่าลำเลียงอะไร) — ไม่ถามซ้ำ
                # main_sim G07 (26 ต.ค.): ลูกค้า "ก็บอกไปแล้วว่า room temp ปกติครับ ถามซ้ำทำไม"
                v = NF.parse_temp(text)
            if v is None:
                return ask("temp", NF.ASK_TEMP_TH, "ถามทีละข้อ: อุณหภูมิ", "modutech_temp")
            slots["temp_c"] = v
        if flow != "wet" and not slots.get("wet_or_dry") and \
                NF.wet_dry_matters(self.mod, self._need_candidates(text), slots.get("pitch_mm"), slots.get("temp_c")):
            return ask("wet", NF.ASK_WET_TH, "ถามทีละข้อ: เปียก/แห้ง (ผลกรองอุณหภูมิต่างกัน)", "wet_or_dry")

        slots.pop(NF.FLOW_KEY, None)
        slots.pop(self.REASK_KEY, None)
        self._remember_need(text, st)
        return Decision("answer", key, reason="ค้นตามการใช้งาน · กรองพิทช์/อุณหภูมิที่ลูกค้าบอก" + tag,
                        effective_text=text, payload=dict(codes=[], slots=dict(slots)))

    # ─────────────────────────── ข้ามแบรนด์ ───────────────────────────

    def cross_brand_section(self, topic: str) -> Optional[list[str]]:
        if topic != "stainless":
            return None
        res = self.search.search(ExploratoryQuery(pin_material="SS"))
        lines = []
        if res["matches"]:
            lines.append(f"• มี {res['matched']} รุ่นที่ใช้ก้าน (พิน) สแตนเลส — ตัวสายพานเป็นพลาสติก:")
            for m in res["matches"]:
                mats = ", ".join(f"{h['belt_material']}/{h['pin_material']}" for h in m["variants"])
                lines.append(f"  – {m['belt_code']} ({m['surface_type']}) เกรด {mats}")
        else:
            lines.append("• ไม่มีรุ่นที่ใช้ชิ้นส่วนสแตนเลส")
        return lines

    # ─────────────────────────── 2 + 4 · ค้นและ prompt / 6 · รูป ───────────────────────────

    def _rt(self):
        if self.runtime is None:
            raise RuntimeError("ปลั๊กอิน Modutech ถูกสร้างแบบไม่มี runtime (โหมดตัดสินอย่างเดียว) — เรียก LLM ไม่ได้")
        return self.runtime

    def build_turn(self, decision, turn):
        return self._rt().build_turn(decision, turn)

    MAX_FOCUS_FROM_REPLY = 6

    def _new_request(self, raw: str) -> bool:
        """ข้อความเทิร์นนี้ขอของใหม่ (งาน · อุตสาหกรรม · ผิว) — ไม่ใช่ถามต่อเรื่องรุ่นที่เพิ่งเสนอ"""
        low = (raw or "").lower()
        if any(th.lower() in low for th, _ in self.search.surfaces) or "กันลื่น" in low:
            return True
        # เปลี่ยนสเปก: พิทช์ใหม่ ("ถ้าเป็นพิทช์ 1 นิ้วล่ะ") · "ถ้า … องศา" — รุ่นที่เสนอมีพิทช์ตายตัว
        # จึงไม่ใช่ถามต่อเรื่องรุ่นเดิม (C16 · 26 ต.ค. เดิมได้ EC508 C/DT เป็นโฟกัสแล้วค้นพิทช์ทั้งฐาน)
        if NF.stated_pitch(raw) is not None:
            return True
        # "เดี๋ยวนะ วัดใหม่แล้วเป็น 2 นิ้ว" (redteam R01 r2) — แก้พิทช์โดยไม่มีคำว่าพิทช์
        if self.REMEASURE_RX.search(raw or "") and NF.parse_pitch(raw) is not None \
                and not re.search(r"กว้าง|ยาว|หนา|width|length", raw or "", re.IGNORECASE):
            return True
        if has(r"ถ้า|เปลี่ยนเป็น", raw or "") and \
                extract_modutech_slots(raw or "", ()).get("operating_temp_c") is not None:
            return True
        try:
            return bool(self.search.match_application(raw)) or bool(self.search.match_industry(raw))
        except Exception:                                    # noqa: BLE001
            return False

    def _use_offered(self, raw: str, st: dict) -> None:
        """รุ่นที่บอทเพิ่งเสนอ (_offered) → โฟกัส เฉพาะเมื่อลูกค้าอ้างถึง

        test_conversation_leaks 25 ต.ค.: เดิมตั้งรุ่นที่เสนอเป็นโฟกัสทันที คำขอใหม่ ("แล้วถ้าเป็นขนมปังล่ะ"
        "มีรุ่นอื่นอีกไหม" "ขอแบบผิวกันลื่น") จึงได้รุ่นเดิมซ้ำ (C07 · C23 · C19)
            อ้างถึง (ตัวแรก · สองตัว · เทียบ …)         → รุ่นที่อ้าง
            ขอรุ่นอื่น                                → ค้นใหม่ ตัดรุ่นที่เสนอไปแล้ว
            ขอของใหม่ (งาน · อุตสาหกรรม · ผิว)          → ค้นใหม่
            ถามต่อสั้น ๆ ("แพงไหม" "ทำไม")              → รุ่นที่เสนอทั้งหมด
        """
        slots = st["slots"]
        offered = list(slots.get(self.OFFERED_KEY) or [])
        if not offered:
            return
        from_offer = not st["codes"] or set(st["codes"]) <= set(offered)
        if not from_offer:
            return
        r = raw or ""
        if has(OTHER_RX, r):
            st["codes"] = []
            slots[EXCLUDE_KEY] = offered
            slots.pop(self.OFFERED_KEY, None)
            return
        refers = has(REFER_RX, r)
        if self._new_request(r) and not refers:
            st["codes"] = []
            slots.pop(self.OFFERED_KEY, None)
            return
        if has(r"ตัวแรก|อันแรก|รุ่นแรก|ตัวที่\s*1|อันที่\s*1", r):
            st["codes"] = offered[:1]
        elif has(r"ตัวหลัง|อันหลัง|ตัวที่สอง|ตัวที่\s*2|อันที่\s*2|รุ่นที่สอง", r) and len(offered) > 1:
            st["codes"] = offered[1:2]
        elif refers or len(r) <= FOLLOWUP_CHARS:
            st["codes"] = offered

    def finish_turn(self, decision, turn, llm, result):
        out = self._rt().finish_turn(decision, turn, llm, result)
        # คำตอบแนะนำรุ่น (ยังไม่มีรหัสในโฟกัส) → รุ่นที่คำตอบเสนอกลายเป็นโฟกัสของเทิร์นหน้า
        # 25 ต.ค. เทสบนเว็บ: เสนอ MD508 C กับ EC508 PR11 แล้วลูกค้าถาม "ขอดูสเปคทั้งสองตัวเทียบกัน"
        # บอทไม่รู้ว่า "สองตัว" คือตัวไหน เพราะสถานะไม่มีรหัสเลย (ชื่อรุ่นอยู่แค่ในข้อความของ LLM)
        # เสนอเกิน 6 รุ่น = รายการยาว ไม่ตั้งโฟกัส (ลูกค้าต้องระบุเอง)
        had_codes = bool((decision.payload or {}).get("codes"))
        if not had_codes and decision.action in ("answer", "search") and out.reply:
            mentioned = list(self.detector.detect(out.reply).parsed.belt_codes)
            # เสนอยาวเกิน 6 รุ่น → จำ 6 รุ่นแรกที่เอ่ย (ลำดับเดียวกับในคำตอบ) — ไม่จำเลย = "ทำไม" / "แพงไหม"
            # ถัดจากรายการยาวถูกตีว่านอกเรื่อง (conv_r1/r2 CONV-30 · Gemini จริง 25 ต.ค. ทั้งสองรอบ)
            mentioned = mentioned[:self.MAX_FOCUS_FROM_REPLY]
            if mentioned:
                slots = {k: v for k, v in ((decision.payload or {}).get("slots") or {}).items() if k != EXCLUDE_KEY}
                out.state_patch = {"slots": {**slots, self.OFFERED_KEY: mentioned}}
        return out

    def close(self) -> None:
        """ปิด Qdrant แบบไฟล์ก่อนโปรแกรมจบ (ไม่บังคับในสัญญา — assistant.py เรียกผ่าน atexit)"""
        try:
            if self.runtime is not None and getattr(self.runtime, "retriever", None) is not None:
                self.runtime.retriever.client.close()
        except Exception:
            pass

    def image_scorer(self):
        return None                      # ยังไม่มีรูปจริง — เปิดเมื่อ brand.yaml › image ผ่าน (enabled: auto)

    def image_gate(self):
        """ประตูรูป (brand.yaml › image_gate) — ไม่ใช่ตัวให้คะแนน · None = ปิด (core/image_policy ถามแบรนด์แทน)"""
        return getattr(self, "_image_gate", None)


def create(ctx):
    """registry เรียก — โหลดแคตตาล็อก (ตรวจ v30_3) กราฟ และ collection แยกของ Modutech"""
    import os
    from brands.modutech.kg import load_modutech_kg
    from brands.modutech.router import modutech_retriever_config_kwargs
    from brands.modutech.runtime import ModutechRuntime
    from core.protocol import BrandInfo
    cfg, d = ctx.config, ctx.brand_dir
    data = cfg.get("data") or {}

    def path(rel):
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(d, rel))

    i = cfg["info"]
    info = BrandInfo(key=cfg["key"], name=i["name"], order=i["order"], kind_th=i["kind_th"],
                     menu_line_th=i["menu_line_th"], offtopic_th=i["offtopic_th"],
                     category_th=i["category_th"], answer_patterns=tuple(i.get("answer_patterns") or ()))
    cat = Catalogue(path(data["catalogue"]))          # ตรวจ v30 + นับครบ ไม่ใช่ v30 = หยุด
    plugin = ModutechPlugin(info, cat, state_defaults=cfg.get("state"))

    sh = ctx.shared
    if sh.get("tool_log") is not None:
        # กราฟความสัมพันธ์สินค้า — ถ้าไฟล์หายหรือลายนิ้วมือไม่ตรงกับ JSON จะเตือนแล้วสร้างจาก JSON ให้รอบนั้น
        kg = load_modutech_kg(cat, path(data["graph_db"]))
        retriever = None
        qpath = path(data["qdrant_path"])
        if sh.get("jina_model") is not None and os.path.exists(qpath):
            from retriever_v4 import RetrieverV4, RetrieverV4Config
            mod_db = {
                p["belt_code_id"]: {"product_id": p["belt_code_id"], "Ref": p["belt_code"],
                                    "belt_series": p.get("belt_series", ""),
                                    "product_type": p["retrieval_card"].get("surface_type", ""),
                                    "Material": ",".join(p["retrieval_card"].get("materials") or [])}
                for p in cat.products
            }
            kw = modutech_retriever_config_kwargs()
            kw["qdrant_path"] = qpath
            # ViT ของแบรนด์อื่นไม่ส่งเข้ามา — retriever ตัวนี้ค้นข้อความอย่างเดียว (image_collection ไม่มีจริง)
            retriever = RetrieverV4(
                cfg=RetrieverV4Config(**kw, device=sh["device"]),
                jina_tokenizer=sh["jina_tokenizer"], jina_model=sh["jina_model"],
                vit_processor=None, vit_model=None,
                siglip_processor=sh["siglip_processor"], siglip_model=sh["siglip_model"],
                product_db=mod_db, kg=kg,
            )
            print(f"✅ Modutech: {len(mod_db)} สายพาน · collection {kw['text_collection']}")
        else:
            print(f"⚠️ Modutech retriever ปิดอยู่ (ไม่พบ {qpath}) — ยังตอบจากรหัสและค้นทั้งฐานได้")
        plugin.runtime = ModutechRuntime(cat, plugin.search, kg, retriever, sh["tool_log"])
        plugin._interpreter = sh.get("answer_interpreter")      # None = กฎเดิม (need_flow)
        if sh.get("device") is not None:
            from brands.modutech.image_gate import load_gate
            plugin._image_gate, why = load_gate(cfg["key"], d, cfg.get("image_gate"), sh["device"])
            print(f"{'✅' if plugin._image_gate else '⚠️'} Modutech ประตูรูป: "
                  f"{'เปิด' if plugin._image_gate else 'ปิด'} — {why}")
    return plugin
