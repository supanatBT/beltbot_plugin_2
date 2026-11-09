#!/usr/bin/env python3
"""ตรวจรับ modutech_v31.json ตามการตัดสินของเจ้าของ (8–9 พ.ย. 2026) — ไม่ต้องใช้ LLM

รัน: python test_v31.py [modutech_v31.json]
ทุกข้ออ้างหมายเลขปัญหา (D…) หรือกฎ (R…) ในเอกสาร "กฎการตอบหลังแก้ (v31) และปัญหาข้อมูล Modutech"
"""
import json
import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "modutech_v31.json"
d = json.load(open(PATH, encoding="utf-8"))
P = {p["belt_code"]: p for p in d["products"]}
FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)


def var(code, belt, pin):
    hit = [v for v in P[code]["specifications"]["variants"] if v["belt_material"] == belt and v["pin_material"] == pin]
    assert len(hit) == 1, (code, belt, pin, len(hit))
    return hit[0]


def every_variant():
    for p in d["products"]:
        for v in p["specifications"]["variants"]:
            yield p, v


# จำนวนสินค้าไม่เปลี่ยน
check(len(d["products"]) == 68, f"products = {len(d['products'])}")
check(sum(len(p["specifications"]["variants"]) for p in d["products"]) == 282, "variants != 282")

# R1–R11 อยู่ใน answering_policy
rules = d["answering_policy"]["rules_th"]
check([r.split()[0] for r in rules] == [f"R{i}" for i in range(1, 12)], "rules_th ไม่ใช่ R1–R11")

# ฟิลด์ที่ตัด
for p, v in every_variant():
    check("temperature_note_th" not in v, f"{v['variant_id']} temperature_note_th")
    t = v.get("temperature") or {}
    check("registry_conflict_th" not in t and "registry_dry_max_c" not in t, f"{v['variant_id']} registry_*")
    check("wet_note_th_v30" not in (v.get("temperature_effective") or {}), f"{v['variant_id']} wet_note_th_v30")
for p in d["products"]:
    a, dq = p["answering"], p["data_quality"]
    check("forbidden_th" not in a and "disqualifiers" not in a, f"{p['belt_code']} answering rules")
    check("blocking" not in dq, f"{p['belt_code']} data_quality.blocking")
    check("temperature_envelope" not in p["derived"], f"{p['belt_code']} temperature_envelope")
    for ind in p.get("industries") or []:
        check("caveats_th" not in ind, f"{p['belt_code']} caveats_th")
    we = p["specifications"]["width_effective"]
    check(not re.search("ผลิตได้|สั่งพิเศษ", we["width_note_th"]), f"{p['belt_code']} width_note_th คำต้องห้าม")

# D3 (ตัดสิน 9 พ.ย.): ตอบ N/m แล้วแปลง lb/ft เอง
check(var("EC508 PR11", "PP", "PP")["belt_strength"]["lb_per_ft"] == 1233, "D3 EC508 PR11 PP lb")
check(var("MD508 FG", "POM", "PP")["belt_strength"]["lb_per_ft"] == 2056, "D3 MD508 FG POM/PP lb")
check(var("EC508 PR11", "PE", "PE")["belt_strength"]["lb_per_ft"] == 685, "lb PE ต้องตรงกับเล่ม 685")

# D6 (ตัดสิน: ตอบตามปกติ) — ไม่ติดธง
check("confirmation" not in var("EC508 R", "PP", "POM") or
      "belt_weight" not in var("EC508 R", "PP", "POM")["confirmation"]["fields"], "D6 ไม่ต้องติดธงน้ำหนัก")

# D14 · D7 · D29: ไม่มีค่าเปียกของวัสดุสายพาน → no_data
for code, mat in [("MP80 FG", "PA"), ("HC152 FG", "PA"), ("MD127 GAP50%", "PA"), ("MD254 GAP48%", "PA"),
                  ("MD254 GAP48%-EHT", "EHT"), ("HC508 C-MTW", "CR"), ("HC508 C-MTW", "IMPR")]:
    for v in P[code]["specifications"]["variants"]:
        if v["belt_material"] == mat:
            te = v["temperature_effective"]
            check(te["wet"] is None and te["wet_status"] == "no_data", f"D14 {code} {mat}")
    check(mat in P[code]["data_quality"]["wet_condition_unknown"], f"wcu {code} {mat}")
impr = var("HC508 C-MTW", "IMPR", "PBT")["temperature_effective"]
check(impr["dry"] == {"min_c": -20.0, "max_c": 65.0}, "D29 IMPR dry ต้องเป็น −20/65 ตามหน้า 217")
check(impr["source_layers"]["belt_material"]["dry"] is None, "D29 IMPR layer dry ต้องว่าง")
check(not re.search(r"93", json.dumps(impr, ensure_ascii=False)), "D29 IMPR ยังมี 93")
check(var("SM254 FG50%", "PA6", "PA6")["temperature_effective"]["wet_status"] == "not_recommended", "D9 PA6")

# D8 (ตัดสิน: เตือนทุกครั้ง) — partial_data มีข้อความบอกวัสดุที่ขาด
n_partial = 0
for p, v in every_variant():
    te = v.get("temperature_effective") or {}
    if te.get("wet_status") == "partial_data":
        n_partial += 1
        check(bool(te.get("wet_note_th")), f"D8 {v['variant_id']} ไม่มี wet_note_th")
check(n_partial == 66, f"partial_data = {n_partial} (74 เดิม − 8 ที่ย้ายเป็น no_data)")

