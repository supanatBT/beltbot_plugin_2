#!/usr/bin/env python3
"""patch_v31.py — สร้าง modutech_v31.json จาก modutech_v30_3.json (ไม่แก้ไฟล์ต้นทาง)

ที่มา: เอกสาร "กฎการตอบหลังแก้ (v31) และปัญหาข้อมูล Modutech" + การตัดสินของเจ้าของ 9 พ.ย. 2026
รายละเอียดทุกข้อและเหตุผลอยู่ใน CHANGELOG_v31.md

หลักของ v31
  · กฎการตอบเหลือ R1–R11 (answering_policy.rules_th) ตัดสินจากฟิลด์โครงสร้าง ไม่ใช่ข้อความกฎในรายรุ่น
  · เพิ่มฟิลด์โครงสร้าง: wet_status = no_data · confirmation · material_status · increment_status
  · ฟิลด์ที่บอท (gates.py) ยังอ่านอยู่ คงชื่อเดิมไว้แต่คำนวณใหม่ให้ตรงกับข้อมูล
    (required_slots · width_note_th · materials_recommended_not_manufactured · blocking_for)
    เพื่อไม่ให้บอทและเครื่องมือของ agent ที่ใช้ Catalogue ร่วมกันพัง
  · ค่าดิบจากเล่ม (catalogue_printed · source_layers) คงไว้เพื่อตรวจย้อน

รัน: python patch_v31.py [modutech_v30_3.json] [modutech_v31.json]
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys

from brands.modutech.gates import catalogue_increment_status

SRC = sys.argv[1] if len(sys.argv) > 1 else "modutech_v30_3.json"
DST = sys.argv[2] if len(sys.argv) > 2 else "modutech_v31.json"

LB_PER_FT = 0.0685218

RULES_V31 = [
    "R1 แหล่งตัวเลข: ตัวเลขมาจาก specifications เท่านั้น · นิ้ว °F lb/ft คำนวณจากค่าเมตริกเสมอ (unit_conversion) · ห้ามใช้ตัวเลขที่พิมพ์ในเล่ม (catalogue_printed) หรือใน sales_knowledge",
    "R2 ผูกเกรด: แรงดึง น้ำหนัก อุณหภูมิ ต้องบอกคู่วัสดุ (สายพาน/พิน) กำกับทุกครั้ง · ไม่รู้เกรดให้แจกทุกเกรด หรือถามเมื่อเกรดมาก · ห้ามรวมหลายเกรดเป็นค่าเดียว",
    "R3 อุณหภูมิ: อ่านจาก temperature_effective · ถามเปียก/แห้งเฉพาะเมื่อ answering.required_slots มี wet_or_dry · เปียกและ wet_status = ok → ตอบ · partial_data → ตอบพร้อมบอกทุกครั้งว่าวัสดุส่วนไหนไม่มีข้อมูลสภาวะเปียก (wet_note_th) · no_data → ไม่ให้ตัวเลขเปียก ให้ยืนยันกับพนักงานฝ่ายขาย · not_recommended → บอกว่าแคตตาล็อกไม่แนะนำสำหรับไลน์เปียก",
    "R4 ไลน์โค้ง: รุ่นที่ has_curve_rating ต้องรู้ว่าไลน์ตรงหรือมีโค้งก่อนตอบแรงดึง · ไลน์โค้งตอบ belt_strength_curve.n_per_m (N/m) ของเกรดนั้น และบอกว่าเป็นค่าช่วงโค้ง",
    "R5 ความกว้าง: ช่วง standard_min_mm–max_mm บอกได้เสมอ · printed_min_mm ที่แคบกว่ามาตรฐาน หรือ conflicting_value_mm ในตาราง บอกได้ แต่ต้องให้ฝ่ายขายยืนยัน · ค่าเพิ่มทีละบอกได้เฉพาะเมื่อ increment_status เป็น match หรือ not_printed · ห้ามใช้คำว่า \"ผลิตได้\" หรือ \"สั่งพิเศษ\"",
    "R6 วัสดุนอกตารางสเปก: ดู material_status · not_listed → ห้ามเสนอ บอกว่าแคตตาล็อกไม่มีข้อมูลสเปกของเกรดนี้ ให้ยืนยันกับพนักงานฝ่ายขาย · pin_only → บอกได้ว่ามีเฉพาะเป็นวัสดุพิน · listed_as → ตอบด้วยเกรดที่อยู่ในตาราง · ห้ามพูดว่า \"ไม่ผลิต\"",
    "R7 ค่าที่ยังไม่ยืนยัน: variant ที่มี confirmation (status = unconfirmed) → บอกค่าที่ใช้ และบอกในประโยคเดียวกันว่ายังไม่ยืนยัน ให้ยืนยันกับพนักงานฝ่ายขาย",
    "R8 งดรายหัวข้อ: data_quality.blocking_for งดเฉพาะหัวข้อนั้นตามกฎ R3 R5 R6 R9 · หัวข้ออื่นของรุ่นเดียวกันตอบปกติ",
    "R9 สเตอร์: จำนวนฟันตอบได้ · รหัสบอกได้พร้อมบอกว่าอนุมานจากซีรีส์ ให้ยืนยันกับฝ่ายขาย · วัสดุตอบได้เฉพาะรหัสที่มี suffix วัสดุ · Do (เส้นผ่านศูนย์กลางนอกที่ปลายฟัน) และ Di (เส้นผ่านศูนย์กลางวงในที่โคนฟัน) ตอบได้ · ขนาดรูเพลาและความหมายของ A B ส่งฝ่ายขาย",
    "R10 ส่งฝ่ายขาย: ราคา · lead time · MOQ · สต็อก · อะไหล่ · ความกว้างนอกมาตรฐาน · รัศมีวงเลี้ยว · ขนาดเพลา · การจำหน่ายรายประเทศ → ห้ามให้ตัวเลขหรือรับปาก ส่งต่อพร้อมช่องทางจริง",
    "R11 ไม่อ้างเกินหลักฐาน: งานหรือวัสดุที่มีหลักฐาน 1–2 รุ่น พูดว่า \"ในแคตตาล็อกนี้ ... มีในรุ่น ...\" · ชื่อผิวใช้ชื่อในแคตตาล็อก ชื่อในโบรชัวร์บอกเป็นชื่อเรียกอีกแบบของผิวเดียวกัน",
]

PENDING_CURVE_UNIT = {
    "id": "curve-strength-unit",
    "field": "belt_strength_curve",
    "question_th": "ความแข็งแรงตอนโค้งของ EC508 R (3200 / 2330) เป็นหน่วย N/m หรือแรงรวม N",
    "detail_th": ("หน้า 337 (EC508 TR) พิมพ์ 3200 / 2330 เป็น N/m แต่หน้า EC508 R พิมพ์ตัวเลขชุดเดียวกันเป็น N "
                  "หน้าอื่นที่มีค่าโค้งพิมพ์ N/m ทั้งหมด เจ้าของตัดสิน 9 พ.ย. 2026 ให้ตีความเป็น N/m "
                  "ถ้าเป็นแรงรวมจริง ค่าต่อเมตรของสายพานกว้างเกิน 1 ม. จะต่ำกว่าที่ตอบ (ที่ 1473 มม. ต่ำกว่า 32%)"),
    "affected_products": ["EC508 R"],
    "decision": "n_per_m (owner 2026-11-09)",
}
PENDING_PPH = {
    "id": "pph-celsius-fahrenheit-mismatch",
    "field": "temperature",
    "question_th": "MD254 RR เกรด PPH/PPH ทนได้สูงสุด 93 °C หรือ 110 °C",
    "detail_th": "ตารางหน้า 165 พิมพ์ 93 °C แต่ค่า °F ในคอลัมน์ถัดไปเท่ากับ 110 °C ระบบตอบ 93 °C ไว้ก่อนและแจ้งว่ายังไม่ยืนยัน",
    "variants": ["md254-rr--pph-pph"],
}

STATS: dict[str, int] = {}


def bump(k: str, n: int = 1) -> None:
    STATS[k] = STATS.get(k, 0) + n


def fmt(x: float) -> str:
    return f"{x:g}"


# ─────────────────────────── variant ───────────────────────────

def fix_variant(p: dict, v: dict, pending_temp: set[str]) -> None:
    vid = v["variant_id"]

    # D18 · D16: ข้อความกฎค้างในค่าอุณหภูมิ
    if v.pop("temperature_note_th", None) is not None:
        bump("removed temperature_note_th")
    t = v.get("temperature") or {}
    for k in ("registry_conflict_th", "registry_dry_max_c"):
        if t.pop(k, None) is not None:
            bump(f"removed temperature.{k}")

    te = v.get("temperature_effective") or {}
    if te.pop("wet_note_th_v30", None) is not None:
        bump("removed wet_note_th_v30")

    layers = te.get("source_layers") or {}
    bl = layers.get("belt_material") or {}

    # D29: IMPR ไม่มีแถวในหน้า 347 (ผู้ใช้ตรวจเล่ม 9 พ.ย.) — ค่า −40/+93 ไม่มีที่มา
    if bl.get("code") == "IMPR":
        bl["dry"] = None
        bl["wet"] = None
        bl["wet_status"] = "no_data"
        bl["note_th"] = "หน้า 347 ไม่มีแถว IMPR (ตรวจเล่ม 9 พ.ย. 2026) ใช้ช่วงจากตารางสเปกของรุ่นเท่านั้น"
        te["dry_limiters"] = [x for x in te.get("dry_limiters") or [] if "IMPR" not in str(x.get("layer"))]
        te["dry_limited_by_th"] = f"ตารางสเปกของรุ่นนี้ (หน้า {(layers.get('spec_table') or {}).get('page')})"
        bump("D29 IMPR layer cleared")

    # D14: วัสดุสายพานไม่มีค่าเปียก แต่ v30 เติมค่าเปียกเท่าค่าแห้ง → no_data
    if bl.get("code") and bl.get("wet") is None and bl.get("wet_status") == "no_data":
        mat = bl["code"]
        te["wet"] = None
        te["wet_status"] = "no_data"
        te.pop("wet_limiters", None)
        te["wet_note_th"] = (f"แคตตาล็อกไม่มีค่าสภาวะเปียกของวัสดุสายพาน {mat} "
                             "จึงให้ตัวเลขสำหรับไลน์เปียกไม่ได้ ต้องยืนยันกับพนักงานฝ่ายขาย")
        bump("D14 wet -> no_data")

    # D22 · D23: แรงโค้งเก็บเป็น N/m ทุกรุ่น (เจ้าของตัดสิน 9 พ.ย.: EC508 R ตีความเป็น N/m เหมือน TR)
    c = v.get("belt_strength_curve")
    if c:
        straight = (v.get("belt_strength") or {}).get("n_per_m")
        if "n_total" in c:
            c["n_per_m"] = c.pop("n_total")
            c["unit"] = "N_per_m"
            c["printed_unit"] = "N"
            c["unit_basis_th"] = ("เล่มหน้านี้พิมพ์หน่วย N แต่หน้า EC508 TR พิมพ์ตัวเลขชุดเดียวกันเป็น N/m "
                                  "เจ้าของตัดสินให้ใช้ N/m (9 พ.ย. 2026) รอผู้ผลิตยืนยัน")
            add_confirmation(v, "belt_strength_curve", "curve-strength-unit")
            bump("D22 n_total -> n_per_m")
        else:
            c.setdefault("printed_unit", "N/m")
        if straight and c.get("n_per_m"):
            c["ratio_vs_straight"] = round(straight / c["n_per_m"], 1)

    # D17: ค่าที่อยู่ในรายการรอผู้ผลิต ต้องติดธงเหมือนกันทุกที่
    if vid in pending_temp:
        if v.get("temperature_trust") != "unconfirmed":
            v["temperature_trust"] = "unconfirmed"
            bump("D17 trust ok -> unconfirmed")
        pid = "pph-celsius-fahrenheit-mismatch" if vid == "md254-rr--pph-pph" else "spec-exceeds-material-limit"
        add_confirmation(v, "temperature", pid)

    # R1: ค่าอิมพีเรียลคำนวณจากเมตริก (D3: lb ที่เล่มพิมพ์ผิด 4 variant)
    bs = v.get("belt_strength") or {}
    if bs.get("n_per_m"):
        bs["lb_per_ft"] = round(bs["n_per_m"] * LB_PER_FT)
        bs["lb_basis"] = "คำนวณจาก N/m (unit_conversion) ไม่ใช้ lb ที่เล่มพิมพ์"
    if c and c.get("n_per_m"):
        c["lb_per_ft"] = round(c["n_per_m"] * LB_PER_FT)


def add_confirmation(v: dict, field: str, pending_id: str) -> None:
    conf = v.setdefault("confirmation", {"status": "unconfirmed", "fields": [], "pending_ids": []})
    if field not in conf["fields"]:
        conf["fields"].append(field)
    if pending_id not in conf["pending_ids"]:
        conf["pending_ids"].append(pending_id)


# ─────────────────────────── product ───────────────────────────

def material_status(p: dict, registry: dict, all_codes: dict) -> dict:
    s = p["specifications"]
    belt = {v["belt_material"] for v in s["variants"]}
    pin = {v["pin_material"] for v in s["variants"]}
    rec = set((p.get("derived") or {}).get("materials_recommended") or [])
    rec |= set((p.get("material_availability") or {}).get("recommended_in_brochures") or [])
    out = {}
    for m in sorted(rec - belt):
        # วัสดุที่อยู่ในตารางในชื่อเกรดย่อย (PA → PA6 · POM → POM-NL)
        alias = sorted(b for b in belt if m in ((registry.get(b) or {}).get("resolves_to") or []) and b != m)
        if alias:
            out[m] = {"status": "listed_as", "listed_as": alias,
                      "note_th": f"ตารางสเปกของรุ่นนี้มี {m} ในเกรด {', '.join(alias)}"}
        elif m in pin:
            out[m] = {"status": "pin_only",
                      "note_th": f"รุ่นนี้มี {m} เฉพาะเป็นวัสดุพิน ตารางสเปกไม่มีสายพานเกรด {m}"}
        else:
            note = f"แคตตาล็อกแนะนำ {m} ไว้ แต่ตารางสเปกของรุ่นนี้ไม่มีเกรด {m} ต้องยืนยันกับพนักงานฝ่ายขาย"
            sib = [c for c, mats in all_codes.items() if c != p["belt_code"] and c.startswith(p["belt_code"])
                   and m in mats]
            if sib:
                note += f" (ในแคตตาล็อกนี้ {m} มีในรุ่น {', '.join(sib)})"
            if m == "IR":
                note += " (ตารางมีเกรด IMPR = Impact Resistant POM ซึ่งอาจเป็นวัสดุเดียวกัน ต้องยืนยัน)"
            out[m] = {"status": "not_listed", "note_th": note}
    return out


def fix_width(p: dict) -> None:
    s = p["specifications"]
    we = s.get("width_effective") or {}

    # D28: EC508 TR 609.9 → 609.6 (24 นิ้ว) · ตารางเพิ่มทีละ 2 นิ้ว = 50.8 (ผู้ใช้ตรวจเล่ม 9 พ.ย.)
    if p["belt_code"] == "EC508 TR":
        s["belt_widths_mm"] = [609.6 if abs(w - 609.9) < 1e-6 else w for w in s["belt_widths_mm"]]
        we["increment_mm"] = 50.8
        bump("D28 EC508 TR widths")

    st, printed_inc = catalogue_increment_status(p)
    inc = we.get("increment_mm")
    if inc is None:
        status = "single_width" if len(s.get("belt_widths_mm") or []) <= 1 else st
    elif st == "found":
        status = "match" if abs(printed_inc - inc) < 0.05 else "mismatch"
    else:
        status = st                     # not_printed · unreadable · no_notes
    we["increment_status"] = status
    if printed_inc is not None:
        we["increment_printed_mm"] = printed_inc
    bump(f"increment_status {status}")

    pm = (s.get("minimum_width") or {}).get("mm")
    if pm is not None:
        we["printed_min_mm"] = pm
    std = we.get("standard_min_mm") or we.get("orderable_min_mm")
    we["standard_min_mm"] = std

    # D20: width_note_th สร้างใหม่จากฟิลด์โครงสร้าง (บอทยังอ่านฟิลด์นี้) — ไม่มีคำว่า ผลิตได้ / สั่งพิเศษ
    mx = we.get("max_mm")
    head = f"ความกว้างมาตรฐาน {fmt(std)} ถึง {fmt(mx)} มม." if mx and mx != std else f"ความกว้าง {fmt(std)} มม."
    if inc is not None and status in ("match", "not_printed"):
        head += f" เพิ่มทีละ {fmt(inc)} มม."
    parts = [head]
    if we.get("confidence") == "consistent" and pm is not None and pm < std:
        parts.append(f"เล่มระบุความกว้างต่ำสุดไว้ {fmt(pm)} มม. ถ้าต้องการแคบกว่า {fmt(std)} มม. "
                     "ต้องยืนยันกับพนักงานฝ่ายขายก่อน")
    if we.get("confidence") == "disputed" and we.get("conflicting_value_mm") is not None:
        cv = we["conflicting_value_mm"]
        parts.append(f"ตารางในแคตตาล็อกมี {fmt(cv)} มม. ด้วยแต่ขัดกับค่าต่ำสุดที่ระบุไว้ "
                     f"ถ้าต้องการ {fmt(cv)} มม. ต้องยืนยันกับพนักงานฝ่ายขายก่อน")
    if status == "mismatch":
        parts.append("ค่าเพิ่มทีละมาตรฐานของรุ่นนี้ยังยืนยันไม่ได้ ต้องยืนยันกับพนักงานฝ่ายขาย")
    we["width_note_th"] = " ".join(parts)


def fix_product(p: dict, registry: dict, all_codes: dict, pending_temp: set[str]) -> None:
    s = p["specifications"]
    for v in s["variants"]:
        fix_variant(p, v, pending_temp)

    ans = p.setdefault("answering", {})
    dq = p.setdefault("data_quality", {})

    # D15 · forbidden_th · D19
    for k in ("forbidden_th", "disqualifiers"):
        if ans.pop(k, None) is not None:
            bump(f"removed answering.{k}")
    ans.pop("material_precedence", None)
    needs = any((v.get("temperature_effective") or {}).get("wet") != (v.get("temperature_effective") or {}).get("dry")
                for v in s["variants"])
    old = ans.get("required_slots") or []
    ans["required_slots"] = ["wet_or_dry"] if needs else []
    if ans["required_slots"] != old:
        bump(f"D19 required_slots {old} -> {ans['required_slots']} ({p['belt_code']})")

    # R6 · D21
    ms = material_status(p, registry, all_codes)
    if ms:
        p["material_status"] = ms
    not_listed = sorted(m for m, x in ms.items() if x["status"] == "not_listed")
    if sorted(dq.get("materials_recommended_not_manufactured") or []) != not_listed:
        bump(f"D21 mrnm {dq.get('materials_recommended_not_manufactured')} -> {not_listed} ({p['belt_code']})")
    dq["materials_recommended_not_manufactured"] = not_listed

    fix_width(p)

    # wet_condition_unknown ตามค่าใหม่
    wcu = sorted({v["belt_material"] for v in s["variants"]
                  if (v.get("temperature_effective") or {}).get("wet_status") == "no_data"})
    dq["wet_condition_unknown"] = wcu

    # R8: blocking_for คำนวณใหม่จากฟิลด์โครงสร้าง
    bf = []
    if not_listed:
        bf.append("material")
    if wcu:
        bf.append("wet")
    we = s.get("width_effective") or {}
    if we.get("confidence") in ("consistent", "disputed") or we.get("increment_status") == "mismatch":
        bf.append("width")
    if bf != (dq.get("blocking_for") or []):
        bump(f"blocking_for {dq.get('blocking_for')} -> {bf} ({p['belt_code']})")
    dq["blocking_for"] = bf
    rc = p.get("retrieval_card") or {}
    rc["blocking_for"] = bf
    rc.pop("has_blocking_issue", None)

    for k in ("blocking", "temperature_disputed_pairs", "temperature_f_typo_pairs",
              "authored_text_conflicts", "physics_issues", "specs_incomplete"):
        if dq.pop(k, None) is not None:
            bump(f"removed data_quality.{k}")

    if (p.get("derived") or {}).pop("temperature_envelope", None) is not None:
        bump("removed derived.temperature_envelope")

    # D24: pitch ในรหัสไม่ใช่พิทช์จริง — เพิ่มชื่อที่ไม่ชวนเข้าใจผิด (image_read.py ยังอ่าน pitch_mm จึงคงไว้)
    cp = p.get("code_parts") or {}
    if "pitch_mm" in cp:
        cp["nominal_pitch_from_code_mm"] = cp["pitch_mm"]
        cp["pitch_note_th"] = "ค่าจากรหัสรุ่น ไม่ใช่พิทช์จริง พิทช์จริงอยู่ที่ specifications.pitch"

    # D25 · D26: caveats ของอุตสาหกรรม (ชื่อผิว → surface_type_note_th · 5 ประเทศ → เรื่องขาย R10)
    for ind in p.get("industries") or []:
        for k in ("caveats_th", "caveats"):
            if ind.pop(k, None) is not None:
                bump(f"removed industries.{k}")


# ─────────────────────────── top level ───────────────────────────

def fix_sprockets(d: dict) -> None:
    for sp in d.get("sprockets") or []:
        if "dimension_note_th" in sp:
            sp["dimension_note_th"] = ("Do = เส้นผ่านศูนย์กลางนอกที่ปลายฟัน · Di = เส้นผ่านศูนย์กลางวงในที่โคนฟัน "
                                       "(อ่านจากภาพวาดหน้าสเตอร์ ตัดสิน 9 พ.ย. 2026) · A และ B เล่มไม่นิยาม")
            sp["dimension_definitions"] = {
                "Do": "outer diameter at tooth tips", "Di": "inner circle diameter at tooth roots",
                "A": None, "B": None, "basis": "drawing labels, owner decision 2026-11-09"}
            bump("sprocket Do/Di defined")
    for link in d.get("belt_sprocket_links") or []:
        a = link.get("answerable_th")
        if isinstance(a, dict):
            a["ขนาด Do / Di"] = "ตอบได้ ตามรหัสที่อนุมาน ต้องบอกว่ารหัสอนุมานจากซีรีส์"
    for q in d.get("sprocket_open_questions") or []:
        if q.get("id") == "di_do_abcex_undefined":
            q["status"] = "partly_resolved"
            q["resolution_th"] = ("Do และ Di อ่านจากภาพวาด (Do = ปลายฟัน · Di = วงในที่โคนฟัน) ตัดสิน 9 พ.ย. 2026 "
                                  "· A B C E X ยังไม่นิยาม")
        if q.get("id") == "z10_pitch_diameter_conflict":
            q["resolution_th"] = ("ค่า Do ของ HC272 Z10 คือ 89.7 มม. (หน้า 192) ส่วน 89 มม. (หน้า 194) และ 81.1 มม. "
                                  "(หน้า 193) เป็น pitch diameter ซึ่งยังขัดกันอยู่")


def main() -> None:
    with open(SRC, encoding="utf-8") as f:
        raw = f.read()
    d = json.loads(raw)
    src_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    d = copy.deepcopy(d)

    registry = {m["material_code"]: m for m in d.get("material_registry") or []}
    # D29: ทะเบียนวัสดุ IMPR ไม่มีค่าในหน้า 347
    if "IMPR" in registry:
        registry["IMPR"]["temperature_c"] = None
        registry["IMPR"]["note_th"] = "หน้า 347 ไม่มีแถว IMPR (ตรวจเล่ม 9 พ.ย. 2026) — v30 ใส่ −40/+93 โดยไม่มีที่มา"
    all_codes = {p["belt_code"]: {v["belt_material"] for v in p["specifications"]["variants"]} for p in d["products"]}

    pending = d.get("pending_vendor_confirmation") or []
    pending_temp = {vid for it in pending if it.get("id") == "spec-exceeds-material-limit"
                    for c in it.get("conflicts") or [] for vid in c["variants"]}
    pending_temp.add("md254-rr--pph-pph")

    for p in d["products"]:
        fix_product(p, registry, all_codes, pending_temp)

    # pending_vendor_confirmation
    d["pending_vendor_confirmation"] = [PENDING_CURVE_UNIT if it.get("id") == "curve-strength-unit" else it
                                        for it in pending]
    for it in d["pending_vendor_confirmation"]:
        if it.get("id") == "wet-condition-missing":
            it["question_th"] = "เกรด PA, CR, IMPR, EHT ใช้ในสภาวะเปียกได้หรือไม่ และถึงกี่องศา"
            it["affected_materials"] = ["PA", "CR", "IMPR", "EHT"]
            it["detail_th"] = "หน้า 347 ไม่ได้ระบุค่าสภาวะเปียกของเกรดเหล่านี้ (IMPR ไม่มีแถวเลย) v31 จึงไม่ให้ตัวเลขไลน์เปียก"
    if not any(it.get("id") == PENDING_PPH["id"] for it in d["pending_vendor_confirmation"]):
        d["pending_vendor_confirmation"].append(PENDING_PPH)

    fix_sprockets(d)

    pol = d.setdefault("answering_policy", {})
    pol["rules_th"] = RULES_V31
    pol["version"] = "v31"

    d["_version"] = {"file": DST, "parent": SRC, "parent_sha256": src_sha, "made_by": "patch_v31.py",
                     "date": "2026-11-09", "changelog": "CHANGELOG_v31.md"}

    out = json.dumps(d, ensure_ascii=False, indent=1)
    with open(DST, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"{DST}  sha256={hashlib.sha256(out.encode('utf-8')).hexdigest()}")
    for k in sorted(STATS):
        print(f"  {STATS[k]:4d}  {k}")


if __name__ == "__main__":
    main()
