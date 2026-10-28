"""
metrics_report.py — สรุปบรรทัด METRIC จาก log ของ Space (28 ต.ค.) · ไม่ต้องลงอะไรเพิ่ม

    & $py metrics_report.py space_logs.txt
    & $py metrics_report.py space_logs.txt --cal "E:\\...\\brand_calibration_rows.csv" --csv metrics_weekly.csv

รับได้ทั้งข้อความที่คัดลอกจากหน้า Logs ของ Space, ไฟล์ที่ดึงผ่าน API (บรรทัด data: {...}),
และ stdout ของ uvicorn บนเครื่อง — อ่านเฉพาะบรรทัดที่มี "METRIC "

⚠️ log ของ Space ฟรีหายเมื่อ Space รีสตาร์ต — ดาวน์โหลดเก็บเป็นช่วง ๆ แล้วส่งหลายไฟล์เข้ามาพร้อมกันได้
   บรรทัดซ้ำ (ดาวน์โหลดทับช่วงกัน) ถูกตัดออกอัตโนมัติ
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.metrics import parse_line                     # noqa: E402

POLICIES = ["direct", "dominant", "context", "confirm", "conflict", "ask", "text_brand",
            "unchanged", "not_product", "off"]


def read(paths: list[str]) -> list[dict]:
    seen, out = set(), []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("data:"):                 # SSE ของ HF: data: {"data": "...", "timestamp": ...}
                    try:
                        line = str(json.loads(line[5:].strip()).get("data", ""))
                    except (json.JSONDecodeError, AttributeError, ValueError):
                        pass
                d = parse_line(line)
                if d is None:
                    continue
                key = json.dumps(d, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    continue
                seen.add(key)
                out.append(d)
    return out


def week_of(at: str) -> str:
    try:
        y, w, _ = dt.datetime.fromisoformat(at[:19]).isocalendar()
        return f"{y}-W{w:02d}"
    except (TypeError, ValueError):
        return "?"


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def quantile(xs: list, q: float):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def cal_means(path: str) -> dict:
    """คะแนนประตูเฉลี่ยของชุด cal ต่อแบรนด์ (คอลัมน์ modutech_score · brand · split)"""
    by = defaultdict(list)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("split") or "").strip() != "cal":
                continue
            try:
                by[(r.get("brand") or "?").strip()].append(float(r["modutech_score"]))
            except (KeyError, ValueError):
                pass
    return {b: sum(v) / len(v) for b, v in by.items() if v}


def summarize(recs: list[dict]) -> list[dict]:
    weeks = defaultdict(lambda: {"turn": [], "api": []})
    for r in recs:
        weeks[week_of(r.get("at", ""))][r.get("src", "?") if r.get("src") in ("turn", "api") else "turn"].append(r)
    rows = []
    for w in sorted(weeks):
        T, A = weeks[w]["turn"], weeks[w]["api"]
        img = [t for t in T if t.get("image")]
        pol = Counter(t.get("policy") or "-" for t in img)
        gate = [((t.get("gate") or {}).get("modutech") or {}).get("score") for t in img]
        gate = [g for g in gate if isinstance(g, (int, float))]
        days = Counter((t.get("at") or "")[:10] for t in T)
        tok = sum(((t.get("tokens") or {}).get("total") or 0) for t in T)
        prep = [t["ms_total"] - t["ms_llm"] for t in T if isinstance(t.get("ms_total"), int)
                and isinstance(t.get("ms_llm"), int)]
        codes = Counter(a.get("code") for a in A)
        row = {
            "week": w, "turns": len(T), "sessions": len({t.get("s") for t in T if t.get("s")}),
            "turn_errors": sum(t.get("status") == "error" for t in T),
            "image_turns": len(img),
            **{f"policy_{p}": pol.get(p, 0) for p in POLICIES},
            "gate_mean_modutech": round(sum(gate) / len(gate), 4) if gate else None,
            "p50_total_ms": quantile([t.get("ms_total") for t in T], .5),
            "p95_total_ms": quantile([t.get("ms_total") for t in T], .95),
            "p95_llm_ms": quantile([t.get("ms_llm") for t in T], .95),
            "p95_before_llm_ms": quantile(prep, .95),
            "tokens_total": tok, "tokens_per_day": round(tok / max(1, len(days))),
            "api_requests": len(A),
            "api_rate_limited": sum(n for c, n in codes.items() if c in ("per_minute", "per_hour", "images_per_hour",
                                                                          "global_day")),
            "api_warming_up": codes.get("warming_up", 0), "api_busy": codes.get("busy", 0),
            "api_5xx": sum(a.get("http", 0) >= 500 for a in A),
            "guards": sum(bool(t.get("guard")) for t in T),
        }
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--cal", help="brand_calibration_rows.csv — เทียบคะแนนประตูเฉลี่ยกับชุด cal")
    ap.add_argument("--csv", help="เขียนตารางรายสัปดาห์ลงไฟล์นี้")
    a = ap.parse_args()
    recs = read(a.logs)
    if not recs:
        print("ไม่พบบรรทัด METRIC — ตรวจว่า Space ไม่ได้ตั้ง METRICS_LOG=0 และคัดลอก log ช่วงที่มีคนใช้")
        return 1
    rows = summarize(recs)
    cal = cal_means(a.cal) if a.cal else {}
    for r in rows:
        it = r["image_turns"]
        print(f"\n━━ {r['week']} ━━ เทิร์น {r['turns']} · บทสนทนา {r['sessions']} · "
              f"ตอบไม่สำเร็จ {r['turn_errors']} ({pct(r['turn_errors'], r['turns'])})")
        if it:
            mix = " · ".join(f"{p} {r['policy_' + p]} ({pct(r['policy_' + p], it)})"
                             for p in POLICIES if r["policy_" + p])
            print(f"  รูป {it} เทิร์น: {mix}")
            if r["gate_mean_modutech"] is not None:
                ref = " · ".join(f"cal {b} {m:.3f}" for b, m in sorted(cal.items()))
                print(f"  คะแนนประตู Modutech เฉลี่ย {r['gate_mean_modutech']:.3f}" + (f"  (เทียบ {ref})" if ref else ""))
        print(f"  เวลา: p50 {r['p50_total_ms']} · p95 {r['p95_total_ms']} ms "
              f"(LLM p95 {r['p95_llm_ms']} · ก่อนเรียก LLM p95 {r['p95_before_llm_ms']})")
        print(f"  token รวม {r['tokens_total']:,} · เฉลี่ย {r['tokens_per_day']:,}/วัน")
        print(f"  คำขอ {r['api_requests']} · ติด rate limit {r['api_rate_limited']} · warming_up {r['api_warming_up']}"
              f" · busy {r['api_busy']} · 5xx {r['api_5xx']} · ชั้นกันคำตอบทำงาน {r['guards']}")
    if a.csv:
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n✅ เขียน {a.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
