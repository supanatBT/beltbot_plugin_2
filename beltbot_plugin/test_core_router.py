"""
test_core_router.py — core/router.py + brands/*/detect.py (ชั้น 3)

หลักฐานหลัก: รัน BrandRouter ตัวเดิม (ดึงจาก git e261bf9) คู่กับตัวใหม่ บนข้อความลูกค้าทุกข้อความ
ในทุกไฟล์เคส × มีรูป/ไม่มีรูป × แบรนด์เทิร์นก่อน 3 แบบ × นโยบายไม่มีสัญญาณ 2 แบบ
ต้องได้ brand · reason · need_clarify · clarify_th · codes เท่ากันทุกกรณี

    python test_core_router.py
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.protocol import BrandSignal                        # noqa: E402
from core.router import choose                               # noqa: E402
import dialogue_state as D                                    # noqa: E402
from modutech_gates import Catalogue                          # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


def old_router_module():
    src = subprocess.run(["git", "show", "e261bf9:modutech_router.py"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8").stdout
    mod = types.ModuleType("old_modutech_router")
    sys.modules["old_modutech_router"] = mod
    exec(compile(src, "e261bf9:modutech_router.py", "exec"), mod.__dict__)
    return mod


def texts():
    out = []
    for f in ("testsuite_120.csv", "testcases_modutech_136.csv", "testcases_graph_relations.csv",
              "training/prompt_snapshot/cases/testcases_v2.csv",
              "training/prompt_snapshot/cases/snapshot_extra.csv"):
        for r in csv.DictReader(open(os.path.join(ROOT, f), encoding="utf-8-sig")):
            for col in ("user_text", "text", "query"):
                if r.get(col):
                    out.append(r[col])
    out += ["", "สวัสดี", "MP80 C กับ LF820 K325", "ไก่ กับ ขวด", "N/m", "chain", "54201", "K750",
            "EC254 TR-TAB", "LF880 TAB", "โมดูลาร์ หรือ โซ่", "ขวด PET", "flush grid", "HC508"]
    return list(dict.fromkeys(out))


cat = Catalogue(os.path.join(ROOT, "modutech_v30_1.json"))

print("1) ตัดสินเท่าตัวเดิมทุกกรณี")
old = old_router_module().BrandRouter(cat)
new = D.BrandRouter(cat)
T = texts()
mismatch = []
n = 0
for t in T:
    for img in (False, True):
        for prev in (None, "movex", "modutech"):
            for pol in (None, "ask"):
                a = old.route(t, has_image=img, prev_brand=prev, no_signal_policy=pol)
                b = new.route(t, has_image=img, prev_brand=prev, no_signal_policy=pol)
                n += 1
                fa = (a.brand, a.reason, a.need_clarify, a.clarify_th, a.codes.__dict__)
                fb = (b.brand, b.reason, b.need_clarify, b.clarify_th, b.codes.__dict__)
                if fa != fb:
                    mismatch.append((t, img, prev, pol, fa, fb))
ok(f"{n} กรณี จาก {len(T)} ข้อความ", not mismatch, mismatch[:3])
ok("weak_terms เท่าเดิม", old.weak_terms == new.weak_terms)

print("\n2) core/router.choose กับสามแบรนด์ — ไม่ต้องแก้ core")
S, W, N = (lambda e="x": BrandSignal("strong", e)), (lambda e="w": BrandSignal("weak", e)), BrandSignal()
r = choose({"a": S(), "b": N, "c": S()})
ok("strong สองแบรนด์จากสาม → ชน ระบุแค่ที่ชน", r.kind == "conflict_strong" and r.conflict == ["a", "c"])
r = choose({"a": W(), "b": S("code"), "c": W()})
ok("strong ชนะ weak", r.brand == "b" and r.kind == "strong" and r.evidence == {"b": "code"})
r = choose({"a": W(), "b": N, "c": W()}, prev_brand="b")
ok("weak ชนกัน → ไม่ตัดสิน (prev ไม่ถูกใช้แทน)", r.brand is None and r.kind == "conflict_weak")
r = choose({"a": N, "b": N, "c": N}, prev_brand="c")
ok("ไม่มีสัญญาณ → แบรนด์เทิร์นก่อน", r.brand == "c" and r.kind == "previous")
r = choose({"a": N, "b": N, "c": N}, has_image=True, image_brands=["c"])
ok("รูป + แบรนด์เดียวที่รับรูป → strong ด้วยหลักฐานรูป", r.brand == "c" and r.evidence["c"] == "รูปภาพ")
r = choose({"a": S(), "b": N, "c": N}, has_image=True, image_brands=["c"])
ok("รหัสของแบรนด์อื่น + รูป → ชน", r.kind == "conflict_strong" and r.conflict == ["a", "c"])
sig = {"a": N}
choose(sig, has_image=True, image_brands=["a"])
ok("choose ไม่แก้สัญญาณที่ส่งมา", sig["a"].strength == "none")

print("\n3) แต่ละแบรนด์รู้จักแค่ตัวเอง")
from brands.movex import detect as mx                         # noqa: E402
from brands.modutech.detect import ModutechDetector           # noqa: E402
md = ModutechDetector(cat)
ok("Movex ไม่รู้จักรหัส Modutech", mx.detect("MP80 C").strength == "none")
ok("Modutech ไม่รู้จักรหัส Movex", md.detect("LF820 K325").strength == "none")
ok("Modutech: รหัส exact → strong + has_code", md.detect("HC508 C").strength == "strong"
   and md.detect("HC508 C").has_code)
ok("Modutech: ชื่อแบรนด์ → strong ไม่ใช่รหัส", md.detect("modutech").strength == "strong"
   and not md.detect("modutech").has_code)
src = open(os.path.join(ROOT, "brands", "modutech", "router.py"), encoding="utf-8").read()
ok("โฟลเดอร์ Modutech ไม่มี regex ของ Movex แล้ว", "MOVEX_PATTERNS" not in src and "MOVEX_WEAK" not in src)

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
