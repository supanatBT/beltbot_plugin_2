"""
training/test_redteam_truth.py — เทสต์ของ redteam_truth.py (ออฟไลน์ · ไม่เรียก API · sim-fair 4 พ.ย. 2026)

    python training/test_redteam_truth.py
กลุ่ม 1 แคตตาล็อกจิ๋วเขียนเอง (กติกาและขอบ) · กลุ่ม 2 ฐานจริง modutech_v30_3.json คำนวณด้วยมือ (เลขหน้า + variant_id)
· กลุ่ม 3 โครงสร้าง (ไม่ import โค้ดบอท · ไม่เขียนทับ · รันซ้ำได้ไบต์เดิม)
"""
from __future__ import annotations

import ast
import contextlib
import io
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import redteam_truth as RT  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


def V(vid, dry=None, wet=None, wet_status="ok"):
    te = {"wet_status": wet_status}
    if dry:
        te["dry"] = {"min_c": dry[0], "max_c": dry[1]}
    if wet:
        te["wet"] = {"min_c": wet[0], "max_c": wet[1]}
    return {"variant_id": vid, "temperature_effective": te}


def P(code, pitch, variants, apps=()):
    return {"belt_code": code, "specifications": {"pitch": {"mm": pitch}, "variants": variants},
            "industries": [{"industry": ind, "applications": [{"application": a}]} for ind, a in apps]}


TOY = {
    "application_vocabulary": [
        {"application": "Trimming", "application_id": "trimming", "raw_variants": []},
        {"application": "Freezing Lines", "application_id": "freezing-lines", "raw_variants": ["Freezing lines"]},
    ],
    "products": [
        P("A10", 10.0, [V("a", (0, 50), (0, 40))], [("Poultry", "Trimming")]),
        P("B10", 10.5, [V("b", (0, 50), (0, 40))]),                                    # ห่าง 0.5 พอดี
        P("C10", 10.51, [V("c", (0, 50), (0, 40))]),                                   # ห่าง 0.51
        P("D10", 10.0, [V("d1", (20, 30), (20, 30)), V("d2", (-10, 60), (-10, 60))]),  # variant หนึ่งครอบ
        P("E10", 10.0, [V("e", (-20, 80))], [("Poultry", "Trimming")]),                 # ไม่มีค่าเปียก
        P("F10", 10.0, [V("f", (-20, 80), (-20, 80), "not_recommended")]),              # เปียกไม่แนะนำ
        P("G10", 10.0, [V("g", (-20, 80), (-20, 20))], [("Poultry", "Trimming")]),      # แห้งผ่าน 50 เปียกไม่ผ่าน
        P("H10", 10.0, [V("h", (-40, 50), (-40, 50))], [("Fish & Seafood", "Freezing lines")]),
    ],
}


def goal(**kw):
    g = {"id": "T", "brand": "modutech", "application": "ไก่ ไลน์ตัดแต่ง", "pitch_mm": 10.0, "temp_c": 50,
         "wet_or_dry": "dry"}
    g.update(kw)
    return g


print("กลุ่ม 1 · แคตตาล็อกจิ๋ว (กติกาและขอบ)")
h = RT.truth_for_goal(TOY, goal())["hard_ok_codes"]
ok("B1 พิทช์ห่าง 0.5 มม. พอดี → ผ่าน (ขอบรวม)", "B10" in h, h)
ok("B2 พิทช์ห่าง 0.51 มม. → ไม่ผ่าน", "C10" not in h, h)
ok("B3 temp เท่าขอบบน/ขอบล่างพอดี → ผ่าน", "A10" in RT.truth_for_goal(TOY, goal(temp_c=50))["hard_ok_codes"]
   and "A10" in RT.truth_for_goal(TOY, goal(temp_c=0))["hard_ok_codes"])
