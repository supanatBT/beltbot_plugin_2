"""
test_conversation_leaks.py — คุยหลายเทิร์นแบบลูกค้าจริง หาเคสรั่วของบริบท (ไม่ใช้ LLM · ไม่ใช้โมเดลรูป)

เกิดจากเทสบนเว็บ 25 ต.ค.: ถามทีละข้อเสร็จ → บอทเสนอสองรุ่น → "ขอดูสเปคทั้งสองตัวเทียบกัน" ถูกตีว่านอกเรื่อง
ชุด test_core_* ตรวจทีละเทิร์น ไม่จับอาการ "คุยไปแล้วหลุด" จึงต้องมีชุดนี้

วิธี
    · เดินผ่าน core/turn.TurnEngine จริง + core/decide จริง + ปลั๊กอินจริงทั้งสองแบรนด์
    · ฝั่ง Modutech เรียก build_modutech_turn จริง (กรอง · application match · gates) แล้วตรวจ context ที่จะส่งให้ LLM
    · LLM ปลอม: ตอบตามบท ถ้าบทไม่ระบุ จะ "เอ่ยชื่อรุ่น" จาก products ใน context สูงสุด 2 รุ่น (เหมือน LLM ที่แนะนำรุ่น)
    · ทุกเทิร์นตรวจกฎกลาง (INV) + กฎเฉพาะเทิร์นในบท

กฎกลาง (ทุกเทิร์น ทุกบท)
    INV-1  ไม่มี exception
    INV-2  เทิร์นที่ 2 ขึ้นไปไม่ถูกตีว่านอกเรื่อง (ยกเว้นบทบอกว่าตั้งใจ)
    INV-3  ตอบ Modutech โดยมีรุ่นในโฟกัส → context ต้องมี products ของรุ่นนั้น (ไม่ถูกกรองหาย)
    INV-4  ไม่ถามแบรนด์ซ้ำเมื่อรู้แบรนด์แล้ว และข้อความไม่ได้เอ่ยแบรนด์อื่น
    INV-5  ส่งให้ LLM แล้ว context ต้องมีอะไรให้ตอบ (products / search_result / application / industry / need_filter)
    INV-6  LLM ไม่เห็นสถานะภายใน (_flow · _pitch_said)

    python test_conversation_leaks.py            # ทุกบท
    python test_conversation_leaks.py -v         # พิมพ์ทุกเทิร์น
    python test_conversation_leaks.py --only C07
    python test_conversation_leaks.py --export-csv testcases_conversation_leaks.csv   # บทเดียวกันสำหรับ Gemini จริง
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as DS  # noqa: E402
from brands.modutech.turn import build_modutech_turn  # noqa: E402
from core.protocol import LLMTurn, TurnOutput  # noqa: E402
from core.turn import TurnEngine  # noqa: E402

data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
REAL_MX = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
CAT = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
MGR = DS.DialogueManager(REAL_MX, CAT)
CORE = MGR.core
MOD, MX = MGR.modutech_plugin, MGR.movex_plugin

FAKE_VECTOR = [p["belt_code_id"] for p in CAT.products[:5]]
ANSWERABLE_KEYS = ("products", "search_result", "application_match", "industry_match", "need_filter",
                   "sprocket_query", "application_pair_absent")


class _Log:
    n = 0

    def new_session(self):
        return "s"

    def start_turn(self, **kw):
        _Log.n += 1
        return SimpleNamespace(turn_id=f"t{_Log.n}", summary_top1_pid="", summary_tool_calls=0)

    def log_llm(self, *a, **k):
        pass

    def finish_turn(self, *a, **k):
        pass


class _Tools:
    calls = []

    def reset(self):
        pass


class Recorder:
    """จำว่าเทิร์นนี้ส่งอะไรให้ LLM · ตอบตามบทหรือเอ่ยชื่อรุ่นจาก context"""

    def __init__(self):
        self.script_reply = None
        self.last = None            # dict(brand, decision, context)

    # ── Modutech ──
    def mod_build(self, decision, turn):
        # ค้นเวกเตอร์ปลอม: คืน 5 รุ่นแรกของแคตตาล็อกเสมอ (ของจริงคืนอะไรสักอย่างเสมอเหมือนกัน)
        t = build_modutech_turn(decision, CAT, MOD.search, vector_search=lambda q: FAKE_VECTOR, kg=None)
        self.last = dict(brand="modutech", decision=decision, context=t.context)
        return LLMTurn(system_prompt="", user_parts=[decision.effective_text])

    def mod_finish(self, decision, turn, llm_turn, result):
        ctx = (self.last or {}).get("context") or {}
        if self.script_reply is not None:
            reply = self.script_reply
        else:
            codes = [p["belt_code"] for p in ctx.get("products") or []][:2]
            reply = ("แนะนำ " + " และ ".join(codes) + " ครับ") if codes else "ไม่มีรุ่นที่ตรงเงื่อนไขครับ"
        return TurnOutput(reply)

    # ── Movex ──
    def mx_build(self, decision, turn):
        self.last = dict(brand="movex", decision=decision, context={})
        return LLMTurn(system_prompt="", user_parts=[decision.effective_text])

    def mx_finish(self, decision, turn, llm_turn, result):
        if self.script_reply is not None:
            return TurnOutput(self.script_reply)
        pids = (decision.payload or {}).get("pids") or []
        return TurnOutput(f"ตอบเรื่อง {', '.join(pids) or 'Movex'} ครับ")


class _LLM:
    def run(self, *a, **k):
        return None


_real_decide = CORE.decide
LAST = {}


def _capture_decide(*a, **k):
    d = _real_decide(*a, **k)
    LAST["d"] = d
    return d


CORE.decide = _capture_decide


def new_engine(rec: Recorder) -> TurnEngine:
    MOD.runtime = SimpleNamespace(build_turn=rec.mod_build, finish_turn=rec.mod_finish)
    MX.build_turn = rec.mx_build
    MX.finish_turn = rec.mx_finish
    CORE.image_brands = ("movex",)
    return TurnEngine(CORE, llm=_LLM(), logger=_Log(), tool_log=_Tools(), image_scorers={})


# ═══════════════════════════════════ บทสนทนา ═══════════════════════════════════
# แต่ละเทิร์น: (ข้อความลูกค้า, ความคาดหวัง) — ความคาดหวังเป็น dict
#   action / not_action      action ที่ต้องได้ / ห้ามได้ (str หรือ tuple)
#   brand                    แบรนด์ที่ต้องได้
#   reply_has                ข้อความบอทต้องมีคำนี้ (str หรือ tuple = อย่างน้อยหนึ่ง)
#   codes                    รหัสที่ต้องอยู่ใน payload.codes (ทุกตัว)
#   ctx_codes                รหัสที่ต้องอยู่ใน products ที่ส่งให้ LLM (ทุกตัว)
#   ctx_has                  key ที่ต้องมีใน context
#   bot                      คำตอบของ LLM ปลอมในเทิร์นนี้ (แทนการเอ่ยชื่อรุ่นอัตโนมัติ)
#   offtopic_ok              เทิร์นนี้ตั้งใจให้นอกเรื่องได้
#   slot                     {ชื่อ: ค่า} ที่ต้องอยู่ใน slots ของ Modutech หลังเทิร์นนี้
# ════════════════════════════════════════════════════════════════════════════════

WEB_BOT = ("สายพาน Modutech ไม่มีรุ่นที่มีระยะพิทช์ 50.6 มม. ครับ มีรุ่นพิทช์ใกล้เคียง 50.8 มม. ได้แก่\n"
           "• MD508 C\n• EC508 PR11")

SCENARIOS = {
    "C01": ("บทจากเว็บ 25 ต.ค. (ถามทีละข้อ → เสนอสองรุ่น → เทียบ)", [
        ("สายพาน modutech รุ่นไหนดี", dict(action="ask", reply_has="ลำเลียงอะไร")),
        ("ใช้ในโรงงานบรรจุ", dict(reply_has="พิทช์")),
        ("50.6", dict(reply_has="หมายถึง 50.8")),
        ("ไม่ใช่", dict(reply_has="ถ้าไม่ใช่ 50.8")),
        ("ไม่ทราบ", dict(reply_has="อุณหภูมิ")),
        ("ไม่แน่ใจ", dict(action="answer", bot=WEB_BOT)),
        ("ขอดูสเปคทั้งสองตัวเทียบกัน", dict(action="answer", codes=["MD508 C", "EC508 PR11"],
                                            ctx_codes=["MD508 C", "EC508 PR11"])),
        ("ตัวไหนทนร้อนกว่ากัน", dict(not_action="refuse_offtopic", codes=["MD508 C", "EC508 PR11"])),
        ("ขอบคุณครับ", dict(action="smalltalk")),
    ]),
    "C02": ("ตอบหลายข้อในประโยคเดียว", [
        ("แนะนำสายพาน modutech หน่อย", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่ พิทช์ 2 นิ้ว 80 องศา ไลน์เปียก", dict(action="answer", slot={"pitch_mm": 50.8, "temp_c": 80.0})),
        ("ตัวแรกกว้างได้เท่าไหร่", dict(not_action="refuse_offtopic")),
    ]),
    "C03": ("ลูกค้าถามกลับระหว่างถามพิทช์", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("เนื้อหมู", dict(reply_has="พิทช์")),
        ("พิทช์คืออะไรครับ", dict(reply_has=("ระยะ", "พิทช์"), not_action="refuse_offtopic")),
    ]),
    "C04": ("พิมพ์รหัสกลางการถาม แล้วคุยต่อเรื่องรหัส", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่", dict(reply_has="พิทช์")),
        ("จริงๆ ใช้ EC508 C อยู่แล้ว ขอสเปกหน่อย", dict(action="answer", codes=["EC508 C"], ctx_codes=["EC508 C"])),
        ("ทนร้อนได้กี่องศา", dict(not_action="refuse_offtopic", codes=["EC508 C"])),
        ("เปียก", dict(not_action="refuse_offtopic", codes=["EC508 C"])),
    ]),
    "C05": ("เปลี่ยนแบรนด์กลางทาง แล้วกลับมา", [
        ("EC508 C ใช้กับไก่ได้ไหม", dict(brand="modutech", codes=["EC508 C"])),
        ("แล้วโซ่ Movex LF820 K325 กว้างเท่าไหร่", dict(brand="movex")),
        ("กลับมาที่ EC508 C พิทช์เท่าไหร่", dict(brand="modutech", codes=["EC508 C"])),
    ]),
    "C06": ("คุยต่อสั้น ๆ หลังได้รหัส", [
        ("MP80 C กว้างเท่าไหร่", dict(codes=["MP80 C"])),
        ("แล้วราคาล่ะ", dict(not_action="refuse_offtopic")),
        ("ส่งของกี่วัน", dict(not_action="refuse_offtopic")),
        ("ขอเป็นนิ้ว", dict(not_action="refuse_offtopic", codes=["MP80 C"])),
        ("มีสีอะไรบ้าง", dict(not_action="refuse_offtopic", codes=["MP80 C"])),
        ("ใช้สเตอร์อะไร", dict(not_action="refuse_offtopic", codes=["MP80 C"])),
    ]),
    "C07": ("แนะนำงานใหม่หลังเพิ่งได้คำแนะนำ (โฟกัสเก่าไม่ควรค้าง)", [
        ("สายพาน modutech สำหรับไก่ รุ่นไหนดี", dict(action="answer")),
        ("แล้วถ้าเป็นขนมปังเข้าเตาอบล่ะ", dict(action="answer", ctx_has="application_match")),
    ]),
    "C08": ("ไม่รู้อะไรเลย", [
        ("อยากได้สายพาน modutech", dict(reply_has="ลำเลียงอะไร")),
        ("ไม่รู้ครับ", dict(not_action="refuse_offtopic")),
        ("ไม่ทราบ", dict(not_action="refuse_offtopic")),
        ("ไม่ทราบ", dict(not_action="refuse_offtopic")),
    ]),
    "C09": ("ขอเบอร์กลางการถาม แล้วตอบต่อ", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        # 26 ต.ค.: ให้เบอร์แล้วถามข้อเดิมต่อ (เดิม escalate แล้วล้างการรอคำตอบ)
        ("ขอเบอร์ฝ่ายขายหน่อย", dict(action="ask", reply_has="086-3451403")),
        ("อาหารทะเล", dict(not_action="refuse_offtopic", reply_has="พิทช์")),
        ("เดี๋ยวก่อน ขอเบอร์อีกที", dict(action="ask", reply_has="ระยะพิทช์")),
        # เดิม "2 นิ้ว" หลังขอเบอร์ถูกบันทึกเป็น "ไม่ทราบ" เพราะการรอคำตอบหาย
        ("2 นิ้ว", dict(reply_has="อุณหภูมิ", slot={"pitch_mm": 50.8})),
    ]),
    "C09b": ("ขอเบอร์กลางการถาม หลังบอกงานด้วยคำว่า 'ใช้กับ' (ลูกค้าจำลอง G11)", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ใช้กับไก่ครับ ไลน์ตัดแต่ง", dict(reply_has="พิทช์")),
        ("ขอเบอร์ฝ่ายขายก่อนได้ไหมครับ พอดีอยากคุยรายละเอียดเพิ่ม", dict(action="ask", reply_has="086-3451403")),
        ("โอเคครับ จดเบอร์ไว้แล้ว ส่วนพิทช์ใช้ 2 นิ้วครับ", dict(reply_has="อุณหภูมิ", slot={"pitch_mm": 50.8})),
    ]),
    "C10": ("อ้างถึงรุ่นด้วยคำอ้างอิงหลายแบบ", [
        ("สายพาน modutech สำหรับไก่ รุ่นไหนดี", dict(action="answer", bot="แนะนำ EC508 C และ HC508 C ครับ")),
        ("ตัวแรกพิทช์เท่าไหร่", dict(not_action="refuse_offtopic", codes=["EC508 C"])),
        ("แล้วตัวหลังล่ะ", dict(not_action="refuse_offtopic")),
        ("สองตัวนี้ต่างกันยังไง", dict(not_action="refuse_offtopic", codes=["EC508 C", "HC508 C"])),
        ("อันไหนดีกว่า", dict(not_action="refuse_offtopic")),
    ]),
    "C11": ("พิมพ์ผิด / ภาษาอังกฤษ / ภาษาพูด", [
        ("สายพานโมดูล่ารุ่นไหนเหมาะกับไก่", dict(not_action="refuse_offtopic")),
        ("belt for chicken which model", dict(not_action="refuse_offtopic", ctx_has="industry_match")),
        ("เอาแบบที่ล้างง่ายๆอ่ะ", dict(not_action="refuse_offtopic")),
    ]),
    "C12": ("อุณหภูมิแบบภาษาพูด", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่", dict(reply_has="พิทช์")),
        ("2 นิ้ว", dict(reply_has="อุณหภูมิ")),
        ("ไม่เกิน 80", dict(slot={"temp_c": 80.0})),
    ]),
    "C13": ("ช่องแช่แข็ง", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่เข้าห้องแช่แข็ง", dict(reply_has="พิทช์")),
        ("ไม่ทราบ", dict(reply_has="อุณหภูมิ")),
        ("ลบ 35", dict(slot={"temp_c": -35.0})),
    ]),
    "C14": ("ถามแบรนด์แล้วตอบด้วยชื่อสินค้า", [
        ("มีสายพานแนะนำไหม", dict(action="ask")),
        ("สายพานโมดูลาร์", dict(brand="modutech")),
        ("ไก่", dict(not_action="refuse_offtopic")),
    ]),
    "C15": ("พูดถึงงานก่อน แล้วค่อยถามหาแบบ", [
        ("ทำโรงงานไก่ครับ", dict(not_action="refuse_offtopic")),
        ("มีสายพานแนะนำไหม", dict(not_action="refuse_offtopic")),
    ]),
    "C16": ("หลังจบการถาม ลูกค้าเปลี่ยนพิทช์", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่", dict(reply_has="พิทช์")),
        ("2 นิ้ว", dict(reply_has="อุณหภูมิ")),
        ("ไม่ทราบ", dict(action="answer")),
        # 26 ต.ค. (c16_*.json): ยังเป็นงานไก่ (ไม่ค้นพิทช์ทั้งฐาน) + พิทช์ใหม่แทนค่าเดิม
        ("ถ้าเป็นพิทช์ 1 นิ้วล่ะ", dict(not_action="refuse_offtopic", action="answer", ctx_has="industry_match",
                                         slot={"pitch_mm": 25.4})),
    ]),
    "C17": ("Movex ซีรีส์ → เลือกความกว้าง → ถามต่อ", [
        ("โซ่ Movex 880 มีขนาดไหนบ้าง", dict(brand="movex")),
        ("ตัวที่กว้างกว่า", dict(brand="movex", not_action=("refuse_offtopic", "ask"))),
        ("ใช้สเตอร์อะไร", dict(brand="movex", not_action="refuse_offtopic")),
        ("ทนร้อนได้กี่องศา", dict(brand="movex", not_action="refuse_offtopic")),
    ]),
    "C18": ("Movex รหัส → เปลี่ยนรุ่นในซีรีส์", [
        ("LF820 K325 ทนร้อนกี่องศา", dict(brand="movex")),
        ("แล้ว K400 ล่ะ", dict(brand="movex", not_action="refuse_offtopic")),
    ]),
    "C19": ("สแตนเลสไม่ระบุแบรนด์ → เลือก Modutech → ถามงาน", [
        ("มีแบบสแตนเลสไหม", dict(action="cross_brand")),
        ("เอาของ Modutech", dict(brand="modutech", action="search")),
        ("ตัวไหนใช้กับอาหารทะเลได้", dict(brand="modutech", not_action="refuse_offtopic", no_codes=True)),
    ]),
    "C20": ("ทักก่อนแล้วค่อยถาม", [
        ("สวัสดีครับ", dict(action="smalltalk")),
        ("อยากได้สายพานสำหรับไก่", dict(not_action="refuse_offtopic")),
        ("modutech", dict(brand="modutech", not_action="refuse_offtopic")),
    ]),
    "C21": ("ออกนอกเรื่องแล้วกลับมา", [
        ("อากาศวันนี้เป็นยังไง", dict(offtopic_ok=True)),
        ("ขอสเปก MP80 C", dict(codes=["MP80 C"])),
        ("วันนี้กินอะไรดี", dict(offtopic_ok=True)),
        ("แล้ว MP80 C กว้างสุดเท่าไหร่", dict(codes=["MP80 C"])),
    ]),
    "C22": ("พิมพ์รหัสแบบหลวม ๆ", [
        ("ec508c สเปก", dict(not_action="refuse_offtopic", brand="modutech")),
        ("EC 508 C ทนร้อนกี่องศา", dict(not_action="refuse_offtopic", brand="modutech")),
    ]),
    "C23": ("หลังแนะนำ ขอรุ่นอื่นเพิ่ม", [
        ("สายพาน modutech สำหรับไก่ รุ่นไหนดี", dict(action="answer")),
        ("มีรุ่นอื่นอีกไหม", dict(not_action="refuse_offtopic", ctx_has="excluded_already_offered",
                                  ctx_not_codes="__prev__")),
        ("ขอแบบผิวกันลื่น", dict(not_action="refuse_offtopic", no_codes=True)),
    ]),
    "C24": ("หลังแนะนำ ถามราคาทั้งสองตัว", [
        ("สายพาน modutech สำหรับไก่ รุ่นไหนดี", dict(action="answer", bot="แนะนำ EC508 C และ HC508 C ครับ")),
        ("ราคาเท่าไหร่ทั้งสองตัว", dict(not_action=("refuse_offtopic", "ask"))),
    ]),
    "C25": ("รหัส → สเตอร์ → เพลา → แบบ", [
        ("EC508 C ใช้สเตอร์อะไร", dict(codes=["EC508 C"])),
        ("แล้วเพลาล่ะ", dict(not_action="refuse_offtopic", codes=["EC508 C"])),
        ("ขอ drawing", dict(not_action="refuse_offtopic")),
    ]),
    "C26": ("ตอบเปียก/แห้งแบบภาษาพูด", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่", dict(reply_has="พิทช์")),
        ("2 นิ้ว", dict(reply_has="อุณหภูมิ")),
        ("80", dict(reply_has="เปียก")),
        ("ฉีดน้ำล้างทุกวัน", dict(action="answer", slot={"wet_or_dry": "wet"})),
    ]),
    "C27": ("ตอบพิทช์แบบภาษาพูด", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่", dict(reply_has="พิทช์")),
        ("ระยะ 50 มิล", dict(reply_has="50.8")),
    ]),
    "C28": ("ขอให้ตอบอีกแบบหลังได้คำตอบ", [
        ("MP80 C กว้างเท่าไหร่", dict(codes=["MP80 C"])),
        ("ขอเป็นภาษาอังกฤษ", dict(not_action="refuse_offtopic")),
        ("สรุปสั้นๆ ให้หน่อย", dict(not_action="refuse_offtopic")),
    ]),
    "C29": ("ตอบแบรนด์ด้วยชื่อ แล้วตอบงาน", [
        ("แนะนำสายพานหน่อย", dict(action="ask")),
        ("Modutech ครับ", dict(brand="modutech")),
        ("ไก่", dict(not_action="refuse_offtopic")),
        ("ไม่ทราบ", dict(not_action="refuse_offtopic")),
    ]),
    "C31": ("ถามต่อสั้น ๆ หลังบอทเสนอรายการยาว (conv_r1/r2 CONV-30 กับ Gemini จริง)", [
        ("สายพาน modutech สำหรับไก่ รุ่นไหนดี", dict(action="answer", bot=(
            "อุตสาหกรรมสัตว์ปีกมี 27 รุ่น เช่น EC508 PR11, MP80 C, MP80 FG, EC508 C, HC508 C, "
            "HC508 MR, HC508 NT, EC508 FG, EC508 TR ครับ"))),
        ("ทำไม", dict(not_action="refuse_offtopic")),
        ("แพงไหม", dict(not_action="refuse_offtopic")),
        ("ตัวแรกพิทช์เท่าไหร่", dict(codes=["EC508 PR11"])),
    ]),
    "C30": ("คำถามสั้นมากต่อจากการถามทีละข้อที่จบแล้ว", [
        ("สายพาน modutech รุ่นไหนดี", dict(reply_has="ลำเลียงอะไร")),
        ("ไก่", dict(reply_has="พิทช์")),
        ("ไม่ทราบ", dict(reply_has="อุณหภูมิ")),
        ("ไม่ทราบ", dict(action="answer", bot="แนะนำ EC508 C และ HC508 C ครับ")),
        ("ทำไม", dict(not_action="refuse_offtopic")),
        ("แพงไหม", dict(not_action="refuse_offtopic")),
    ]),
}


def check(cid, i, text, exp, d, rec, engine, reply, prev_brand) -> list[str]:
    errs = []
    ctx = (rec.last or {}).get("context") if rec.last and rec.last.get("decision") is d else None
    acts = lambda v: (v,) if isinstance(v, str) else tuple(v)  # noqa: E731
    if "action" in exp and d.action not in acts(exp["action"]):
        errs.append(f"action {d.action} ≠ {exp['action']} ({d.reason})")
    if "not_action" in exp and d.action in acts(exp["not_action"]):
        errs.append(f"action {d.action} ต้องไม่ใช่ ({d.reason})")
    if "brand" in exp and d.brand != exp["brand"]:
        errs.append(f"brand {d.brand} ≠ {exp['brand']}")
    if "reply_has" in exp:
        need = acts(exp["reply_has"])
        if not any(w in (reply or "") for w in need):
            errs.append(f"คำตอบไม่มี {need}: {(reply or '')[:70]!r}")
    if "codes" in exp:
        got = list((d.payload or {}).get("codes") or (d.payload or {}).get("pids") or [])
        miss = [c for c in exp["codes"] if c not in got]
        if miss:
            errs.append(f"โฟกัสขาด {miss} (ได้ {got})")
    if "ctx_codes" in exp:
        got = [p["belt_code"] for p in (ctx or {}).get("products") or []]
        miss = [c for c in exp["ctx_codes"] if c not in got]
        if miss:
            errs.append(f"products ที่ส่ง LLM ขาด {miss} (ได้ {got})")
    if exp.get("no_codes") and (d.payload or {}).get("codes"):
        errs.append(f"ควรค้นใหม่ แต่ใช้โฟกัสเดิม {(d.payload or {}).get('codes')}")
    if exp.get("ctx_not_codes") == "__prev__" and ctx is not None:
        prev = set(engine._prev_offered)
        got = [p["belt_code"] for p in ctx.get("products") or []]
        if prev & set(got):
            errs.append(f"เสนอรุ่นเดิมซ้ำ {sorted(prev & set(got))}")
    if "ctx_has" in exp and exp["ctx_has"] not in (ctx or {}):
        errs.append(f"context ไม่มี {exp['ctx_has']} (มี {sorted((ctx or {}).keys())})")
    if "slot" in exp:
        st = CORE.state_cls.from_dict(engine.dialog_states.get("s"))
        sl = st.brands["modutech"]["slots"]
        for k, v in exp["slot"].items():
            if sl.get(k) != v:
                errs.append(f"slot {k}={sl.get(k)!r} ≠ {v!r}")
    # ── กฎกลาง ──
    if i > 0 and d.action == "refuse_offtopic" and not exp.get("offtopic_ok"):
        errs.append("INV-2 นอกเรื่องกลางบทสนทนา")
    if d.brand == "modutech" and ctx is not None and (d.payload or {}).get("codes") and not ctx.get("products"):
        errs.append(f"INV-3 มีโฟกัส {(d.payload or {}).get('codes')} แต่ products ว่าง")
    if d.action == "ask" and d.topic == "brand" and prev_brand and not any(
            CORE.plugins[k].detect(text).strength == "strong" for k in CORE.plugins if k != prev_brand):
        errs.append(f"INV-4 ถามแบรนด์ซ้ำ ทั้งที่รู้แล้วว่า {prev_brand}")
    if ctx is not None and d.brand == "modutech" and not any(ctx.get(k) for k in ANSWERABLE_KEYS):
        errs.append(f"INV-5 ส่งให้ LLM แต่ context ว่าง (keys {sorted(ctx)})")
    if ctx is not None and any(k.startswith("_") for k in (ctx.get("slots_known") or {})):
        errs.append("INV-6 LLM เห็นสถานะภายใน")
    return errs


def run_scenario(cid, title, turns, verbose=False) -> list[tuple]:
    rec = Recorder()
    eng = new_engine(rec)
    hist, failures, prev_brand = [], [], None
    eng._prev_offered = []
    for i, (text, exp) in enumerate(turns):
        rec.script_reply = exp.get("bot")
        rec.last = None
        LAST.pop("d", None)
        try:
            out = eng.chat(text, None, hist, session_id="s")
        except Exception as e:  # noqa: BLE001
            failures.append((cid, i + 1, text, [f"INV-1 exception {type(e).__name__}: {e}"]))
            if verbose:
                traceback.print_exc()
            break
        hist = out[0]
        reply = hist[-1]["content"] if hist else ""
        st = CORE.state_cls.from_dict(eng.dialog_states.get("s"))
        d = LAST.pop("d")
        errs = check(cid, i, text, exp, d, rec, eng, reply, prev_brand)
        if verbose:
            mark = "✗" if errs else "·"
            print(f"   {mark} t{i + 1} {text!r:34} → {d.action:9} brand={d.brand} | {reply[:60]!r}")
            for e in errs:
                print(f"        {e}")
        if errs:
            failures.append((cid, i + 1, text, errs))
        prev_brand = st.brand or prev_brand
        eng._prev_offered = list(st.brands["modutech"]["slots"].get("_offered") or [])
    return failures


OFFTOPIC_TH = "ผมตอบได้เฉพาะเรื่องสินค้า"


def export_csv(path: str) -> int:
    """บทเดียวกันในรูป testcases สำหรับ run_answer_eval.py (Gemini จริง)

    ตรวจแค่สิ่งที่ไม่ขึ้นกับสำนวน LLM: เทิร์น 2 ขึ้นไปห้ามปฏิเสธนอกเรื่อง · คำถามที่โค้ดเขียนเอง (reply_has) ·
    รหัสที่ลูกค้าพิมพ์ในเทิร์นนั้นต้องอยู่ในคำตอบ (รหัสจากเทิร์นก่อนไม่บังคับ — เทิร์นนั้นอาจเป็นคำถามกลับ
    เช่น ถามเปียก/แห้ง ซึ่งไม่เอ่ยรหัส · conv_r1 CONV-04 t4 ตกเพราะกฎเดิม ไม่ใช่บอทรั่ว)"""
    import csv
    cols = ["id", "category", "subcategory", "turn_type", "turn_number", "user_text", "image", "must_contain",
            "must_contain_any", "must_not_contain", "must_ask_back", "expected_value", "expected_unit",
            "reply_max_length", "metrics", "description"]
    rows = []
    for cid, (title, turns) in SCENARIOS.items():
        for i, (text, exp) in enumerate(turns, 1):
            typed = [c for c in CAT.by_code if c.lower() in text.lower()]
            must = [c for c in exp.get("codes", []) if c in typed]
            rh = exp.get("reply_has")
            rh = [rh] if isinstance(rh, str) else list(rh or [])
            forbid = [] if (i == 1 or exp.get("offtopic_ok")) else [OFFTOPIC_TH]
            rows.append(dict(id=f"CONV-{cid[1:]}", category="conversation", subcategory="leak", turn_type="multi",
                             turn_number=str(i), user_text=text, image="", must_contain=" | ".join(must),
                             must_contain_any=" | ".join(rh), must_not_contain=" | ".join(forbid),
                             must_ask_back="", expected_value="", expected_unit="", reply_max_length="",
                             metrics="conversation", description=title if i == 1 else ""))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"เขียน {path}: {len(SCENARIOS)} บท {len(rows)} เทิร์น")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--export-csv", default="", help="เขียนบทเป็น testcases CSV สำหรับ run_answer_eval.py แล้วจบ")
    a = ap.parse_args()
    if a.export_csv:
        return export_csv(a.export_csv)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    all_fail, n_turns = [], 0
    for cid, (title, turns) in SCENARIOS.items():
        if only and cid not in only:
            continue
        if a.v:
            print(f"\n{cid} {title}")
        f = run_scenario(cid, title, turns, a.v)
        n_turns += len(turns)
        all_fail += f
        if not a.v:
            print(f"  {'✗' if f else '✓'} {cid} {title}" + (f"  ({len(f)} เทิร์นรั่ว)" if f else ""))
    if all_fail and not a.v:
        print("\nเทิร์นที่รั่ว")
        for cid, t, text, errs in all_fail:
            print(f"  {cid} t{t} {text!r}")
            for e in errs:
                print(f"      {e}")
    n_sc = len([c for c in SCENARIOS if not only or c in only])
    bad_sc = len({f[0] for f in all_fail})
    print(f"\nรวม {n_sc - bad_sc}/{n_sc} บทผ่าน · {len(all_fail)} เทิร์นรั่ว จาก {n_turns} เทิร์น")
    return 1 if all_fail else 0


if __name__ == "__main__":
    sys.exit(main())
