"""
core/decide.py
==============
ทาง จ ส่วนกลาง — ตัดสินในโค้ดว่าจะ "ตอบ / ถามกลับ / ปฏิเสธ / ส่งฝ่ายขาย" ก่อนถึง LLM
ย้ายมาจาก DialogueManager.decide ชั้น 4 · ส่วนที่ผูกกับแบรนด์ย้ายไป brands/<key>/plugin.py

ลำดับการตัดสินในหนึ่งเทิร์น (เท่าเดิม)
    รูปที่ระบบปฏิเสธ            → reject_image
    คำตอบของการถามกลับ          → รวมกับคำถามเดิม (ถ้าถามแบรนด์ไว้ ดูว่าตอบแบรนด์ไหน)
                                   ถามแบรนด์เพราะรูป (core/image_policy) → ใช้ผลรูปที่เก็บไว้กับแบรนด์ที่ตอบ
    ทักทาย/ขอบคุณ               → smalltalk
    ไม่เกี่ยวกับสินค้า             → refuse_offtopic
    ขอช่องทางติดต่ออย่างเดียว     → escalate (ไม่ต้องรู้แบรนด์)
    สัญญาณแข็งหลายแบรนด์         → ask ยืนยันแบรนด์
    สแตนเลสไม่ระบุแบรนด์         → cross_brand (ทุกแบรนด์ตอบส่วนของตัวเอง)
    ยังไม่รู้แบรนด์               → ask แบรนด์
    รู้แบรนด์แล้ว                 → plugin.decide()

ไม่ import torch / qdrant / genai — เทสต์ด้วย python ล้วน
"""
from __future__ import annotations

import copy
from typing import Optional, Sequence

from core import router as _router
from core import templates as T
from core.protocol import BrandPlugin, DecideInput, Decision, ImageScore
from core.image_policy import ImageCarry
from core.sales import escalation_gate
from core.text import any_word, has

# คำที่บอกว่าเป็นคำถามเรื่องสินค้า (ไม่มีคำพวกนี้ + ไม่มีรหัส = นอกเรื่อง)
# ชื่อแบรนด์ไม่อยู่ที่นี่ — แต่ละแบรนด์เติมผ่าน plugin.domain_terms()
DOMAIN_WORDS = [
    "สายพาน", "โซ่", "สเตอร์", "เฟือง", "เพลา", "พิน", "ก้าน", "ลำเลียง", "คอนเวเยอร์",
    "belt", "chain", "sprocket", "conveyor",
    "กว้าง", "ความยาว", "หนา", "workload", "โหลด", "รับน้ำหนัก", "แรงดึง", "น้ำหนัก", "แข็งแรง",
    "วัสดุ", "ทำจาก", "เลี้ยว", "โค้ง", "วิ่งตรง", "รัศมี", "ผลิต", "ทน", "อุณหภูมิ", "องศา",
    "ร้อน", "เย็น", "แช่แข็ง", "เปียก", "แห้ง", "drawing", "datasheet", "ดรออิ้ง", "แบบ", "สเปก", "spec",
    "ราคา", "สต็อก", "สต๊อก", "ส่งของ", "อะไหล่", "ผิว", "ไลน์", "รุ่น", "series", "ซีรีส์",
    "สเปค", "เทียบ",   # 25 ต.ค. เทสบนเว็บ: "ขอดูสเปคทั้งสองตัวเทียบกัน" (สะกด ค) ถูกตีเป็นนอกเรื่อง
    "ฟัน", "pitch", "พิทช์", "เบอร์", "ขนาด",
    # หน่วยวัด — ลูกค้าถามเปลี่ยนหน่วยบ่อยมาก และเดิมถูกตีเป็นคำถามนอกเรื่อง
    # (พบตอนเทส 2026-09-29: "ขอให้ตอบเป็นหน่วยนิ้วได้ไหม" ถูกปฏิเสธ ทั้งที่คุยรุ่น HC127 C ค้างอยู่)
    "นิ้ว", "inch", "มิลลิเมตร", "เซนติเมตร", "มม", "ซม", "ฟุต", "feet", "หน่วย", "เมตร",
    # การค้า — ลูกค้าถามเรื่องสั่งซื้อและช่องทางติดต่อเป็นข้อความแรกได้
    # (พบตอนเทส 2026-10-02: "ขอช่องทางติดต่อฝ่ายขาย" ถูกตีเป็นนอกเรื่อง
    #  เพราะด่านตรวจนอกเรื่องอยู่ก่อนเกตฝ่ายขาย จึงไม่มีโอกาสถึงเกต)
    "สั่งซื้อ", "ซื้อ", "สั่ง", "ออเดอร์", "order", "ใบเสนอราคา", "quotation",
    "ติดต่อ", "ฝ่ายขาย", "เซลล์", "อีเมล", "email", "โทร", "ไลน์",
]