ok("B4 variant หนึ่งไม่ครอบ อีก variant ครอบ → รุ่นผ่าน", "D10" in h, h)
hw = RT.truth_for_goal(TOY, goal(wet_or_dry="wet", temp_c=30))
ok("B5 ลูกค้าบอกเปียก · ช่วง wet ไม่ครอบ (G10 เปียกถึง 20) → ไม่ผ่าน (ไม่ใช้ dry แทน)", "G10" not in hw["hard_ok_codes"])
ok("B6 เปียก + wet_status=not_recommended → ไม่ผ่าน แม้ช่วงครอบ", "F10" not in hw["hard_ok_codes"])
ok("B7 เปียกแต่ไม่มีค่า wet → ไม่ผ่าน (ไม่เดาจาก dry)", "E10" not in hw["hard_ok_codes"])
t8 = RT.truth_for_goal(TOY, goal())
ok("B8 จับงานได้ → accept = hard_ok ∩ ระบุใช้กับงาน · accept ⊆ hard_ok",
   t8["accept_codes"] == ["A10", "E10", "G10"] and set(t8["accept_codes"]) <= set(t8["hard_ok_codes"])
   and t8["truth_note"] == "", t8["accept_codes"])
t9 = RT.truth_for_goal(TOY, goal(application="ถุงปุ๋ย"))
ok("B9 จับชื่องานไม่ได้ → truth_note 'จับชื่องานไม่ได้' · accept = hard_ok (แบบ ก.)",
   t9["truth_note"].startswith("จับชื่องานไม่ได้") and t9["accept_codes"] == t9["hard_ok_codes"] != [], t9["truth_note"])
ok("B9 อุตสาหกรรมกรองเสริม: 'ไก่ แช่แข็ง' ไม่นับ H10 (ปลา) · 'แช่แข็ง' เฉย ๆ นับ",
   "H10" not in RT.truth_for_goal(TOY, goal(application="ไก่ แช่แข็ง", temp_c=-30, pitch_mm=10.0))["accept_codes"]
   and "H10" in RT.truth_for_goal(TOY, goal(application="อาหารแช่แข็ง", temp_c=-30))["accept_codes"])
mv = RT.build({"goals": [{"id": "M", "brand": "movex", "expect_any": ["x"]}]}, TOY)
ok("B10 Movex → คัดลอกเดิม ไม่มีคีย์เฉลย", mv["goals"][0] == {"id": "M", "brand": "movex", "expect_any": ["x"]})
t11 = RT.truth_for_goal(TOY, goal(wet_or_dry=None))
ok("B11 wet_or_dry = null → ต้องผ่านทั้งสองสภาวะ: G10 (แห้งผ่าน เปียกไม่ผ่าน) ตก · A10 ผ่าน · มี truth_note",
   "G10" not in t11["hard_ok_codes"] and "A10" not in t11["hard_ok_codes"] and "D10" in t11["hard_ok_codes"]
   and "ไม่ระบุสภาวะ" in t11["truth_note"], (t11["hard_ok_codes"], t11["truth_note"]))
ok("B11 null: hard_ok_by_stated ทุกคีย์ที่มี temp ต้องผ่านทั้งสองสภาวะด้วย (G10 ไม่อยู่)",
   all("G10" not in v for k, v in t11["hard_ok_by_stated"].items() if "temp" in k))
ok("by_stated: ยังไม่พูดสภาวะ (เป้าหมายบอกแห้ง) → ผ่านสภาวะใดก็ได้", "G10" in t8["hard_ok_by_stated"]["pitch+temp"]
   and t8["hard_ok_by_stated"]["pitch+temp+wet"] == t8["hard_ok_codes"])
ok("pitch_mm = null → ไม่กรองพิทช์ + truth_note", "C10" in RT.truth_for_goal(TOY, goal(pitch_mm=None))["hard_ok_codes"]
   and "ไม่รู้พิทช์" in RT.truth_for_goal(TOY, goal(pitch_mm=None))["truth_note"])
ok("--pitch-tol 0.05: ห่าง 0.5 ไม่ผ่านแล้ว", "B10" not in RT.truth_for_goal(TOY, goal(), tol=0.05)["hard_ok_codes"])

print("\nกลุ่ม 2 · ฐานจริง modutech_v30_3.json (คำนวณด้วยมือ)")
CAT = RT.load_catalog()


def real(**kw):
    return RT.truth_for_goal(CAT, goal(**kw))


# 1) แห้ง ผ่านหลายรุ่น — EC508 C หน้า 231 · ec508-c--pom-pom แห้ง −40..93 °C ครอบ 35 · พิทช์ 50.8
#    นับมือ: ทุกรุ่นพิทช์ 50.8 มี variant แห้งครอบ 35 → 24 รุ่น (EC508 GT แห้ง 5..60 ก็ผ่าน)
r1 = real(application="ถุงปุ๋ย", pitch_mm=50.8, temp_c=35, wet_or_dry="dry")
ok("R1 แห้ง 50.8 · 35 °C → 24 รุ่น มี EC508 C และ EC508 GT", len(r1["hard_ok_codes"]) == 24
   and {"EC508 C", "EC508 GT"} <= set(r1["hard_ok_codes"]), len(r1["hard_ok_codes"]))
