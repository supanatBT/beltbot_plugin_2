#!/usr/bin/env python3
"""
latency_probe.py — วัดว่าอะไรทำให้ Gemini ตอบช้า โดยไม่แตะโค้ดบอต (11 ต.ค. 2026)

ใช้ prompt จริงที่บอตส่งให้ Gemini (อ่านจาก training/prompt_snapshot/baseline.json — system prompt
และคำถามเหมือนของจริงทุกตัวอักษร ส่วนคำตอบเทิร์นก่อนในประวัติเป็นข้อความจำลอง) แล้วยิงซ้ำหลายแบบ:

  asis      prompt เหมือนบอตปัจจุบันทุกตัวอักษร (ตัวเทียบ)
  compact   Context เป็น JSON แบบไม่เว้นวรรค (เล็กลงราว 20%) — เนื้อหาเท่าเดิม
  short     asis + ขอให้รายการความกว้าง/ตัวเลขเขียนบรรทัดเดียวคั่นจุลภาค (คำตอบสั้นลง)
  lite      asis แต่ใช้โมเดล gemini-flash-lite-latest
  think:X   asis ผ่าน google-genai พร้อมจำกัด thinking — X = minimal | low | medium | high | ตัวเลข budget
            (13 ต.ค.) ตัวเดียวกับที่บอตใช้เมื่อตั้ง GEMINI_THINKING=X · ต้องติดตั้ง google-genai ก่อน:
              pip install "google-genai==2.8.0" "pydantic==2.11.10" "pydantic-core==2.33.2"
            ⚠ ห้ามติดตั้ง google-genai รุ่นล่าสุด — ≥ 2.9 อัป pydantic เป็น ≥ 2.12.5 ซึ่งพังบน Python 3.10.0 (11 ต.ค.)
  genai     asis ผ่าน google-genai โดยไม่จำกัด thinking — ตัวเทียบที่ยุติธรรมของ think:X (แยกผลของ SDK ออกจากผลของ thinking)
  nothink   = think:0 (ชื่อเดิม)

ทุกแบบยิงสลับกันเทิร์นต่อเทิร์น เพื่อไม่ให้ความช้าของเครือข่ายช่วงหนึ่งตกกับแบบเดียว
ผลคือเวลา (มัธยฐาน · p90) ความยาวคำตอบ และจำนวน token ถ้า API ส่งมา — ไม่ได้ตรวจความถูกต้อง
แบบไหนเร็วกว่าชัด ต้องรัน run_answer_eval ซ้ำก่อนเอาไปใช้จริง

    python training/latency_probe.py --n 20 --variants genai,think:minimal,think:low,think:medium
    python training/latency_probe.py --n 20 --variants asis,compact,short,lite   # ไม่ต้องติดตั้งอะไรเพิ่ม
    python training/latency_probe.py --n 20 --variants asis,lite
ต้องตั้ง GEMINI_API_KEY · ใช้โควตา: n × จำนวนแบบ ครั้ง
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAP = HERE / "prompt_snapshot" / "baseline.json"
MODEL = os.getenv("GEMINI_MODEL") or "gemini-flash-latest"   # ใช้ชื่อเดียวกับบอต (22 ต.ค.)
LITE = "gemini-flash-lite-latest"
SHORT_RULE = ("\n- รายการความกว้างหรือรายการตัวเลขยาว ให้เขียนเป็นบรรทัดเดียวคั่นด้วยจุลภาค "
              "ไม่ต้องแยกบรรทัดละค่า")
_CTX_RX = re.compile(r"(\[Context[^\n]*\n)(.*?)(\n\nกฎ\n)", re.S)


def load_calls(n: int, seed: int) -> list[dict]:
    turns = json.loads(SNAP.read_text(encoding="utf-8"))["turns"]
    calls = [g | {"id": f"{t['id']} t{t.get('turn')}"} for t in turns for g in t.get("gemini") or []
             if "Modutech Assistant" in (g.get("system_instruction") or "")]
    random.Random(seed).shuffle(calls)
    return calls[:n]


def compact(si: str) -> str:
    m = _CTX_RX.search(si)
    if not m:
        return si
    ctx = json.dumps(json.loads(m.group(2)), ensure_ascii=False, separators=(",", ":"))
    return si[:m.start(2)] + ctx + si[m.end(2):]


def call_old_sdk(model: str, system: str, history: list, parts: list) -> tuple[float, str, dict]:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    m = genai.GenerativeModel(model_name=model, system_instruction=system)
    t0 = time.perf_counter()
    r = m.start_chat(history=history).send_message(parts)
    dt = time.perf_counter() - t0
    try:
        text = r.text
    except ValueError:
        text = ""
    u = getattr(r, "usage_metadata", None)
    usage = {k: getattr(u, k, None) for k in ("prompt_token_count", "candidates_token_count",
                                              "thoughts_token_count", "total_token_count")} if u else {}
    return dt, text, usage


def call_think(model: str, system: str, history: list, parts: list, thinking: dict) -> tuple[float, str, dict]:
    from google import genai as gg                       # แพ็กเกจใหม่ google-genai
    from google.genai import types
    client = gg.Client(api_key=os.environ["GEMINI_API_KEY"])
    contents = [types.Content(role=h["role"], parts=[types.Part(text=p) for p in h["parts"]]) for h in history]
    contents.append(types.Content(role="user", parts=[types.Part(text=p) for p in parts]))
    tc = (types.ThinkingConfig(thinking_level=thinking["level"]) if "level" in thinking
          else types.ThinkingConfig(thinking_budget=thinking["budget"]) if "budget" in thinking else None)
    cfg = types.GenerateContentConfig(system_instruction=system, thinking_config=tc)
    t0 = time.perf_counter()
    r = client.models.generate_content(model=model, contents=contents, config=cfg)
    dt = time.perf_counter() - t0
    u = r.usage_metadata
    usage = {"prompt_token_count": u.prompt_token_count, "candidates_token_count": u.candidates_token_count,
             "thoughts_token_count": getattr(u, "thoughts_token_count", None)} if u else {}
    return dt, r.text or "", usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--variants", default="genai,think:minimal,think:low,think:medium")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("-o", "--out", default="latency_probe.json")
    a = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("ตั้ง GEMINI_API_KEY ก่อน")
    variants = [("think:0" if v.strip() == "nothink" else v.strip()) for v in a.variants.split(",") if v.strip()]
    if any(v.startswith("think:") or v == "genai" for v in variants):
        sys.path.insert(0, str(HERE.parent))
        from core.llm import parse_thinking
        for v in variants:
            if v.startswith("think:"):
                parse_thinking(v.split(":", 1)[1])      # ค่าผิด = หยุดก่อนยิงจริง
        try:
            import google.genai  # noqa: F401
        except Exception as e:                           # noqa: BLE001 — ImportError หรือ pydantic ไม่เข้ากัน
            print(f"⚠ import google-genai ไม่ได้ ({type(e).__name__}) — ข้ามแบบ think:* (ดูหัวไฟล์)")
            variants = [v for v in variants if not (v.startswith("think:") or v == "genai")]

    calls = load_calls(a.n, a.seed)
    rows = []
    for i, g in enumerate(calls, 1):
        hist, parts, si = g["history"], g["parts"], g["system_instruction"]
        order = variants[:]
        random.Random(i).shuffle(order)                  # สลับลำดับทุกเทิร์น
        for v in order:
            try:
                if v == "asis":
                    dt, txt, u = call_old_sdk(MODEL, si, hist, parts)
                elif v == "compact":
                    dt, txt, u = call_old_sdk(MODEL, compact(si), hist, parts)
                elif v == "short":
                    dt, txt, u = call_old_sdk(MODEL, si + SHORT_RULE, hist, parts)
                elif v == "lite":
                    dt, txt, u = call_old_sdk(LITE, si, hist, parts)
                elif v == "genai":
                    dt, txt, u = call_think(MODEL, si, hist, parts, {})
                elif v.startswith("think:"):
                    dt, txt, u = call_think(MODEL, si, hist, parts, parse_thinking(v.split(":", 1)[1]))
                else:
                    continue
                rows.append({"id": g["id"], "variant": v, "seconds": round(dt, 2), "reply_chars": len(txt),
                             "prompt_chars": len(si), **u, "reply": txt})
                print(f"{i:>3}/{len(calls)} {g['id']:<14} {v:<8} {dt:6.2f}s  {len(txt):>5} ตัวอักษร")
            except Exception as e:                       # noqa: BLE001
                print(f"{i:>3}/{len(calls)} {g['id']:<14} {v:<8} ✗ {e}")
            time.sleep(0.5)

    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'แบบ':<9}{'มัธยฐาน':>9}{'p90':>8}{'คำตอบ':>8}{'thinking tok':>14}")
    for v in variants:
        s = sorted(r["seconds"] for r in rows if r["variant"] == v)
        if not s:
            continue
        L = statistics.median(r["reply_chars"] for r in rows if r["variant"] == v)
        th = [r.get("thoughts_token_count") for r in rows if r["variant"] == v and r.get("thoughts_token_count")]
        print(f"{v:<9}{statistics.median(s):>8.2f}s{s[int(0.9 * (len(s) - 1))]:>7.2f}s{L:>8.0f}"
              f"{(statistics.median(th) if th else '-'):>14}")
    print(f"\n📄 {a.out}  (มีคำตอบเต็มของทุกแบบไว้เทียบความถูกต้อง)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
