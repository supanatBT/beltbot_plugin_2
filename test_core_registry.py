"""
test_core_registry.py — core/registry.py + core/models.py (ชั้น 1)
ไม่ใช้ LLM ไม่ใช้ torch ไม่ใช้เน็ต

    python test_core_registry.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core import models as M                                  # noqa: E402
from core.registry import RegistryError, discover, load_plugins  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


def raises(fn, exc, *must_contain):
    try:
        fn()
    except exc as e:
        msg = str(e)
        return all(s in msg for s in must_contain), msg
    except Exception as e:                                    # noqa: BLE001
        return False, f"ได้ {type(e).__name__}: {e}"
    return False, "ไม่ได้ raise"


# ─────────────────────────── ของจริง ───────────────────────────
print("1) แบรนด์ที่มีอยู่")
real = discover()
keys = [b.key for b in real]
ok("หาเจอ movex แล้ว modutech เรียงตาม order", keys[:2] == ["movex", "modutech"], keys)
mx, md = real[0], real[1]
ok("พาธนับจากโฟลเดอร์แบรนด์", os.path.samefile(mx.path(mx.config["data"]["qdrant_path"]),
                                             os.path.join(ROOT, "qdrant_db")))
ok("Modutech ไม่มีรูป → auto ปิด พร้อมเหตุผล", not md.image.enabled and "auto" in md.image.reason,
   md.image.reason)
ok("Movex ไม่ส่งตัวตรวจ collection → auto ยังไม่เปิด (ยืนยันไม่ได้)",
   not mx.image.enabled and mx.image.spec is not None, mx.image.reason)

print("\n2) ทะเบียนโมเดล Movex")
spec = M.load_image_spec("movex", mx.dir, mx.config["image"])
ok("labels.json มี 10 คลาส", spec.num_labels == 10, spec.num_labels)
ok("checkpoint มี 10 คลาสจริง (อ่านหัว safetensors)", M.checkpoint_num_labels(spec.adapter) == 10)
ok("revision ตรงกับ hash ของไฟล์", spec.revision == M.file_revision(spec.adapter))
ok("ลำดับคลาสตาม id", spec.labels[0] == "movex_chain_LF820_K325" and spec.labels[9] == "movex_sprocket_57801")
ok("thresholds ระบุที่มา", "legacy_hardcoded" in spec.thresholds.get("source", ""))
st = M.resolve_image("movex", mx.dir, mx.config["image"], collection_points=lambda c: 91)
ok("auto + collection มีข้อมูล → เปิด", st.enabled and "91" in st.reason, st.reason)
st = M.resolve_image("movex", mx.dir, mx.config["image"], collection_points=lambda c: 0)
ok("auto + collection ว่าง → ปิด", not st.enabled and "ไม่มีข้อมูล" in st.reason, st.reason)

print("\n3) ข้อความรวมหลายแบรนด์ประกอบจาก brand.yaml ได้ตรงของเดิมทุกตัวอักษร (core/templates.py)")
# ของเดิมดึงจาก git e261bf9 — ไม่เทียบกับ dialogue_state ปัจจุบันซึ่งสร้างจาก templates เอง (จะกลายเป็นเทียบกับตัวเอง)
import subprocess                                             # noqa: E402
from core import templates as TPL                             # noqa: E402
from core.decide import Dialogue                              # noqa: E402
_old = subprocess.run(["git", "show", "e261bf9:dialogue_state.py"], cwd=ROOT, capture_output=True,
                      text=True, encoding="utf-8").stdout
OLD: dict = {}
exec(_old[_old.index("BRAND_ANSWERS = {"):_old.index("# หัวข้อคำถาม Movex")], OLD)
exec(_old[_old.index("REJECT_IMAGE_TH = ("):], OLD)
_oldr = subprocess.run(["git", "show", "e261bf9:modutech_router.py"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8").stdout
I = [b.info for b in real[:2]]
sys.path.insert(0, os.path.join(ROOT, "training"))
from phase2_expected import expected_reply                    # noqa: E402  เฟส 2: ความต่างที่ตั้งใจ
ok("เมนูถามแบรนด์ (ท้ายเมนูเปลี่ยนตามเฟส 2)", TPL.ask_brand(I) == expected_reply(OLD["ASK_BRAND_TH"], ""))
ok("ปฏิเสธนอกเรื่อง", TPL.offtopic(I) == OLD["OFFTOPIC_TH"])
ok("ทักทาย", TPL.smalltalk(I) == OLD["SMALLTALK_TH"])
ok("ทักทายกลับ (เฟส 2)", TPL.greeting(I) == expected_reply(OLD["SMALLTALK_TH"], "สวัสดีครับ"))
ok("ลำดับในข้อความตาม order ไม่ใช่ลำดับที่ส่งมา", TPL.ask_brand(I[::-1]) == expected_reply(OLD["ASK_BRAND_TH"], ""))
ok("ถามยืนยันเมื่อเจอสองแบรนด์", f'"{TPL.clarify_conflict(I)}"' in _oldr.replace('"\n                         "', ""))
ok("ปฏิเสธรูป", spec.reject_th == OLD["REJECT_IMAGE_TH"])
ok("คำตอบเลือกแบรนด์ (รวมเลขเมนู)",
   TPL.brand_answer_patterns(I[0]) == OLD["BRAND_ANSWERS"]["movex"]
   and TPL.brand_answer_patterns(I[1]) == OLD["BRAND_ANSWERS"]["modutech"])
ok("คำเรียกรวมสองแบรนด์ตรงกับหัวข้อคำตอบสแตนเลสเดิม",
   f"ของ{TPL.all_brands_th(2)}ครับ" in _old)

# ─────────────────────────── ทางผิด ───────────────────────────
print("\n4) ของที่ประกาศไม่ตรงของจริง ต้องหยุดพร้อมบอกค่าทั้งสองฝั่ง")
tmp = tempfile.mkdtemp(prefix="reg_")


def fake_adapter(path, n_classes):
    os.makedirs(path, exist_ok=True)
    hdr = json.dumps({"base_model.model.classifier.bias": {"dtype": "F32", "shape": [n_classes],
                                                           "data_offsets": [0, 4 * n_classes]}}).encode()
    with open(os.path.join(path, M.WEIGHT_FILE), "wb") as f:
        f.write(struct.pack("<Q", len(hdr)) + hdr + b"\0" * 4 * n_classes)


def labels_file(path, n):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"id2label": {str(i): f"c{i}" for i in range(n)}}, f)


bdir = os.path.join(tmp, "x")
os.makedirs(bdir)
fake_adapter(os.path.join(bdir, "ad"), 10)
labels_file(os.path.join(bdir, "l9.json"), 9)
labels_file(os.path.join(bdir, "l10.json"), 10)
with open(os.path.join(bdir, "th.json"), "w", encoding="utf-8") as f:
    json.dump({"answer": 0.9}, f)
with open(os.path.join(bdir, "th_bad.json"), "w", encoding="utf-8") as f:
    json.dump({"answer": 1.7}, f)
rev = M.file_revision(os.path.join(bdir, "ad"))
good = {"enabled": "true", "vit": {"base": "b", "adapter": "ad", "revision": rev},
        "labels": "l10.json", "thresholds": "th.json", "collection": "c"}


def cfg(**over):
    c = json.loads(json.dumps(good))
    for k, v in over.items():
        if k.startswith("vit_"):
            c["vit"][k[4:]] = v
        else:
            c[k] = v
    return c


r, m = raises(lambda: M.load_image_spec("x", bdir, cfg(labels="l9.json")), M.ModelSpecError, "9", "10")
ok("labels 9 แต่ checkpoint 10", r, m)
r, m = raises(lambda: M.load_image_spec("x", bdir, cfg(vit_revision="sha256:0000000000000000")),
              M.ModelSpecError, "sha256:0000000000000000", rev)
ok("revision ไม่ตรงกับไฟล์", r, m)
r, m = raises(lambda: M.load_image_spec("x", bdir, cfg(vit_adapter="org/repo", vit_revision="main")),
              M.ModelSpecError, "main")
ok("adapter บน Hub ห้ามใช้ main", r, m)
spec_hub = M.load_image_spec("x", bdir, cfg(vit_adapter="org/repo", vit_revision="v1.2"))
ok("adapter บน Hub ที่มี tag ผ่าน", spec_hub.adapter == "org/repo" and not spec_hub.adapter_is_local)
r, m = raises(lambda: M.load_image_spec("x", bdir, cfg(thresholds="th_bad.json")), M.ModelSpecError, "1.7")
ok("threshold นอกช่วง 0..1", r, m)
r, m = raises(lambda: M.resolve_image("x", bdir, cfg(labels=None)), M.ModelSpecError, "labels")
ok("enabled: true แต่ขาด labels → หยุด", r, m)
st = M.resolve_image("x", bdir, cfg(enabled="auto", labels=None))
ok("enabled: auto แต่ขาด labels → ปิดพร้อมเหตุผล", not st.enabled and "labels" in st.reason, st.reason)
r, m = raises(lambda: M.resolve_image("x", bdir, cfg(), collection_points=lambda c: 0),
              M.ModelSpecError, "ไม่มีข้อมูล")
ok("enabled: true แต่ collection ว่าง → หยุด", r, m)

print("\n5) brand.yaml ผิดรูป")


def make_brand(root, folder, **over):
    d = os.path.join(root, folder)
    os.makedirs(d, exist_ok=True)
    y = {"protocol": 1, "key": folder, "enabled": True,
         "info": {"name": folder.title(), "order": 1, "kind_th": "k", "menu_line_th": "m",
                  "offtopic_th": "o", "category_th": "c", "answer_patterns": [folder]}}
    for k, v in over.items():
        if k.startswith("info_"):
            y["info"][k[5:]] = v
        else:
            y[k] = v
    import yaml
    with open(os.path.join(d, "brand.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(y, f, allow_unicode=True)


def fresh():
    p = tempfile.mkdtemp(prefix="brands_", dir=tmp)
    return p


p = fresh(); make_brand(p, "aa", key="bb")
r, m = raises(lambda: discover(p), RegistryError, "bb", "aa"); ok("key ไม่ตรงชื่อโฟลเดอร์", r, m)
p = fresh(); make_brand(p, "a_b")
r, m = raises(lambda: discover(p), RegistryError, "a_b"); ok("key มี _ (แยกสถานะกลับไม่ได้)", r, m)
p = fresh(); make_brand(p, "aa", protocol=2)
r, m = raises(lambda: discover(p), RegistryError, "2", "1"); ok("protocol ไม่ตรง", r, m)
p = fresh(); make_brand(p, "aa"); make_brand(p, "bb")
r, m = raises(lambda: discover(p), RegistryError, "aa", "bb"); ok("order ซ้ำ", r, m)
p = fresh(); make_brand(p, "aa", info_answer_patterns=["(ไม่ปิด"])
r, m = raises(lambda: discover(p), RegistryError, "answer_patterns"); ok("regex เสีย", r, m)
p = fresh(); make_brand(p, "aa", info_menu_line_th="")
r, m = raises(lambda: discover(p), RegistryError, "menu_line_th"); ok("info ขาดช่อง", r, m)
p = fresh(); make_brand(p, "aa"); make_brand(p, "bb", enabled=False, info_order=2)
ok("enabled: false → ข้าม", [b.key for b in discover(p)] == ["aa"])
ok("include_disabled เห็นครบ", [b.key for b in discover(p, include_disabled=True)] == ["aa", "bb"])
r, m = raises(lambda: discover(p, only=["zz"]), RegistryError, "zz"); ok("only ระบุแบรนด์ที่ไม่มี", r, m)
r, m = raises(lambda: load_plugins(discover(p)), RegistryError, "plugin.py")
ok("ยังไม่มี plugin.py → หยุดพร้อมบอกไฟล์", r, m)

print("\n6) ชื่อเดิมของ Modutech ชี้ไปโมดูลจริงตัวเดียวกัน (ไม่ใช่สำเนา)")
import importlib                                              # noqa: E402
for n in ("gates", "router", "turn", "kg"):
    ok(f"modutech_{n} is brands.modutech.{n}",
       importlib.import_module(f"modutech_{n}") is importlib.import_module(f"brands.modutech.{n}"))

src = open(os.path.join(ROOT, "chatbot_v5.py"), encoding="utf-8").read()
ok("chatbot_v5.py เป็นตัวชี้ไป assistant (ไม่ใช่สำเนา)",
   'sys.modules[__name__] = importlib.import_module("assistant")' in src and len(src.splitlines()) < 15)

print("\n7) แกนกลางไม่มีชื่อแบรนด์")
hits = [f"{f}:{i}" for f in sorted(os.listdir(os.path.join(ROOT, "core"))) if f.endswith(".py")
        for i, line in enumerate(open(os.path.join(ROOT, "core", f), encoding="utf-8"), 1)
        if re.search(r"movex|modutech", line, re.I)]
ok("grep core/*.py", not hits, hits)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
