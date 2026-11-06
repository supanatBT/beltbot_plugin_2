"""
run_image_read_eval.py — วัดตัวอ่านรูป (core/image_interpreter + brands/modutech/image_read) กับรูปจริง · 6 พ.ย.

ไม่ผ่านบอททั้งตัว — อ่านรูปทีละใบ แล้วคัดรุ่นด้วยโค้ดเหมือนในเทิร์นจริง จึงไม่ต้องโหลด ViT/SigLIP/Qdrant
ใช้ Gemini จริง (GEMINI_API_KEY · GEMINI_MODEL · GEMINI_THINKING จาก .env แบบเดียวกับ assistant.py)

    python run_image_read_eval.py --list รูป.csv [--out ผล.csv] [--limit 20] [--runs 3] [--by belt_code,view,angle]

รูป.csv คอลัมน์: path (จำเป็น) · belt_code (รุ่นจริง ถ้ารู้) · surface (ผิวจริงตามชื่อใน vocabulary ถ้ารู้)
          คอลัมน์อื่น (view · angle · card ...) ติดไปในผลรายรูป และใช้แยกผลด้วย --by ได้
--runs    อ่านรูปเดิมซ้ำหลายรอบ (LLM ตอบไม่เหมือนเดิมทุกครั้ง) · ผลรวมนับทุกรอบ + บอกว่ากี่รูปผ่านครบทุกรอบ
ช่วงความเชื่อมั่น Wilson 95% ต่อท้ายทุกสัดส่วน · ceiling = รายชื่อที่ได้ถ้าอ่านผิวถูกหมด (ไม่เรียก LLM)

ตัวชี้วัด (พิมพ์ท้ายไฟล์ · ผลรายรูปลง --out)
    usable          อ่านแล้วใช้กรองได้ (เป็นสินค้า · มั่นใจไม่ต่ำ · มีผิวหรือความทึบ)
    keeps_true      รุ่นจริงยังอยู่ในรายชื่อที่คัด — ต้องใกล้ 100% (ต่ำ = กรองรุ่นถูกทิ้ง อันตรายกว่าไม่กรอง)
    surface_ok      ผิวที่อ่าน (รวมผิวสำรอง) ตรงกับผิวจริง
    list_size       จำนวนรุ่นที่เหลือ (มัธยฐาน) เทียบทั้งฐาน — ยิ่งน้อยยิ่งช่วยถามน้อยลง
    rank_true       ลำดับของรุ่นจริงในรายชื่อ (เมื่อมีพิทช์จากสเกล)
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def load_env(path=os.path.join(ROOT, ".env")):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def make_complete():
    from core.llm import DEFAULT_TIMEOUT_S, GeminiClient, GenAIClient, parse_thinking
    model = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()   # ค่าเดียวกับ assistant.py
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("ไม่มี GEMINI_API_KEY (.env)")
    timeout = float(os.getenv("GEMINI_TIMEOUT_S") or DEFAULT_TIMEOUT_S) or None
    thinking = parse_thinking(os.getenv("GEMINI_THINKING"))
    if thinking:
        from google import genai as genai_new
        return GenAIClient(genai_new, model, key, thinking, timeout_s=timeout).complete, model
    import google.generativeai as genai
    genai.configure(api_key=key)
    return GeminiClient(genai, model, timeout_s=timeout).complete, model


def wilson(k, n, z=1.96):
    """ช่วงความเชื่อมั่น 95% ของสัดส่วน k/n (Wilson) — ใช้ได้แม้ k = n"""
    if not n:
        return ""
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return f"[{100 * max(0, c - h):.0f}–{100 * min(1, c + h):.0f}%]"


def pct(k, n):
    return f"{k}/{n} ({100 * k / n:.0f}%) {wilson(k, n)}" if n else "-"


def summarize(label, ok, total, short=False):
    used = [r for r in ok if r["usable"]]
    kt = [r for r in used if r["keeps_true"] != ""]
    so = [r for r in ok if r["surface_ok"] != ""]
    med = statistics.median(r["list_size"] for r in used) if used else "-"
    if short:
        print(f"  {label:<28} n={len(ok):<4} usable {pct(len(used), len(ok)):<22} keeps_true "
              f"{pct(sum(r['keeps_true'] for r in kt), len(kt)):<22} surface_ok {pct(sum(r['surface_ok'] for r in so), len(so)):<22} list {med}")
        return
    print("usable      ", pct(len(used), len(ok)))
    print("keeps_true  ", pct(sum(r["keeps_true"] for r in kt), len(kt)), "(เฉพาะรูปที่ใช้กรอง)")
    print("surface_ok  ", pct(sum(r["surface_ok"] for r in so), len(so)))
    if used:
        print("list_size   ", f"มัธยฐาน {med} จาก {total} รุ่น")
    rk = [r["rank_true"] for r in used if r["rank_true"] != ""]
    if rk:
        print("rank_true   ", f"มัธยฐาน {statistics.median(rk)}")


def ceiling(rows, cat, search, spec, total):
    """รายชื่อที่ตัวคัดให้ถ้าตัวอ่านอ่านผิวถูกทุกรูป (ไม่มีพิทช์) — เพดานที่ตัวอ่านดีขึ้นแค่ไหนก็ไม่เกินนี้"""
    import json
    from brands.modutech.image_read import CLOSED_SURFACES
    from core.image_interpreter import parse_reading
    from brands.modutech.image_read import image_match
    seen = {}
    for row in rows:
        code, surf = (row.get("belt_code") or "").strip(), (row.get("surface") or "").strip()
        if not code or not surf or code in seen:
            continue
        d = {"is_product": "yes", "surface": surf, "confidence": "high",
             "openness": "closed" if surf in CLOSED_SURFACES else "open"}
        m, _ = image_match(parse_reading(json.dumps(d), spec), search, cat, spec)
        codes = m["belt_codes_complete"] if m else []
        seen[code] = (surf, len(codes), code in codes)
    if seen:
        print("\nceiling (อ่านผิวถูก 100%):")
        for code, (surf, n, keep) in seen.items():
            print(f"  {code:<14} {surf:<22} เหลือ {n}/{total} รุ่น · มีรุ่นจริง={int(keep)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True)
    ap.add_argument("--out", default="image_read_eval.csv")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--by", default="belt_code", help="คอลัมน์ที่ใช้แยกผล คั่นด้วย , (เช่น belt_code,view,angle)")
    a = ap.parse_args()

    load_env()
    from PIL import Image, ImageOps

    from brands.modutech.gates import Catalogue
    from brands.modutech.image_read import image_match, image_spec
    from brands.modutech.router import CatalogueSearch
    from core.image_interpreter import ImageInterpreter

    cat = Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
    search = CatalogueSearch(cat)
    spec = image_spec(cat)
    complete, model = make_complete()
    reader = ImageInterpreter(complete, log=print)
    total = len(cat.products)

    rows = list(csv.DictReader(open(a.list, encoding="utf-8-sig")))
    if a.limit:
        rows = rows[:a.limit]
    out, t0 = [], time.time()
    extra = [k for k in (rows[0] if rows else {}) if k not in ("path", "belt_code", "surface")]
    jobs = [(run, row) for run in range(1, a.runs + 1) for row in rows]
    for i, (run, row) in enumerate(jobs, 1):
        path = row["path"] if os.path.isabs(row["path"]) else os.path.join(os.path.dirname(os.path.abspath(a.list)), row["path"])
        truth, true_surface = (row.get("belt_code") or "").strip(), (row.get("surface") or "").strip()
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception as e:                                   # noqa: BLE001
            out.append({"run": run, "path": row["path"], "error": f"เปิดรูปไม่ได้: {e}"})
            continue
        r = reader.read(img, "", spec)
        m, why = image_match(r, search, cat, spec)
        codes = m["belt_codes_complete"] if m else []
        rec = {
            "run": run, "path": row["path"], "belt_code": truth, "surface_true": true_surface,
            "is_product": r.is_product if r else "", "confidence": r.confidence if r else "",
            "surface_read": "|".join(r.surfaces()) if r else "", "openness": (r.openness or "") if r else "",
            "pitch_mm": (r.pitch_mm or "") if r else "", "usable": int(m is not None),
            "list_size": len(codes) if m else total,
            "keeps_true": (int(truth in codes) if m else 1) if truth else "",
            "rank_true": (codes.index(truth) + 1 if truth in codes else "") if (m and truth) else "",
            "surface_ok": (int(true_surface in r.surfaces()) if r else 0) if true_surface else "",
            "ms": r.ms if r else "", "why": why, "note": r.note if r else "",
            **{k: row.get(k, "") for k in extra},
        }
        out.append(rec)
        print(f"[{i}/{len(jobs)}] {row['path']}: {rec['surface_read'] or '-'} → {rec['list_size']} รุ่น"
              + (f" · มีรุ่นจริง={rec['keeps_true']}" if truth else ""))

    keys = sorted({k for r in out for k in r}, key=lambda k: list(out[0]).index(k) if out and k in out[0] else 99)
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)

    ok = [r for r in out if "error" not in r]
    print(f"\nโมเดล {model} · {len(rows)} รูป × {a.runs} รอบ · {time.time() - t0:.0f} วินาที · เรียกพัง {reader.failures}")
    summarize("ทั้งหมด", ok, total)
    for col in [c.strip() for c in a.by.split(",") if c.strip()]:
        groups = {}
        for r in ok:
            groups.setdefault(str(r.get(col, "")), []).append(r)
        print(f"\n── แยกตาม {col}")
        for g in sorted(groups):
            summarize(f"{col}={g}", groups[g], total, short=True)
    if a.runs > 1:
        by_img = {}
        for r in ok:
            by_img.setdefault(r["path"], []).append(r)
        stable = sum(all(x["usable"] and x["keeps_true"] in (1, "") for x in v) for v in by_img.values())
        print(f"\nผ่าน (ใช้กรองได้ + มีรุ่นจริง) ครบทุก {a.runs} รอบ: {stable}/{len(by_img)} รูป {wilson(stable, len(by_img))}")
    ceiling(rows, cat, search, spec, total)
    print(f"ผลรายรูป → {a.out}")


if __name__ == "__main__":
    main()
