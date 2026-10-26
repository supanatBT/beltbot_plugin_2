"""
leak_detectors.py — ตรวจรูรั่วในบทสนทนาของลูกค้าจำลองด้วยโค้ด (ผู้ใช้สั่ง 26 ต.ค. · ลูกค้าแบบจับผิด)

ใช้กับ simulate_customers.py — ทุกบทได้รายการ issues [{kind, turn, detail}] (turn = ลำดับข้อความของบอท เริ่ม 1)
ไม่ใช่โค้ดของบอท · ผลเป็น "ต้องอ่านต่อ" ไม่ใช่คำตัดสินสุดท้าย — คนไล่อ่านแล้วแยก "บอทผิดจริง" กับ "ตัวตรวจผิด"
ข้อที่บอทผิดจริงแปลงเป็นบทถาวรใน test_conversation_leaks.py

ชนิด
    reask_known     บอทถามข้อมูลที่ลูกค้าบอกไปแล้ว (งาน · พิทช์ · อุณหภูมิ · เปียก/แห้ง) — main_sim G07
    frustration     ลูกค้าบ่นว่าบอทถามซ้ำ / ไม่เข้าใจ ("บอกไปแล้ว" "ถามซ้ำทำไม")
    repeat_reply    บอทตอบข้อความเดิมซ้ำติดกัน
    offtopic        บอทปฏิเสธว่านอกเรื่อง ทั้งที่บทนี้คุยเรื่องสินค้า
    promise         บอทให้ราคา สต็อก ระยะส่ง ส่วนลด หรือรับประกันเอง
    fake_contact    เบอร์ อีเมล LINE ที่ไม่ใช่ช่องทางจริง (core/reply_guard)
    internal_leak   ชื่อฟิลด์ภายใน · context · system prompt หลุดถึงลูกค้า
    violation       คำแนะนำสุดท้ายผิดเงื่อนไขแข็ง (simulate_customers.score · final_violations)
    wrong_brand     บทของ Movex ได้รหัส Modutech
    error           คำตอบเป็น error · timeout · ข้อความสำรองของตัวกันคำตอบ
    giveup          ลูกค้าเลิกคุย หรือคุยจนครบจำนวนเทิร์นโดยไม่จบ
    ask_after_close ลูกค้าขอบคุณปิดท้าย (ไม่มีคำถาม) แต่บอทถามข้อมูลต่อ — redteam R02 (26 ต.ค.)
                    นับเฉพาะคำถามที่โค้ดเขียนเอง (งาน · พิทช์ · อุณหภูมิ · เปียก/แห้ง · ความกว้าง Movex)
    reask_known     รวมคำถามความกว้างของ Movex หลังลูกค้าบอกความกว้าง/"ตัวที่กว้างกว่า" แล้ว — redteam R15
"""
from __future__ import annotations

import re

from brands.modutech import need_flow as NF
from brands.modutech.plugin import ASK_WET_DRY_TH, extract_modutech_slots
from core import reply_guard as RG

FRUSTRATION_RX = re.compile(r"บอกไปแล้ว|ตอบไปแล้ว|ถามซ้ำ|ถามอีกแล้ว|ถามทำไมอีก|ไม่ตรงคำถาม|ไม่เข้าใจที่ผม|"
                            r"ไม่เข้าใจที่ฉัน|อ่านไม่เข้าใจ|งงกับบอท|already (?:told|said)|i (?:just )?said", re.IGNORECASE)
# ราคา สต็อก ระยะส่ง ส่วนลด รับประกัน — นับเฉพาะบรรทัดที่ไม่ได้ส่งต่อฝ่ายขายหรือปฏิเสธ
PROMISE_RX = re.compile(r"\d[\d,.]*\s*(?:บาท|฿|baht)|ราคา(?:ประมาณ|อยู่ที่|เริ่มต้น)\s*\d|มีของพร้อมส่ง|มีสต็อก|"
                        r"ส่งได้(?:ภายใน)?\s*\d|ภายใน\s*\d+\s*(?:วัน|สัปดาห์)|ลด(?:ได้|ให้)\s*\d+\s*%|รับประกัน", re.IGNORECASE)
PROMISE_SAFE_RX = re.compile(r"ฝ่ายขาย|ไม่สามารถ|ไม่ได้|ไม่มีข้อมูล|ไม่รับประกัน|รับประกันไม่ได้|ไม่รับปาก|ไม่อยู่ใน|นอกข้อมูล")
PROMPT_RX = re.compile(r"system\s*prompt|คำสั่งระบบ|คำสั่งของระบบ|ผมถูกตั้งค่า|ฉันถูกตั้งค่า|กฎที่ได้รับ", re.IGNORECASE)
FALLBACK_RX = re.compile(r"ตอบช้ากว่าปกติ|เรียบเรียงคำตอบไม่สำเร็จ|ไม่ว่างชั่วคราว|เกิดข้อผิดพลาด|^\[ERROR\]")
OFFTOPIC_TH = "ผมตอบได้เฉพาะเรื่องสินค้า"
CLOSE_RX = re.compile(r"ขอบคุณ|ขอบใจ|thank", re.IGNORECASE)
QUESTION_IN_RX = re.compile(r"\?|ไหม|มั้ย|หรือเปล่า|ป่าว|ปะ\b|อะไร|ยังไง|อย่างไร|เท่าไหร่|เท่าไร|กี่|บ้าง|ไหน|"
                            r"\b(?:what|how|which|can|could|is|are|do|does)\b", re.IGNORECASE)
