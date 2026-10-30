"""
probe_tools.py
==============
รันคำถามทดสอบเรื่องเครื่องมือ (function calling) แชตใหม่ทุก id · id เดียวกันหลายแถว = คุยต่อกันตาม turn_number
บันทึก: คำตอบ · ผลตรวจแบบ run_answer_eval · การเรียก tool พร้อมพารามิเตอร์ที่ LLM ส่งมาจริง ·
บรรทัด debug ของเส้นทาง (บอกว่าโค้ดค้นเองหรือส่ง LLM)

ไม่แก้โค้ดบอท อ่านอย่างเดียว · tool_log.calls ถูกล้างทุกต้นเทิร์นโดย TurnEngine.chat อยู่แล้ว

รัน
---
  python probe_tools.py -o probe_tools_r1.json
  python probe_tools.py --only TL-B1,TL-C2 -o probe_tools_b1c2.json
  python probe_tools.py --testcases testcases_probe_tools_v2.csv -o probe_tools_r2.json
"""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
import time

import run_answer_eval as RAE


def short(x, n=800) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + f" …(+{len(s) - n})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="assistant")
    ap.add_argument("--testcases", default="testcases_probe_tools.csv")
    ap.add_argument("--only")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("-o", "--out", default="probe_tools_r1.json")
    args = ap.parse_args()

    print(f"⏳ โหลด {args.module} ...")
    bot = importlib.import_module(args.module)
    tool_log = getattr(bot, "tool_log", None)
    if tool_log is None:
        sys.exit("❌ โมดูลไม่มี tool_log — บันทึกการเรียกเครื่องมือไม่ได้")
    llm = getattr(getattr(bot, "engine", None), "llm", None)
    print(f"✅ พร้อม · LLM: {llm.describe() if hasattr(llm, 'describe') else '(ไม่ทราบ)'}")

    rows = list(csv.DictReader(open(args.testcases, encoding="utf-8-sig")))
    if args.only:
        keep = {s.strip() for s in args.only.split(",")}
        rows = [r for r in rows if r["id"] in keep]

    # จัดกลุ่มตาม id แล้วเล่นต่อกันตาม turn_number (แชตใหม่ทุก id)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["id"], []).append(r)
    results = []
    for cid, turns in groups.items():
        turns.sort(key=lambda r: int(r.get("turn_number") or 1))
        history, last_pids, session_id, vit, graph = [], [], "", None, None
        for case in turns:
            if llm is not None and hasattr(llm, "last_model_version"):
                llm.last_model_version = None
            error, reply, refs = None, "", ""
            t0 = time.perf_counter()
            try:
                out = bot.chat_interaction(case["user_text"], None, history, last_pids, session_id, vit, graph)
                history, _state, refs, last_pids, session_id, vit, graph = out
                reply = RAE.extract_reply(history)
            except Exception as exc:                                # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            secs = round(time.perf_counter() - t0, 1)

            calls = [{"tool": c.get("tool_name"), "args": c.get("args"), "success": c.get("success"),
                      "result": short(c.get("result"))} for c in list(tool_log.calls)]
            outcome = RAE.check_reply(case, reply, error)
            outcome.update({
                "id": cid, "turn": case.get("turn_number", "1"), "subcategory": case.get("subcategory", ""),
                "query": case["user_text"], "description": case.get("description", ""),
                "seconds": secs, "model_version": getattr(llm, "last_model_version", None),
                "llm_called": getattr(llm, "last_model_version", None) is not None,
                "tool_calls": calls, "route_debug": short(refs, 1500),
            })
            results.append(outcome)

            mark = "⚠️ " if error else ("✅" if outcome["passed"] else "❌")
            tools = ", ".join(f"{c['tool']}({json.dumps(c['args'], ensure_ascii=False)})" for c in calls) or "-"
            print(f"{mark} {cid:7s} t{outcome['turn']} {secs:5.1f}s  LLM={'ใช่' if outcome['llm_called'] else 'ไม่'}  tools={tools}")
            time.sleep(args.sleep)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"module": args.module, "testcases": args.testcases, "results": results},
                  f, ensure_ascii=False, indent=2)
    passed = sum(1 for r in results if r["passed"])
    print(f"\nผ่าน {passed}/{len(results)} · เรียก tool {sum(1 for r in results if r['tool_calls'])} ข้อ · บันทึก {args.out}")


if __name__ == "__main__":
    main()
