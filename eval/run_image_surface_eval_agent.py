"""
run_image_surface_eval_agent.py — วัด agent กับรูปจริงที่รู้รุ่น (ชุด Test) · 6 พ.ย. 2026

    python run_image_surface_eval_agent.py --labels <โฟลเดอร์ Modutech>\\labels_test.csv --runs 3 -o ..\\agent_surface_r.json
    python run_image_surface_eval_agent.py --labels ... --text "" --text "สายพานแบบนี้มีรุ่นไหนบ้างครับ" -o ...

labels_test.csv คอลัมน์: path (สัมพัทธ์กับโฟลเดอร์ของไฟล์) · belt_code · surface · (view · angle · card ... ใช้แยกผลด้วย --by)
                   brand (ไม่ใส่ = modutech) · movex / none = รูปกลุ่มควบคุม ไม่มีรุ่นจริงให้คัด

กลุ่มควบคุม (8 พ.ย.) — รูปที่ไม่ใช่สายพาน Modutech ตรงจาก brand_calibration_rows.csv ฝั่ง eval:
    python run_image_surface_eval_agent.py --from-rows <ผล 05>\brand_calibration_rows.csv --brands movex,none \
        --root <โฟลเดอร์รูป Movex> --root <โฟลเดอร์รูปไม่ใช่สายพาน> -o ..\agent_img_control_r1.json
    ต่อรูปบันทึก: เรียก belts_by_surface ไหม (ไม่ควร) · ตอบรายชื่อ Modutech ไหม · แบรนด์ที่ผู้ตรวจอ่านได้
    สรุป: "ตอบเป็น Modutech" = เรียกเครื่องมือผิวจนได้รายชื่อ หรือคำตอบยืนยันว่าเป็น Modutech (ต้องใกล้ 0)
ทุกรูปเป็นบทสนทนาใหม่ · ใช้ค่าตั้งที่ล็อกของ agent (ไม่ตั้งอะไร = r3 + สวิตช์ blind v2 + AGENT_IMAGE_SURFACE เปิด)

ต่อรูปบันทึก
    called        agent เรียก belts_by_surface ไหม (LLM เลือกเอง)
    surface_ok    ผิวที่ agent กรอก (รวมผิวสำรอง) ตรงกับผิวจริง
    keeps_true    รุ่นจริงอยู่ในรายชื่อที่เครื่องมือคืน (คำนวณซ้ำจาก args ที่ agent ส่ง ด้วยโค้ดตัวเดียวกัน)
    list_size     จำนวนรุ่นในรายชื่อ (จาก 68)
    claimed       ผู้ตรวจ (LLM temperature 0) อ่านคำตอบ: ฟันธงรุ่นเดียวไหม · ถ้าฟันธง ถูกไหม
    asks_useful   ถามข้อที่ช่วยคัดต่อ (พิทช์ · รหัสบนสายพาน · งาน/อุตสาหกรรม · ขนาด)
    brand         ถูกแบรนด์ · ถามแบรนด์ · ผิดแบรนด์ · ปฏิเสธ (นิยามเดียวกับ run_image_eval_agent.py)
    seconds · llm_calls · total_tokens · tools
สรุป: สัดส่วน + Wilson 95% · แยกตาม --by · กี่รูปผ่านครบทุกรอบ
"""
from __future__ import annotations
import os as _os, sys as _sys  # รากของ repo: import แพ็กเกจได้ และพาธข้อมูลนับจากราก
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter

from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval.run_image_eval_agent import codes_in, known_codes, outcome  # noqa: E402

