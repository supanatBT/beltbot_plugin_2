"""
run_image_eval_agent.py — ชุดรูปเทียบ agent กับบอทหลัก (ฝั่ง eval ของ brand_calibration_rows.csv)

    python run_image_eval_agent.py --rows ..\\final\\21_image_eval\\results\\brand_calibration_rows.csv ^
        --root <โฟลเดอร์รูป Modutech> --root <โฟลเดอร์รูป Movex> --root <โฟลเดอร์รูปที่ไม่ใช่สายพาน> -o ..\\agent_img_r1.json

ใช้เฉพาะ split = eval (เกณฑ์ของบอทหลักตั้งจาก cal · ถ้าเอา cal มาเทียบ บอทหลักจะได้เปรียบเกินจริง)
ลูกค้าส่งรูปอย่างเดียว ไม่มีข้อความ (เหมือน IMG-001 ใน testcases_v2) · ทุกรูปเป็นบทสนทนาใหม่

ตัดสินผลแต่ละรูปเป็น 4 แบบเดียวกับคอลัมน์ outcome_gated ของบอทหลัก
    ถูกแบรนด์ · ผิดแบรนด์ · ถามแบรนด์ (ถามกลับโดยยังไม่ยืนยันแบรนด์) · ปฏิเสธ (บอกว่าไม่ใช่สินค้า/ใช้รูปไม่ได้)
  · รหัสรุ่นที่เอ่ยในคำตอบ หาด้วยโค้ด (รายชื่อรหัส Modutech 68 + Movex) — ใช้วัดการระบุรุ่น
  · แบรนด์/ถาม/ปฏิเสธ ใช้ LLM ตัดสิน (โมเดลเดียวกัน temperature 0) แล้วบันทึกเหตุผลไว้ให้คนตรวจทุกข้อ
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
from collections import Counter, defaultdict

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

JUDGE_PROMPT = """คุณเป็นผู้ตรวจคำตอบของแชทบอทขายสายพาน ลูกค้าส่งรูปมา 1 รูปโดยไม่พิมพ์อะไร
อ่านคำตอบของบอทแล้วตอบเป็น JSON เท่านั้น:
{"brand_claimed": "modutech" | "movex" | "other" | "none",
 "asked_back": true | false,
 "rejected_image": true | false,
 "reason_th": "เหตุผลสั้น ๆ"}
