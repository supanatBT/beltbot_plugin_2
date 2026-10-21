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
from core.sales import attach_handoff, escalation_gate
from core.text import any_word, has

MOD_TEMP_TOPIC = r"อุณหภูมิ|องศา|°\s*[cC]|ร้อน|เย็น|แช่แข็ง|ฟรีซ|freez|temp|ทนความร้อน|ทนเย็น"
MOD_STRENGTH_TOPIC = r"แรงดึง|ความแข็งแรง|รับแรง|strength|N\s*/\s*m|รับน้ำหนัก|โหลด"
MOD_RECOMMEND = r"แนะนำ|ใช้รุ่นไหน|ใช้อะไรดี|ตัวไหนดี|รุ่นไหนดี|เหมาะกับ|มีอะไรบ้าง|สายพานอะไร"

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
    if has(r"ไลน์ตรง|วิ่งตรง|straight|ไม่มีโค้ง|ไม่เลี้ยว", t):
        out["line_shape"] = "straight"
    elif has(r"มีโค้ง|วิ่งโค้ง|เลี้ยว|โค้ง|curve|radius", t):
        out["line_shape"] = "curve"
    for m in materials:                                 # ยาวก่อน: POM-NL ก่อน POM
        if re.search(rf"(?<![A-Za-z]){re.escape(m)}(?![A-Za-z])", t, re.IGNORECASE):
            out["material"] = m.upper()
            break
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:°\s*C|องศา|℃)", t)
    if m:
        out["operating_temp_c"] = float(m.group(1))
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
        return ["modutech", "โมดูล"] + list(self.detector.weak_terms)

    @property
    def weak_terms(self) -> list[str]:
        return self.detector.weak_terms

    # ─────────────────────────── 5 · สถานะ ───────────────────────────

    def empty_state(self) -> dict:
        return {k: (type(v)() if isinstance(v, (list, dict)) else v) for k, v in self._state_defaults.items()}

    def has_focus(self, st: dict) -> bool:
        return bool(st.get("codes"))

    def on_brand_switch(self, st: dict) -> dict:
        # ล้างรุ่นกับ slot · sprocket_codes ไม่ล้าง (ของเดิมก็ไม่ล้าง — เทิร์นถัดไปเขียนทับเอง)
        return {**st, "codes": [], "slots": {}}

    # slot ที่ decide รู้จัก — ค่าอื่นทิ้ง (ย้ายมาจาก webapi/bot.py _SLOT_KEYS ชั้น 6)
    SLOT_KEYS = ("wet_or_dry", "material", "line_shape", "operating_temp_c")

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
        if codes.belt_codes:
            st["codes"] = list(codes.belt_codes)
        # รหัสสเตอร์ไม่เก็บลง state เพราะไม่ใช่ "รุ่นที่อยู่ในความสนใจ" แต่ต้องส่งต่อ
        # ให้ turn แปลงกลับเป็นสายพานด้วยกราฟ ไม่งั้นรหัสที่ลูกค้าพิมพ์หายทั้งตัว
        st["sprocket_codes"] = list(codes.sprocket_codes)

        esc = escalation_gate(text, belt_code=(st["codes"] or [None])[0])
        if esc and not esc.has_spec_question:
            return Decision("escalate", self.info.key, esc.reply_th, f"หัวข้อ {esc.topics}",
                            topic="escalate", effective_text=text,
                            payload=dict(codes=st["codes"], slots=dict(slots)))
        d = self._decide_core(text, st, codes)
        if esc:
            attach_handoff(d, esc.handoff_th, esc.topics)
        # แนบรหัสสเตอร์ที่จุดเดียว แทนการแก้ทุก return ใน _decide_core
        # ซึ่งมี 7 ทางออกและเพิ่มได้เรื่อย ๆ ถ้าแก้ทีละที่จะมีทางที่ลืม
        if codes.sprocket_codes and isinstance(d.payload, dict):
            d.payload["sprocket_codes"] = list(codes.sprocket_codes)
        return d

    def _decide_core(self, text: str, st: dict, codes) -> Decision:
        slots = st["slots"]
        key = self.info.key

        q = self.search.parse(text)
        if q is not None and not codes.belt_codes:
            return Decision("search", key, reason="คำถามเชิงสำรวจ → ค้นทั้งฐาน", topic="explore",
                            effective_text=text,
                            payload=dict(codes=[], slots=dict(slots), search_query=q.__dict__))

        if codes.candidates and not codes.belt_codes:
            shown = codes.candidates[:10]
            reply = ("รหัสนี้มีหลายรุ่นครับ หมายถึงรุ่นไหนครับ\n"
                     + "\n".join(f"• {c} — {self.mod.by_code[c]['retrieval_card'].get('surface_type', '')}"
                                 for c in shown))
            return Decision("ask", key, reply, "รหัสกำกวม", topic="code", effective_text=text,
                            payload=dict(codes=[], candidates=codes.candidates, slots=dict(slots)),
                            pending="modutech_code")

        focus = self.mod.records(st["codes"])
        temp_topic = has(MOD_TEMP_TOPIC, text) or "operating_temp_c" in slots and not st["codes"]
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
        has_need = bool(any_word(self.detector.weak_terms, text)) or bool(slots) \
            or bool(codes.sprocket_codes)
        if not focus and not has_need and has(MOD_RECOMMEND + r"|สายพาน", text):
            return Decision("ask", key, ASK_MODUTECH_NEED_TH, "ยังไม่รู้งานของลูกค้า",
                            topic="recommend", effective_text=text,
                            payload=dict(codes=[], slots=dict(slots)), pending="modutech_need")

        return Decision("answer", key, reason="รหัสชัด" if focus else "ค้นตามการใช้งาน",
                        topic="temperature" if temp_topic else None, effective_text=text,
                        payload=dict(codes=st["codes"], slots=dict(slots)))

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

    def finish_turn(self, decision, turn, llm, result):
        return self._rt().finish_turn(decision, turn, llm, result)

    def close(self) -> None:
        """ปิด Qdrant แบบไฟล์ก่อนโปรแกรมจบ (ไม่บังคับในสัญญา — assistant.py เรียกผ่าน atexit)"""
        try:
            if self.runtime is not None and getattr(self.runtime, "retriever", None) is not None:
                self.runtime.retriever.client.close()
        except Exception:
            pass

    def image_scorer(self):
        return None                      # ยังไม่มีรูปจริง — เปิดเมื่อ brand.yaml › image ผ่าน (enabled: auto)


def create(ctx):
    """registry เรียก — โหลดแคตตาล็อก (ตรวจ v30_1) กราฟ และ collection แยกของ Modutech"""
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
    return plugin
