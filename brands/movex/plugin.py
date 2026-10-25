"""
brands/movex/plugin.py
======================
ปลั๊กอิน Movex — ย้ายมาจาก DialogueManager (dialogue_state.py) ชั้น 4 · ตรรกะเท่าเดิม

สิ่งที่เปลี่ยนตอนย้าย
  st.movex_pids → st["pids"] · st.movex_series → st["series"]   (สถานะของแบรนด์ตัวเอง)
  VIT_ANSWER / VIT_SERIES → อ่านจาก thresholds.json (answer / series) ค่าเท่าเดิม 0.90 / 0.50
  pending ส่งคืนทาง Decision.pending (แกนกลางเก็บคำถามเดิมให้)

ค้นข้อมูล รูป tool และ prompt อยู่ใน runtime.py (ต้องใช้โมเดล) — ชุดเกตสร้างปลั๊กอินแบบไม่มี runtime ได้
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from brands.movex import detect as _detect
from core.protocol import BrandInfo, BrandSignal, DecideInput, Decision
from core.sales import attach_handoff, escalation_gate
from core.text import has, norm_code

# หัวข้อที่เป็นเรื่องการค้าล้วน (รัศมีวงเลี้ยว/สเตอร์ของ Movex มีในฐานข้อมูล ตอบเองได้)
# ช่องทางติดต่อกับการสั่งซื้อเป็นเรื่องการค้าของทุกแบรนด์ จึงใส่ไว้ด้วย
# รอบ 5 (11 ต.ค. ค่ำ · RT-014): ลูกค้าบอกงาน ("โซ่ลำเลียงขวด PET") แต่ไม่รู้รุ่น — เดิมได้แค่ "ขอทราบรุ่นก่อน"
# ซึ่งลูกค้าตอบไม่ได้ ตอนนี้ยกรุ่นที่ช่อง usage ในข้อมูล Movex เขียนถึงงานนั้นมาให้เลือกก่อน (ข้อความตายตัว ไม่ผ่าน LLM)
# คำในคำถาม → คำใน usage · ต้องตรงทุกคำที่ลูกค้าพูด ("ขวด PET" = bottle และ PET)
MOVEX_APP_TERMS = [
    ("ขวด", re.compile(r"ขวด|bottle", re.I), re.compile(r"bottl", re.I)),   # bottles · bottling lines
    ("PET", re.compile(r"\bPET\b", re.I), re.compile(r"\bPET\b")),
    ("กระป๋อง", re.compile(r"กระป๋อง|\bcans?\b", re.I), re.compile(r"(?<!jerry )\bcans?\b", re.I)),  # jerry can = แกลลอน
    ("แก้ว", re.compile(r"แก้ว|glass", re.I), re.compile(r"glass", re.I)),
    ("ลัง", re.compile(r"ลัง|crate", re.I), re.compile(r"crate", re.I)),
    ("กล่อง", re.compile(r"กล่อง|box|carton", re.I), re.compile(r"box|carton", re.I)),
    ("ถัง", re.compile(r"ถัง|แกลลอน|keg|drum|jug", re.I), re.compile(r"keg|drum|jug", re.I)),
]
_CHAIN_TYPE_TH = {"Straight Running Chain": "โซ่ไลน์ตรง", "Sideflexing Chain": "โซ่เลี้ยวโค้งได้"}


def movex_application_block(text: str, products: dict) -> Optional[str]:
    """รุ่นโซ่ที่ usage เขียนถึงงานในคำถาม — None ถ้าคำถามไม่มีคำงาน หรือไม่มีรุ่นที่ตรงทุกคำ"""
    terms = [(label, rx_usage) for label, rx_q, rx_usage in MOVEX_APP_TERMS if rx_q.search(text or "")]
    if not terms:
        return None
    hits = [p for pid, p in products.items()
            if "Chain" in str(p.get("product_type") or "") and p.get("Ref")
            and all(rx.search(str(p.get("usage") or "")) for _, rx in terms)]
    if not hits:
        return None
    hits.sort(key=lambda p: (str(p.get("product_type")), p.get("Plate_Width_mm") or 0))
    label = ""
    for l, _ in terms:   # ไทยต่อไทยไม่เว้นวรรค (ขวดแก้ว) · มีอังกฤษเว้นวรรค (ขวด PET)
        label += l if not label or (l[0] >= "\u0e00" and label[-1] >= "\u0e00") else f" {l}"
    lines = [f"ข้อมูล Movex ระบุงาน{label} ไว้กับโซ่รุ่นเหล่านี้ครับ"]
    for p in hits:
        t = str(p.get("product_type"))
        lines.append(f"• {p['Ref']} — {_CHAIN_TYPE_TH.get(t, t)} ({t}) กว้าง {p.get('Plate_Width_mm'):g} มม.")
    lines.append("พิมพ์ชื่อรุ่นที่ตรงกับไลน์ (ไลน์ตรงหรือมีโค้ง) มาได้เลยครับ "
                 "ถ้ามีรหัสรุ่นอื่นหรือรหัสสเตอร์ 5 หลักก็พิมพ์มาแทนได้ หรือส่งรูปโซ่มาให้ดูครับ")
    return "\n".join(lines)


MOVEX_ESCALATE_TOPICS = ("ราคา", "lead time", "MOQ", "สต็อก", "ช่องทางติดต่อ", "สั่งซื้อ")

# หัวข้อคำถาม Movex → ฟิลด์ที่ต้องใช้ตอบ (None = ตอบระดับซีรีส์ได้เสมอ)
MOVEX_TOPICS = [
    ("sprocket", r"สเตอร์|sprocket|เฟือง", None),
    ("curve", r"เลี้ยว|โค้ง|sideflex|curve|รัศมี|radius", "product_type"),
    ("material", r"วัสดุ|ทำจาก|material", "Material"),
    ("process", r"ผลิต|process|manufactur", None),
    ("workload", r"workload|โหลด|รับแรง|รับน้ำหนัก|load", "Max_Working_Load_N"),
    ("width", r"กว้าง|width", "Plate_Width_mm"),
    ("weight", r"น้ำหนัก|หนักเท่า|weight|kg", "Weight_kg_m"),
    ("drawing", r"drawing|datasheet|ดรออิ้ง|ขอรูป|ขอดูแบบ|แสดงแบบ", "product_id"),
]

ASK_MOVEX_UNCLEAR_IMAGE_TH = ("จากรูปยังระบุรุ่นได้ไม่ชัดครับ รบกวนแจ้งรหัสรุ่นที่ปั๊มบนตัวโซ่ "
                              "หรือส่งรูปด้านบนของโซ่ที่เห็นแผ่นชัด ๆ อีกครั้งครับ")


class MovexPlugin:
    gate_chain = ("escalation", "image_confidence", "code_or_series", "series_uniform_or_ask_width")

    def __init__(self, info: BrandInfo, products: dict, materials: Optional[dict] = None,
                 thresholds: Optional[dict] = None, reject_th: str = "", state_defaults: Optional[dict] = None):
        self.info = info
        self.mx = products
        self.mx_materials = materials or {}
        th = thresholds or {}
        self.vit_answer = float(th.get("answer", 0.90))
        self.vit_series = float(th.get("series", 0.50))
        self.image_reject_th = reject_th
        self._state_defaults = dict(state_defaults or {"pids": [], "series": None})
        self.runtime = None             # brands.movex.runtime.MovexRuntime — ตั้งใน create() เมื่อมีโมเดล
        self.image_enabled = False      # brand.yaml › image ผ่านการตรวจ (core/models.py)
        self._index_movex()

    # ─────────────────────────── ดัชนี ───────────────────────────

    def _index_movex(self) -> None:
        self.mx_ref: dict[str, str] = {}
        self.mx_art: dict[str, str] = {}
        self.mx_series_members: dict[str, list[str]] = {}
        for pid, p in self.mx.items():
            if p.get("Ref"):
                key = norm_code(p["Ref"])
                self.mx_ref[key] = pid
                self.mx_ref.setdefault(key.replace("TAB", ""), pid)      # "LF880 K450" ไม่มี TAB
            if p.get("Art_Nr"):
                self.mx_art[str(p["Art_Nr"])] = pid
            ser = self._series_of(p)
            if ser and "chain" in pid.lower():
                self.mx_series_members.setdefault(ser, []).append(pid)
        self._mx_keys = sorted(self.mx_ref, key=len, reverse=True)

    @staticmethod
    def _series_of(p: dict) -> Optional[str]:
        m = re.search(r"\d+", str(p.get("series", "")))
        return m.group() if m else None

    def movex_series_uniform(self, series: str, fieldname: Optional[str]) -> bool:
        """ทุกรุ่นในซีรีส์มีค่าฟิลด์นี้เท่ากัน → ตอบระดับซีรีส์ได้โดยไม่ต้องรู้ความกว้าง"""
        if fieldname is None:
            return True
        vals = {str(self.mx[p].get(fieldname)) for p in self.mx_series_members.get(series, [])}
        return len(vals) == 1

    def resolve_movex(self, text: str) -> dict:
        t = text or ""
        key = norm_code(t)
        pids: list[str] = []
        for k in self._mx_keys:
            if k in key and self.mx_ref[k] not in pids:
                pids.append(self.mx_ref[k])
                key = key.replace(k, " ")
        for art in re.findall(r"(?<!\d)5[4-9]\d{3}(?!\d)", t):
            if art in self.mx_art and self.mx_art[art] not in pids:
                pids.append(self.mx_art[art])
        series = None
        m = re.search(r"(?:LFN?\s*)?(?<!\d)(820|821|880|882)(?!\d)", t, re.IGNORECASE) \
            or re.search(r"LFN\s*(83|103)|(?<!\d)(83|103)\s*(?:MF[MH]|series|ซีรีส์)", t, re.IGNORECASE)
        if m:
            series = next(g for g in m.groups() if g)
        if not pids and series:
            pids = self.movex_pick_width(series, t)
        return {"pids": pids, "series": series}

    def movex_pick_width(self, series: str, text: str) -> list[str]:
        """เลือกรุ่นในซีรีส์จาก K-code หรือความกว้าง (ใช้ตอนลูกค้าตอบคำถาม "ความกว้างไหน")"""
        k = re.search(r"K\s?(\d{3,4})", text or "", re.IGNORECASE)
        nums = [float(n) for n in re.findall(r"(?<![\d.])(\d{2,3}(?:\.\d)?)(?![\d.])", text or "")]
        out = []
        for pid in self.mx_series_members.get(series, []):
            p = self.mx[pid]
            if k and pid.upper().endswith("K" + k.group(1)):
                out.append(pid)
            elif not k and any(abs(float(p.get("Plate_Width_mm", 0)) - n) < 0.05 for n in nums):
                out.append(pid)
        if not out and not k and not nums:
            # "ตัวที่กว้างกว่า" / "ตัวเล็ก" (test_conversation_leaks C17 · 25 ต.ค.) — เดิมถามความกว้างซ้ำไม่จบ
            members = [pid for pid in self.mx_series_members.get(series, []) if pid in self.mx]
            widths = {pid: float(self.mx[pid].get("Plate_Width_mm", 0) or 0) for pid in members}
            if len(set(widths.values())) > 1:
                if re.search(r"กว้าง(?:กว่า|สุด|ที่สุด)|ใหญ่(?:กว่า|สุด|ที่สุด)|ตัวใหญ่|wide", text or "", re.IGNORECASE):
                    out = [max(widths, key=widths.get)]
                elif re.search(r"แคบ(?:กว่า|สุด|ที่สุด)?|เล็ก(?:กว่า|สุด|ที่สุด)|ตัวเล็ก|narrow", text or "", re.IGNORECASE):
                    out = [min(widths, key=widths.get)]
        return out

    # ─────────────────────────── 1 · รู้จักข้อความ ───────────────────────────

    def detect(self, text: str) -> BrandSignal:
        s = _detect.detect(text)
        codes = self.resolve_movex(text)
        return BrandSignal(s.strength, s.evidence, bool(codes["pids"] or codes["series"]), codes)

    def domain_terms(self) -> list[str]:
        return ["movex"]

    # ─────────────────────────── 5 · สถานะ ───────────────────────────

    def empty_state(self) -> dict:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in self._state_defaults.items()}

    def has_focus(self, st: dict) -> bool:
        return bool(st.get("pids") or st.get("series"))

    def on_brand_switch(self, st: dict) -> dict:
        return {**st, "pids": [], "series": None}

    def sanitize_state(self, raw: dict) -> dict:
        """ย้ายมาจาก webapi/bot.py sanitize_dialog_state (ชั้น 6) — เก็บเฉพาะ pid ที่มีจริง"""
        pids = raw.get("pids")
        series = raw.get("series")
        return {"pids": [p for p in pids if p in self.mx] if isinstance(pids, list) else [],
                "series": series if isinstance(series, str) and len(series) <= 16 else None}

    def resumable(self, st: dict) -> bool:
        return bool(st.get("pids"))       # ซีรีส์อย่างเดียวไม่นับ (เงื่อนไขเดิม)

    # ─────────────────────────── 3 · ตัดสิน ───────────────────────────

    def _movex_topic(self, text: str) -> tuple[Optional[str], Optional[str]]:
        for name, rx, fld in MOVEX_TOPICS:
            if has(rx, text):
                return name, fld
        return None, None

    def decide(self, inp: DecideInput, st: dict) -> Decision:
        text, codes = inp.text, inp.signal.parsed
        esc = escalation_gate(text, allowed_topics=MOVEX_ESCALATE_TOPICS)
        if esc and not esc.has_spec_question:
            ref = None
            pid = (codes["pids"] or st["pids"] or [None])[0]
            if pid and pid in self.mx:
                ref = self.mx[pid].get("Ref") or pid
            esc = escalation_gate(text, belt_code=ref, allowed_topics=MOVEX_ESCALATE_TOPICS)
            if pid:
                st["pids"] = list(codes["pids"] or st["pids"])
            return Decision("escalate", self.info.key, esc.reply_th.replace("สายพาน ", "โซ่ "),
                            f"หัวข้อ {esc.topics}", topic="escalate", effective_text=text)
        d = self._decide_core(text, inp, st, codes)
        if esc:
            ref = (self.mx.get((st["pids"] or [None])[0]) or {}).get("Ref")
            esc = escalation_gate(text, belt_code=ref, allowed_topics=MOVEX_ESCALATE_TOPICS)
            attach_handoff(d, esc.handoff_th.replace("สายพาน ", "โซ่ "), esc.topics)
        return d

    def _decide_core(self, text: str, inp: DecideInput, st: dict, codes: dict) -> Decision:
        topic, fld = self._movex_topic(text)
        pids, series, why = codes["pids"], codes["series"], "รหัสในข้อความ"
        vit = inp.image
        key = self.info.key

        if not pids and inp.has_image and vit is not None:
            if vit.group and vit.confidence >= self.vit_answer and vit.dominant and vit.product_ref:
                pids, series, why = [vit.product_ref], vit.group, f"ViT {vit.confidence:.2f} dominant"
            elif vit.group and vit.confidence >= self.vit_series:
                series, why = vit.group, f"ViT {vit.confidence:.2f} รู้แค่ซีรีส์"
            else:
                # ViT < 0.5 = ไม่มั่นใจว่ารูปเป็นสินค้าเลย → ปฏิเสธรูป ไม่ยกรหัสตัวอย่าง
                # (IMG-003: รูปที่ไม่ใช่โซ่ ระบบค้นได้ผลแต่คะแนนต่ำ — ต้องไม่ตอบรหัสรุ่นใด ๆ)
                return Decision("reject_image", key, self.image_reject_th,
                                f"ViT {vit.confidence:.2f} ต่ำกว่า {self.vit_series}",
                                topic=topic, effective_text=text)

        # เลือกความกว้างจากคำตอบดิบของเทิร์นนี้ (ไม่ใช่ข้อความรวม — เลขซีรีส์ในคำถามเดิมจะถูกอ่านเป็นความกว้าง)
        # test_conversation_leaks 25 ต.ค.: "ตัวที่กว้างกว่า" หลังถามความกว้าง → ถามซ้ำ (C17)
        #                                "แล้ว K400 ล่ะ" ต่อจาก LF820 K325 → ยังตอบ K325 (C18)
        raw = inp.answer or text
        cur = series or st["series"]
        if not pids and cur and (not st["pids"] or re.search(r"(?<![A-Za-z])K\s?\d{3,4}", raw, re.IGNORECASE)):
            picked = self.movex_pick_width(cur, raw)
            if picked:
                pids, why = picked, "ลูกค้าเลือกความกว้าง"
        if pids:
            st["pids"] = pids
            st["series"] = self._series_of(self.mx[pids[0]]) or series
        elif series:
            if series != st["series"]:
                st["pids"] = []
            st["series"] = series
        else:
            why = "ต่อจากเทิร์นก่อน"

        pids, series = st["pids"], st["series"]
        base = dict(pids=pids, series=series, topic=topic)
        if pids:
            return Decision("answer", key, reason=why, topic=topic, effective_text=text,
                            payload={**base, "level": "product"})
        if series:
            if topic and self.movex_series_uniform(series, fld):
                return Decision("answer", key, reason=f"{why} · {topic} เท่ากันทั้งซีรีส์",
                                topic=topic, effective_text=text,
                                payload={**base, "level": "series"})
            return Decision("ask", key, self.ask_movex_width_th(series, from_image=inp.has_image),
                            f"{why} · ต้องรู้ความกว้าง", topic=topic, effective_text=text,
                            payload={**base, "level": "series"}, pending="movex_width")
        app = movex_application_block(text, self.mx)
        return Decision("ask", key, app or self.ask_movex_model_th(topic),
                        "ยังไม่รู้รุ่น",
                        topic=topic, effective_text=text, pending="movex_model")  # noqa: E128

    def ask_movex_width_th(self, series: str, from_image: bool = False) -> str:
        members = self.mx_series_members.get(series, [])
        ptype = self.mx[members[0]].get("product_type", "") if members else ""
        lines = [f"{'จากรูปเป็น' if from_image else 'รุ่น'} {series} Series ({ptype}) ครับ มีความกว้างให้เลือก:"]
        for pid in sorted(members, key=lambda x: self.mx[x].get("Plate_Width_mm", 0)):
            p = self.mx[pid]
            lines.append(f"• {p.get('Plate_Width_mm'):g} มม. — {p.get('Ref')}")
        lines.append("ต้องการความกว้างไหนครับ")
        return "\n".join(lines)

    def ask_movex_model_th(self, topic: Optional[str]) -> str:
        by_type: dict[str, list[str]] = {}
        for ser, members in self.mx_series_members.items():
            by_type.setdefault(self.mx[members[0]].get("product_type", ""), []).append(ser)
        opts = " · ".join(f"{t}: {', '.join(sorted(s))}" for t, s in sorted(by_type.items()))
        return ("ขอทราบรุ่นก่อนนะครับ เพื่อให้ตอบได้ตรง\n"
                "• รหัสรุ่น เช่น LF 820 K325 หรือรหัสสเตอร์ 5 หลัก\n"
                "• หรือซีรีส์ + ความกว้าง เช่น 880 กว้าง 82.5 มม.\n"
                "• หรือส่งรูปโซ่มาให้ดูครับ\n"
                f"ซีรีส์ที่มี — {opts}")

    # ─────────────────────────── ข้ามแบรนด์ ───────────────────────────

    def cross_brand_section(self, topic: str) -> Optional[list[str]]:
        if topic != "stainless":
            return None
        mx_chain_mats = sorted({str(p.get("Material")) for pid, p in self.mx.items()
                                if "chain" in pid.lower() and p.get("Material")})
        mx_ss = [p.get("Ref") or pid for pid, p in self.mx.items()
                 if "SS" in {str(p.get("Material")), str(p.get("Pivot_material"))}]
        lines = []
        if mx_ss:
            lines.append("• รุ่นที่ใช้ SS: " + ", ".join(mx_ss))
        else:
            lines.append(f"• ไม่มีรุ่นที่ตัวโซ่ทำจากสแตนเลส — ตัวโซ่ผลิตจาก {', '.join(mx_chain_mats)} "
                         f"(LF = Low Friction Acetal)")
        ss_note = (self.mx_materials.get("SS") or {}).get("technical_specs", {}).get("application")
        if ss_note:
            lines.append(f"• ตารางวัสดุของ Movex ระบุ SS ไว้ว่า \"{ss_note}\" แต่ข้อมูลรายรุ่นไม่ได้ระบุวัสดุพิน "
                         f"ต้องยืนยันกับฝ่ายขาย")
        return lines

    # ─────────────────────────── 2 + 4 · ค้นและ prompt / 6 · รูป ───────────────────────────

    def _rt(self):
        if self.runtime is None:
            raise RuntimeError("ปลั๊กอิน Movex ถูกสร้างแบบไม่มีโมเดล (โหมดตัดสินอย่างเดียว) — เรียก LLM ไม่ได้")
        return self.runtime

    def build_turn(self, decision, turn):
        return self._rt().build_turn(decision, turn)

    def finish_turn(self, decision, turn, llm, result):
        return self._rt().finish_turn(decision, turn, llm, result)

    def close(self) -> None:
        """ปิด Qdrant แบบไฟล์ก่อนโปรแกรมจบ (ไม่บังคับในสัญญา — assistant.py เรียกผ่าน atexit)"""
        try:
            if self.runtime is not None and getattr(self.runtime, "retriever", None) is not None:
                self.runtime.retriever.inner.client.close()
        except Exception:
            pass

    def image_scorer(self):
        if self.runtime is None or not self.image_enabled:
            return None
        rt = self.runtime

        class _Scorer:
            def score(self, image, text):
                return rt.score_image(image, text)
        return _Scorer()


def load_thresholds(brand_dir: str, cfg: dict) -> dict:
    rel = (cfg.get("image") or {}).get("thresholds")
    if not rel:
        return {}
    with open(os.path.join(brand_dir, rel), encoding="utf-8") as f:
        return json.load(f)


def reject_text(cfg: dict) -> str:
    return " ".join(str((cfg.get("image") or {}).get("reject_th") or "").split())


def create(ctx):
    """registry เรียก — อ่านข้อมูลตาม brand.yaml › data แล้วต่อโมเดลถ้าตัวเริ่มระบบส่งมาใน ctx.shared"""
    from core.registry import BrandConfig  # noqa: F401  (ชนิดเท่านั้น)
    from core.protocol import BrandInfo
    cfg, d = ctx.config, ctx.brand_dir
    data = cfg.get("data") or {}

    def path(rel):
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(d, rel))

    with open(path(data["products"]), "r", encoding="utf-8") as f:
        raw = json.load(f)
    product_db = {p["product_id"]: p for p in raw.get("products", []) if "product_id" in p}
    material_db = {m["material_code"]: m for m in raw.get("Materials", [])}
    process_db = {p["manufacturing_process"]: p for p in raw.get("manufacturing_process", [])}
    print(f"✅ JSON: {len(product_db)} products | {len(material_db)} materials | {len(process_db)} processes")

    i = cfg["info"]
    info = BrandInfo(key=cfg["key"], name=i["name"], order=i["order"], kind_th=i["kind_th"],
                     menu_line_th=i["menu_line_th"], offtopic_th=i["offtopic_th"],
                     category_th=i["category_th"], answer_patterns=tuple(i.get("answer_patterns") or ()))
    plugin = MovexPlugin(info, product_db, material_db, thresholds=load_thresholds(d, cfg),
                         reject_th=reject_text(cfg), state_defaults=cfg.get("state"))
    plugin.image_enabled = ctx.image_model is not None

    sh = ctx.shared
    if sh.get("jina_model") is not None:
        from knowledge_graph import KnowledgeGraph
        from retriever_v4 import RetrieverV4, RetrieverV4Config
        from brands.movex import runtime as R
        vit_proc, vit_model = (sh.get("vit") or {}).get(cfg["key"], (None, None))
        graph = KnowledgeGraph.load_from_db(path(data["graph_db"]))
        inner = RetrieverV4(
            cfg=RetrieverV4Config(qdrant_path=path(data["qdrant_path"]), device=sh["device"]),
            jina_tokenizer=sh["jina_tokenizer"], jina_model=sh["jina_model"],
            vit_processor=vit_proc, vit_model=vit_model,
            siglip_processor=sh["siglip_processor"], siglip_model=sh["siglip_model"],
            product_db=product_db, kg=graph,
        )
        print("✅ RetrieverV4 + KnowledgeGraph")
        R.bind(product_db, material_db, process_db, graph, inner)
        plugin.runtime = R.MovexRuntime(cfg["key"], R.InstrumentedRetriever(inner), sh["logger"], sh["tool_log"])
    return plugin
