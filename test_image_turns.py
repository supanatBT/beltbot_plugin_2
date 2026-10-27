"""
test_image_turns.py — เทิร์นที่มีรูป ครบทุกคู่ (ประวัติแชต × ผลรูป × มี/ไม่มีข้อความ) ผ่าน TurnEngine จริง

ที่มา (27 ต.ค. 2026): ส่งรูปเปล่ากลางแชตที่คุย HC508 C อยู่ → ลูกค้าเห็น
    ❌ เกิดข้อผิดพลาด: 400 INVALID_ARGUMENT … Requests ending with a model turn are not supported.
เพราะประตูรูป Modutech มั่นใจ → ปลั๊กอินตัดสินว่า "ตอบ" ด้วยข้อความว่าง → Modutech ไม่ส่งรูปให้ LLM
(user_parts = [effective_text] = [""]) → Gemini ได้ประวัติที่จบด้วยคำตอบบอท
ชุด TEST_web_local ข้อ B และ test_core_image_policy ไม่มีเคส "รูปเปล่ากลางแชต" จึงไม่เคยเจอ

ไม่โหลดโมเดล ไม่เรียก Gemini
    ตัวตัดสิน · ปลั๊กอิน · build_turn ของ Modutech = ของจริง (retriever ปิด — ค้นจากรหัสและทั้งฐานแทน)
    build_turn ของ Movex = ของปลอมตามสัญญา brands/movex/runtime.py บรรทัด 822: [รูป, prompt] / [prompt]
    ตัวให้คะแนนรูป Movex · ประตูรูป Modutech · LLM = ของปลอม
    LLM ปลอมโยน error แบบเดียวกับ Gemini เมื่อเทิร์นผู้ใช้ว่าง — เคสเดิมจึงตกในเทสต์นี้ก่อนแก้

    python test_image_turns.py
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as DS                                    # noqa: E402
from brands.modutech.kg import load_modutech_kg                # noqa: E402
from brands.modutech.runtime import ModutechRuntime            # noqa: E402
from core.decide import GENERIC_REJECT_IMAGE_TH                # noqa: E402
from core.image_policy import GateReading                      # noqa: E402
from core.llm import LLMResult                                 # noqa: E402
from core.protocol import ImageScore, LLMTurn                  # noqa: E402
from core.tools import ToolLog                                 # noqa: E402
from core.turn import TurnEngine                               # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


# ── ของจริง ──
data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
mgr = DS.DialogueManager(real, cat)
core = mgr.core
tool_log = ToolLog()
mod = mgr.modutech_plugin
mod.runtime = ModutechRuntime(cat, mod.search, load_modutech_kg(cat, os.path.join(ROOT, "modutech_kg.db"), quiet=True),
                              None, tool_log)

IMG_PART = {"mime_type": "image/jpeg", "data": b"img"}


def movex_build(decision, turn):
    """สัญญาของ MovexRuntime.build_turn — prompt ประกอบจากเทมเพลตจึงไม่ว่าง รูปแนบเมื่อมี"""
    prompt = f"[prompt Movex] คำถาม: {decision.effective_text}"
    return LLMTurn("sys", [IMG_PART, prompt] if turn.image is not None else [prompt])


def movex_finish(decision, turn, llm_turn, result):
    from core.protocol import TurnOutput
    return TurnOutput(result.response.text)


mgr.movex_plugin.build_turn = movex_build
mgr.movex_plugin.finish_turn = movex_finish


class FakeLLM:
    """จำสิ่งที่ส่งมา · เทิร์นผู้ใช้ว่าง = error เดียวกับ Gemini"""

    def __init__(self):
        self.calls = []

    def run(self, llm_turn, chat_history, tool_calls):
        parts = list(llm_turn.user_parts)
        self.calls.append(parts)
        if not any((p.strip() if isinstance(p, str) else p is not None) for p in parts):
            raise RuntimeError("400 INVALID_ARGUMENT. Requests ending with a model turn are not supported.")
        resp = SimpleNamespace(text="คำตอบจำลอง", candidates=[])
        session = SimpleNamespace(send_message=lambda m: resp)
        return LLMResult(resp, session, tool_calls)


class _Log:
    def new_session(self):
        return "s"

    def start_turn(self, **k):
        return SimpleNamespace(turn_id="t", summary_top1_pid="", summary_tool_calls=0)

    def log_llm(self, *a, **k):
        pass

    def finish_turn(self, *a, **k):
        pass


class Scorer:
    def __init__(self, sc):
        self.sc = sc

    def score(self, image, text):
        return self.sc


class Gate:
    brand = "modutech"

    def __init__(self, reading):
        self.reading = reading

    def read(self, image):
        return self.reading


# ── ผลรูป 4 แบบ (ตัวเลขตามเกณฑ์ใน test_core_image_policy) ──
IMAGES = {
    "movex_dominant": (ImageScore("movex", 0.95, True, group="880", dominant=True,
                                  product_ref="movex_chain_LF880_TAB_K450"),
                       GateReading("modutech", True, False, {})),
    "modutech_direct": (ImageScore("movex", 0.30, False), GateReading("modutech", True, True, {})),
    # ViT รับ (0.50–0.85) + ประตูบอกว่าเป็นสินค้าแต่ไม่มั่นใจ = กำกวมจริง
    "ambiguous": (ImageScore("movex", 0.70, True, group="880"), GateReading("modutech", True, False, {})),
    # ViT ไม่รับ + ประตูบอกว่าเป็นสินค้าแต่ไม่มั่นใจ = น่าจะ Modutech (เคส R5 · 27 ต.ค.)
    "modutech_maybe": (ImageScore("movex", 0.30, False), GateReading("modutech", True, False, {})),
    # ของจริงจาก log 27 ต.ค.: ViT 0.4257 ระบุซีรีส์ไม่ได้ แต่ accepted = true (ระบบค้นเจอสินค้าบางอย่าง)
    "modutech_maybe_acc": (ImageScore("movex", 0.4257, True, group=None), GateReading("modutech", True, False, {})),
    "not_product": (ImageScore("movex", 0.13, False), GateReading("modutech", False, False, {})),
}
# ── ประวัติ 4 แบบ ──
HISTORIES = {
    "แชตใหม่": [],
    "คุย Modutech": ["HC508 C กว้างเท่าไหร่"],
    "คุย Movex": ["LF820 K325 รับแรงดึงเท่าไหร่"],
    "Modutech ถามค้าง": ["MP80 C ทนอุณหภูมิได้เท่าไหร่"],        # บอทถามเปียก/แห้งค้างไว้
}
TEXTS = {"รูปเปล่า": "", "รูป+ข้อความ": "รุ่นนี้คืออะไร"}

BAD = ("เกิดข้อผิดพลาด", "INVALID_ARGUMENT", "model turn")


def run_case(hist_name, img_name, text_name):
    sc, reading = IMAGES[img_name]
    llm = FakeLLM()
    e = TurnEngine(core, llm=llm, logger=_Log(), tool_log=tool_log,
                   image_scorers={"movex": Scorer(sc)}, image_gates={"modutech": Gate(reading)})
    core.image_brands = ("movex",)
    hist, sid = [], "s1"
    for t in HISTORIES[hist_name]:
        hist = e.chat(t, None, hist, session_id=sid)[0]
    before = len(llm.calls)
    out = e.chat(TEXTS[text_name], Image.new("RGB", (800, 600), (90, 90, 90)), hist, session_id=sid)
    reply, refs = out[0][-1]["content"], out[2]
    sent = llm.calls[before:]
    return reply, refs, sent


print("ทุกคู่: ประวัติ × ผลรูป × ข้อความ")
rows = []
for h in HISTORIES:
    for i in IMAGES:
        for t in TEXTS:
            reply, refs, sent = run_case(h, i, t)
            tag = f"{h} · {i} · {t}"
            decision = next((ln.split("**Decision:**")[1].split("·")[0].strip()
                             for ln in refs.splitlines() if "**Decision:**" in ln), "-")
            how = "ขอคำถาม" if "**Image-only:**" in refs else ("LLM" if sent else "ไม่เรียก LLM")
            rows.append((tag, decision, how, reply.replace("\n", " ")[:70]))

            ok(f"{tag}: ไม่มี error ดิบ", not any(b in reply for b in BAD), reply[:120])
            ok(f"{tag}: ไม่ส่งเทิร์นว่างให้ LLM",
               all(any((p.strip() if isinstance(p, str) else p is not None) for p in s) for s in sent), sent)

            if i == "not_product":
                ok(f"{tag}: ปฏิเสธรูป", "reject_image" in refs and reply == GENERIC_REJECT_IMAGE_TH, reply[:80])
            pending = h == "Modutech ถามค้าง"
            in_mod = h in ("คุย Modutech", "Modutech ถามค้าง")
            if i in ("ambiguous", "modutech_maybe", "modutech_maybe_acc") and in_mod:
                # กรณี 1 (ผู้ใช้เลือก 27 ต.ค.): แชตคุย Modutech อยู่ → ถือเป็น Modutech ไม่ถามแบรนด์ + บอกสิ่งที่สมมติ
                ok(f"{tag}: แชต Modutech → ไม่ถามแบรนด์ · บอกว่าน่าจะ Modutech และให้แก้ได้",
                   "ขอยืนยันก่อน" not in reply and "ถ้ารูปนี้ไม่ใช่" in reply, reply[:120])
                if h == "Modutech ถามค้าง":
                    ok(f"{tag}: คำถามเปียก/แห้งที่ค้างไม่หาย", "เปียก" in reply and not sent, (reply[:160], sent))
            elif i in ("modutech_maybe", "modutech_maybe_acc"):
                # กรณี 2: ไม่มีบริบท Modutech + ViT ไม่รับ → ถามยืนยันแบรนด์เดียว
                ok(f"{tag}: ถาม 'ใช่ Modutech ไหม' (ไม่ใช่เมนูสองแบรนด์) · ไม่เรียก LLM",
                   "Modutech ใช่ไหม" in reply and "Movex" not in reply and not sent, reply[:120])
            elif i == "ambiguous":
                # กรณี 3: กำกวมจริง → ถามสองแบรนด์เหมือนเดิม
                ok(f"{tag}: ถามแบรนด์ (ไม่เดา)", "ขอยืนยันก่อน" in reply and "Movex" in reply and not sent, reply[:80])
            if i == "modutech_direct" and t == "รูปเปล่า":
                if pending:
                    # บอทรอคำตอบเปียก/แห้งอยู่ → ถามข้อเดิมซ้ำ (ไม่เรียก LLM) พร้อมบอกว่าอ่านรุ่นจากรูปไม่ได้ — พฤติกรรมเดิม
                    ok(f"{tag}: ถามข้อที่ค้างซ้ำ + บอกว่ายังระบุรุ่นจากรูปไม่ได้ · ไม่เรียก LLM",
                       "ระบุรุ่นจากรูปไม่ได้" in reply and "เปียก" in reply and not sent, (reply[:100], sent))
                else:
                    ok(f"{tag}: บอกว่ายังระบุรุ่นจากรูปไม่ได้ + ขอคำถาม · ไม่เรียก LLM",
                       "ระบุรุ่นจากรูปไม่ได้" in reply and "พิมพ์คำถาม" in reply and not sent, (reply[:100], sent))
                ok(f"{tag}: ไม่อ้างรุ่นเดิมในแชตเหมือนเป็นรุ่นในรูป",
                   "HC508" not in reply and "MP80" not in reply and "LF820" not in reply, reply[:100])
            if i == "movex_dominant":
                if pending:
                    # Modutech รอคำตอบอยู่ + รูป Movex ชัด → ถามแบรนด์ก่อน (ไม่เดาว่าเปลี่ยนเรื่อง) — พฤติกรรมเดิม
                    # บันทึกไว้เป็นข้อสังเกต ยังไม่เปลี่ยน (รายงาน ไม่ตัดสินแทน)
                    ok(f"{tag}: ถามแบรนด์ (ไม่เดา) · ไม่เรียก LLM", "ขอยืนยันก่อน" in reply and not sent, reply[:80])
                else:
                    ok(f"{tag}: Movex ได้รูปแนบไปกับ LLM", bool(sent) and IMG_PART in sent[-1], sent)
            if i == "modutech_direct" and t == "รูป+ข้อความ":
                ok(f"{tag}: มีข้อความ → ทางเดิม (ไม่ใช่ขอคำถาม) และบอกว่ายังระบุรุ่นจากรูปไม่ได้",
                   "**Image-only:**" not in refs and "ระบุรุ่น" in reply, (reply[:100], refs[-300:]))

print("\nตอบคำถามยืนยันแบรนด์ (กรณี 2)")


def confirm_then(answer, first_text="", hist_name="แชตใหม่"):
    sc, reading = IMAGES["modutech_maybe"]
    llm = FakeLLM()
    e = TurnEngine(core, llm=llm, logger=_Log(), tool_log=tool_log,
                   image_scorers={"movex": Scorer(sc)}, image_gates={"modutech": Gate(reading)})
    core.image_brands = ("movex",)
    hist, sid = [], "c1"
    for t in HISTORIES[hist_name]:
        hist = e.chat(t, None, hist, session_id=sid)[0]
    hist = e.chat(first_text, Image.new("RGB", (800, 600)), hist, session_id=sid)[0]
    n = len(llm.calls)
    out = e.chat(answer, None, hist, session_id=sid)
    return out[0][-1]["content"], out[2], llm.calls[n:], e.dialog_states.get(sid) or {}


for ans in ("ใช่", "ใช่ครับ", "ครับ", "Modutech", "2"):
    reply, refs, sent, st = confirm_then(ans)
    ok(f"รูปเปล่า → '{ans}' = Modutech · บอกว่าระบุรุ่นจากรูปไม่ได้ + ขอคำถาม · ไม่เรียก LLM",
       st.get("brand") == "modutech" and "ระบุรุ่น" in reply and "พิมพ์คำถาม" in reply and not sent
       and reply.count("ระบุรุ่น") == 1, (reply[:150], st.get("brand"), sent))
for ans in ("ไม่ใช่", "ไม่ใช่ครับ เป็นโซ่", "ไม่", "Movex"):
    reply, refs, sent, st = confirm_then(ans)
    ok(f"รูปเปล่า → '{ans}' = Movex ใช้ผลรูปเดิม (ViT ไม่รับ) → ปฏิเสธรูปสุภาพ ไม่เดาซีรีส์",
       st.get("brand") == "movex" and "reject_image" in refs and not sent, (reply[:120], refs[-200:]))
reply, refs, sent, st = confirm_then("ใช่", first_text="รุ่นนี้ทนอุณหภูมิเท่าไหร่")
ok("รูป+คำถาม → 'ใช่' = ตอบคำถามเดิมทาง Modutech (ไม่มีคำว่า 'ใช่' ปนในคำถาม)",
   st.get("brand") == "modutech" and "ระบุรุ่น" in reply
   and not any(isinstance(p, str) and "ใช่" in p for c in sent for p in c), (reply[:150], sent))
reply, refs, sent, st = confirm_then("ใช่", hist_name="คุย Movex")
ok("แชต Movex + รูปน่าจะ Modutech → ถามยืนยัน → 'ใช่' เปลี่ยนไป Modutech", st.get("brand") == "modutech"
   and "พิมพ์คำถาม" in reply, (reply[:120], st.get("brand")))
reply, refs, sent, st = confirm_then("HC508 C กว้างเท่าไหร่")
ok("ไม่ตอบ ใช่/ไม่ใช่ แต่พิมพ์คำถามใหม่ที่มีรหัส → ตอบคำถามนั้น (ไม่วนถามซ้ำ)",
   st.get("brand") == "modutech" and "ใช่ไหม" not in reply and any(
       isinstance(p, str) and "HC508" in p for c in sent for p in c), (reply[:120], sent))

print("\nกันชั้นสุดท้าย: ปลั๊กอินคืน user_parts ว่าง (ทางที่ยังไม่รู้) → ไม่เรียก LLM")
orig = mgr.movex_plugin.build_turn
mgr.movex_plugin.build_turn = lambda d, t: LLMTurn("sys", [""])
llm = FakeLLM()
e = TurnEngine(core, llm=llm, logger=_Log(), tool_log=tool_log, image_scorers={"movex": Scorer(IMAGES["movex_dominant"][0])})
out = e.chat("LF820 K325 รับแรงดึงเท่าไหร่", None, [], session_id="g1")
ok("ไม่เรียก LLM · ไม่มี error ดิบ", not llm.calls and not any(b in out[0][-1]["content"] for b in BAD),
   out[0][-1]["content"][:80])
ok("log บอกเหตุผล", "**Empty turn:**" in out[2])
mgr.movex_plugin.build_turn = orig

print("\nerror ที่ไม่รู้จักจาก LLM → ข้อความทางการ ไม่มีรายละเอียดทางเทคนิค (27 ต.ค.)")


class BoomLLM(FakeLLM):
    def run(self, llm_turn, chat_history, tool_calls):
        raise RuntimeError("400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'x', 'status': 'INVALID_ARGUMENT'}}")


e = TurnEngine(core, llm=BoomLLM(), logger=_Log(), tool_log=tool_log,
               image_scorers={"movex": Scorer(IMAGES["ambiguous"][0])})
out = e.chat("HC508 C กว้างเท่าไหร่", None, [], session_id="b1")
rep_ = out[0][-1]["content"]
ok("ไม่มี INVALID_ARGUMENT / code / ❌ ถึงลูกค้า", not any(w in rep_ for w in ("INVALID_ARGUMENT", "'code'", "❌", "400")),
   rep_[:120])
ok("ขอโทษ + ให้ส่งใหม่ + ช่องทางฝ่ายขาย", rep_.startswith("ขออภัยครับ") and "ส่งคำถามอีกครั้ง" in rep_
   and "ติดต่อฝ่ายขาย" in rep_, rep_)
from leak_detectors import FALLBACK_RX  # noqa: E402
from core.turn import TIMEOUT_REPLY_TH, TRANSIENT_REPLY_TH  # noqa: E402
ok("ตัวนับเทิร์นที่ตอบไม่สำเร็จยังจับข้อความใหม่ได้ครบสามแบบ",
   all(FALLBACK_RX.search(t) for t in (rep_, TIMEOUT_REPLY_TH, TRANSIENT_REPLY_TH)))
ok("ข้อความปฏิเสธรูปของ Movex ไม่กล่าวหาว่ารูปไม่เกี่ยว",
   "ไม่เกี่ยวข้อง" not in mgr.movex_plugin.image_reject_th or not mgr.movex_plugin.image_reject_th)

print("\nข้อความไม่มีรูป — ไม่เปลี่ยนจากเดิม")
llm = FakeLLM()
e = TurnEngine(core, llm=llm, logger=_Log(), tool_log=tool_log, image_scorers={"movex": Scorer(IMAGES["ambiguous"][0])})
out = e.chat("HC508 C กว้างเท่าไหร่", None, [], session_id="n1")
ok("คำถามข้อความล้วนยังไปถึง LLM พร้อมข้อความ", llm.calls and "HC508" in " ".join(
    p for p in llm.calls[-1] if isinstance(p, str)), llm.calls)

print("\nlog ทดสอบรูป (IMAGE_TEST_LOG) → image_test_log.py → CSV")
import csv as _csv  # noqa: E402
import tempfile  # noqa: E402
import core.turn as CT  # noqa: E402
import image_test_log as ITL  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    logf = os.path.join(tmp, "image_test.log")
    CT.IMAGE_TEST_LOG, CT.IMAGE_TEST_LOG_FILE = True, logf
    try:
        for h, i, t in (("แชตใหม่", "modutech_maybe", "รูปเปล่า"), ("คุย Modutech", "ambiguous", "รูปเปล่า"),
                        ("แชตใหม่", "not_product", "รูป+ข้อความ"), ("แชตใหม่", "movex_dominant", "รูปเปล่า")):
            run_case(h, i, t)
        run_case("คุย Modutech", "ambiguous", "รูปเปล่า")       # เทิร์นข้อความในประวัติต้องไม่ลง log
    finally:
        CT.IMAGE_TEST_LOG = False
    rows_, bad_ = ITL.parse(ITL.read_text(logf))
    ok("ลง log เฉพาะเทิร์นที่มีรูป (5 บรรทัด) · อ่านได้ทุกบรรทัด", len(rows_) == 5 and bad_ == 0, (len(rows_), bad_))
    ok("policy ตรงกับเคส", [r["policy"] for r in rows_] == ["confirm", "context", "not_product", "dominant", "context"],
       [r["policy"] for r in rows_])
    ok("รูปเปล่าที่ถูกกันไว้มีช่อง guard (action ของปลั๊กอินอย่างเดียวอ่านผิดได้)",
       rows_[1].get("guard", "").startswith("รูปเปล่า") and not rows_[0].get("guard"), rows_[1])
    ok("มีคะแนนตัวให้คะแนนรูปและค่าประตู", all(r["scores"] and r["gates"] for r in rows_), rows_[0])
    ok("ข้อความไทยไม่เพี้ยน", rows_[2]["text"] == "รุ่นนี้คืออะไร" and "ใช่ไหม" in rows_[0]["reply_head"], rows_[2])
    out_csv = os.path.join(tmp, "t.csv")
    ok("สร้าง CSV ได้", ITL.main([logf, "-o", out_csv]) == 0)
    with open(out_csv, encoding="utf-8-sig") as f:
        table = list(_csv.DictReader(f))
    ok("CSV มีคอลัมน์ให้เติม และ 5 แถว", len(table) == 5 and all(k in table[0] for k in ITL.FILL), list(table[0])[:6])
    ok("ไม่เขียนทับไฟล์ที่มีอยู่ (อาจเติมผลไว้แล้ว)", ITL.main([logf, "-o", out_csv]) == 2)
    with open(logf, "rb") as f:
        utf16 = f.read().decode("utf-8").encode("utf-16")
    with open(os.path.join(tmp, "u16.log"), "wb") as f:
        f.write(utf16)
    ok("อ่าน log UTF-16 (PowerShell 5) ได้", len(ITL.parse(ITL.read_text(os.path.join(tmp, "u16.log")))[0]) == 5)
ok("ปิดไว้เป็นค่าเริ่มต้น", os.environ.get("IMAGE_TEST_LOG", "") != "" or not CT.IMAGE_TEST_LOG)

print("\nสรุปผลแต่ละคู่ (ดูด้วยตา)")
w = max(len(r[0]) for r in rows)
for tag, dec, how, rep in rows:
    print(f"  {tag:<{w}}  {dec:<13} {how:<12} {rep}")

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
