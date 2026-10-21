"""
test_core_dialogue.py — core/dialogue.py (ชั้น 2)
เทียบตรงกับ DialogState แบบ dataclass เดิม (ดึงจาก git คอมมิต e261bf9) ไม่ใช่เทียบกับความจำ

    python test_core_dialogue.py
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.dialogue import state_class                        # noqa: E402
from dialogue_state import DialogState                        # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


# ── ของเดิมจาก git ─────────────────────────────────────────────
def old_dialogstate():
    src = subprocess.run(["git", "show", "e261bf9:dialogue_state.py"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8").stdout
    start = src.index("@dataclass\nclass DialogState:")
    end = src.index("@dataclass\nclass Decision:")
    mod = types.ModuleType("old_state")
    sys.modules["old_state"] = mod                 # dataclass ต้องหาโมดูลของคลาสเจอ
    exec("from __future__ import annotations\nfrom dataclasses import asdict, dataclass, field\n"
         "from typing import Optional\n" + src[start:end], mod.__dict__)
    return mod.DialogState


print("1) เหมือน dataclass เดิม")
Old = old_dialogstate()
ok("คีย์และลำดับคีย์เท่าเดิม", list(Old().to_dict()) == list(DialogState().to_dict()),
   (list(Old().to_dict()), list(DialogState().to_dict())))
ok("ค่าเริ่มต้นเท่าเดิม", Old().to_dict() == DialogState().to_dict())
samples = [
    None, {}, {"brand": "movex", "movex_pids": ["movex_chain_LF820_K325"], "movex_series": "820"},
    {"brand": "modutech", "modutech_codes": ["HC508 C"], "modutech_slots": {"wet_or_dry": "wet"},
     "modutech_sprocket_codes": ["EC127SQZ24*PA"], "pending": "wet_or_dry", "pending_question": "q"},
    {"brand": "x", "unknown": 1, "movex_extra": 2, "modutech_codes": ["A"], 5: "int key"},
]
for i, d in enumerate(samples):
    a = Old.from_dict({k: v for k, v in d.items() if isinstance(k, str)} if d else d).to_dict()
    b = DialogState.from_dict(d).to_dict()
    ok(f"from_dict → to_dict ตัวอย่าง {i}", json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False),
       (a, b))
ok("สร้างด้วย keyword แบบเดิม", DialogState(brand="movex", movex_pids=["p"]).to_dict()
   == Old(brand="movex", movex_pids=["p"]).to_dict())
try:
    DialogState(nope=1)
    ok("ชื่อที่ไม่รู้จัก → AttributeError", False)
except AttributeError:
    ok("ชื่อที่ไม่รู้จัก → AttributeError", True)

print("\n2) ชื่อแบนกับที่เก็บจริง")
s = DialogState()
s.modutech_slots.update(wet_or_dry="dry")
ok("แก้ในที่ผ่านชื่อแบน ถึง brands จริง", s.brands["modutech"]["slots"] == {"wet_or_dry": "dry"})
s.movex_pids = ["a"]
ok("เขียนผ่านชื่อแบน", s.brands["movex"]["pids"] == ["a"])
c = copy.deepcopy(s)
c.movex_pids.append("b")
c.modutech_slots["material"] = "PP"
ok("deepcopy แยกขาด", s.movex_pids == ["a"] and "material" not in s.modutech_slots)
d = s.to_dict()
d["movex_pids"].append("z")
ok("to_dict ไม่ผูกกับสถานะจริง", s.movex_pids == ["a"])
ok("เท่ากันเมื่อค่าเท่ากัน", DialogState.from_dict(s.to_dict()) == s)
s.reset_brand("modutech")
ok("reset_brand คืนค่าเริ่มต้นเฉพาะแบรนด์นั้น", s.modutech_slots == {} and s.movex_pids == ["a"])

print("\n3) แบรนด์ที่สาม — ไม่ต้องแก้ core")
S3 = state_class({"movex": {"pids": []}, "modutech": {"codes": []}, "demo": {"codes": [], "note": ""}})
t = S3.from_dict({"brand": "demo", "demo_codes": ["D1"], "modutech_codes": ["M"], "movex_pids": ["P"]})
ok("แยก demo_codes กลับเข้า brands['demo']", t.brands["demo"]["codes"] == ["D1"])
ok("รหัสของแต่ละแบรนด์ไม่ปนกัน", t.brands["modutech"]["codes"] == ["M"] and t.brands["movex"]["pids"] == ["P"])
ok("ส่งออกครบสามแบรนด์", {"demo_codes", "demo_note", "modutech_codes", "movex_pids"} <= set(t.to_dict()))
ok("สถานะแบบสองแบรนด์อ่านสถานะสามแบรนด์ได้ (ทิ้งของที่ไม่รู้จัก)",
   "demo_codes" not in DialogState.from_dict(t.to_dict()).to_dict())

print("\n4) schema ผิดรูป")
for name, sch in [("key มี _", {"a_b": {"x": 1}}), ("ช่องไม่ใช่ identifier", {"a": {"x-y": 1}}),
                  ("state ไม่ใช่ dict", {"a": ["x"]})]:
    try:
        state_class(sch)
        ok(name, False, "ไม่ raise")
    except ValueError:
        ok(name, True)

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