JUDGE = """คุณเป็นผู้ตรวจคำตอบของแชทบอทขายสายพาน ลูกค้าส่งรูปมา{text_note}
อ่านคำตอบของบอทแล้วตอบเป็น JSON เท่านั้น:
{{"brand_claimed": "modutech" | "movex" | "other" | "none",
 "asked_back": true | false,
 "rejected_image": true | false,
 "model_claimed": "<รหัสรุ่นเดียวที่บอทยืนยันว่าเป็นรุ่นในรูป>" | null,
 "asks_useful": true | false,
 "reason_th": "เหตุผลสั้น ๆ"}}
- brand_claimed: แบรนด์ที่บอทยืนยันว่าสินค้าในรูปเป็น (เดาพร้อมถามยืนยัน หรือไม่ระบุ = "none")
- asked_back: บอทถามข้อมูลเพิ่มจากลูกค้า
- rejected_image: บอทบอกว่ารูปไม่ใช่สายพาน/ใช้รูปไม่ได้ และไม่ได้ให้ข้อมูลสินค้า
- model_claimed: ใส่รหัสเฉพาะเมื่อบอทยืนยันรุ่นเดียวว่า "คือรุ่นนี้" · แค่ยกตัวอย่าง/ให้รายชื่อหลายรุ่น/ถามยืนยัน = null
- asks_useful: บอทถามอย่างน้อยหนึ่งข้อที่ช่วยคัดรุ่น เช่น ระยะพิทช์ รหัสที่พิมพ์บนสายพาน งานหรืออุตสาหกรรมที่ใช้ ขนาดหรือความกว้าง
คำตอบของบอท:
"""


def wilson(k, n, z=1.96):
    if not n:
        return ""
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return f"[{100 * max(0, c - h):.0f}–{100 * min(1, c + h):.0f}%]"


def pct(k, n):
    return f"{k}/{n} ({100 * k / n:.0f}%) {wilson(k, n)}" if n else "-"


def norm(s):
    return re.sub(r"[\s\-_%]", "", (s or "").upper())


