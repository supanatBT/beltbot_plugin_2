"""
image_test_log.py — แปลง log ของ backend (บรรทัด IMGLOG) เป็นตาราง CSV สำหรับทดสอบรูปผ่านหน้าเว็บ (27 ต.ค.)

ขั้นตอน
  1. เปิด backend โดยตั้ง IMAGE_TEST_LOG=1 → บอทเขียน image_test.log (UTF-8) ในโฟลเดอร์ที่รันเอง
  2. ส่งรูปผ่านหน้าเว็บตามลำดับในรายการรูปของคุณ
  3. python image_test_log.py image_test.log -o image_test.csv
  4. เปิด CSV ใน Excel เติมคอลัมน์ ไฟล์ · กลุ่ม · บริบท · ตัดสิน · หมายเหตุ

ไม่เขียนทับไฟล์ที่มีอยู่ (อาจเป็นตารางที่เติมผลไว้แล้ว) — ใส่ --force ถ้าตั้งใจ
อ่านได้ทั้ง UTF-8 และ UTF-16 (PowerShell 5 Tee-Object / Out-File เขียน UTF-16) · CSV เขียนเป็น UTF-8 มี BOM ให้ Excel อ่านไทยได้

    python image_test_log.py image_test.log -o image_test.csv
    python image_test_log.py image_test.log --summary          # สรุปอย่างเดียว ไม่เขียนไฟล์
อ่าน log ที่คัดลอกจากหน้าต่าง backend ได้ด้วย (หาบรรทัดที่มี "IMGLOG {")
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter

FILL = ["ไฟล์", "กลุ่ม", "บริบท", "ตัดสิน", "หมายเหตุ"]   # ให้ผู้ทดสอบเติม
VERDICTS = "ถูกแบรนด์ · ถาม · ผิดแบรนด์ · ปฏิเสธของจริง · รับของปลอม"


def read_text(path: str) -> str:
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace")
    # UTF-16 ไม่มี BOM (มี \x00 สลับ) — เจอได้เมื่อ log ถูกต่อหลายรอบ
    if raw[1:200:2].count(b"\x00") > 50:
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def parse(text: str) -> tuple[list[dict], int]:
    rows, bad = [], 0
    for line in text.splitlines():
        i = line.find("IMGLOG {")
        if i < 0:
            continue
        try:
            rows.append(json.loads(line[i + len("IMGLOG "):]))
        except json.JSONDecodeError:
            bad += 1                                    # บรรทัดถูกตัด/ปนกับบรรทัดอื่น — นับไว้ ไม่ข้ามเงียบ
    return rows, bad


def flatten(rows: list[dict]) -> tuple[list[str], list[dict]]:
    brands = sorted({b for r in rows for b in (r.get("scores") or {})})
    gates = sorted({b for r in rows for b in (r.get("gates") or {})})
    gate_keys = sorted({k for r in rows for g in (r.get("gates") or {}).values() for k in g})
    cols = ["ลำดับ", "turn", "ขนาดรูป", "ข้อความที่พิมพ์"]
    for b in brands:
        cols += [f"{b}_conf", f"{b}_รับ", f"{b}_dominant", f"{b}_group"]
    for b in gates:
        cols += [f"ประตู_{b}_{k}" for k in gate_keys]
    cols += ["policy", "action", "brand", "เหตุผล", "ตัวกัน", "คำตอบ (ต้น)", "เวลา"] + FILL
    out = []
    for n, r in enumerate(rows, 1):
        d = {"ลำดับ": n, "turn": r.get("turn", ""), "ขนาดรูป": "×".join(map(str, r.get("size") or [])),
             "ข้อความที่พิมพ์": r.get("text", ""), "policy": r.get("policy", ""), "action": r.get("action", ""),
             "brand": r.get("brand") or "", "เหตุผล": r.get("reason", ""), "ตัวกัน": r.get("guard", ""),
             "คำตอบ (ต้น)": r.get("reply_head", ""), "เวลา": r.get("at", "")}
        for b in brands:
            sc = (r.get("scores") or {}).get(b) or {}
            d.update({f"{b}_conf": sc.get("conf", ""), f"{b}_รับ": int(bool(sc.get("accepted"))) if sc else "",
                      f"{b}_dominant": int(bool(sc.get("dominant"))) if sc else "", f"{b}_group": sc.get("group", "")})
        for b in gates:
            g = (r.get("gates") or {}).get(b) or {}
            for k in gate_keys:
                v = g.get(k, "")
                d[f"ประตู_{b}_{k}"] = int(v) if isinstance(v, bool) else v
        for k in FILL:
            d[k] = ""
        out.append(d)
    return cols, out


def summary(rows: list[dict]) -> str:
    lines = [f"เทิร์นที่มีรูป {len(rows)}"]
    lines.append("policy:  " + " · ".join(f"{k} {v}" for k, v in Counter(r.get("policy") for r in rows).most_common()))
    lines.append("action:  " + " · ".join(f"{k} {v}" for k, v in Counter(r.get("action") for r in rows).most_common()))
    lines.append("แบรนด์:  " + " · ".join(f"{k or '-'} {v}" for k, v in Counter(r.get("brand") for r in rows).most_common()))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IMGLOG → CSV")
    ap.add_argument("logs", nargs="+", help="ไฟล์ log ของ backend (หลายไฟล์ได้ เรียงตามที่ใส่)")
    ap.add_argument("-o", "--out", default="image_test.csv")
    ap.add_argument("--force", action="store_true", help="เขียนทับไฟล์ CSV ที่มีอยู่")
    ap.add_argument("--summary", action="store_true", help="สรุปอย่างเดียว ไม่เขียนไฟล์")
    a = ap.parse_args(argv)

    rows, bad = [], 0
    for p in a.logs:
        r, b = parse(read_text(p))
        rows += r
        bad += b
    if not rows:
        print("ไม่พบบรรทัด IMGLOG — backend เปิดด้วย IMAGE_TEST_LOG=1 หรือยัง และ log ถูกเก็บลงไฟล์ไหม", file=sys.stderr)
        return 1
    print(summary(rows))
    if bad:
        print(f"⚠ อ่านไม่ได้ {bad} บรรทัด (ถูกตัดหรือปนกับบรรทัดอื่น) — ตรวจ log ช่วงนั้นด้วยตา")
    if a.summary:
        return 0
    if os.path.exists(a.out) and not a.force:
        print(f"มีไฟล์ {a.out} อยู่แล้ว (อาจเติมผลไว้) — ไม่เขียนทับ ใช้ -o ชื่อใหม่ หรือ --force", file=sys.stderr)
        return 2
    cols, out = flatten(rows)
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"เขียน {a.out} · {len(out)} แถว · คอลัมน์ ตัดสิน ใช้: {VERDICTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# ── เปิด backend แบบเก็บ log ทดสอบรูป (PowerShell) ──
#   $env:IMAGE_TEST_LOG="1"; $env:PYTHONUTF8="1"
#   .\run_app.ps1 -Python $py          # หน้าต่างลูกได้ค่า env นี้ไปด้วย