# D17 · R7: ค่ารอผู้ผลิตติดธงตรงกับ pending
pend_ids = {x["id"] for x in d["pending_vendor_confirmation"]}
for vid in ["md254-gap48pct-eht--eht-ss", "md254-gap48pct--pa-pa", "hc152-fg--pa-pa", "mp80-fg--pa-pa",
            "hp508-rr--pph-pph", "md254-rr--pph-pph"]:
    v = next(v for p, v in every_variant() if v["variant_id"] == vid)
    check(v.get("temperature_trust") == "unconfirmed", f"D17 {vid} trust")
    check(v.get("confirmation", {}).get("status") == "unconfirmed", f"D17 {vid} confirmation")
    check(set(v["confirmation"]["pending_ids"]) <= pend_ids, f"D17 {vid} pending id ไม่มีอยู่จริง")
n_conf = sum(1 for p, v in every_variant() if v.get("confirmation"))
check(n_conf == 10, f"confirmation = {n_conf} (6 อุณหภูมิ + 4 แรงโค้ง EC508 R)")

# D19: required_slots ตรงกับค่า
for p in d["products"]:
    need = any(v["temperature_effective"].get("wet") != v["temperature_effective"].get("dry")
               for v in p["specifications"]["variants"])
    check(("wet_or_dry" in p["answering"]["required_slots"]) == need, f"D19 {p['belt_code']}")
check("wet_or_dry" in P["EC508 PR11"]["answering"]["required_slots"], "D19 EC508 PR11")

# D21 · R6: material_status
check(P["MD254 GT"]["material_status"]["POM"]["status"] == "pin_only", "D21 MD254 GT POM pin_only")
check(P["EC508 PR11"]["material_status"]["POM"]["status"] == "pin_only", "D21 EC508 PR11 POM pin_only")
check("POM" not in P["MD254 GT"]["data_quality"]["materials_recommended_not_manufactured"], "D21 mrnm MD254 GT")
check("material" not in P["MD254 GT"]["data_quality"]["blocking_for"], "D21 blocking MD254 GT")
check(P["SM254 FG50%"]["material_status"]["PA"]["status"] == "listed_as", "D21 SM254 FG50% PA")
for code, mat in [("SM127 FG", "PE"), ("SM127 CRV", "PE"), ("HC127 C", "PP"), ("MD254 C-RT", "PP"),
                  ("EC508 C-RT", "PP"), ("XP254 EVO FLT", "PE"), ("XP254 EVO FLT", "PP"), ("MD254 GAP48%", "PE")]:
    check(P[code]["material_status"][mat]["status"] == "not_listed", f"D21 {code} {mat}")

# D22 · D23 (ตัดสิน 9 พ.ย.: N/m)
for v in P["EC508 R"]["specifications"]["variants"]:
    c = v["belt_strength_curve"]
    check("n_total" not in c and c["n_per_m"] in (3200.0, 2330.0), "D22 EC508 R n_per_m")
    check(c["printed_unit"] == "N", "D23 EC508 R printed_unit")
    check("belt_strength_curve" in v["confirmation"]["fields"], "D23 EC508 R ติดธงหน่วย")
for p, v in every_variant():
    if v.get("belt_strength_curve"):
        check("n_per_m" in v["belt_strength_curve"], f"D22 {v['variant_id']} ไม่มี n_per_m")

# D28: EC508 TR ความกว้าง
tr = P["EC508 TR"]["specifications"]
check(609.6 in tr["belt_widths_mm"] and 609.9 not in tr["belt_widths_mm"], "D28 609.6")
check(tr["width_effective"]["increment_mm"] == 50.8, "D28 increment 50.8")
check(tr["width_effective"]["increment_status"] == "match", "D28 EC508 TR ต้องออกจากรายการไม่ตรง")

# D12 · R5: increment_status
mism = sorted(p["belt_code"] for p in d["products"]
              if p["specifications"]["width_effective"].get("increment_status") == "mismatch")
check(mism == sorted(["HC127 C", "MD127 GAP50%", "HC152 FG", "XP254 EVO FLT", "XP254 GT", "HC508 C",
                      "HC508 C-MTW", "HC508 MR", "HC508 NT", "HC508 PR22", "XP254 EVO CR"]),
      f"D12 mismatch = {mism}")
for p in d["products"]:
    we = p["specifications"]["width_effective"]
    if we.get("increment_status") == "mismatch":
        check(not re.search(r"เพิ่มทีละ\s*[\d.]+", we["width_note_th"]), f"R5 {p['belt_code']} width_note บอกค่าเพิ่มทีละ")

# D25 · D26: caveats ไม่มีแล้ว (ชื่อผิวยังอยู่ใน surface_type_note_th)
check(any(i.get("surface_type_note_th") for i in P["MP80 NS"]["industries"]), "D25 surface_type_note_th")

# N6 · R9: Do / Di
spr = d["sprockets"][0]
check("Do" in spr["dimension_definitions"] and spr["dimension_definitions"]["A"] is None, "N6 Do/Di")

# ทุก variant ที่มีแรงดึงมี lb/ft ที่คำนวณ
for p, v in every_variant():
    bs = v.get("belt_strength") or {}
    if bs.get("n_per_m"):
        check(bs.get("lb_per_ft") == round(bs["n_per_m"] * 0.0685218), f"R1 lb {v['variant_id']}")

if FAIL:
    print(f"FAIL {len(FAIL)}")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print(f"OK  {PATH}  ผ่านทุกข้อ")
