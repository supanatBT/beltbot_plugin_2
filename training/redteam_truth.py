"""
training/redteam_truth.py — เฉลยของลูกค้าจำลองแบบจับผิด คำนวณจากฐานข้อมูลตรง ๆ ไม่ใช้โค้ดบอท (branch sim-fair · 4 พ.ย. 2026)

ทำไม: simulate_customers.Judge.acceptable() ของเป้าหมายที่ไม่มี accept_codes ใช้ need_flow.filter_by_need ของบอท
      = บอทตัดสินตัวเอง · ไฟล์นี้ห้าม import brands/ core/ need_flow (เทสต์ตรวจด้วย AST)

กติกา (ตกลงกับเจ้าของ 4 พ.ย.) — ตัดสินรายรุ่น รุ่นผ่านเมื่อมี variant อย่างน้อยหนึ่งตัวที่ผ่านทุกข้อ
    1. พิทช์ห่างจาก pitch_mm ไม่เกิน 0.5 มม. (ขอบรวม · ค่าตาม PROMPT_friend_sim_fix) · pitch_mm = null → ไม่กรองพิทช์
       ⚠ need_flow ของบอทใช้ 0.05 มม. (25.4 ไม่นับ 25.7/25.8/26.0 — สเตอร์คนละตัว) → รอเจ้าของตัดสิน
         เปลี่ยนได้ด้วย --pitch-tol 0.05 (ค่าที่ใช้บันทึกใน _truth ของไฟล์ผล)
    2. temperature_effective ของสภาวะที่ลูกค้าบอก (dry / wet) ครอบ temp_c (ขอบรวม)
       · wet_or_dry = null (ลูกค้าไม่รู้) → ต้องผ่านทั้ง dry และ wet (B11 แบบ ข.2)
       · ไม่มีค่าของสภาวะนั้น → ไม่ผ่าน (ไม่ใช้ dry แทน wet)
    3. สภาวะเปียก (หรือ null) และ temperature_effective.wet_status = not_recommended → ไม่ผ่าน
    hard_ok_codes = รุ่นทั้งฐานที่ผ่าน
    accept_codes  = hard_ok ∩ รุ่นที่แคตตาล็อกระบุใช้กับงานนั้น (industries[].applications)
                    จับชื่องานไม่ได้ → accept_codes = hard_ok + truth_note "จับชื่องานไม่ได้" (B9 แบบ ก. · ห้ามเว้นว่าง)
    hard_ok_by_stated = hard_ok ตามเงื่อนไขที่ลูกค้าพิมพ์แล้ว (คีย์ "pitch+temp+wet" แบบที่ Judge.hard_ok_stated อ่าน)
                    เงื่อนไขที่ยังไม่พูด = ไม่กรอง · สภาวะที่ยังไม่พูด = ผ่านสภาวะใดก็ได้
                    ยกเว้นเป้าหมาย wet_or_dry = null → ต้องผ่านทั้งสองสภาวะเสมอ
    Movex (brand = movex) → คัดลอกเดิม ไม่เพิ่มเฉลย (ใช้ expect_any)

จับชื่องาน: ตารางคำเขียนเองในไฟล์นี้ (ไม่อ่านจากไฟล์ของบอท) · ต้องจับ "สถานี" ได้ · อุตสาหกรรมเป็นตัวกรองเสริม
    (ไม่พบคำอุตสาหกรรม = ทุกอุตสาหกรรม) · ไม่เดา: คำกว้าง ๆ อย่าง "แปรรูป" "ถุง" ไม่อยู่ในตาราง

    python training/redteam_truth.py training/redteam_goals_v2.json     # → training/redteam_goals_v2_truth.json
    python training/redteam_truth.py                                     # → training/redteam_goals_truth.json
ไม่เขียนทับไฟล์เป้าหมายเดิม · ผลเรียงแน่นอน (รันซ้ำได้ไบต์เดิม)
"""
from __future__ import annotations