# 2) เปียก not_recommended — SM254 FG50% หน้า 179 · sm254-fg50pct--pa6-pa6 แห้ง −35..116 · เปียก ไม่มีค่า · not_recommended
ok("R2 SM254 FG50% · 25.4 · 20 °C: แห้งผ่าน · เปียกไม่ผ่าน (not_recommended)",
   "SM254 FG50%" in real(pitch_mm=25.4, temp_c=20, wet_or_dry="dry")["hard_ok_codes"]
   and "SM254 FG50%" not in real(pitch_mm=25.4, temp_c=20, wet_or_dry="wet")["hard_ok_codes"])
# 3) เย็นจัด วัสดุตก — 25.4 · −38 °C ไม่รู้สภาวะ: HD254 C หน้า 149 มีแต่ hd254-c--pom-pa (−35) → ตก
#    EC254 C หน้า 131 · ec254-c--pom-pom แห้ง/เปียก −40 → ผ่าน · รวม 14 รุ่น (V04)
r3 = real(application="อาหารแช่แข็ง", pitch_mm=25.4, temp_c=-38, wet_or_dry=None)
ok("R3 25.4 · −38 °C ไม่รู้สภาวะ → HD254 C ตก (PA −35) · EC254 C ผ่าน (POM-POM −40) · 14 รุ่น",
   "HD254 C" not in r3["hard_ok_codes"] and "EC254 C" in r3["hard_ok_codes"] and len(r3["hard_ok_codes"]) == 14,
   len(r3["hard_ok_codes"]))
# 4) ค่าเปียก = แห้ง — HC152 C หน้า 87 · hc152-c--pe-pe แห้ง/เปียก −70..65 → ผลเหมือนกันทั้งสองสภาวะ
ok("R4 HC152 C · 15.24 · −65 °C: ผ่านทั้งเปียก แห้ง และไม่รู้สภาวะ (PE −70 ทั้งสอง)",
   all("HC152 C" in real(pitch_mm=15.24, temp_c=-65, wet_or_dry=c)["hard_ok_codes"] for c in ("wet", "dry", None)))
# 5) จับชื่องานไม่ได้ — "ถุงปุ๋ย" ไม่มีใน application_vocabulary 73 คำ → accept = hard_ok
ok("R5 ถุงปุ๋ย → จับชื่องานไม่ได้ · accept = hard_ok 24 รุ่น", r1["truth_note"] == "จับชื่องานไม่ได้"
   and r1["accept_codes"] == r1["hard_ok_codes"])
# 6) ไม่มีรุ่นผ่าน — สูงสุดทั้งฐาน 210 °C (MD254 GAP48%-EHT หน้า 169 · md254-gap48pct-eht--eht-ss · พิทช์ 25.7)
ok("R6 240 °C แห้ง → ไม่มีรุ่นผ่าน · 210 °C ที่ 25.4 (±0.5) → MD254 GAP48%-EHT",
   real(pitch_mm=25.4, temp_c=240)["hard_ok_codes"] == []
   and real(pitch_mm=25.4, temp_c=210)["hard_ok_codes"] == ["MD254 GAP48%-EHT"])

print("\nกลุ่ม 3 · โครงสร้าง")
src = open(os.path.join(HERE, "redteam_truth.py"), encoding="utf-8").read()
mods = set()
for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.Import):
        mods |= {a.name.split(".")[0] for a in n.names}
    elif isinstance(n, ast.ImportFrom):
        mods.add((n.module or "").split(".")[0])
ok("B12 ไม่ import brands · core · need_flow · dialogue_state · simulate_customers",
   not (mods & {"brands", "core", "need_flow", "dialogue_state", "simulate_customers"}), mods)
ok("B16 ตารางคำอยู่ในไฟล์นี้ (ไม่เปิดไฟล์อื่นนอกจากแคตตาล็อกและเป้าหมาย)",
   "INDUSTRY_WORDS" in src and "STATION_WORDS" in src and src.count("open(") == 3)
