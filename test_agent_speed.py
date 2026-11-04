"""ทดสอบสวิตช์ลดเวลาตอบของ agent (4 พ.ย. 2026) แบบออฟไลน์ — ไม่เรียก Gemini

    python test_agent_speed.py          (venv ของ agent · ต้องมี movex_kg.db ของจริง)

AGENT_RESOLVE_TAB=1   รหัสที่ไม่มีคำว่า TAB ("LF880 K325") หาเจอ · รหัสที่เคยหาเจอได้ผลเดิมทุกตัว · ปิด = เดิม
AGENT_IMAGE_MAX_SIDE  รูปที่ส่งเข้า Gemini ย่อ + JPEG · ไฟล์ที่เครื่องมือรูปอ่านยังเต็มขนาด · ไม่ตั้ง = PNG เต็มแบบเดิมทุกไบต์
ข้อความทดสอบเขียนเอง ไม่ใช่จากชุด blind
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["AGENT_LAZY"] = "1"
for k in ("AGENT_RESOLVE_TAB", "AGENT_IMAGE_MAX_SIDE", "AGENT_REPLY_GUARD", "AGENT_DATASHEET_FILES"):
    os.environ.pop(k, None)

import importlib.util  # noqa: E402
import types as _types  # noqa: E402


class _Any:
    def __init__(self, *a, **k):
        pass

    def __call__(self, f=None, *a, **k):
        return f

    def __getattr__(self, attr):
        return _Any()


_MISSING = {top for top in ("torch", "transformers", "peft") if importlib.util.find_spec(top) is None}
for _name in ("torch", "torch.nn", "torch.nn.functional", "transformers", "peft"):
    if _name.split(".")[0] in _MISSING:
        _m = _types.ModuleType(_name)
        _m.__getattr__ = lambda attr: _Any
        sys.modules[_name] = _m
if "torch" in _MISSING:
    sys.modules["torch"].nn = sys.modules["torch.nn"]
    sys.modules["torch.nn"].functional = sys.modules["torch.nn.functional"]
    sys.modules["torch"].cuda = _types.SimpleNamespace(is_available=lambda: False)

from PIL import Image  # noqa: E402

from agent_baseline import movex_tools as M  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


print("\n=== test_agent_speed ===")
_R, products, _g = M._data()
probes = ["LF880 K325", "lf 882 k750", "LF882 K1200", "880 K450", "LF880", "LF882", "LF820 K325",
          "LF 880 TAB K325", "54901", "LFN 83 MFM", "lf821k1000", "K325", "LF999", "TAB", ""]
probes += [p.get("Ref") or "" for p in products.values()] + [str(p.get("Art_Nr") or "") for p in products.values()]
probes += list(products)

print("1) AGENT_RESOLVE_TAB ปิด = เดิม")
check("ค่าเริ่มต้นปิด", not M.resolve_tab_on())
before = {q: M.resolve_product(q) for q in probes}
check("LF880 K325 หาไม่เจอ (พฤติกรรมเดิม)", before["LF880 K325"][0] is None, before["LF880 K325"])

print("2) เปิด")
os.environ["AGENT_RESOLVE_TAB"] = "1"
after = {q: M.resolve_product(q) for q in probes}
for q, want in (("LF880 K325", "movex_chain_LF880_TAB_K325"), ("lf 882 k750", "movex_chain_LF882_TAB_K750"),
                ("LF882 K1200", "movex_chain_LF882_TAB_K1200"), ("880 K450", "movex_chain_LF880_TAB_K450")):
    check(f"{q!r} → {want}", after[q][0] == want, after[q])
changed = [q for q in probes if before[q][0] is not None and after[q] != before[q]]
check("รหัสที่เคยหาเจอได้ผลเดิมทุกตัว", not changed, changed[:5])
check("LF820 K325 ไม่ถูกดึงไป 880/882", after["LF820 K325"][0] == "movex_chain_LF820_K325", after["LF820 K325"])
check("LF880 ยังกำกวม (คืนตัวเลือก ไม่เลือกเอง)", after["LF880"][0] is None and len(after["LF880"][1]) >= 2, after["LF880"])
check("LF999 ยังหาไม่เจอ", after["LF999"][0] is None, after["LF999"])
check("ช่องว่างยังหาไม่เจอ", after[""] == (None, []), after[""])
lk = M.movex_lookup("LF880 K325")
check("movex_lookup ใช้ทางใหม่", "LF 880 TAB K325" in lk and "error" not in lk[:30], lk[:80])
os.environ.pop("AGENT_RESOLVE_TAB")

print("3) AGENT_IMAGE_MAX_SIDE")
import agent_assistant as A  # noqa: E402
big = Image.merge("RGB", [Image.effect_noise((3000, 2000), 40 + 20 * i) for i in range(3)])   # คล้ายรูปถ่าย (บีบอัดยาก)
ref = io.BytesIO(); big.convert("RGB").save(ref, format="PNG")
data, mime = A.llm_image_bytes(big)
check("ไม่ตั้ง = PNG เต็มขนาดเดิมทุกไบต์", mime == "image/png" and data == ref.getvalue())
os.environ["AGENT_IMAGE_MAX_SIDE"] = "1024"
data, mime = A.llm_image_bytes(big)
im = Image.open(io.BytesIO(data))
check("ตั้ง 1024 = JPEG ด้านยาว 1024", mime == "image/jpeg" and max(im.size) == 1024, (mime, im.size))
check("รักษาสัดส่วน", im.size == (1024, 683), im.size)
check("เล็กกว่าเดิมมาก", len(data) < len(ref.getvalue()) / 5, (len(data), len(ref.getvalue())))
check("รูปต้นฉบับไม่ถูกย่อตาม", big.size == (3000, 2000), big.size)
small = Image.new("RGB", (400, 300), (10, 10, 10))
d2, _m2 = A.llm_image_bytes(small)
check("รูปเล็กกว่าเกณฑ์ไม่ถูกขยาย", Image.open(io.BytesIO(d2)).size == (400, 300))
os.environ["AGENT_IMAGE_MAX_SIDE"] = "abc"
check("ค่าผิดรูปแบบ = ปิด", A.llm_image_bytes(small)[1] == "image/png")

print("4) ต่อกับ chat: ไฟล์ให้เครื่องมือยังเต็มขนาด · Gemini ได้รูปย่อ")
os.environ["AGENT_IMAGE_MAX_SIDE"] = "1024"
A.IMAGE_DIR = tempfile.mkdtemp(prefix="agent_img_")
eng = A._Engine.__new__(A._Engine)
eng.llm = A._LLMInfo(); eng.last_images = []
sent = []


def fake_call(coro):
    if coro.__name__ != "_turn":
        coro.close(); return "s1"
    sent.append(coro.cr_frame.f_locals.get("message")); coro.close()
    return "ตอบ", {"tool_calls": []}, "fake"


eng._call = fake_call
eng.chat("รุ่นอะไร", big, "s1")
files = os.listdir(A.IMAGE_DIR)
check("บันทึกไฟล์ให้เครื่องมือ 1 ไฟล์", len(files) == 1, files)
check("ไฟล์ให้เครื่องมือเต็มขนาด", files and Image.open(os.path.join(A.IMAGE_DIR, files[0])).size == (3000, 2000))
blob = [p for p in sent[-1].parts if getattr(p, "inline_data", None)]
check("Gemini ได้ JPEG ย่อ", blob and blob[0].inline_data.mime_type == "image/jpeg"
      and max(Image.open(io.BytesIO(blob[0].inline_data.data)).size) == 1024)
check("ข้อความ image_id ยังชี้ไฟล์เดิม", any(files[0] in (getattr(p, "text", "") or "") for p in sent[-1].parts))

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
