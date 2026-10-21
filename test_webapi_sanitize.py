"""
test_webapi_sanitize.py — กู้บทสนทนาผ่านปลั๊กอิน (ชั้น 6)

sanitize_dialog_state ตัวเดิม (git e261bf9 · อ่าน modutech_cat.by_code / product_db ตรง)
เทียบกับตัวใหม่ (แต่ละแบรนด์ตรวจรหัสของตัวเองผ่าน plugin.sanitize_state) บนข้อมูลจริง
ต้องได้ dict เท่ากันทุกไบต์ และตัดสิน "กู้ได้ไหม" (seed_session) เหมือนกัน

    python test_webapi_sanitize.py
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import dialogue_state as D                                    # noqa: E402
from modutech_gates import Catalogue                          # noqa: E402
from webapi.bot import sanitize_dialog_state, state_resumable  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


# ── ของเดิม ──
src = subprocess.run(["git", "show", "e261bf9:webapi/bot.py"], cwd=ROOT, capture_output=True,
                     text=True, encoding="utf-8").stdout
old_mod = types.ModuleType("old_webapi_bot")
sys.modules["old_webapi_bot"] = old_mod
exec(compile(src, "e261bf9:webapi/bot.py", "exec"), old_mod.__dict__)
OLD_SEED = lambda st: bool(st and any(st.get(k) for k in ("brand", "modutech_codes", "movex_pids")))  # noqa: E731

# ── ข้อมูลจริง ──
cat = Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
dm = D.DialogueManager(real, cat)
legacy_mod = types.SimpleNamespace(modutech_cat=cat, product_db=real)
new_mod = types.SimpleNamespace(plugins={"movex": dm.movex_plugin, "modutech": dm.modutech_plugin},
                                DialogState=D.DialogState)

codes = list(cat.by_code)[:12] + ["ไม่มีรุ่นนี้", "HC508", ""]
pids = list(real)[:10] + ["movex_chain_ปลอม", "LF820"]
VALUES = [None, True, 0, 1.5, "x", [], {}, ["a"], {"a": 1}, "y" * 20]
SLOTS = [{"wet_or_dry": "wet"}, {"material": "PP", "ราคาลับ": 1}, {"operating_temp_c": -20.0},
         {"line_shape": True}, {"wet_or_dry": ["x"]}, {f"k{i}": i for i in range(20)},
         dict([(f"k{i}", i) for i in range(11)] + [("material", "POM")]),
         dict([(f"k{i}", i) for i in range(12)] + [("material", "POM")])]

cases = [
    {"brand": "modutech", "modutech_codes": ["HC508 C", "ไม่มีรุ่นนี้", 42],
     "modutech_slots": {"wet_or_dry": "wet", "ราคาลับ": 1, "material": "ไก่"},
     "movex_pids": ["movex_chain_LF820_K325", "movex_chain_ปลอม"], "movex_series": "LF820",
     "pending": "ask_width", "role_admin": True},
    {"brand": "acme"}, {}, {"movex_series": "820"}, {"brand": None, "movex_pids": pids[:2]},
    {"modutech_codes": codes * 3}, {"movex_pids": "not a list"}, {"modutech_slots": "x"},
    {"modutech_sprocket_codes": ["EC127SQZ24*PA"]}, {"movex_series": "x" * 17},
    {"brand": "movex", "pending_question": "ค้างไว้", "pending": "brand"},
]
rng = random.Random(20261007)
keys = ["brand", "movex_pids", "movex_series", "modutech_codes", "modutech_slots",
        "modutech_sprocket_codes", "pending", "pending_question", "junk", "movex_x", "modutech_"]
for _ in range(3000):
    c = {}
    for k in rng.sample(keys, rng.randint(0, len(keys))):
        r = rng.random()
        if k == "brand":
            c[k] = rng.choice(["movex", "modutech", "acme", None, "", 3])
        elif k.endswith("_codes") or k.endswith("_pids"):
            pool = codes if "modutech" in k else pids
            c[k] = rng.sample(pool + VALUES, rng.randint(0, 14)) if r < 0.85 else rng.choice(VALUES)
        elif k.endswith("_slots"):
            c[k] = rng.choice(SLOTS) if r < 0.85 else rng.choice(VALUES)
        else:
            c[k] = rng.choice(VALUES + ["820", "LF821"])
    cases.append(c)

print("1) sanitize_dialog_state เดิม (e261bf9) กับใหม่ (ผ่านปลั๊กอิน) บนข้อมูลจริง")
bad, seed_bad = [], []
for c in cases:
    a = old_mod.sanitize_dialog_state(c, legacy_mod)
    b = sanitize_dialog_state(c, new_mod)
    if json.dumps(a, ensure_ascii=False) != json.dumps(b, ensure_ascii=False):
        bad.append((c, a, b))
    if OLD_SEED(a) != state_resumable(b, new_mod):
        seed_bad.append(c)
ok(f"{len(cases)} กรณี — dict เท่ากันทุกไบต์ (รวมลำดับคีย์)", not bad, bad[:2])
ok("ตัดสินกู้ได้/ไม่ได้ เหมือนเดิม", not seed_bad, seed_bad[:3])
ok("input ไม่ใช่ dict → {}", sanitize_dialog_state(None, new_mod) == {} and sanitize_dialog_state("x", new_mod) == {})

print("\n2) ทางเดิมสำหรับโมดูลที่ไม่มีปลั๊กอิน (fakebot) ยังให้ผลเท่าเดิม")
import fakebot                                                # noqa: E402
bad2 = [c for c in cases[:200]
        if old_mod.sanitize_dialog_state(c, fakebot) != sanitize_dialog_state(c, fakebot)]
ok("200 กรณีแรกกับ fakebot", not bad2, bad2[:2])

print("\n3) แบรนด์ที่สาม — webapi ไม่ต้องแก้")
from core.dialogue import state_class                         # noqa: E402


class _Demo:
    def sanitize_state(self, raw):
        return {"codes": [c for c in raw.get("codes") or [] if c in ("D1", "D2")]}

    def resumable(self, st):
        return bool(st.get("codes"))


S3 = state_class({"movex": {"pids": [], "series": None},
                  "modutech": {"codes": [], "slots": {}, "sprocket_codes": []}, "demo": {"codes": []}})
m3 = types.SimpleNamespace(plugins={**new_mod.plugins, "demo": _Demo()}, DialogState=S3)
st = sanitize_dialog_state({"brand": "demo", "demo_codes": ["D1", "X", 5], "movex_pids": ["nope"]}, m3)
ok("demo_codes ผ่านปลั๊กอินของ demo", st["demo_codes"] == ["D1"] and st["brand"] == "demo", st)
ok("กู้ได้เพราะ demo มีรุ่นในโฟกัส", state_resumable({"demo_codes": ["D1"]}, m3))

src_bot = open(os.path.join(ROOT, "webapi", "bot.py"), encoding="utf-8").read()
gen = src_bot[src_bot.index("def sanitize_dialog_state"):src_bot.index("def _sanitize_legacy")]
ok("ทางใหม่ใน webapi ไม่มีชื่อแบรนด์ (นอกทางเดิมของ fakebot)",
   "movex" not in gen.split("if not plugins:")[0].lower() and "modutech" not in gen.split("if not plugins:")[0].lower())

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