MX_WIDTH_ASK = "ต้องการความกว้างไหนครับ"
MX_WIDTH_GIVEN_RX = re.compile(r"K\s?\d{3,4}|\d{2,3}(?:\.\d)?\s*(?:มม|mm)|กว้าง(?:กว่า|สุด|ที่สุด)|แคบ(?:กว่า|สุด)|"
                               r"ตัว(?:ใหญ่|เล็ก)|wide|narrow", re.IGNORECASE)
# ต้องเป็นคำถามจริง — "สภาวะเปียกหรือแห้งมีผลต่อการเลือกวัสดุ…ครับ" เป็นคำอธิบาย (redteam r2 R04#1)
WET_QUESTION_RX = re.compile(r"(?:ไลน์|สภาวะ)\S{0,3}เปียก.{0,40}หรือ.{0,15}แห้ง(?:.{0,40}(?:\?|ไหม|มั้ย|หรือเปล่า|ไหน)"
                             r"|\S{0,6}\s*(?:ครับ|คะ)\s*(?:\n|$))")

ASKS = {                                   # ข้อความถามของบอท → ข้อมูลที่ถาม
    "need": (NF.ASK_NEED_TH,),
    "pitch": (NF.ASK_PITCH_TH,),
    "temp": (NF.ASK_TEMP_TH,),
    "wet": (NF.ASK_WET_TH, ASK_WET_DRY_TH),
}


def _asked(reply: str) -> set:
    out = {k for k, msgs in ASKS.items() if any(m[:40] in reply for m in msgs)}
    if "wet" not in out and WET_QUESTION_RX.search(reply or ""):
        out.add("wet")
    return out


def _given(text: str, need_in) -> dict:
    """ข้อมูลที่ข้อความลูกค้านี้บอก — ใช้ตัวอ่านชุดเดียวกับบอท (ถ้าบอทอ่านไม่ออก ก็ไม่นับว่าบอก)"""
    t = text or ""
    got = {}
    if need_in is not None and need_in(t):
        got["need"] = True
    if NF.parse_pitch(t) is not None or NF.stated_pitch(t) is not None:
        got["pitch"] = True
    if NF.parse_temp(t) is not None:
        got["temp"] = True
    if extract_modutech_slots(t, ()).get("wet_or_dry"):
        got["wet"] = True
    return got


def detect(goal: dict, transcript: list[dict], score: dict | None = None, need_in=None, codes_in=None) -> list[dict]:
    """need_in(text) → ข้อความบอกงานไหม (plugin._need_in) · codes_in(text) → รหัส Modutech ในข้อความ"""
    issues: list[dict] = []
    known: dict = {}
    bot_i = 0
    prev_bot = None

    def add(kind, detail):
        issues.append({"kind": kind, "turn": bot_i, "detail": detail})

    closed = False                               # ข้อความลูกค้าล่าสุดเป็นการขอบคุณปิดท้าย
    for t in transcript:
        text = t.get("text") or ""
        if t["role"] == "customer":
            closed = bool(CLOSE_RX.search(text)) and not QUESTION_IN_RX.search(text)
            got = _given(text, need_in)
            if MX_WIDTH_GIVEN_RX.search(text):
                got["mx_width"] = True
            if got.get("need") and known.get("need"):
                known = {}                       # เปลี่ยนงาน → ข้อมูลเดิมไม่ใช้กับงานใหม่ (C33)
            known.update(got)
            if FRUSTRATION_RX.search(text):
                add("frustration", text[:120])
            continue
        bot_i += 1
        asked = _asked(text) | ({"mx_width"} if MX_WIDTH_ASK in text else set())
        for k in sorted(asked):
            if known.get(k):
                add("reask_known", f"ถาม{ {'need': 'งาน', 'pitch': 'พิทช์', 'temp': 'อุณหภูมิ', 'wet': 'เปียก/แห้ง', 'mx_width': 'ความกว้าง'}[k] } ที่ลูกค้าบอกแล้ว")
        if closed and asked:
            add("ask_after_close", f"ลูกค้าขอบคุณปิดท้ายแล้ว บอทถาม{'/'.join(sorted(asked))}")
        if prev_bot is not None and text.strip() and text.strip() == prev_bot.strip():
            add("repeat_reply", text[:80])
        prev_bot = text
        if OFFTOPIC_TH in text and bot_i > 1:
            add("offtopic", text[:80])
        for line in text.split("\n"):
            if PROMISE_RX.search(line) and not PROMISE_SAFE_RX.search(line):
                add("promise", line.strip()[:160])
        _, fake = RG.scrub_contacts(text)
        if fake:
            add("fake_contact", ", ".join(fake[:3]))
        leak = RG.leaks(text)
        if leak or PROMPT_RX.search(text):
            add("internal_leak", ", ".join(leak[:3]) or PROMPT_RX.search(text).group(0))
        if FALLBACK_RX.search(text):
            add("error", text[:80])
        if goal.get("brand") == "movex" and codes_in is not None and codes_in(text):
            add("wrong_brand", ", ".join(codes_in(text)[:3]))
    if score:
        if score.get("final_violations"):
            issues.append({"kind": "violation", "turn": None, "detail": ", ".join(score["final_violations"][:5])})
        if score.get("ended") in ("giveup", "max_turns"):
            issues.append({"kind": "giveup", "turn": None, "detail": score["ended"]})
    return issues
