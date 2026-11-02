"""ทดสอบการบันทึกผลเข้า MLflow (2 พ.ย.) — ไม่เรียก LLM · เขียนลงโฟลเดอร์ชั่วคราว ไม่แตะ training/mlruns

    python test_eval_mlflow.py      (ต้องมี mlflow หรือ mlflow-skinny)

ตรวจ: ค่าตั้งระบบเป็น param · prompt ฉบับเต็มเป็นไฟล์แนบ · ต้นทุน (โทเคน · เรียก LLM · เวลา · เครื่องมือ) เป็น metric ·
      tag blind จากชื่อชุดทดสอบ · ไฟล์เก่าที่ไม่มี system_info อ่านรุ่น prompt จากข้อความ llm ได้
"""
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["EVAL_MLRUNS"] = tmp
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent / "training"))
import eval_mlflow as E   # noqa: E402
import mlflow             # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


res = [{"id": "A", "turn": "1", "category": "c", "passed": True, "reply": "ok", "seconds": 2.0,
        "llm_usage": {"total_token_count": 1000, "prompt_token_count": 900, "candidates_token_count": 100,
                      "llm_calls": 2, "tool_calls": [{"tool": "lookup_belt"}]}},
       {"id": "B", "turn": "1", "category": "c", "passed": False, "reply": "ห้าม", "seconds": 4.0,
        "llm_usage": {"total_token_count": 3000, "prompt_token_count": 2800, "candidates_token_count": 200,
                      "llm_calls": 4, "tool_calls": [{"tool": "a"}, {"tool": "b"}, {"tool": "c"}]}},
       {"id": "C", "turn": "1", "category": "c", "skipped": True, "reply": ""}]
summary = {"module": "agent_assistant", "llm": "ADK agent · m · thinking low · prompt r2m · …",
           "testcases": "testcases_blind.csv", "total_turns": 3, "graded": 2, "passed": 1, "failed": 1,
           "by_category": {"c": 0.5}, "results": res,
           "system_info": {"system": "agent", "prompt_version": "r2m", "prompt_sha": "abc123", "prompt_text": "คำสั่งเต็ม",
                           "brands": "modutech,movex", "search_engine": "qdrant", "code_sha": "x", "commit": "e1b331f"}}

rid = E.log_eval(summary, round_no="1")
r = mlflow.get_run(rid)
p, m, t = r.data.params, r.data.metrics, r.data.tags
check("param ระบบ (sys.system · prompt_version · search_engine · brands)",
      p.get("sys.system") == "agent" and p.get("sys.prompt_version") == "r2m"
      and p.get("sys.search_engine") == "qdrant" and p.get("sys.brands") == "modutech,movex", p)
check("prompt ไม่ถูกยัดเป็น param", "sys.prompt_text" not in p)
art = [a.path for a in mlflow.MlflowClient().list_artifacts(rid)]
check("prompt ฉบับเต็มเป็นไฟล์แนบ", "prompt_r2m_abc123.txt" in art, art)
check("tag blind=true จากชื่อชุด · system=agent", t.get("blind") == "true" and t.get("system") == "agent", t)
check("ต้นทุน: โทเคนมัธยฐาน 2000 รวม 4000", m.get("cost.tokens_median") == 2000 and m.get("cost.tokens_total") == 4000, m)
check("ต้นทุน: เรียก LLM มัธยฐาน 3 · เครื่องมือรวม 4", m.get("cost.llm_calls_median") == 3 and m.get("cost.tool_calls_total") == 4, m)
check("ต้นทุน: เวลามัธยฐาน 3 วินาที (ไม่นับเทิร์นที่ข้าม)", m.get("cost.seconds_median") == 3.0, m)

old = {k: v for k, v in summary.items() if k != "system_info"}
old["testcases"] = "testcases_modutech_136.csv"
r2 = mlflow.get_run(E.log_eval(old))
check("ไฟล์เก่า: อ่าน prompt r2m และ thinking low จากข้อความ llm · ติดป้าย backfilled",
      r2.data.params.get("sys.prompt_version") == "r2m" and r2.data.params.get("sys.gemini_thinking") == "low"
      and r2.data.params.get("sys.backfilled") == "True", r2.data.params)
check("ชุดเดิม blind=false", r2.data.tags.get("blind") == "false")
bot = dict(old, module="assistant", llm="google-genai · gemini-3.8-flash · thinking low · timeout 60 วิ")
check("ไฟล์เก่าของบอท → system=bot", mlflow.get_run(E.log_eval(bot)).data.params.get("sys.system") == "bot")

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