def judge(reply: str, text: str) -> dict:
    """ผู้ตรวจแบบเดียวกับ run_image_eval_agent.py (โมเดลเดียวกัน temperature 0 · JSON) + ช่องฟันธงรุ่น/ถามต่อ"""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    model = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
    note = f" พร้อมข้อความ \"{text}\"" if text else " 1 รูปโดยไม่พิมพ์อะไร"
    err = ""
    for attempt in range(3):
        try:
            r = client.models.generate_content(
                model=model, contents=JUDGE.format(text_note=note) + reply,
                config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"))
            return json.loads(r.text)
        except Exception as e:                               # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
    return {"reason_th": f"judge error {err}"}


def surface_result(args: dict) -> dict:
    """เรียกเครื่องมือซ้ำด้วย args เดิม (โค้ดคัดรุ่นไม่มีสุ่ม) เพื่อให้ได้รายชื่อที่ agent เห็น"""
    from agent import tools_impl as T
    keep = {k: args[k] for k in ("surface", "alternatives", "openness", "pitch_mm", "scale_visible", "confidence") if k in args}
    try:
        return json.loads(T.belts_by_surface(**keep))
    except Exception as e:                                   # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def summarize_control(label, rs, short=False):
    """รูปที่ไม่ใช่สายพาน Modutech — วัดว่าเอเจนต์หลงตอบเป็น Modutech แค่ไหน"""
    n = len(rs)
    called = sum(r["called"] for r in rs)
    listed = sum(bool(r["matched"]) for r in rs)
    as_mod = sum(r["as_modutech"] for r in rs)
    mod_codes = sum(bool(r["modutech_codes"]) for r in rs)
    oc = Counter(r["brand_outcome"] for r in rs)
    if short:
        print(f"  {label:<26} n={n:<4} ตอบเป็น Modutech {pct(as_mod, n):<22} เรียกเครื่องมือผิว {pct(called, n):<22} {dict(oc)}")
        return
    print(f"ตอบเป็น Modutech           {pct(as_mod, n)}   (ต้องใกล้ 0)")
    print(f"เรียก belts_by_surface     {pct(called, n)}   · ได้รายชื่อ {listed}")
    print(f"คำตอบเอ่ยรหัส Modutech     {pct(mod_codes, n)}")
    print(f"แบรนด์ (ผู้ตรวจ)           {dict(oc)}")
    secs = sorted(r["seconds"] for r in rs)
    if secs:
        print(f"เวลา (มัธยฐาน / p90)       {secs[len(secs) // 2]} / {secs[int(len(secs) * 0.9) - 1 if len(secs) > 1 else 0]} วินาที")


def rows_from_calibration(path, roots, brands, split):
    """แถวจาก brand_calibration_rows.csv (05_brand_calibration.py) → แถวแบบ labels · path เป็น path เต็ม"""
    out, missing = [], []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r.get("split") != split or (r.get("brand") or "none") not in brands:
            continue
        fp = next((os.path.join(rt, r["path"]) for rt in roots if os.path.isfile(os.path.join(rt, r["path"]))), None)
        if fp is None:
            missing.append(r["path"])
            continue
        out.append({"path": os.path.abspath(fp), "belt_code": "", "surface": "", "brand": r.get("brand") or "none",
                    "cls": r.get("cls", "")})
    return out, missing


def summarize(label, rs, short=False):
    n = len(rs)
    called = [r for r in rs if r["called"]]
    so = [r for r in called if r["surface_ok"] is not None]
    kt = [r for r in called if r["keeps_true"] is not None]
    claimed = [r for r in rs if r["model_claimed"]]
    sizes = sorted(r["list_size"] for r in called if r["list_size"] is not None)
    med = sizes[len(sizes) // 2] if sizes else "-"
    useful = sum(bool(r["asks_useful"]) for r in rs)
    if short:
        print(f"  {label:<26} n={n:<4} เรียก {pct(len(called), n):<22} ผิวถูก {pct(sum(r['surface_ok'] for r in so), len(so)):<22}"
              f" มีรุ่นจริง {pct(sum(r['keeps_true'] for r in kt), len(kt)):<22} ฟันธง {len(claimed):<3} รายชื่อ {med}")
        return
    print(f"เรียก belts_by_surface     {pct(len(called), n)}")
    print(f"ผิวที่กรอกตรงผิวจริง        {pct(sum(r['surface_ok'] for r in so), len(so))}   (เฉพาะที่เรียก)")
    print(f"รายชื่อมีรุ่นจริง           {pct(sum(r['keeps_true'] for r in kt), len(kt))}   (เฉพาะที่เรียก · ต้องใกล้ 100%)")
    print(f"ขนาดรายชื่อ (มัธยฐาน)      {med} จาก 68")
    print(f"ฟันธงรุ่นเดียว             {pct(len(claimed), n)}   · ฟันธงถูก {sum(r['claim_correct'] for r in claimed)}/{len(claimed)}")
    print(f"ถามข้อที่ช่วยคัดต่อ         {pct(useful, n)}")
    print(f"แบรนด์                    {dict(Counter(r['brand_outcome'] for r in rs))}")
    secs = sorted(r["seconds"] for r in rs)
    if secs:
        print(f"เวลา (มัธยฐาน / p90)       {secs[len(secs) // 2]} / {secs[int(len(secs) * 0.9) - 1 if len(secs) > 1 else 0]} วินาที")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", help="ไฟล์ป้ายรูป (หรือใช้ --from-rows)")
    ap.add_argument("--from-rows", help="brand_calibration_rows.csv — ใช้รูปกลุ่มควบคุมจากการปรับเกณฑ์ประตูรูป")
    ap.add_argument("--root", action="append", default=[], help="โฟลเดอร์ที่ path ใน --from-rows อ้างถึง (ใส่ได้หลายครั้ง)")
    ap.add_argument("--brands", default="movex,none", help="แบรนด์ที่เลือกจาก --from-rows")
    ap.add_argument("--split", default="eval", help="ฝั่งที่เลือกจาก --from-rows (eval = ไม่ได้ใช้ตั้งเกณฑ์)")
    ap.add_argument("--text", action="append", help="ข้อความที่ลูกค้าพิมพ์มากับรูป (ใส่ได้หลายครั้ง · ไม่ใส่ = ส่งรูปอย่างเดียว)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--by", default="belt_code,view")
    ap.add_argument("--no-judge", action="store_true", help="ไม่เรียกผู้ตรวจ (ประหยัด · ไม่มีผลฟันธง/แบรนด์/ถามต่อ)")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    texts = a.text or [""]

    if bool(a.labels) == bool(a.from_rows):
        print("❌ ใส่ --labels หรือ --from-rows อย่างใดอย่างหนึ่ง")
        return 1
    if a.from_rows:
        rows, miss = rows_from_calibration(a.from_rows, a.root, {b.strip() for b in a.brands.split(",")}, a.split)
        print(f"กลุ่มควบคุมจาก {os.path.basename(a.from_rows)}: {len(rows)} รูป {dict(Counter(r['brand'] for r in rows))}"
              + (f" · หาไม่เจอ {len(miss)} เช่น {miss[:3]} (เติม --root)" if miss else ""))
        if not rows:
            return 1
        base = ""
        if "brand" not in a.by:
            a.by = "brand,cls"
    else:
        base = os.path.dirname(os.path.abspath(a.labels))
        rows = list(csv.DictReader(open(a.labels, encoding="utf-8-sig")))
    if a.limit:
        rows = rows[: a.limit]
    missing = [r["path"] for r in rows if not os.path.isfile(os.path.join(base, r["path"]))]
    if missing:
        print(f"❌ หารูปไม่เจอ {len(missing)} รูป เช่น {missing[:3]} — labels ต้องอยู่ในโฟลเดอร์เดียวกับโฟลเดอร์รุ่น")
        return 1

    from agent import assistant as A
    from agent.agent import image_surface_enabled, prompt_version
    if not image_surface_enabled():
        print("⚠️ AGENT_IMAGE_SURFACE=0 — agent ไม่มี belts_by_surface (วัดได้แค่ตัวเทียบ)")
    codes = known_codes()
    extra = [k for k in rows[0] if k not in ("path", "belt_code", "surface", "brand")]
    jobs = [(run, t, r) for run in range(1, a.runs + 1) for t in texts for r in rows]
    print(f"✅ {A.engine.llm.describe()} · {len(rows)} รูป × {len(texts)} ข้อความ × {a.runs} รอบ = {len(jobs)} บทสนทนา")
    results = []
    for i, (run, text, r) in enumerate(jobs, 1):
        img = ImageOps.exif_transpose(Image.open(os.path.join(base, r["path"]))).convert("RGB")
        t0 = time.perf_counter()
        err = None
        try:
            h, *_ = A.chat_interaction(text, img, [], [], "", None, None)
            reply = h[-1]["content"]
        except Exception as e:                               # noqa: BLE001
            reply, err = "", f"{type(e).__name__}: {e}"
        sec = round(time.perf_counter() - t0, 1)
        usage = A.engine.llm.last_usage or {}
        calls = usage.get("tool_calls", []) or []
        sc = [c for c in calls if c.get("tool") == "belts_by_surface"]
        args = sc[-1].get("args", {}) if sc else {}
        res = surface_result(args) if sc else {}
        lst = res.get("belt_codes_complete") if res.get("matched") else None
        read = [args.get("surface") or ""] + [x.strip() for x in (args.get("alternatives") or "").split(",") if x.strip()]
        truth, tsurf = (r.get("belt_code") or "").strip(), (r.get("surface") or "").strip()
        brand = (r.get("brand") or "modutech").strip().lower()
        j = (judge(reply, text) if reply else {}) if not a.no_judge else {}
        claimed = j.get("model_claimed") or None
        mentioned = codes_in(reply, codes)
        rec = {
            "run": run, "text": text, "path": r["path"], "brand": brand, "belt_code": truth, "surface_true": tsurf,
            **{k: r.get(k, "") for k in extra},
            "called": bool(sc), "n_surface_calls": len(sc), "surface_args": args,
            "surface_ok": (tsurf in read) if sc else None,
            "matched": res.get("matched") if sc else None,
            "list_size": len(lst) if lst is not None else None,
            "keeps_true": (truth in lst) if lst is not None else None,
            "rank_true": (lst.index(truth) + 1 if truth in lst else None) if lst else None,
            "model_claimed": claimed, "claim_correct": bool(claimed) and norm(claimed) == norm(truth),
            "asks_useful": j.get("asks_useful"), "brand_outcome": outcome(brand, j) if j else None,
            "codes_mentioned": mentioned, "modutech_codes": [c for c in mentioned if codes.get(c) == "modutech"],
            "as_modutech": bool(res.get("matched")) or j.get("brand_claimed") == "modutech",
            "judge": j,
            "reply": reply, "error": err, "seconds": sec, "tools": [c.get("tool") for c in calls],
            "llm_calls": usage.get("llm_calls"), "total_tokens": usage.get("total_token_count"),
        }
        results.append(rec)
        print(f"  {i:>3}/{len(jobs)} {truth or brand:<12} {'เรียก ' + (args.get('surface') or '?') if sc else 'ไม่เรียก':<26}"
              f" {('มีรุ่นจริง' if rec['keeps_true'] else 'ไม่มีรุ่นจริง') if lst is not None else '':<12}"
              f" {'ฟันธง ' + claimed if claimed else ''} {sec}s")

    print(f"\n=== {A.engine.llm.describe()} · prompt {prompt_version()} ===")
    main_rs = [x for x in results if x["brand"] == "modutech"]
    ctrl_rs = [x for x in results if x["brand"] != "modutech"]
    if main_rs:
        summarize("ทั้งหมด", main_rs)
    if ctrl_rs:
        print("\n── กลุ่มควบคุม (ไม่ใช่สายพาน Modutech)")
        summarize_control("กลุ่มควบคุม", ctrl_rs)
        for b in sorted({x["brand"] for x in ctrl_rs}):
            summarize_control(f"brand={b}", [x for x in ctrl_rs if x["brand"] == b], short=True)
    for col in [c.strip() for c in a.by.split(",") if c.strip()] + (["text"] if len(texts) > 1 else []):
        print(f"\n── แยกตาม {col}")
        groups = {}
        for x in results:
            groups.setdefault(str(x.get(col, "")), []).append(x)
        for g in sorted(groups):
            fn = summarize if all(x["brand"] == "modutech" for x in groups[g]) else summarize_control
            fn(f"{col}={g or '(รูปอย่างเดียว)'}", groups[g], short=True)
    if a.runs > 1:
        by = {}
        for x in results:
            by.setdefault((x["path"], x["text"]), []).append(x)
        ok = lambda x: (not x["as_modutech"]) if x["brand"] != "modutech" else (   # noqa: E731
            x["called"] and x["keeps_true"] and not (x["model_claimed"] and not x["claim_correct"]))
        stable = sum(all(ok(x) for x in v) for v in by.values())
        print(f"\nผ่านครบทุก {a.runs} รอบ (Modutech: เรียก · มีรุ่นจริง · ไม่ฟันธงผิด · กลุ่มควบคุม: ไม่ตอบเป็น Modutech): {pct(stable, len(by))}")

    commit = os.popen(f'git -C "{ROOT}" rev-parse --short HEAD').read().strip()
    env = {k: os.environ.get(k) for k in ("AGENT_PROMPT", "AGENT_REPLY_GUARD", "AGENT_RESOLVE_TAB", "AGENT_DATASHEET_FILES",
                                          "AGENT_IMAGE_SURFACE", "AGENT_MODUTECH_JSON", "AGENT_IMAGE_DECISION", "GEMINI_MODEL", "GEMINI_THINKING")}
    from agent.tools_impl import CATALOGUE_PATH                # 10 พ.ย.: ฐาน Modutech ที่ใช้จริง (บันทึกอย่างเดียว)
    env["modutech_json_used"] = CATALOGUE_PATH
    json.dump({"labels": a.labels or a.from_rows, "brands": a.brands if a.from_rows else "modutech", "texts": texts, "runs": a.runs, "commit": commit, "env": env,
               "llm": A.engine.llm.describe(), "prompt": prompt_version(), "results": results},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"ผลรายรูป → {a.out} · commit {commit}")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