import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(ROOT, "modutech_v30_3.json")
PITCH_TOL_MM = 0.5

# (คำในชื่องาน, อุตสาหกรรมในแคตตาล็อก) — ไม่พบ = ไม่กรองอุตสาหกรรม
INDUSTRY_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("ไก่", "สัตว์ปีก", "เป็ด"), "Poultry"),
    (("หมู", "เนื้อวัว", "เนื้อสัตว์"), "Meat Processing"),
    (("ปลา", "กุ้ง", "อาหารทะเล"), "Fish & Seafood"),
    (("ขนมปัง", "ขนมอบ", "เบเกอรี่"), "Bakery Processing"),
    (("ผัก", "ผลไม้"), "Fruit & Vegetable"),
    (("กล่องลูกฟูก",), "Corrugated"),
]
# (คำในชื่องาน, application_id ใน application_vocabulary) — ต้องจับได้อย่างน้อยหนึ่งแถว
STATION_WORDS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("ตัดแต่ง",), ("trimming", "cut-up-deboning-trim-lines")),
    (("แช่แข็ง", "ฟรีซ"), ("freezing-lines", "freezing-lines-spiral", "spiral-freezers",
                         "spiral-proofing-cooling-freezing")),
    (("เตาอบ",), ("oven-infeed-outfeed",)),
    (("ล้าง",), ("washers", "prewashing-rinsing")),
    (("ตรวจจับโลหะ",), ("metal-detection",)),
]

NOTE_NO_APP = "จับชื่องานไม่ได้"


def load_catalog(path: str = CATALOG) -> dict:
    return json.load(open(path, encoding="utf-8"))


def _range_ok(rng, t: float) -> bool:
    return isinstance(rng, dict) and rng.get("min_c") is not None and rng.get("max_c") is not None \
        and rng["min_c"] <= t <= rng["max_c"]


def variant_ok(v: dict, temp_c, cond: str | None, both: bool) -> bool:
    """cond: "dry" | "wet" | None (ยังไม่รู้) · both=True: ต้องผ่านทั้งสองสภาวะ (เป้าหมาย wet_or_dry = null)"""
    te = v.get("temperature_effective") or {}
    if both:
        conds = ("dry", "wet")
    elif cond in ("dry", "wet"):
        conds = (cond,)
    else:
        conds = None                                   # ยังไม่พูดสภาวะ → ผ่านสภาวะใดก็ได้
    if temp_c is None:
        # ไม่กรองอุณหภูมิ แต่ยังตัด not_recommended เมื่อรู้ว่าเปียก/ต้องผ่านทั้งสอง
        return not ((both or cond == "wet") and te.get("wet_status") == "not_recommended")
    if conds is None:
        return any(variant_ok(v, temp_c, c, False) for c in ("dry", "wet"))
    for c in conds:
        if c == "wet" and te.get("wet_status") == "not_recommended":
            return False
        if not _range_ok(te.get(c), temp_c):
            return False
    return True


def passing(cat: dict, pitch_mm, temp_c, cond, both: bool, tol: float = PITCH_TOL_MM) -> list[str]:
    out = []
    for p in cat["products"]:
        if pitch_mm is not None and abs(p["specifications"]["pitch"]["mm"] - pitch_mm) > tol + 1e-9:
            continue
        if any(variant_ok(v, temp_c, cond, both) for v in p["specifications"]["variants"]):
            out.append(p["belt_code"])
    return sorted(out)


def match_application(text: str) -> tuple[str | None, tuple[str, ...]]:
    """(อุตสาหกรรม | None, application_id ที่จับได้) — ไม่จับสถานี = ()"""
    t = text or ""
    industry = next((ind for words, ind in INDUSTRY_WORDS if any(w in t for w in words)), None)
    ids: list[str] = []
    for words, app_ids in STATION_WORDS:
        if any(w in t for w in words):
            ids += [a for a in app_ids if a not in ids]
    return industry, tuple(ids)