for name in ("redteam_goals.json", "redteam_goals_v2.json"):
    gp = os.path.join(HERE, name)
    if not os.path.exists(gp):
        ok(f"B13–B15 {name}", False, "ไม่มีไฟล์")
        continue
    sha0 = hashlib.sha256(open(gp, "rb").read()).hexdigest()
    with tempfile.TemporaryDirectory() as d:
        cp = os.path.join(d, name)
        open(cp, "wb").write(open(gp, "rb").read())
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            RT.main([cp])
            a = open(RT.out_path(cp), "rb").read()
            RT.main([cp])
            b = open(RT.out_path(cp), "rb").read()
        sha_cp = hashlib.sha256(open(cp, "rb").read()).hexdigest()
    ok(f"B13 {name}: ไฟล์เป้าหมายไม่ถูกแก้", sha0 == sha_cp == hashlib.sha256(open(gp, "rb").read()).hexdigest())
    ok(f"B15 {name}: รันสองครั้งได้ไบต์เดิม", a == b)
    src_doc, out_doc = json.load(open(gp, encoding="utf-8")), json.loads(a)
    added = {"accept_codes", "hard_ok_codes", "hard_ok_by_stated", "truth_note"}
    same = len(src_doc["goals"]) == len(out_doc["goals"]) and all(
        {k: v for k, v in o.items() if k not in added} == s for s, o in zip(src_doc["goals"], out_doc["goals"]))
    ok(f"B14 {name}: เป้าหมายครบ · ฟิลด์เดิมเท่าเดิม · เพิ่มแค่ 4 คีย์เฉลย", same)
    mt = [g for g in out_doc["goals"] if g.get("brand") != "movex"]
    ok(f"B9b {name}: Modutech ทุกข้อมีคีย์ accept_codes · จับงานไม่ได้ + hard_ok ไม่ว่าง → accept ไม่ว่าง "
       "(ไม่มีคีย์ = Judge กลับไปใช้ need_flow ของบอท)",
       all("accept_codes" in g for g in mt)
       and all(g["accept_codes"] for g in mt if g["truth_note"].startswith("จับชื่องานไม่ได้") and g["hard_ok_codes"]))

print("\nblind_review.py · สำเนาซ่อนชื่อระบบ")
import csv  # noqa: E402
import blind_review as BR  # noqa: E402
with tempfile.TemporaryDirectory() as d:
    files = []
    for name in ("bot", "agent"):
        p = os.path.join(d, f"sim_{name}.json")
        json.dump({"module": name, "results": [
            {"goal": "V01", "run": k, "tactic": "แผน", "transcript": [
                {"role": "customer", "text": "สวัสดี"}, {"role": "bot", "text": f"ตอบจาก{name}ลับ"}]}
            for k in (1, 2)]}, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        files.append(p)
    raw = [open(f, "rb").read() for f in files]
    out = os.path.join(d, "rv")
    with contextlib.redirect_stdout(io.StringIO()):
        BR.make(files, None, out)
    txt = open(os.path.join(out, "review.txt"), encoding="utf-8").read()
    ok("review.txt ไม่มีชื่อไฟล์/module · ใช้คำว่า 'ระบบ'", "sim_bot" not in txt and "sim_agent" not in txt
       and "module" not in txt and "🤖 ระบบ" in txt and txt.count("=== ") == 4)
    rows = list(csv.DictReader(open(os.path.join(out, "sheet.csv"), encoding="utf-8-sig")))
    ok("sheet.csv มี 4 แถว ช่อง tactic_checked ว่าง", len(rows) == 4 and all(r["tactic_checked"] == "" for r in rows))
    for i, r in enumerate(rows):
        r["tactic_checked"] = "true" if i % 2 == 0 else "false"
    with open(os.path.join(out, "sheet.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BR.SHEET_COLS)
        w.writeheader()
        w.writerows(rows)
    with contextlib.redirect_stdout(io.StringIO()):
        written = BR.merge(out)
    vals = [r["tactic_checked"] for p in written for r in json.load(open(p, encoding="utf-8"))["results"]]
    ok("merge: ได้ _checked.json สองไฟล์ ค่า true/false ครบ 4 บท · ไฟล์ดิบไม่ถูกแก้",
       len(written) == 2 and sorted(vals) == [False, False, True, True]
       and [open(f, "rb").read() for f in files] == raw)

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
