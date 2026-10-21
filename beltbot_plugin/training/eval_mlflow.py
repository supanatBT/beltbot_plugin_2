"""
training/eval_mlflow.py — ผลประเมินแชตบอตเข้า MLflow (HANDOFF ข้อ 5.3) + ตรวจคำต้องห้ามทั้งชุด (เฟส 0)

ใช้สองทาง
    python run_answer_eval.py --module assistant --testcases testcases_modutech_136.csv -o run8.json --mlflow --round 1
    python training/eval_mlflow.py run3.json run4.json run5.json run6.json run7.json --code pre-refactor

คำต้องห้ามทั้งชุด (global forbidden words)
    เป็นตัวชี้วัดแยก **ไม่เปลี่ยนผ่าน/ตก** ของเทิร์นใด — ถ้าเอาไปปนกับเกณฑ์เดิม ตัวเลข 170/172
    จะขยับทั้งที่ระบบไม่ได้เปลี่ยน (บทเรียนเดียวกับ MOD-REJ-002 ใน HANDOFF ข้อ 7)
    คำที่จับ: ห้าม · ให้บอกเฉพาะ · ระบบจึง · ลูกค้า (บอตควรพูดกับลูกค้าว่า "คุณ" ไม่ใช่พูดถึง "ลูกค้า")
    คำพวกนี้มาจาก prompt — เจอในคำตอบแปลว่า LLM ทวนกฎภายในให้ลูกค้าเห็น

ข้อควรระวัง (ข้อ 5.3): ตัวเลขชุดนี้แปรปรวนตามโมเดลภาษา อ่านคู่กับจำนวนรอบเสมอ ห้ามสรุปจากรอบเดียว
MLflow เป็นหลักฐานวิศวกรรม ไม่ใช่ผลประเมินในเล่ม
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MLRUNS = HERE / "mlruns"

GLOBAL_FORBIDDEN = ("ห้าม", "ให้บอกเฉพาะ", "ระบบจึง", "ลูกค้า")
# ชื่อ metric ของ MLflow รับแค่ ASCII — คำไทยอยู่ใน leaks.json
LEAK_METRIC = {"ห้าม": "leak.ham", "ให้บอกเฉพาะ": "leak.hai_bok_chapo",
               "ระบบจึง": "leak.rabop_jueng", "ลูกค้า": "leak.luk_kha"}


def leak_hits(reply: str) -> dict:
    reply = reply or ""
    return {w: reply.count(w) for w in GLOBAL_FORBIDDEN if w in reply}


def leak_summary(results: list) -> dict:
    graded = [r for r in results if not r.get("skipped")]
    per_word: Counter = Counter()
    turns = []
    for r in graded:
        h = leak_hits(r.get("reply", ""))
        if h:
            per_word.update(h)
            turns.append(f"{r['id']} t{r['turn']}")
    return {"turns_with_leak": len(turns), "per_word": dict(per_word), "turns": turns}


def _cat_metrics(by_category: dict) -> dict:
    out = {}
    for cat, frac in (by_category or {}).items():
        try:
            p, t = (int(x) for x in str(frac).split("/"))
        except ValueError:
            continue
        key = re.sub(r"[^A-Za-z0-9_.\-/ ]", "_", cat)
        out[f"cat.{key}.passed"] = p
        out[f"cat.{key}.total"] = t
    return out


def log_eval(summary: dict, json_path: str | None = None, code: str = "", round_no: str = "",
             note: str = "") -> str:
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")     # ข้อ 5.2 กำหนด file store
    import mlflow
    mlflow.set_tracking_uri(MLRUNS.as_uri())
    mlflow.set_experiment("answer_eval")
    leaks = summary.get("leaks") or leak_summary(summary.get("results", []))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    tc = summary.get("testcases", "")
    tc_hash = ""
    if tc and (ROOT / tc).exists():
        tc_hash = hashlib.sha256((ROOT / tc).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
    name = Path(json_path).stem if json_path else f"{summary.get('module')}-{round_no or 'run'}"
    with mlflow.start_run(run_name=name) as run:
        mlflow.set_tags({"kind": "answer_eval", "code": code or "unknown", "round": str(round_no or ""),
                         "commit_at_logging": commit, "source_file": json_path or "", "note": note})
        mlflow.log_params({"module": summary.get("module"), "testcases": tc, "testcases_sha": tc_hash})
        for k in ("total_turns", "graded", "passed", "failed", "errors", "skipped_no_image", "turns_with_image"):
            if isinstance(summary.get(k), (int, float)):
                mlflow.log_metric(k, summary[k])
        mlflow.log_metrics(_cat_metrics(summary.get("by_category")))
        mlflow.log_metric("leak.turns", leaks["turns_with_leak"])
        for w in GLOBAL_FORBIDDEN:
            mlflow.log_metric(LEAK_METRIC[w], leaks["per_word"].get(w, 0))
        if json_path and Path(json_path).exists():
            mlflow.log_artifact(json_path)
        else:
            mlflow.log_dict(summary, "eval.json")
        mlflow.log_dict(leaks, "leaks.json")
        return run.info.run_id


def main() -> int:
    ap = argparse.ArgumentParser(description="นำไฟล์ผลประเมินที่มีอยู่เข้า MLflow + นับคำต้องห้ามย้อนหลัง")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--code", default="", help="เช่น pre-refactor / refactor")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-mlflow", action="store_true", help="แค่พิมพ์ผล ไม่ log")
    a = ap.parse_args()
    for f in a.files:
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        lk = leak_summary(s.get("results", []))
        words = " · ".join(f"{w} {n}" for w, n in lk["per_word"].items()) or "-"
        print(f"  {f:<22} ผ่าน {s.get('passed')}/{s.get('graded', s.get('total_turns'))}   "
              f"เทิร์นที่หลุดคำต้องห้าม {lk['turns_with_leak']:>3}   ({words})")
        if not a.no_mlflow:
            log_eval({**s, "leaks": lk}, json_path=f, code=a.code, note=a.note)
    if not a.no_mlflow:
        print(f"  → MLflow experiment 'answer_eval' ที่ {MLRUNS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
