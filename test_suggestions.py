"""
test_suggestions.py — ปุ่มตอบเร็ว (webapi/bot.py suggestions_for + plugin.reply_suggestions · 27 ต.ค.)

ทุกปุ่มต้อง "บอทอ่านออก": ส่งข้อความของปุ่มกลับเข้าตัวตัดสินใจจริง แล้วคำถามเดิมต้องไม่ถูกถามซ้ำ
(ไม่ใช่แค่ปุ่มขึ้นถูก — ปุ่มที่บอทอ่านไม่ออกแย่กว่าไม่มีปุ่ม)
ไม่โหลดโมเดล ไม่เรียก LLM

    python test_suggestions.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as DS                         # noqa: E402
from brands.modutech import need_flow as NF         # noqa: E402
from webapi.bot import suggestions_for              # noqa: E402

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
MOD = SimpleNamespace(plugins=core.plugins)
INTERNAL = re.compile(r"[a-z]+_[a-z_]+|[\\/]")      # snake_case หรือ path


def reach(*texts):
    st = None
    d = None
    for t in texts:
        core.image_brands = ()
        d = core.decide(t, state=st)
        st = d.state
    return d, st


def answer(st, text):
    core.image_brands = ()
    return core.decide(text, state=st)


def check(name, texts, expect_pending, min_buttons=2):
    print(f"\n{name}")
    d, st = reach(*texts)
    sd = st.to_dict()
    ok(f"บอทถามค้าง pending={expect_pending}", sd.get("pending") == expect_pending, (sd.get("pending"), d.reply_th[:60]))
    sug = suggestions_for(sd, MOD)
    ok(f"มีปุ่ม ≥ {min_buttons}: {[s['label'] for s in sug]}", len(sug) >= min_buttons, sug)
    ok("ปุ่มไม่มีชื่อฟิลด์ภายในหรือ path", not any(INTERNAL.search(s["label"] + " " + s["text"]) for s in sug), sug)
    flow = (sd.get("modutech_slots") or {}).get(NF.FLOW_KEY)
    for s in sug:
        d2 = answer(st, s["text"])
        sd2 = d2.state.to_dict()
        flow2 = (sd2.get("modutech_slots") or {}).get(NF.FLOW_KEY)
        same = sd2.get("pending") == expect_pending and flow2 == flow
        ok(f"  ปุ่ม '{s['label']}' → บอทอ่านออก ไม่ถามข้อเดิมซ้ำ",
           not same and NF.REASK_TH.strip() not in d2.reply_th,
           (d2.action, sd2.get("pending"), flow2, d2.reply_th[:80]))
    return sug, st


sug, st = check("ถามแบรนด์ (เมนู)", ["แนะนำสายพานหน่อย"], "brand")
for s in sug:
    d2 = answer(st, s["text"])
    ok(f"  '{s['label']}' → เลือกแบรนด์นั้น", d2.brand and d2.brand.lower() == s["text"].lower(), (d2.brand, s))

check("ถามพิทช์ (ถามทีละข้อ)", ["ช่วยเลือกสายพานลำเลียงชิ้นไก่หน่อย"], "modutech_pitch", 4)
sug, _ = check("ยืนยันพิทช์ใกล้เคียง (15 มม. ไม่มี)", ["ช่วยเลือกสายพานลำเลียงชิ้นไก่หน่อย", "15 มม."], "modutech_pitch", 3)
ok("  มีปุ่มค่าใกล้เคียงที่บอทเสนอ (15.24)", any("15.24" in s["label"] for s in sug), sug)
check("ถามอุณหภูมิ", ["ช่วยเลือกสายพานลำเลียงชิ้นไก่หน่อย", "1 นิ้ว"], "modutech_temp")
check("ถามเปียก/แห้ง (ถามทีละข้อ)", ["ช่วยเลือกสายพานลำเลียงชิ้นไก่หน่อย", "1 นิ้ว", "80 องศา"], "wet_or_dry", 3)
check("ถามเปียก/แห้ง (ถามอุณหภูมิของรุ่น)", ["MP80 C ทนอุณหภูมิได้เท่าไหร่"], "wet_or_dry")
check("ถามตรง/โค้ง", ["EC254 R รับแรงดึงเท่าไหร่"], "line_shape")
sug, _ = check("ถามความกว้าง Movex", ["LF 820 กว้างเท่าไหร่"], "movex_width")
ok("  ปุ่มเรียงตามความกว้าง และส่งรหัสรุ่นเต็ม", all("มม." in s["label"] and s["text"].startswith("LF") for s in sug), sug)

print("\nถามยืนยันแบรนด์เดียวจากรูป (brand:<key>)")
st = core.state_cls()
st.pending, st.pending_question = "brand:modutech", ""
sug = suggestions_for(st.to_dict(), MOD)
ok("ปุ่ม ใช่ / ไม่ใช่", [s["text"] for s in sug] == ["ใช่", "ไม่ใช่"], sug)
for s, want in zip(sug, ("modutech", "movex")):
    d2 = answer(st, s["text"])
    ok(f"  '{s['label']}' → {want}", d2.brand == want and d2.state.to_dict().get("pending") is None,
       (d2.brand, d2.state.to_dict().get("pending")))

print("\nไม่มีคำถามค้าง / ข้อมูลแปลก → ไม่มีปุ่ม")
_, st = reach("HC508 C กว้างเท่าไหร่")
ok("ตอบแล้ว ไม่มีคำถามค้าง → []", suggestions_for(st.to_dict(), MOD) == [])
ok("state ไม่ใช่ dict → []", suggestions_for(None, MOD) == [] and suggestions_for("x", MOD) == [])
ok("โมดูลไม่มีปลั๊กอิน (fakebot) → []", suggestions_for({"pending": "brand"}, SimpleNamespace()) == [])
ok("pending ไม่รู้จัก → []", suggestions_for({"pending": "อะไรก็ไม่รู้"}, MOD) == [])

print("\nAPI ส่งฟิลด์ suggestions (บอตปลอม)")
try:
    from fastapi.testclient import TestClient
    import fakebot  # noqa: F401
    from app import create_app
    from webapi.bot import BotAdapter
    from webapi.settings import Settings
    cfg = Settings()
    cfg.warm_on_start, cfg.proxy_secret = False, ""
    bot = BotAdapter("fakebot")
    bot.load()
    with TestClient(create_app(cfg, bot)) as c:
        r = c.post("/api/chat", data={"text": "HC508 C"})
        body = r.json()
    ok("มีคีย์ suggestions เป็น list · ฟิลด์เดิมครบ", r.status_code == 200 and isinstance(body.get("suggestions"), list)
       and {"session_id", "messages", "turns_left", "state"} <= set(body), body)
except ImportError as e:
    print(f"  · ข้าม (ไม่มี {e.name})")

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
