"""
test_image_interpreter.py — ตัวอ่านรูป (core/image_interpreter) + การคัดรุ่นจากผิว (brands/modutech/image_read) · 6 พ.ย.

ไม่โหลดโมเดล ไม่เรียก Gemini
    ตัวตรวจ JSON · การคัดรุ่น · ตัวตัดสิน · ปลั๊กอิน · build_turn ของ Modutech = ของจริง (retriever ปิด)
    LLM ที่อ่านรูป = ของปลอม (คืน JSON ตามเคส) · LLM ที่ตอบลูกค้า = ของปลอม (จำ prompt ที่ได้รับ)

    python test_image_interpreter.py
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
from brands.modutech.image_read import image_match, image_spec  # noqa: E402
from brands.modutech.kg import load_modutech_kg                # noqa: E402
from brands.modutech.runtime import ModutechRuntime            # noqa: E402
from core.image_interpreter import ImageInterpreter, build_system, parse_reading  # noqa: E402
from core.image_policy import GateReading                      # noqa: E402
from core.llm import LLMResult                                 # noqa: E402
from core.protocol import ImageScore                           # noqa: E402
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


data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
mgr = DS.DialogueManager(real, cat)
core = mgr.core
mod = mgr.modutech_plugin
tool_log = ToolLog()
mod.runtime = ModutechRuntime(cat, mod.search, load_modutech_kg(cat, os.path.join(ROOT, "modutech_kg.db"), quiet=True),
                              None, tool_log)
spec = image_spec(cat)
TOTAL = len(cat.products)


def J(**k):
    base = {"is_product": "yes", "surface": None, "surface_alternatives": [], "openness": None,
            "scale_visible": False, "pitch_mm": None, "confidence": "high", "note": ""}
    base.update(k)
    return json.dumps(base, ensure_ascii=False)


# ═══════════════════════ 1 · ตรวจ JSON ═══════════════════════
print("1 · ตรวจ JSON จาก LLM")
ok("spec มีผิวครบตาม vocabulary", set(spec.surfaces) == {s["surface_type"] for s in cat.data["surface_type_vocabulary"]})
ok("prompt บอกรายชื่อผิวและห้ามระบุรุ่น", "Flush Grid" in build_system(spec) and "ห้ามระบุรหัสรุ่น" in build_system(spec))
r = parse_reading(J(surface="flush  grid"), spec)
ok("ชื่อผิวไม่สนตัวพิมพ์/ช่องว่าง → ชื่อตามฐาน", r is not None and r.surface == "Flush Grid", r)
ok("ผิวที่ไม่มีในรายการ → ไม่เชื่อทั้งก้อน", parse_reading(J(surface="Mesh Magic"), spec) is None)
ok("is_product แปลก → None", parse_reading(J(is_product="maybe"), spec) is None)
ok("confidence แปลก → None", parse_reading(J(confidence="very"), spec) is None)
ok("ไม่ใช่ JSON → None", parse_reading("ผิวตะแกรงครับ", spec) is None)
ok("JSON มีข้อความรอบ ๆ → ยังอ่านได้", parse_reading("```json\n" + J(surface="Flat Top") + "\n```", spec).surface == "Flat Top")
r = parse_reading(J(surface="Flush Grid", surface_alternatives=["Perforated Flat Top", "ปลอม", "Flush Grid", "Nub Top", "Flat Top"]), spec)
ok("ผิวสำรอง: ทิ้งค่าปลอม/ซ้ำ · ไม่เกิน 2", r.alternatives == ["Perforated Flat Top", "Nub Top"], r.alternatives)
r = parse_reading(J(surface=None, surface_alternatives=["Flat Top"]), spec)
ok("มีแค่ผิวสำรอง → เลื่อนเป็นผิวหลัก", r.surface == "Flat Top" and r.alternatives == [], r)
r = parse_reading(J(surface="Flat Top", pitch_mm=25.4, scale_visible=False), spec)
ok("พิทช์ที่ไม่มีสเกลในรูป → ทิ้ง", r.pitch_mm is None)
r = parse_reading(J(surface="Flat Top", pitch_mm="25.4", scale_visible=True), spec)
ok("พิทช์ + มีสเกล → เก็บ", r.pitch_mm == 25.4, r.pitch_mm)
r = parse_reading(J(surface="Flat Top", pitch_mm=500, scale_visible=True), spec)
ok("พิทช์หลุดช่วง → ทิ้ง", r.pitch_mm is None)
ok("openness แปลก → None (ไม่ล้มทั้งก้อน)", parse_reading(J(surface="Flat Top", openness="half"), spec).openness is None)

# ═══════════════════════ 2 · คัดรุ่นด้วยโค้ด ═══════════════════════
print("\n2 · ลักษณะผิว → รายชื่อรุ่น (CatalogueSearch ตัวเดิม)")
fg_direct = [m["belt_code"] for m in mod.search.search(
    __import__("brands.modutech.router", fromlist=["ExploratoryQuery"]).ExploratoryQuery(surface="Flush Grid"))["matches"]]
m, why = image_match(parse_reading(J(surface="Flush Grid"), spec), mod.search, cat, spec)
ok("Flush Grid → ทุกรุ่นที่ค้นทั้งฐานได้ (เท่ากับคำถามค้นผิวแบบเดิม)", m and m["belt_codes_complete"] == fg_direct,
   (why, m and m["count"]))
ok("ลดรุ่นได้จริง", m and 0 < m["count"] < TOTAL, why)
ok("บอกพิทช์ที่มีในรายชื่อ (ไว้ถามลูกค้า)", m and m.get("pitches_mm_in_list") and all(
    isinstance(x, float) for x in m["pitches_mm_in_list"]), m and m.get("pitches_mm_in_list"))
ok("หมายเหตุว่าไม่ใช่การระบุรุ่น", m and "ไม่ใช่การระบุรุ่น" in m["note_th"])
m2, _ = image_match(parse_reading(J(surface="Flush Grid", surface_alternatives=["Perforated Flat Top"]), spec),
                    mod.search, cat, spec)
ok("ผิวที่ยังแยกไม่ออก → รวมทั้งสองผิว (มากกว่าผิวเดียว)", m2 and m2["count"] > m["count"]
   and set(m["belt_codes_complete"]) <= set(m2["belt_codes_complete"]), (m2 and m2["count"], m["count"]))
mo, why = image_match(parse_reading(J(surface=None, openness="closed"), spec), mod.search, cat, spec)
ok("อ่านผิวไม่ได้แต่รู้ว่าทึบ → กลุ่มผิวทึบ", mo and mo["basis"] == "openness" and 0 < mo["count"] < TOTAL, why)
ok("กลุ่มผิวทึบไม่มีรุ่น Flush Grid", mo and not set(mo["belt_codes_complete"]) & set(fg_direct))
mp, _ = image_match(parse_reading(J(surface="Flush Grid", scale_visible=True, pitch_mm=50.8), spec), mod.search, cat, spec)
first_pitch = (cat.by_code[mp["belt_codes_complete"][0]]["specifications"].get("pitch") or {}).get("mm")
ok("พิทช์จากสเกล → เรียงใกล้ก่อน ไม่ตัดรุ่น", mp["count"] == m["count"] and first_pitch == 50.8
   and mp.get("pitch_estimate_mm") == 50.8, (first_pitch, mp["count"]))
ok("พิทช์จากสเกล → หมายเหตุให้ยืนยัน", "ยืนยัน" in mp["note_th"])
for name, rd in {
    "ไม่ใช่สินค้า": parse_reading(J(is_product="no", surface="Flat Top"), spec),
    "ไม่ชัด": parse_reading(J(is_product="unclear", surface="Flat Top"), spec),
    "มั่นใจต่ำ": parse_reading(J(surface="Flat Top", confidence="low"), spec),
    "ไม่มีผิว ไม่มีความทึบ": parse_reading(J(), spec),
    "อ่านไม่ได้": None,
}.items():
    mm, why = image_match(rd, mod.search, cat, spec)
    ok(f"{name} → ไม่กรอง (ทางเดิม)", mm is None, why)

# ═══════════════════════ 3 · ตัวอ่าน + LLM ปลอม ═══════════════════════
print("\n3 · ImageInterpreter: ส่งรูปเป็น JPEG ย่อ · พังแล้วกลับทางเดิม")


class FakeVision:
    def __init__(self, out):
        self.out, self.calls = out, []

    def __call__(self, system, user, json_mode=False, temperature=None):
        self.calls.append((system, user, json_mode, temperature))
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


fv = FakeVision(J(surface="Flat Top"))
r = ImageInterpreter(fv).read(Image.new("RGB", (4000, 3000)), "รุ่นนี้อะไร", spec)
part = fv.calls[0][1][0]
ok("ส่ง [รูป, ข้อความ] · json_mode · temperature 0", isinstance(fv.calls[0][1], list) and fv.calls[0][2] is True
   and fv.calls[0][3] == 0)
im_sent = Image.open(__import__("io").BytesIO(part["data"]))
ok("รูปเป็น JPEG ย่อด้านยาว ≤ 1280", part["mime_type"] == "image/jpeg" and max(im_sent.size) <= 1280, im_sent.size)
ok("ข้อความลูกค้าเป็นบริบท", "รุ่นนี้อะไร" in fv.calls[0][1][1])
ok("ผลอ่านผิวถูก + จับเวลา", r.surface == "Flat Top" and r.ms >= 0)
ok("LLM error → None", ImageInterpreter(FakeVision(RuntimeError("503"))).read(Image.new("RGB", (9, 9)), "", spec) is None)
ok("JSON เสีย → None", ImageInterpreter(FakeVision("ไม่รู้ครับ")).read(Image.new("RGB", (9, 9)), "", spec) is None)
ok("ไม่มีรูป → None ไม่เรียก LLM", (lambda f: ImageInterpreter(f).read(None, "x", spec) is None and not f.calls)(FakeVision("")))

# ═══════════════════════ 4 · ทั้งเทิร์นผ่าน TurnEngine ═══════════════════════
print("\n4 · ทั้งเทิร์น (TurnEngine จริง · ประตูรูปบอกว่า Modutech)")


class FakeLLM:
    def __init__(self):
        self.calls = []

    def run(self, llm_turn, chat_history, tool_calls):
        self.calls.append(llm_turn)
        parts = list(llm_turn.user_parts)
        if not any((p.strip() if isinstance(p, str) else p is not None) for p in parts):
            raise RuntimeError("400 INVALID_ARGUMENT. Requests ending with a model turn are not supported.")
        resp = SimpleNamespace(text="คำตอบจำลอง", candidates=[])
        return LLMResult(resp, SimpleNamespace(send_message=lambda m: resp), tool_calls)


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
    def score(self, image, text):
        return ImageScore("movex", 0.30, False)


class Gate:
    brand = "modutech"

    def read(self, image):
        return GateReading("modutech", True, True, {})        # มั่นใจว่า Modutech (direct)


def run(text, vision_out, history=(), interp=True):
    llm = FakeLLM()
    fv = FakeVision(vision_out)
    mod._image_interpreter = ImageInterpreter(fv) if interp else None
    e = TurnEngine(core, llm=llm, logger=_Log(), tool_log=tool_log,
                   image_scorers={"movex": Scorer()}, image_gates={"modutech": Gate()})
    core.image_brands = ("movex",)
    hist, sid = [], "s-img"
    for t in history:
        hist = e.chat(t, None, hist, session_id=sid)[0]
    n = len(llm.calls)
    out = e.chat(text, Image.new("RGB", (800, 600), (90, 90, 90)), hist, session_id=sid)
    return out[0][-1]["content"], out[2], llm.calls[n:], fv.calls


BAD = ("เกิดข้อผิดพลาด", "INVALID_ARGUMENT", "model turn")

reply, refs, sent, vc = run("", J(surface="Flush Grid"))
sp = sent[0].system_prompt if sent else ""
ok("รูปเปล่า + อ่านผิวได้ → ถึง LLM (เดิมขอให้พิมพ์คำถาม)", bool(sent) and "**Image-only:**" not in refs, refs[-300:])
ok("เทิร์นผู้ใช้ไม่ว่าง", sent and any(isinstance(p, str) and p.strip() for p in sent[0].user_parts), sent and sent[0].user_parts)
ok("prompt มี image_match + กฎห้ามระบุรุ่น", '"image_match"' in sp and "ไม่ใช่การระบุรุ่น" in sp)
ok("prompt มีรายชื่อครบเท่าที่โค้ดคัด", all(c in sp for c in fg_direct))
ok("ไม่มี error ดิบ", not any(b in reply for b in BAD), reply[:120])
ok("log บอกผลอ่านรูป", "อ่านรูป:" in refs and "Flush Grid" in refs, refs[-400:])

reply, refs, sent, vc = run("รุ่นนี้คืออะไรครับ", J(surface="Flat Top"))
sp = sent[0].system_prompt if sent else ""
ok("รูป + ข้อความ → image_match ใน prompt", '"image_match"' in sp and "Flat Top" in sp)
ok("ตัวอ่านได้ข้อความลูกค้าเป็นบริบท", vc and "รุ่นนี้คืออะไรครับ" in vc[0][1][1])

reply, refs, sent, vc = run("ใช้ลำเลียงไก่ครับ รุ่นนี้ใช้ได้ไหม", J(surface="Flush Grid"))
sp = sent[0].system_prompt if sent else ""
ctx = json.loads(sp.split("[Context — ผ่านการคัดกรองจากระบบแล้ว]")[1].split("\n\nกฎ")[0]) if sent else {}
im = ctx.get("image_match") or {}
ok("งานใช้ + รูป → รายชื่อเป็นส่วนที่ตรงทั้งสองทาง", im.get("combined_with_text") is True
   and set(im["belt_codes_complete"]) <= set(fg_direct), (im.get("count"), refs[-300:]))
ok("รายชื่องานใช้ใน prompt ถูกตัดเหลือส่วนที่ตรงด้วย",
   all(set(ctx[k]["belt_codes_complete"]) <= set(fg_direct) for k in ("application_match", "industry_match") if k in ctx))

reply, refs, sent, vc = run("", "อ่านไม่ออก")
ok("อ่านรูปไม่ได้ + รูปเปล่า → ขอคำถามแบบเดิม · ไม่เรียก LLM", not sent and "พิมพ์คำถาม" in reply, (reply[:100], refs[-200:]))
reply, refs, sent, vc = run("รุ่นนี้คืออะไรครับ", J(is_product="unclear", confidence="low"))
ok("อ่านได้แต่ไม่ชัด → ไม่มี image_match (ทางเดิม)", sent and '"image_match"' not in sent[0].system_prompt)

reply, refs, sent, vc = run("รูปนี้ล่ะครับ", J(surface="Flush Grid"), history=["HC508 C กว้างเท่าไหร่"])
ok("มีรหัสในโฟกัส (HC508 C) → ไม่เรียกตัวอ่าน ไม่กรองด้วยรูป", not vc and all('"image_match"' not in t.system_prompt for t in sent),
   (len(vc), refs[-200:]))

print("\n5 · สวิตช์ปิด = บอทเดิม")
reply, refs, sent, vc = run("", J(surface="Flush Grid"), interp=False)
ok("รูปเปล่า → ขอคำถาม · ไม่เรียก LLM", not sent and "**Image-only:**" in refs and "พิมพ์คำถาม" in reply)
reply, refs, sent, vc = run("รุ่นนี้คืออะไรครับ", J(surface="Flush Grid"), interp=False)
ok("รูป + ข้อความ → ไม่มี image_match · ไม่มีกฎรูปใน prompt", sent and '"image_match"' not in sent[0].system_prompt
   and "ถ้ามี image_match" not in sent[0].system_prompt and not vc)
mod._image_interpreter = None

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
