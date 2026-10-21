"""
training/run_gates.py
=====================
รันชุดเกต (ไม่ใช้ LLM) ทั้งหมด แล้ว log เป็น MLflow run หนึ่งอัน — HANDOFF_brand_plugin ข้อ 5.3 / 6

    python training/run_gates.py --label baseline
    python training/run_gates.py --label layer1-dialogue --compare baseline

ตรวจสองชั้น
  1. คะแนนของแต่ละชุด ต้องเท่าเกณฑ์ในข้อ 6 ทุกตัว
  2. ไฟล์ CSV ที่ชุดเกตเขียนออกมา (เคสที่ส่งให้ LLM eval) ต้องตรงกับ baseline ทุกไบต์
     — ชั้นนี้จับ "คะแนนเท่าเดิมแต่ context ที่ส่งให้ LLM เปลี่ยน" ได้ ซึ่งคะแนนอย่างเดียวจับไม่ได้

ใช้ MLflow แบบ file store ที่ training/mlruns เท่านั้น ไม่มี tracking server
ไฟล์นี้อยู่ใต้ training/ จึงไม่ถูกแพ็กขึ้น Space (.dockerignore)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MLRUNS = Path(__file__).resolve().parent / "mlruns"
SNAP_DIR = Path(__file__).resolve().parent / "gate_snapshots"

# ชื่อไฟล์ · regex ดึงคะแนน · คะแนนเต็มตามข้อ 6 (None = ไม่อยู่ในเกณฑ์ข้อ 6 แต่รันไว้ดู)
SUITES = [
    ("testsuite_120.py",        r"รวม\s+(\d+)/(\d+)",                150),
    ("test_sprocket_flow.py",   r"รวม\s+(\d+)/(\d+)",                41),
    ("testcases_graph.py",      r"ตรวจแล้ว\s+(\d+)\s+เคสเป็นธรรม",      33),
    ("test_resume.py",          r"(\d+)/(\d+)\s+ผ่าน",               22),
    ("test_api_resume.py",      r"(\d+)/(\d+)\s+ผ่าน",               17),
    ("test_modutech_kg.py",     r"รวม\s+(\d+)/(\d+)",                None),
    ("test_increment_status.py", r"(ผ่านทุกข้อ)",                     None),
    ("test_core_registry.py",   r"รวม\s+(\d+)/(\d+)",                None),   # ชั้น 1 — registry + ทะเบียนโมเดล
    ("test_core_dialogue.py",   r"รวม\s+(\d+)/(\d+)",                None),   # ชั้น 2 — สถานะบทสนทนา
    ("test_core_router.py",     r"รวม\s+(\d+)/(\d+)",                None),   # ชั้น 3 — เลือกแบรนด์ N ตัว
    ("test_core_decide.py",     r"รวม\s+(\d+)/(\d+)",                None),   # ชั้น 4 — ตัดสินเทียบของเดิมทุกเทิร์น
    ("test_webapi_sanitize.py", r"รวม\s+(\d+)/(\d+)",                None),   # ชั้น 6 — กู้สถานะผ่านปลั๊กอิน เทียบของเดิม
    ("test_assistant_resume.py", r"รวม\s+(\d+)/(\d+)",               None),   # ชั้น 6 — webapi → assistant ตัวจริง
]
# เทสต์ของแต่ละแบรนด์ — brands/<key>/test_*.py หาเองทุกครั้ง เพิ่มแบรนด์ไม่ต้องแก้ไฟล์นี้
def brand_suites() -> list:
    out = []
    for f in sorted((ROOT / "brands").glob("*/test_*.py")):
        out.append((f.relative_to(ROOT).as_posix(), r"รวม\s+(\d+)/(\d+)", None))
    return out


# ไฟล์ที่ชุดเกตเขียนออกมา — ต้องคงที่ข้ามการย้ายโครง
GENERATED = ["testcases_modutech_136.csv", "testcases_graph_relations.csv"]

# prompt snapshot — ชั้นที่ชุดเกตทั้งห้าวัดไม่ถึง (chat_interaction ทั้งเส้น ผ่าน Gemini ปลอม)
# เปลี่ยนชื่อโมดูลบอตเมื่อไหร่ แก้ที่นี่ที่เดียว
BASELINE_BRANDS = "movex,modutech"   # แบรนด์ที่มีตอนวัด baseline.json (7 ต.ค.)
BOT_MODULE = "assistant"     # ชั้น 5: ชื่อใหม่ · chatbot_v5 เป็นตัวชี้มาที่นี่
SNAPSHOT = Path(__file__).resolve().parent / "prompt_snapshot"

CORE_DIR = ROOT / "core"
BRAND_WORDS = re.compile(r"movex|modutech", re.IGNORECASE)


def sha(path: Path) -> str:
    # เทียบแบบไม่สน CRLF/LF — .gitattributes ของ repo เปลี่ยนปลายบรรทัดได้
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]


def run_suite(name: str, rx: str) -> dict:
    t0 = time.time()
    p = subprocess.run([sys.executable, name], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = p.stdout + p.stderr
    m = None
    for m in re.finditer(rx, out):
        pass                                      # เอาบรรทัดสรุปตัวสุดท้าย
    passed = total = None
    if m and p.returncode == 0:
        g = m.groups()
        if len(g) == 2:
            passed, total = int(g[0]), int(g[1])
        elif g[0].isdigit():
            passed = total = int(g[0])
        else:
            passed = total = 1
    return dict(exit=p.returncode, passed=passed, total=total,
                seconds=round(time.time() - t0, 1), log=out)


def core_grep() -> list[str]:
    """คืนบรรทัดใน core/ ที่มีชื่อแบรนด์ — ต้องว่าง (ข้อ 6)"""
    hits = []
    if not CORE_DIR.exists():
        return ["core/ ยังไม่มี"]
    for f in sorted(CORE_DIR.rglob("*")):
        if f.is_file() and f.suffix in (".py", ".yaml", ".yml", ".json", ".md", ".txt"):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if BRAND_WORDS.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:90]}")
    return hits


def dockerignore_excludes_training() -> bool:
    di = ROOT / ".dockerignore"
    if not di.exists():
        return False
    lines = [l.strip() for l in di.read_text(encoding="utf-8").splitlines()]
    return any(l in ("training", "training/", "training/**", "/training") for l in lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="ชื่อรอบ เช่น baseline, layer1-dialogue")
    ap.add_argument("--compare", default="baseline", help="snapshot ที่ใช้เทียบไฟล์ CSV")
    ap.add_argument("--no-mlflow", action="store_true")
    a = ap.parse_args()

    results = {}
    suites = SUITES + brand_suites()
    for name, rx, full in suites:
        r = run_suite(name, rx)
        results[name] = r
        ok = r["passed"] is not None and (full is None or (r["passed"] == full == r["total"]))
        r["ok"] = ok
        tag = "✓" if ok else "✗"
        want = f" (ต้อง {full}/{full})" if full else ""
        print(f"  {tag} {name:<26} {r['passed']}/{r['total']}{want}  exit={r['exit']}  {r['seconds']}s")

    # ── prompt snapshot ──
    # รอบ 1: เฉพาะแบรนด์ที่มีตอนวัด baseline — ต้องตรง baseline.json ทุกเทิร์น
    #        (มีแบรนด์ใหม่วางอยู่ในเครื่องก็ต้องไม่เปลี่ยนสิ่งที่แบรนด์เดิมส่งให้ LLM)
    # รอบ 2: ทุกแบรนด์ที่เปิด — เทียบ baseline_all.json ถ้ามี (ตั้งเป็นคอมมิตแยกหลังตรวจ diff แล้ว)
    def snapshot(tag, ref, env_extra):
        out = SNAP_DIR / f"prompt_{a.label}{tag}.json"
        cmd = [sys.executable, str(SNAPSHOT / "harness.py"), "--module", BOT_MODULE, "-o", str(out)]
        if ref.exists():
            cmd += ["--compare", str(ref)]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", **env_extra})
        lines = [l for l in p.stdout.splitlines() if l.startswith(("เทิร์น", "ตรงกับ", "ต่าง", "  ✗", "  !"))]
        if p.returncode != 0 and not lines:
            lines = [(p.stderr.strip().splitlines() or ["(ไม่มีข้อความ)"])[-1]]
        return p.returncode == 0 and ref.exists(), lines, ref.exists()

    SNAP_DIR.mkdir(exist_ok=True)
    prompt_ok, snap_lines, _ = snapshot("", SNAPSHOT / "baseline.json", {"BRANDS": BASELINE_BRANDS})
    print(f"  {'✓' if prompt_ok else '✗'} prompt snapshot ({BOT_MODULE} · BRANDS={BASELINE_BRANDS})")
    for l in snap_lines:
        print(f"      {l.strip()}")
    all_ok, all_lines, has_all = snapshot("_all", SNAPSHOT / "baseline_all.json", {"BRANDS": ""})
    if has_all:
        print(f"  {'✓' if all_ok else '✗'} prompt snapshot ({BOT_MODULE} · ทุกแบรนด์)")
        prompt_ok = prompt_ok and all_ok
    else:
        print(f"  · prompt snapshot ทุกแบรนด์: ยังไม่มี baseline_all.json — เขียนผลไว้ที่ "
              f"{(SNAP_DIR / f'prompt_{a.label}_all.json').relative_to(ROOT)} ให้ตรวจก่อนตั้ง")
    for l in all_lines:
        print(f"      {l.strip()}")
    snap_lines = snap_lines + [f"[ทุกแบรนด์] {l}" for l in all_lines]

    hashes = {g: sha(ROOT / g) for g in GENERATED if (ROOT / g).exists()}
    SNAP_DIR.mkdir(exist_ok=True)
    ref_path = SNAP_DIR / f"{a.compare}.json"
    drift = []
    if a.label != a.compare and ref_path.exists():
        ref = json.loads(ref_path.read_text(encoding="utf-8"))["generated"]
        drift = [g for g in GENERATED if ref.get(g) != hashes.get(g)]
    for g in GENERATED:
        print(f"  {'✗' if g in drift else '✓'} {g:<34} {hashes.get(g)}"
              + ("  ← ต่างจาก " + a.compare if g in drift else ""))

    grep_hits = core_grep()
    docker_ok = dockerignore_excludes_training()
    print(f"  {'✓' if not grep_hits else '✗'} grep core/ ไม่มีชื่อแบรนด์   ({len(grep_hits)} จุด)")
    for h in grep_hits[:10]:
        print(f"      {h}")
    print(f"  {'✓' if docker_ok else '✗'} .dockerignore ตัด training/")

    # ทุกชุดต้องผ่าน — ชุดที่ไม่มีเลขเต็มตายตัว (None) ต้องผ่านครบเท่าที่มี
    gates_ok = all(r["ok"] and r["passed"] == r["total"] for r in results.values()) \
        and not drift and prompt_ok
    snap = dict(label=a.label, time=time.strftime("%Y-%m-%d %H:%M:%S"),
                suites={n: {k: v for k, v in r.items() if k != "log"} for n, r in results.items()},
                generated=hashes, drift=drift, core_grep_hits=len(grep_hits),
                dockerignore_training=docker_ok, prompt_snapshot_ok=prompt_ok,
                prompt_snapshot=snap_lines, gates_ok=gates_ok)
    (SNAP_DIR / f"{a.label}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                                              encoding="utf-8")

    if not a.no_mlflow:
        # MLflow 3.17 ขึ้น error ถ้าใช้ file store โดยไม่ยืนยัน — ข้อ 5.2 กำหนด mlruns/ จึงยืนยันตรงนี้
        # ถ้าจะย้ายไป sqlite:///training/mlflow.db ให้เปลี่ยนแค่บรรทัดนี้กับ set_tracking_uri
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        import mlflow
        mlflow.set_tracking_uri(MLRUNS.as_uri())
        mlflow.set_experiment("gates")
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip())
        with mlflow.start_run(run_name=a.label):
            mlflow.set_tags({"label": a.label, "commit": commit, "dirty": str(dirty),
                             "kind": "gate", "date": snap["time"]})
            for n, r in results.items():
                key = n.removesuffix(".py").replace("/", ".")
                if r["passed"] is not None:
                    mlflow.log_metric(f"{key}.passed", r["passed"])
                    mlflow.log_metric(f"{key}.total", r["total"])
                mlflow.log_metric(f"{key}.ok", int(r["ok"]))
            mlflow.log_metric("generated_drift", len(drift))
            mlflow.log_metric("core_grep_hits", len(grep_hits))
            mlflow.log_metric("dockerignore_training", int(docker_ok))
            mlflow.log_metric("prompt_snapshot_ok", int(prompt_ok))
            mlflow.log_metric("gates_ok", int(gates_ok))
            mlflow.log_params({f"sha.{g}": h for g, h in hashes.items()})
            mlflow.log_dict(snap, "snapshot.json")
            mlflow.log_text("\n\n".join(f"===== {n}\n{r['log']}" for n, r in results.items()),
                            "suite_logs.txt")
        print(f"  → MLflow run '{a.label}' ที่ {MLRUNS.relative_to(ROOT)} (commit {commit}{' +dirty' if dirty else ''})")

    print("\nเกตครบ" if gates_ok else "\nเกตไม่ครบ — ห้ามไปชั้นถัดไป")
    return 0 if gates_ok else 1


if __name__ == "__main__":
    sys.exit(main())