def products_for_application(cat: dict, industry: str | None, app_ids: tuple[str, ...]) -> set[str]:
    name2id = {}
    for a in cat["application_vocabulary"]:
        for n in [a["application"], *a.get("raw_variants", [])]:
            name2id[n.strip().lower()] = a["application_id"]
    out = set()
    for p in cat["products"]:
        for ind in p.get("industries", []):
            if industry is not None and ind["industry"] != industry:
                continue
            if any(name2id.get(x["application"].strip().lower()) in app_ids for x in ind.get("applications", [])):
                out.add(p["belt_code"])
    return out


def truth_for_goal(cat: dict, g: dict, tol: float = PITCH_TOL_MM) -> dict:
    """คืนเฉพาะคีย์ที่เพิ่ม: accept_codes · hard_ok_codes · hard_ok_by_stated · truth_note"""
    pitch, temp, cond = g.get("pitch_mm"), g.get("temp_c"), g.get("wet_or_dry")
    both = "wet_or_dry" in g and cond is None
    notes = []
    if pitch is None:
        notes.append("ไม่รู้พิทช์ ไม่กรองพิทช์")
    if temp is None:
        notes.append("ไม่รู้อุณหภูมิ ไม่กรองอุณหภูมิ")
    if both:
        notes.append("ไม่ระบุสภาวะ ใช้ทั้งเปียกและแห้ง")
    hard = passing(cat, pitch, temp, cond, both, tol)
    industry, app_ids = match_application(g.get("application", ""))
    if app_ids:
        accept = sorted(set(hard) & products_for_application(cat, industry, app_ids))
    else:
        accept = list(hard)
        notes.insert(0, NOTE_NO_APP + (f" (อุตสาหกรรม {industry})" if industry else ""))
    by_stated = {}
    for n in range(4):
        for combo in itertools.combinations(("pitch", "temp", "wet"), n):
            key = "+".join(combo)
            by_stated[key] = passing(cat, pitch if "pitch" in combo else None, temp if "temp" in combo else None,
                                     cond if "wet" in combo else None, both, tol)
    return {"accept_codes": accept, "hard_ok_codes": hard, "hard_ok_by_stated": by_stated,
            "truth_note": " · ".join(notes)}


def build(goals_doc: dict, cat: dict, tol: float = PITCH_TOL_MM) -> dict:
    out = json.loads(json.dumps(goals_doc))               # สำเนาลึก — ไม่แตะของเดิม
    for g in out["goals"]:
        if g.get("brand") == "movex":
            continue
        g.update(truth_for_goal(cat, g, tol))
    out["_truth"] = ("เพิ่มโดย training/redteam_truth.py (อ่าน modutech_v30_3.json ตรง ไม่ใช้โค้ดบอท) · "
                     f"กติกาอยู่หัวไฟล์ redteam_truth.py · pitch_tol_mm={tol:g}")
    return out


def out_path(goals_path: str) -> str:
    base, ext = os.path.splitext(goals_path)
    return base + "_truth" + ext


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("goals", nargs="?", default=os.path.join(HERE, "redteam_goals.json"))
    ap.add_argument("--pitch-tol", type=float, default=PITCH_TOL_MM)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    src = a.goals
    doc = json.load(open(src, encoding="utf-8"))
    res = build(doc, load_catalog(), a.pitch_tol)
    dst = out_path(src)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")
    for g in res["goals"]:
        if g.get("brand") == "movex":
            print(f"  {g['id']:4} Movex — ข้าม (expect_any)")
            continue
        print(f"  {g['id']:4} hard_ok {len(g['hard_ok_codes']):2} · accept {len(g['accept_codes']):2}"
              + (f" · {g['truth_note']}" if g["truth_note"] else ""))
    print(f"เขียนแล้ว: {dst}")


if __name__ == "__main__":
    main()