# คำถามต่อเนื่องสั้น ๆ หลังจากมีรุ่นอยู่ในโฟกัสแล้ว ให้ถือว่าเป็นเรื่องสินค้า
# เหตุผล: ลูกค้าที่เพิ่งถามสเปกของรุ่นหนึ่งแล้วพิมพ์สั้น ๆ ต่อ ("แล้วราคาล่ะ" "อันไหนดีกว่า"
# "ส่งของกี่วัน") กำลังถามถึงรุ่นนั้น การปฏิเสธว่านอกเรื่องทำให้เสียงานโดยไม่จำเป็น
# ไม่กระทบเคสนอกเรื่องจริง (CLARIF-002 "อากาศวันนี้เป็นยังไง") เพราะเป็นเทิร์นแรก ยังไม่มีรุ่นในโฟกัส
FOLLOWUP_MAX_CHARS = 40
THANKS_WORDS = ["ขอบคุณ", "ขอบใจ", "thank"]
THANKS_MAX_CHARS = 25
SMALLTALK_WORDS = ["สวัสดี", "ขอบคุณ", "ขอบใจ", "hello", "hi ", "thank", "thanks", "ดีครับ", "ดีค่ะ"]
GREETING_WORDS = ["สวัสดี", "hello", "hi ", "ดีครับ", "ดีค่ะ"]   # ทัก (ไม่ใช่ขอบคุณ) → ข้อความทักกลับ
REFERENCE_WORDS = ["ตัวนั้น", "ตัวนี้", "อันนั้น", "อันนี้", "รุ่นนั้น", "รุ่นนี้", "ตัวที่", "อันที่",
                   "ตัวแรก", "ตัวหลัง", "เมื่อกี้", "ข้างบน", "ตัวเดิม"]

STAINLESS_RX = r"สแตนเลส|stainless|(?<![A-Za-z])SS(?![A-Za-z])"
CROSS_BRAND_STAINLESS = "stainless"

GENERIC_REJECT_IMAGE_TH = ("❌ ระบบตรวจพบว่ารูปภาพที่อัปโหลดไม่เกี่ยวข้องกับสินค้าในระบบ หรือยังไม่ชัดพอให้ระบุรุ่น "
                           "กรุณาอัปโหลดภาพสินค้าที่ชัดเจน หรือแจ้งรหัสที่ปั๊มบนตัวสินค้าครับ")


