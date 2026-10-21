#!/usr/bin/env python3
"""modutech_v30_2.json → modutech_v30_3.json — ใช้ "พนักงานฝ่ายขาย" แทน "ฝ่ายเทคนิค" (11 ต.ค. 2026)

ทำไม
  ผลรอบ 4 (RESULTS_phase2_answer_review.md): คำตอบมี "ฝ่ายเทคนิค" 22 จุด ปนกับ "ฝ่ายขาย" บางข้อในประโยคเดียว
  ("ยืนยันกับพนักงานฝ่ายขายหรือฝ่ายเทคนิค") ทั้งที่ช่องทางติดต่อที่บอตให้ลูกค้ามีแต่ฝ่ายขาย
  เจ้าของตัดสิน 11 ต.ค.: ให้ใช้ "พนักงานฝ่ายขาย" ทุกจุด

ทำอะไร
  ไล่ทุกสตริงในไฟล์ ที่มีคำว่า ฝ่ายเทคนิค
    "ยืนยันกับฝ่ายเทคนิคก่อนเสนอ" → "ยืนยันกับพนักงานฝ่ายขายก่อนใช้งานจริง"  (ก่อนเสนอ เป็นคำของฝ่ายขาย)
    "ฝ่ายเทคนิค" ที่เหลือ          → "พนักงานฝ่ายขาย"
  ของเดิมทุกจุดเก็บใน _text_patch_v30_3 ที่รากของไฟล์ (path · เดิม · ใหม่)
  ไม่เก็บเป็นฟิลด์คู่ข้าง ๆ เพราะบาง dict (variant) ถูกคัดลอกเข้า Context ทั้งก้อน — ข้อความเดิมจะหลุดไปถึง LLM

ไม่แตะ: ตัวเลข · สถานะ · ฟิลด์อื่น · จำนวนนับ · ไฟล์ต้นทาง

รัน: python patch_v30_3.py [modutech_v30_2.json] [modutech_v30_3.json] [--changelog CHANGELOG_v30_3.md]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys

OLD = "ฝ่ายเทคนิค"
SUBS = [("ยืนยันกับฝ่ายเทคนิคก่อนเสนอ", "ยืนยันกับพนักงานฝ่ายขายก่อนใช้งานจริง"),
        ("ฝ่ายเทคนิค", "พนักงานฝ่ายขาย")]
LOG_KEY = "_text_patch_v30_3"


def fingerprint(o) -> str:
    return hashlib.sha256(json.dumps(o, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def fix(s: str) -> str:
    for a, b in SUBS:
        s = s.replace(a, b)
    return s


def walk(o, path, log):
    """แก้ในที่ คืน log ของจุดที่แก้"""
    if isinstance(o, dict):
        for k in list(o):
            o[k] = walk(o[k], f"{path}/{k}", log)
    elif isinstance(o, list):
        for i in range(len(o)):
            o[i] = walk(o[i], f"{path}/{i}", log)
    elif isinstance(o, str) and OLD in o:
        new = fix(o)
        log.append({"path": path, "old": o, "new": new})
        return new
    return o


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="modutech_v30_2.json")
    ap.add_argument("dst", nargs="?", default="modutech_v30_3.json")
    ap.add_argument("--changelog")
    a = ap.parse_args()
    if a.src == a.dst:
        raise SystemExit("ห้ามเขียนทับไฟล์ต้นทาง")

    data = json.load(open(a.src, encoding="utf-8"))
    if LOG_KEY in data:
        raise SystemExit(f"มี {LOG_KEY} อยู่แล้ว — ไฟล์นี้ถูกแพตช์แล้ว หยุด")
    shadow = copy.deepcopy(data)
    log: list[dict] = []
    walk(data, "", log)

    print(f"1) แก้ {len(log)} สตริง")
    left = json.dumps(data, ensure_ascii=False).count(OLD)
    if left:
        raise SystemExit(f"❌ ยังเหลือ '{OLD}' {left} จุด")
    if any("ก่อนเสนอ" in x["new"] and "ก่อนเสนอ" not in x["old"] for x in log):
        raise SystemExit("❌ เกิดคำว่า ก่อนเสนอ ใหม่")
    print(f"   ✅ ไม่เหลือ '{OLD}'")

    print("2) เทียบกับ shadow copy — ย้อนทุกจุดใน log แล้วต้องได้ไฟล์เดิมทุกไบต์")
    back = copy.deepcopy(data)
    for x in log:
        keys = x["path"].split("/")[1:]
        o = back
        for k in keys[:-1]:
            o = o[int(k)] if isinstance(o, list) else o[k]
        last = keys[-1]
        if isinstance(o, list):
            o[int(last)] = x["old"]
        else:
            o[last] = x["old"]
    if fingerprint(back) != fingerprint(shadow):
        raise SystemExit("❌ มีอย่างอื่นเปลี่ยน — ไม่เขียนไฟล์")
    print("   ✅ นอกจากจุดใน log ไม่มีอะไรเปลี่ยน")

    prods = data["products"]
    n_pair = sum(len(p.get("industries") or []) for p in prods)
    n_app = sum(len(x.get("applications") or []) for p in prods for x in p.get("industries") or [])
    if (len(prods), n_pair, n_app) != (68, 211, 651):
        raise SystemExit("❌ จำนวนนับเปลี่ยน")
    print(f"3) จำนวนนับ {len(prods)} · {n_pair} · {n_app}")

    data[LOG_KEY] = log
    json.dump(data, open(a.dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nเขียน {a.dst} แล้ว · {a.src} ไม่ถูกแตะต้อง")

    if a.changelog:
        groups: dict[tuple, list] = {}
        for x in log:
            field = [k for k in x["path"].split("/") if not k.isdigit()][-1]
            groups.setdefault((field, x["old"], x["new"]), []).append(x["path"])
        out = [f"# CHANGELOG {a.dst}", "",
               f"สร้างจาก `{a.src}` ด้วย `patch_v30_3.py` · แทน \"ฝ่ายเทคนิค\" ด้วย \"พนักงานฝ่ายขาย\" {len(log)} สตริง",
               f"(\"ยืนยันกับฝ่ายเทคนิคก่อนเสนอ\" → \"ยืนยันกับพนักงานฝ่ายขายก่อนใช้งานจริง\") · ของเดิมเก็บใน `{LOG_KEY}`", "",
               "เหตุผล: เจ้าของตัดสิน 11 ต.ค. ให้ทุกจุดที่ให้ลูกค้ายืนยันใช้พนักงานฝ่ายขาย (ช่องทางติดต่อที่บอตให้มีแต่ฝ่ายขาย)", "",
               "ฟิลด์ที่ไปถึงคำตอบลูกค้า: `width_note_th` · `temperature_unconfirmed_th` · "
               "`forbidden_th` อยู่ในส่วนกฎของ prompt · `temperature_note_th` และ `answering_policy` ไม่ได้ส่งให้ LLM", "",
               f"## ก่อน → หลัง ({len(groups)} แบบข้อความ)", ""]
        for i, ((field, old, new), paths) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], -len(kv[1]))), 1):
            codes = sorted({data["products"][int(p.split('/')[2])]["belt_code"] for p in paths
                            if p.startswith("/products/")})
            out += [f"### {i}. `{field}` · {len(paths)} จุด" + (f" · {', '.join(codes)}" if codes else ""), "",
                    f"- ก่อน: {old}", f"- หลัง: {new}", ""]
        open(a.changelog, "w", encoding="utf-8").write("\n".join(out))
        print(f"เขียน {a.changelog} แล้ว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
