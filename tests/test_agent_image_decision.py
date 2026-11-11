"""AGENT_IMAGE_DECISION (11 พ.ย. 2026) — ไม่โหลดโมเดล ไม่เรียก Gemini

สัญญาณ ViT + อันดับรวมของทุกเคสมาจากผลจริงของ diag_movex_images.py บนเครื่องผู้ใช้ (11 พ.ย.)
รูปจริงของแต่ละเคส: eval/cases/testcases_movex_old_image.csv คอลัมน์ image

    python tests/test_agent_image_decision.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("AGENT_LAZY", "1")
# ต้องตั้งก่อน import: tools_impl อ่านไฟล์ฐานตอน import (กฎ {policy} ใน prompt มาจากฐานนี้)
os.environ.update({"AGENT_PROMPT": "r4", "AGENT_MODUTECH_JSON": os.path.join(ROOT, "data", "modutech_v31.json"),
                   "AGENT_IMAGE_SURFACE": "1"})

from agent import movex_tools as MX  # noqa: E402

PRODUCTS = {p["product_id"]: p for p in json.load(open(
    os.path.join(ROOT, "data", "extracted_data_v3_machine_ready.json"), encoding="utf-8"))["products"]}
TH = {"answer": 0.90, "series": 0.50}
C = "movex_chain_"


def sig(series, conf, dom, top):
    return {"series": series, "confidence": conf, "dominant": dom, "top_pid": top}


# (เคส, สัญญาณ, อันดับรวม, คาด brand, คาด action, คาด product_id หรือ series)
CASES = [
    ("I01 880 K325 บน · ViT ชี้ K450", sig("880", 0.9038, True, C + "LF880_TAB_K450"),
     [(C + "LF880_TAB_K450", 0.0208), (C + "LF880_TAB_K325", 0.0200), ("movex_sprocket_54901", 0.0049)],
     "movex", "ask_width", "880"),
    ("I02 880 K325 ข้าง · ViT 0.84", sig("880", 0.838, False, C + "LF880_TAB_K325"),
     [(C + "LF880_TAB_K325", 0.0161), (C + "LF880_TAB_K450", 0.0159), (C + "LF820_K325", 0.0070)],
     "uncertain", "ask_width", "880"),
    ("I05 880 K450 บน", sig("880", 0.936, True, C + "LF880_TAB_K450"),
     [(C + "LF880_TAB_K450", 0.0209), (C + "LF880_TAB_K325", 0.0206), (C + "LF821_K750", 0.0128)],
     "movex", "ask_width", "880"),
    ("I08/M06 LFN 83 MFM · ViT 1.00 (agent เดิมถามแบรนด์/ตอบ Modutech)", sig("83", 1.0, True, C + "LFN_83_MFM"),
     [(C + "LFN_83_MFM", 0.0167), (C + "LFN_103_MFH", 0.0147)],
     "movex", "answer", C + "LFN_83_MFM"),
    ("I09 LFN 83 MFM หลัง · ViT 0.83", sig("83", 0.8349, False, C + "LFN_83_MFM"),
     [(C + "LFN_83_MFM", 0.0160), (C + "LFN_103_MFH", 0.0159), (C + "LF820_K325", 0.0071)],
     "uncertain", "ask_width", "83"),
    ("I14 820 K325 บน", sig("820", 0.9621, True, C + "LF820_K325"),
     [(C + "LF820_K325", 0.0209), (C + "LF820_K750", 0.0044), (C + "LF820_K400", 0.0034)],
     "movex", "answer", C + "LF820_K325"),
    ("M08 LFN 103 MFH · ViT 1.00 (agent เดิมถาม 83 หรือ 103)", sig("103", 1.0, True, C + "LFN_103_MFH"),
     [(C + "LFN_103_MFH", 0.0167), (C + "LFN_83_MFM", 0.0156)],
     "movex", "answer", C + "LFN_103_MFH"),
    ("M15 880 แสงน้อย · ViT ผิดเองเป็น 820 (ข้อจำกัด ไม่ใช่ที่แก้)", sig("820", 0.9388, True, C + "LF820_K325"),
     [(C + "LF820_K325", 0.0208), (C + "LF820_K750", 0.0047), (C + "LF820_K400", 0.0036)],
     "movex", "answer", C + "LF820_K325"),
    ("I17 สเตอร์", sig("103", 0.9464, True, "movex_sprocket_57801"),
     [("movex_sprocket_57801", 0.0158)], "movex", "answer", "movex_sprocket_57801"),
    ("ไม่มีสัญญาณ ViT", None, [], "uncertain", "ask_back", None),
    ("ViT ต่ำ 0.31", sig("880", 0.31, False, C + "LF880_TAB_K450"),
     [(C + "LF880_TAB_K450", 0.01), (C + "LF820_K325", 0.0099)], "uncertain", "ask_back", None),
]

fail = 0


def check(name, ok, detail=""):
    global fail
    fail += not ok
    print(f"{'✓' if ok else '✗'} {name}{'' if ok else '  ' + detail}")


for name, s, rows, brand, action, want in CASES:
    d = MX.image_decision(s, rows, PRODUCTS, TH)
    got = d.get("product_id") if action == "answer" else d.get("series")
    ok = d["brand"] == brand and d["action"] == action and (want is None or got == want)
    check(name, ok, json.dumps(d, ensure_ascii=False)[:300])
    if d["action"] == "ask_width" and d.get("series") == "880":
        refs = [w["product_id"] for w in d["widths"]]
        check("   ↳ widths ของ 880 มีแค่ K325 · K450 (ไม่มี 882/820)",
              refs == [C + "LF880_TAB_K325", C + "LF880_TAB_K450"], str(refs))

# รูป Modutech ที่ ViT (closed-set) ให้คะแนนสูงแต่ไม่ dominant หรือต่ำกว่า 0.90 → ต้องไม่ตัดสินเป็น Movex
for conf, dom in ((0.87, True), (0.89, True), (0.95, False), (0.62, False)):
    d = MX.image_decision(sig("103", conf, dom, C + "LF820_K325"), [(C + "LF820_K325", 0.01)], PRODUCTS, TH)
    check(f"ViT {conf} dominant={dom} → brand uncertain", d["brand"] == "uncertain", d["brand"])

# สวิตช์: ปิด = prompt และคำบรรยายผิวเดิมทุกตัวอักษร · เปิด = กฎ decision แทนกฎช่องห่างเดิม
from agent import agent as AG  # noqa: E402
from agent import tools_impl as T  # noqa: E402
import hashlib  # noqa: E402

os.environ["AGENT_IMAGE_DECISION"] = "0"
off = AG.instruction_text()
curve_off = T.surface_choices()["Curve Top"]
check("ปิด: prompt sha = 221c6b1fe5fe (ตัวที่รันเทส 10 พ.ย.)",
      hashlib.sha256(off.encode("utf-8")).hexdigest()[:12] == "221c6b1fe5fe")
check("ปิด: คำบรรยาย Curve Top เดิม", "โมดูลเป็นแถวแคบต่อกันเลี้ยวได้" in curve_off, curve_off)
os.environ["AGENT_IMAGE_DECISION"] = "1"
on = AG.instruction_text()
curve_on = T.surface_choices()["Curve Top"]
check("เปิด: ไม่มีกฎ top1_top2_gap เดิม", "top1_top2_gap < 0.003" not in on)
check("เปิด: ไม่มีกฎ 'ใช้ results อันดับ 1' เดิม", "ใช้ results อันดับ 1" not in on)
check("เปิด: บังคับเรียก movex_match_image ก่อน", "เรียก movex_match_image ก่อนเสมอ" in on)
check("เปิด: belts_by_surface ใช้เมื่อ decision.brand ไม่ใช่ movex", 'ไม่ใช่ "movex") → ดูชนิดผิวเอง' in on)
check("เปิด: Curve Top บอกว่าโซ่แถวเดียวไม่ใช่ผิวนี้", "โซ่แถวเดียวแคบ" in curve_on and "แถวแคบต่อกัน" not in curve_on, curve_on)
check("เปิด: ไม่มีชื่อรุ่นในกฎที่เพิ่ม", not any(c in "\n".join(n for _o, n in AG.IMAGE_DECISION_EDITS)
                                            for c in ("LFN", "K325", "K450", "LF8")))

print(f"\n{'ผ่านทุกข้อ' if not fail else f'{fail} ข้อไม่ผ่าน'}")
sys.exit(1 if fail else 0)