class Dialogue:
    """
    plugins       เรียงตาม info.order (ลำดับนี้คือลำดับในข้อความและการจับคำตอบเลือกแบรนด์)
    state_cls     คลาสจาก core.dialogue.state_class ที่ผูก schema ของแบรนด์ชุดเดียวกัน
    image_brands  แบรนด์ที่รูปในเทิร์นนี้อาจเป็นของมัน (ImageRouter ตัดสินก่อนส่งมา)
    """

    def __init__(self, plugins: Sequence[BrandPlugin], state_cls: type,
                 image_brands: Sequence[str] = ()):
        self.plugins = {p.info.key: p for p in sorted(plugins, key=lambda p: p.info.order)}
        self.infos = [p.info for p in self.plugins.values()]
        self.state_cls = state_cls
        self.image_brands = tuple(image_brands)
        self.ask_brand_th = T.ask_brand(self.infos)
        self.offtopic_th = T.offtopic(self.infos)
        self.smalltalk_th = T.smalltalk(self.infos)
        self.greeting_th = T.greeting(self.infos)
        self._domain_extra = [w for p in self.plugins.values() for w in p.domain_terms()]

    # ─────────────────────────── API หลัก ───────────────────────────

    def decide(self, text: str, has_image: bool = False, image: Optional[ImageScore] = None,
               image_rejected: bool = False, state=None,
               image_carry: Optional[ImageCarry] = None) -> Decision:
        st = copy.deepcopy(state) if state is not None else self.state_cls()
        text = (text or "").strip()

        if image_rejected:
            key = image.brand if image is not None else (
                self.image_brands[0] if len(self.image_brands) == 1 else None)
            reply = (self.plugins[key].image_reject_th if key in self.plugins else "") or GENERIC_REJECT_IMAGE_TH
            return Decision("reject_image", key, reply, "ViT/SigLIP ไม่พบสินค้า",
                            effective_text=text, state=st)

        # ── ขอบคุณ/ขอบใจล้วน ๆ ตอนบอทค้างคำถามไว้ = จบเรื่องนั้น ไม่ใช่คำตอบ (test_conversation_leaks C01 · 25 ต.ค.)
        # เดิมรวมกับคำถามเดิมแล้วถามซ้ำ เช่น บอทถามเปียก/แห้ง → "ขอบคุณครับ" → ถามเปียก/แห้งอีกรอบ
        if st.pending and any_word(THANKS_WORDS, text) and not any_word(DOMAIN_WORDS, text) \
                and len(text) <= THANKS_MAX_CHARS:
            st.pending, st.pending_question = None, ""
            return Decision("smalltalk", st.brand, self.smalltalk_th, "ขอบคุณ (ปิดคำถามที่ค้าง)",
                            effective_text=text, state=st)

        # ── คำตอบของการถามกลับรอบก่อน: รวมกับคำถามเดิม ──
        effective = text
        carried = None                    # ผลรูปของเทิร์นที่ถามแบรนด์ ใช้ได้เมื่อตอบแบรนด์เจ้าของคะแนนรูป
        # ถามแบรนด์จากเทิร์นที่มีแต่รูป (ไม่มีข้อความ) — คำถามเดิมว่างได้ แต่ยังต้องอ่านคำตอบแบรนด์
        if st.pending and (st.pending_question or st.pending == "brand"):
            if st.pending == "brand":
                for key, p in self.plugins.items():
                    if any(has(pat, text) for pat in T.brand_answer_patterns(p.info)):
                        st.brand = key
                        break
                if image_carry is not None and st.brand is not None and not has_image:
                    sc = image_carry.best
                    if sc is not None and sc.brand == st.brand:
                        if image_carry.rejected:
                            reply = self.plugins[st.brand].image_reject_th or GENERIC_REJECT_IMAGE_TH
                            st.pending, st.pending_question = None, ""
                            return Decision("reject_image", st.brand, reply,
                                            f"ตอบ {st.brand} · รูปเทิร์นก่อนถูกปฏิเสธ",
                                            effective_text=text, state=st,
                                            payload={"image_carried": True})
                        carried = sc
            effective = f"{st.pending_question} {text}".strip()
        pending_q_before = st.pending_question
        st.pending, pending_before, st.pending_question = None, st.pending, ""

        # ── สัญญาณของทุกแบรนด์ ──
        signals = {k: p.detect(effective) for k, p in self.plugins.items()}
        route = _router.choose(signals, prev_brand=st.brand, has_image=has_image,
                               image_brands=self.image_brands)
        has_code = any(s.has_code for s in signals.values())

        # ── ทักทาย / นอกเรื่อง ──
        # มีรุ่นค้างอยู่ในบทสนทนา + พิมพ์สั้น = ถามต่อเรื่องรุ่นนั้น ไม่ใช่เปลี่ยนเรื่อง
        in_focus = bool(st.brand) and any(p.has_focus(st.brands[k]) for k, p in self.plugins.items())
        followup = in_focus and len(text) <= FOLLOWUP_MAX_CHARS
        domain = has_code or has_image or bool(any_word(DOMAIN_WORDS, effective)) \
            or bool(any_word(self._domain_extra, effective)) or pending_before is not None \
            or has(STAINLESS_RX, effective) or followup
        if not domain:
            if any_word(SMALLTALK_WORDS, text):
                greet = any_word(GREETING_WORDS, text) and not any_word(["ขอบคุณ", "ขอบใจ", "thank"], text)
                return Decision("smalltalk", st.brand, self.greeting_th if greet else self.smalltalk_th, "ทักทาย",
                                effective_text=effective, state=st)
            if not (st.brand and any_word(REFERENCE_WORDS, text)):
                return Decision("refuse_offtopic", st.brand, self.offtopic_th, "ไม่มีคำเกี่ยวกับสินค้า",
                                effective_text=effective, state=st)

        # ── ขอช่องทางติดต่อ — ตอบได้โดยไม่ต้องรู้แบรนด์ ──
        # บริษัทเดียว เบอร์เดียว ถามแบรนด์ก่อนให้เบอร์เป็นการกั้นโดยไม่จำเป็น
        # ต้องอยู่ก่อนด่านถามแบรนด์ ไม่งั้น "ขอเบอร์ฝ่ายขาย" จะได้คำถามกลับว่าสนใจแบรนด์ไหน
        # เงื่อนไข: หัวข้อต้องเป็นช่องทางติดต่อล้วน ถ้ามีคำถามสเปกปนมาให้ไหลไปทางปกติ
        # (หัวข้อช่องทางติดต่อไม่ใช้ชื่อรุ่นในข้อความ จึงไม่ต้องส่งรหัสของแบรนด์ใดเข้าไป)
        _esc = escalation_gate(effective)
        if _esc and _esc.topics == ["ช่องทางติดต่อ"] and not _esc.has_spec_question:
            # ขอเบอร์กลางคำถามที่แบรนด์ถามค้าง → ให้เบอร์แล้วถามข้อเดิมต่อ (การรอคำตอบไม่หาย)
            # ปลั๊กอินเลือกเองผ่าน pending_reask(state) — ไม่มีเมธอดนี้ = พฤติกรรมเดิม
            # 26 ต.ค. (C09): เดิมล้างการรอคำตอบ เทิร์นหน้า "2 นิ้ว" ไม่ถูกอ่านเป็นคำตอบ → บันทึกเป็น "ไม่ทราบ"
            reask = getattr(self.plugins.get(st.brand), "pending_reask", None) \
                if pending_before not in (None, "brand") and st.brand else None
            q = reask(st.brands[st.brand]) if reask else None
            if q:
                st.pending, st.pending_question = pending_before, pending_q_before
                return Decision("ask", st.brand, f"{_esc.reply_th}\n\n{q}", "ขอช่องทางติดต่อกลางการถาม → ถามข้อเดิมต่อ",
                                topic="escalate", effective_text=effective, state=st)
            return Decision("escalate", st.brand, _esc.reply_th, "ขอช่องทางติดต่อ",
                            topic="escalate", effective_text=effective, state=st)

        # ── slot 0: แบรนด์ ──
        if route.kind == "conflict_strong":
            st.pending, st.pending_question = "brand", effective
            conflict = [self.plugins[k].info for k in route.conflict]
            only_image = all(v == _router.IMAGE_EVIDENCE for v in route.evidence.values())
            why = ("รูปไม่ระบุแบรนด์ (บางแบรนด์ยังไม่มีตัวให้คะแนนรูป)" if only_image
                   else f"เจอรหัสของ{T.all_brands_th(len(conflict))}")
            return Decision("ask", None, T.clarify_conflict(conflict), why,
                            topic="brand", effective_text=effective, state=st)
        brand = route.brand if route.brand else st.brand
        if route.brand and st.brand and route.brand != st.brand:
            # เปลี่ยนแบรนด์กลางบทสนทนา — แต่ละแบรนด์เลือกเองว่าล้างอะไร
            for k, p in self.plugins.items():
                st.brands[k] = p.on_brand_switch(st.brands[k])
        if brand is None and has(STAINLESS_RX, effective):
            # คำถามเรื่องวัสดุสแตนเลสโดยไม่บอกแบรนด์ → ตอบจากข้อมูลทุกแบรนด์ (ผู้ใช้เลือก 2026-09-25)
            n = len(self.plugins)
            # ค้างคำถามแบรนด์ไว้ — ลูกค้าเลือกแบรนด์ทีหลัง ("เอาของแบรนด์นี้") ต้องได้คำถามสแตนเลสต่อ
            # (test_conversation_leaks C19 · 25 ต.ค. — เดิมเรื่องสแตนเลสหาย ได้คำแนะนำทั่วไป)
            st.pending, st.pending_question = "brand", effective
            return Decision("cross_brand", None, self.cross_brand_th(CROSS_BRAND_STAINLESS),
                            f"SS ไม่ระบุแบรนด์ → ตอบ{T.all_brands_th(n)}",
                            topic="material", effective_text=effective, state=st)
        if brand is None:
            st.pending, st.pending_question = "brand", effective
            return Decision("ask", None, self.ask_brand_th, "ยังไม่รู้แบรนด์", topic="brand",
                            effective_text=effective, state=st)
        st.brand = brand

        plugin = self.plugins[brand]
        img = image if (has_image and image is not None and image.brand == brand) else None
        use_image = has_image
        if carried is not None and carried.brand == brand:
            img, use_image = carried, True
        d = plugin.decide(DecideInput(text=effective, signal=signals[brand], has_image=use_image,
                                      image=img, answer=text if pending_before else ""), st.brands[brand])
        if d.pending:
            # ข้อความที่ปลั๊กอินใช้ตัดสินจริง (ปกติ = effective) — ปลั๊กอินเริ่มคำขอใหม่จากคำตอบได้
            # 26 ต.ค. (C33): เปลี่ยนงานกลางการถาม ปลั๊กอินตัดคำขอเดิมทิ้ง แต่ที่นี่เคยเก็บข้อความรวมเดิมไว้
            # เทิร์นหน้าจึงกลับไปเป็นงานเดิม
            st.pending, st.pending_question = d.pending, (d.effective_text or effective)
        if carried is not None and carried.brand == brand:
            d.payload = {**(d.payload or {}), "image_carried": True}
        d.state = st
        return d

    # ─────────────────────────── ข้ามแบรนด์ ───────────────────────────

    def cross_brand_th(self, topic: str) -> str:
        """สร้างจากข้อมูลจริงของทุกแบรนด์ทุกครั้ง — แต่ละแบรนด์เขียนส่วนของตัวเอง"""
        sections = [(p.info, p.cross_brand_section(topic)) for p in self.plugins.values()]
        sections = [(i, s) for i, s in sections if s is not None]
        lines = [f"สินค้าที่เกี่ยวกับสแตนเลส (SS) ของ{T.all_brands_th(len(self.plugins))}ครับ", ""]
        for n, (info, sec) in enumerate(sections):
            if n:
                lines.append("")
            lines.append(f"**{info.name} ({info.kind_th})**")
            lines += sec
        lines += ["", "สนใจแบรนด์ไหนหรือรุ่นไหน บอกได้เลยครับ จะให้รายละเอียดสเปกเพิ่ม"]
        return "\n".join(lines)