- brand_claimed: แบรนด์ที่บอท "ยืนยัน" ว่าสินค้าในรูปเป็น (ถ้าบอทแค่เดาพร้อมถามยืนยัน หรือไม่ได้ระบุแบรนด์ = "none")
- asked_back: บอทถามข้อมูลเพิ่มจากลูกค้าเพื่อระบุสินค้า (แบรนด์ รหัส พิทช์ ฯลฯ)
- rejected_image: บอทบอกว่ารูปนี้ไม่ใช่สายพาน/โซ่/เฟือง หรือใช้รูปนี้ไม่ได้ และไม่ได้ให้ข้อมูลสินค้า
คำตอบของบอท:
---
{reply}
---"""


def known_codes() -> dict[str, str]:
    """รหัสที่ค้นในคำตอบ → แบรนด์"""
    out = {}
    for p in json.load(open(os.path.join(ROOT, "data/modutech_v30_3.json"), encoding="utf-8"))["products"]:
        out[p["belt_code"]] = "modutech"
    try:
        data = json.load(open(os.path.join(ROOT, "data/extracted_data_v3_machine_ready.json"), encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("products") or data.get("items") or []
        for it in items:
            ref = (it.get("specifications") or {}).get("Ref") or it.get("Ref") or it.get("product_id")
            if ref:
                out[str(ref)] = "movex"
    except Exception:                                        # noqa: BLE001
        pass
    return out


def norm(s: str) -> str:
    return re.sub(r"[\s_\-]", "", (s or "").upper())


def codes_in(reply: str, codes: dict[str, str]) -> list[str]:
    """รหัสที่เอ่ยถึง · ตำแหน่งที่อยู่ในรหัสที่ยาวกว่าไม่นับ ("EC254 TR-TAB" ไม่นับเป็น "EC254 TR")
    แต่ถ้าเอ่ยรหัสสั้นแยกอีกที่หนึ่งก็นับ"""
    r = norm(reply)
    spans = {}
    for c in codes:
        k = norm(c)
        if k:
            spans[c] = [(m.start(), m.start() + len(k)) for m in re.finditer(re.escape(k), r)]
    longer = [(a, b) for c, ss in spans.items() for a, b in ss]
    out = []
    for c, ss in spans.items():
        if any(not any(a2 <= a and b <= b2 and (b2 - a2) > (b - a) for a2, b2 in longer) for a, b in ss):
            out.append(c)
    return out


def judge(reply: str) -> dict:
    from google import genai
    from google.genai import types
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=key)
    model = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
    for attempt in range(3):
        try:
            r = client.models.generate_content(
                model=model, contents=JUDGE_PROMPT.replace("{reply}", reply),
                config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"))
            return json.loads(r.text)
        except Exception as e:                               # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
    return {"brand_claimed": "none", "asked_back": False, "rejected_image": False, "reason_th": f"judge error {err}"}


def outcome(truth: str, j: dict) -> str:
    if j.get("rejected_image") and j.get("brand_claimed") in ("none", "other"):
        return "ปฏิเสธ"
    claimed = j.get("brand_claimed")
    if claimed in ("modutech", "movex"):
        if truth == "none":
            return "ผิดแบรนด์"
        return "ถูกแบรนด์" if claimed == truth else "ผิดแบรนด์"
    if j.get("asked_back"):
        return "ถามแบรนด์"
    return "ผิดแบรนด์" if truth != "none" and j.get("brand_claimed") == "other" else "ถามแบรนด์"


def find(path: str, roots: list[str]) -> str | None:
    for r in roots:
        p = os.path.join(r, path)
        if os.path.isfile(p):
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--root", action="append", default=[], help="โฟลเดอร์ที่ path ในไฟล์ rows อ้างถึง (ใส่ได้หลายครั้ง)")
    ap.add_argument("--split", default="eval")
    ap.add_argument("--limit", type=int)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    rows = [r for r in csv.DictReader(open(a.rows, encoding="utf-8-sig")) if r["split"] == a.split]
    if a.limit:
        rows = rows[: a.limit]
    missing = [r["path"] for r in rows if not find(r["path"], a.root)]
    if missing:
        print(f"❌ หารูปไม่เจอ {len(missing)} รูป เช่น {missing[:3]} — ตรวจ --root")
        return 1

    from agent import assistant as A
    print(f"✅ {A.engine.llm.describe()} · {len(rows)} รูป")
    codes = known_codes()
    results = []
    for i, r in enumerate(rows, 1):
        img = Image.open(find(r["path"], a.root)).convert("RGB")
        t0 = time.perf_counter()
        err = None
        try:
            h, *_ = A.chat_interaction("", img, [], [], "", None, None)
            reply = h[-1]["content"]
        except Exception as e:                               # noqa: BLE001
            reply, err = "", f"{type(e).__name__}: {e}"
        sec = round(time.perf_counter() - t0, 1)
        j = judge(reply) if reply else {"brand_claimed": "none", "asked_back": False, "rejected_image": False}
        out = outcome(r["brand"], j)
        mentioned = codes_in(reply, codes)
        usage = A.engine.llm.last_usage or {}
        results.append({
            "path": r["path"], "brand": r["brand"], "cls": r["cls"], "drawing": r.get("drawing"),
            "outcome_agent": out, "outcome_bot": r.get("outcome_gated"),
            "codes_mentioned": mentioned,
            "model_correct": (r["brand"] == "modutech" and r["cls"] in mentioned) if r["brand"] == "modutech" else None,
            "judge": j, "reply": reply, "error": err, "seconds": sec,
            "tool_calls": [c["tool"] for c in usage.get("tool_calls", [])],
            "llm_calls": usage.get("llm_calls"), "total_tokens": usage.get("total_token_count"),
        })
        print(f"  {i:>3}/{len(rows)} {r['brand']:<8} {out:<9} (บอท: {r.get('outcome_gated')}) {sec}s {mentioned[:2]}")

    summary = {}
    for b in ("modutech", "movex", "none"):
        s = [x for x in results if x["brand"] == b]
        summary[b] = {"n": len(s),
                      "agent": dict(Counter(x["outcome_agent"] for x in s)),
                      "bot": dict(Counter(x["outcome_bot"] for x in s))}
        if b == "modutech":
            summary[b]["agent_model_correct"] = sum(1 for x in s if x["model_correct"])
            per = defaultdict(lambda: [0, 0])
            for x in s:
                per[x["cls"]][0] += bool(x["model_correct"]); per[x["cls"]][1] += 1
            summary[b]["agent_model_correct_by_cls"] = {k: f"{v[0]}/{v[1]}" for k, v in sorted(per.items())}
    json.dump({"rows": a.rows, "split": a.split, "llm": A.engine.llm.describe(), "summary": summary,
               "results": results}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
