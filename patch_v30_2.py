#!/usr/bin/env python3
"""modutech_v30_1.json → modutech_v30_2.json — แก้ถ้อยคำ wet_note_th อย่างเดียว (11 ต.ค. 2026)

ปัญหาใน v30 / v30_1 (ดู RESULTS_phase2_answer_review.md · เรื่อง "เกรด PA")
  temperature_effective.wet_note_th ทั้ง 75 ข้อความสร้างจากแม่แบบเดียว:
      "ไม่มีข้อมูลสภาวะเปียกของเกรด PA ค่านี้คำนวณจากชั้นที่มีข้อมูลเท่านั้น ต้องยืนยันก่อนเสนอ"
  1. เรียก PA ว่า "เกรด" ทั้งที่ PA เป็นวัสดุพิน — ลูกค้าเข้าใจว่าสายพานเกรด PA
  2. ไม่บอกว่าชั้นไหน (สายพาน/พิน) ขาดข้อมูล และตัวเลขแต่ละตัวมาจากไหน
  3. "ชั้นที่มีข้อมูล" เป็นศัพท์ภายใน · "ก่อนเสนอ" เป็นคำของฝ่ายขาย ไม่ใช่ของลูกค้า
  4. รุ่นที่สายพานกับพินเป็นวัสดุเดียวกันพิมพ์ซ้ำ "เกรด PA, PA"

สิ่งที่สคริปต์นี้ทำ
  สร้าง wet_note_th ใหม่จาก source_layers ของแต่ละ variant (ไม่ใช่แก้คำทีละตัว)
  - บอกว่าวัสดุชั้นไหนไม่มีค่าเปียก และมีค่าแห้งหรือไม่
  - บอกที่มาของค่าสูงสุดและค่าต่ำสุดของช่วงเปียก โดยไล่หาค่าที่ตรงจากชั้นจริง
    ถ้าหาที่มาไม่เจอ → หยุด ไม่เดา
  - ปิดท้าย "ต้องให้ฝ่ายเทคนิคยืนยันก่อนใช้งานจริง"
  ของเดิมเก็บไว้ใน temperature_effective.wet_note_th_v30 (เก็บของดิบคู่ของที่ซ่อม)

ไม่แตะ: ตัวเลขทุกตัว · wet_status · wet/dry · limiters · temperature.wet_note_th (ฟิลด์อื่น)
         · จำนวนนับ · ไฟล์ต้นทาง (เขียนไฟล์ใหม่เสมอ)

รัน: python patch_v30_2.py [modutech_v30_1.json] [modutech_v30_2.json] [--changelog CHANGELOG_v30_2.md]
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys

LAYER_TH = {"belt_material": "วัสดุสายพาน", "pin_material": "วัสดุพิน"}
FORBIDDEN = ("เกรด", "ก่อนเสนอ", "ชั้นที่มีข้อมูล", "ระบบ", "ห้าม")
CLOSING = "ต้องยืนยันกับพนักงานฝ่ายขายก่อนใช้งานจริง"


def fingerprint(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def c(x: float) -> str:
    return f"{x:g}"


def rng(a) -> str:
    return f"{c(a[0])} ถึง {c(a[1])} °C"


def layers(te: dict) -> list[tuple[str, dict]]:
    L = te["source_layers"]
    return [(k, L[k]) for k in ("belt_material", "pin_material") if L.get(k)]


def missing_phrase(te: dict) -> str:
    """'วัสดุพิน PA (มีแต่ค่าแห้ง -35 ถึง 120 °C)' · รวมเป็นวลีเดียวถ้าสองชั้นเป็นวัสดุเดียวกัน"""
    miss = [(k, l) for k, l in layers(te) if l.get("wet") is None]
    if not miss:
        raise SystemExit("variant partial_data แต่ไม่มีชั้นไหนขาดค่าเปียก — หยุด")

    def dry(l):
        return f"มีแต่ค่าแห้ง {rng(l['dry'])}" if l.get("dry") else "ไม่มีทั้งค่าแห้งและค่าเปียก"

    if len(miss) == 2 and miss[0][1]["code"] == miss[1][1]["code"]:
        l = miss[0][1]
        return f"วัสดุ {l['code']} ซึ่งใช้ทั้งสายพานและพิน ({dry(l)})"
    return " และ".join(f"{LAYER_TH[k]} {l['code']} ({dry(l)})" for k, l in miss)


def origin(te: dict, cond_val: float, idx: int) -> str:
    """ที่มาของค่าขอบเขตช่วงเปียก idx=0 ต่ำสุด · idx=1 สูงสุด — ไล่ตามลำดับที่ gate ใช้คำนวณ"""
    # 1) ค่าเปียกของวัสดุชั้นที่มีข้อมูลเปียก
    for k, l in layers(te):
        if l.get("wet") and abs(l["wet"][idx] - cond_val) < 1e-6:
            return f"ค่าสภาวะเปียกของ{LAYER_TH[k]} {l['code']}"
    # 2) ตารางสเปกของรุ่น (เล่มพิมพ์ช่วงเดียว ไม่แยกเปียก/แห้ง)
    st = te["source_layers"].get("spec_table") or {}
    key = ("min_c", "max_c")[idx]
    if st.get(key) is not None and abs(st[key] - cond_val) < 1e-6:
        return f"ช่วงอุณหภูมิในตารางสเปกของรุ่น (หน้า {st['page']})"
    # 3) ค่าแห้งของวัสดุ (ไม่มีค่าเปียก จึงใช้ค่าแห้งเป็นเพดาน)
    same = len({l["code"] for _, l in layers(te)}) == 1 and len(layers(te)) == 2
    for k, l in layers(te):
        if l.get("dry") and abs(l["dry"][idx] - cond_val) < 1e-6:
            who = f" {l['code']}" if same else f"{LAYER_TH[k]} {l['code']}"   # วัสดุเดียวกันสองชั้น ไม่ต้องระบุชั้น
            return f"ค่าสภาวะแห้งของ{who}"
    raise SystemExit(f"หาที่มาของ {cond_val} ไม่เจอ — หยุด ไม่เดา\n{json.dumps(te, ensure_ascii=False)}")


def new_note(te: dict) -> str:
    st = te["wet_status"]
    if st == "not_recommended":
        bad = [(k, l) for k, l in layers(te) if l.get("wet_status") == "not_recommended"]
        page = bad[0][1]["page"]
        codes = sorted({l["code"] for _, l in bad})
        if len(bad) == 2 and len(codes) == 1:
            who = f"วัสดุ {codes[0]} ซึ่งใช้ทั้งสายพานและพินของรุ่นนี้"
        else:
            who = " และ".join(f"{LAYER_TH[k]} {l['code']}" for k, l in bad)
        return f"แคตตาล็อกหน้า {page} ระบุว่า{who} ไม่แนะนำให้ใช้ในสภาวะเปียก"
    if st != "partial_data":
        raise SystemExit(f"wet_status {st!r} ไม่อยู่ในขอบเขตแพตช์ — หยุด")
    w = te["wet"]
    lo, hi = origin(te, w["min_c"], 0), origin(te, w["max_c"], 1)
    head = f"แคตตาล็อกไม่มีค่าสภาวะเปียกของ{missing_phrase(te)}"
    if lo == hi:
        body = f"ช่วง {c(w['min_c'])} ถึง {c(w['max_c'])} °C ในสภาวะเปียกมาจาก{hi}"
    else:
        body = (f"ค่าสูงสุด {c(w['max_c'])} °C ในสภาวะเปียกมาจาก{hi} "
                f"ส่วนค่าต่ำสุด {c(w['min_c'])} °C มาจาก{lo}")
    return f"{head} {body} {CLOSING}"


def check(note: str, te: dict) -> list[str]:
    errs = [f"มีคำต้องห้าม '{f}'" for f in FORBIDDEN if f in note]
    for _, l in layers(te):
        if l["code"] not in note and l.get("wet") is None:
            errs.append(f"ไม่ได้เอ่ยถึง {l['code']} ที่ขาดค่าเปียก")
    if te.get("wet"):
        for k in ("min_c", "max_c"):
            if not re.search(rf"(?<![\d.-]){re.escape(c(te['wet'][k]))}(?![\d.])", note):
                errs.append(f"ไม่มีตัวเลข {k}={te['wet'][k]}")
    return errs


def scrub(doc: dict) -> dict:
    d = copy.deepcopy(doc)
    for p in d["products"]:
        for v in p["specifications"].get("variants") or []:
            te = v.get("temperature_effective") or {}
            te.pop("wet_note_th", None)
            te.pop("wet_note_th_v30", None)
    return d


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="modutech_v30_1.json")
    ap.add_argument("dst", nargs="?", default="modutech_v30_2.json")
    ap.add_argument("--changelog")
    a = ap.parse_args()
    src, dst, cl = a.src, a.dst, a.changelog
    if src == dst:
        raise SystemExit("ห้ามเขียนทับไฟล์ต้นทาง")

    data = json.load(open(src, encoding="utf-8"))
    shadow = copy.deepcopy(data)

    rows, errs = [], []
    for p in data["products"]:
        for v in p["specifications"].get("variants") or []:
            te = v.get("temperature_effective") or {}
            if "wet_note_th" not in te:
                continue
            if "wet_note_th_v30" in te:
                raise SystemExit(f"{v['variant_id']}: มี wet_note_th_v30 อยู่แล้ว — ไฟล์นี้ถูกแพตช์แล้ว หยุด")
            old = te["wet_note_th"]
            new = new_note(te)
            for e in check(new, te):
                errs.append(f"{v['variant_id']}: {e}")
            te["wet_note_th_v30"] = old
            te["wet_note_th"] = new
            rows.append((p["belt_code"], v["variant_id"], te["wet_status"], old, new))

    print(f"1) สร้าง wet_note_th ใหม่ {len(rows)} ข้อความ")
    if errs:
        raise SystemExit("❌ ตรวจข้อความไม่ผ่าน:\n  " + "\n  ".join(errs))
    print("   ✅ ไม่มี เกรด/ก่อนเสนอ/ชั้นที่มีข้อมูล · ทุกวัสดุที่ขาดค่าเปียกถูกเอ่ยชื่อ · ตัวเลขตรงกับช่วงเปียก")

    print("2) เทียบกับ shadow copy")
    if fingerprint(scrub(shadow)) != fingerprint(scrub(data)):
        raise SystemExit("❌ มีอย่างอื่นเปลี่ยนนอกจาก wet_note_th — ไม่เขียนไฟล์")
    print("   ✅ นอกจาก wet_note_th / wet_note_th_v30 ไม่มีอะไรเปลี่ยน")

    print("3) จำนวนนับ")
    n_pair = sum(len(p.get("industries") or []) for p in data["products"])
    n_app = sum(len(a.get("applications") or []) for p in data["products"] for a in p.get("industries") or [])
    print(f"   สินค้า {len(data['products'])} · คู่ {n_pair} · การใช้งาน {n_app}")
    if (len(data["products"]), n_pair, n_app) != (68, 211, 651):
        raise SystemExit("❌ จำนวนนับเปลี่ยน")

    json.dump(data, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nเขียน {dst} แล้ว · {src} ไม่ถูกแตะต้อง")

    if cl:
        write_changelog(cl, src, dst, rows)
        print(f"เขียน {cl} แล้ว")
    return 0


def write_changelog(path, src, dst, rows):
    groups: dict[tuple, list] = {}
    for code, vid, st, old, new in rows:
        groups.setdefault((old, new), []).append((code, vid))
    out = [f"# CHANGELOG {dst}", "",
           f"สร้างจาก `{src}` ด้วย `patch_v30_2.py` · แก้ `temperature_effective.wet_note_th` อย่างเดียว "
           f"{len(rows)} variant · ของเดิมเก็บใน `wet_note_th_v30`", "",
           "ตัวเลข สถานะ และฟิลด์อื่นทุกตัวเหมือน v30_1 (ตรวจด้วย shadow copy)", "",
           "## ทำไมต้องแก้", "",
           "- ข้อความเดิมเรียกวัสดุพินว่า \"เกรด\" (เช่น \"เกรด PA\") ลูกค้าเข้าใจว่าสายพานเป็นเกรด PA",
           "- ไม่บอกว่าวัสดุชั้นไหนขาดค่าเปียก และตัวเลขแต่ละตัวมาจากไหน",
           "- \"ชั้นที่มีข้อมูล\" เป็นศัพท์ภายใน · \"ก่อนเสนอ\" เป็นคำของฝ่ายขาย",
           "- รุ่นที่สายพานกับพินเป็นวัสดุเดียวกันพิมพ์ซ้ำ \"PA, PA\"", "",
           f"## ก่อน → หลัง ({len(groups)} แบบข้อความ)", ""]
    for i, ((old, new), vs) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        out += [f"### {i}. {len(vs)} variant", "",
                "รุ่น: " + " · ".join(f"{code} (`{vid}`)" for code, vid in vs), "",
                f"- ก่อน: {old}", f"- หลัง: {new}", ""]
    open(path, "w", encoding="utf-8").write("\n".join(out))


if __name__ == "__main__":
    sys.exit(main())
