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
bp = mlflow.get_run(E.log_eval(bot)).data.params
check("ไฟล์เก่าของบอท → system=bot", bp.get("sys.system") == "bot")
check("ไฟล์เก่าของบอท → token_scope=final_response (นับแค่ LLM ตัวตอบ) ติดป้ายว่าสันนิษฐาน",
      bp.get("sys.token_scope") == "final_response" and bp.get("sys.token_scope_from") == "assumed_pre_2nov", bp)
mv = dict(summary, system_info=dict(summary.get("system_info") or {}, gemini_model=""),
          results=[dict(r, model_version="gemini-3.8-flash") for r in summary["results"]])
mp = mlflow.get_run(E.log_eval(mv)).data.params
check("gemini_model ว่าง → เติมจาก model_version ของเทิร์น",
      mp.get("sys.gemini_model") == "gemini-3.8-flash" and mp.get("sys.gemini_model_from") == "model_version", mp)

# บันทึกย้อนหลัง: วันที่ไฟล์ · commit ที่รัน · กันบันทึกซ้ำ · ขยาย * เอง (PowerShell ไม่ขยายให้)
import json as _json, subprocess as _sp
d = Path(tempfile.mkdtemp())          # นอก mlruns (file store อ่านทุกโฟลเดอร์ในนั้นเป็น experiment)
for n in ("qi_blind_r1.json", "qi_blind_r2.json"):
    (d / n).write_text(_json.dumps(dict(summary, results=res)), encoding="utf-8")
(d / "qi_blind_r2.json").write_text(_json.dumps(dict(summary, results=res, passed=2)), encoding="utf-8")
check("ขยาย * เป็นไฟล์เรียงชื่อ", [Path(x).name for x in E.expand([str(d / "qi_*.json")])] == ["qi_blind_r1.json", "qi_blind_r2.json"])
rr = mlflow.get_run(E.log_eval(_json.loads((d / "qi_blind_r1.json").read_text(encoding="utf-8")),
                               json_path=str(d / "qi_blind_r1.json"))).data.tags
check("tag source_sha · source_mtime · run_commit จาก system_info",
      rr.get("source_sha") == E.file_sha(d / "qi_blind_r1.json") and rr.get("source_mtime", "").startswith("20")
      and rr.get("run_commit") == "e1b331f", rr)
check("ไฟล์ที่บันทึกแล้วถูกจับได้ · ไฟล์ใหม่ไม่", E.already_logged(d / "qi_blind_r1.json") and not E.already_logged(d / "qi_blind_r2.json"))
out = _sp.run([sys.executable, str(Path(E.__file__)), str(d / "*.json"), "--round", "1"], capture_output=True, text=True,
              encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
check("main: ข้ามไฟล์ที่บันทึกแล้ว บันทึกไฟล์ใหม่", "ข้าม" in out and out.count("ผ่าน ") == 1, out)

# ลูกค้าจำลอง (sim-fair 5 พ.ย.) — โครงไฟล์ของ simulate_customers.py · แยก experiment sim_redteam
print("\nลูกค้าจำลอง → experiment sim_redteam")
def _conv(goal, run, hit, fv=(), tactic=None, extra=None):
    r = {"goal": goal, "run": run, "hit": hit, "final_violations": list(fv), "violations": list(fv), "issues": [],
         "ended": "done", "turns": 3, "acceptable_source": "goal", "tactic": "แผน", "tactic_checked": tactic,
         "transcript": [{"role": "customer", "text": "x"},
                        {"role": "bot", "text": "ตอบ", "sec": 2.0,
                         "usage": {"total_token_count": 100, "prompt_token_count": 90, "candidates_token_count": 10, "llm_calls": 1}},
                        {"role": "customer", "text": "y"},
                        {"role": "bot", "text": "ห้ามบอก", "sec": 4.0,
                         "usage": {"total_token_count": 300, "prompt_token_count": 270, "candidates_token_count": 30, "llm_calls": 2}}]}
    r.update(extra or {})
    return r
sim = {"module": "agent_assistant", "llm": "ADK agent · gemini-3.8-flash · thinking low · prompt r3 · เครื่องมือผ่าน MCP (stdio)",
       "answer_interpreter": "?", "repeats": 2, "max_turns": 10, "temperature": 1.0,
       "customer_model": "gemini-3.8-flash", "customer_thinking": "low", "customer_source": "separate",
       "customer_usage_total": {"llm_calls": 8, "prompt_token_count": 8000, "candidates_token_count": 400, "total_token_count": 8400},
       "system_usage_total": {"llm_calls": 12, "prompt_token_count": 1440, "candidates_token_count": 160, "total_token_count": 1600},
       "goals": "training/redteam_goals_v2_truth.json", "goals_sha": "e6bf3fe62a4b13c8aee11f861979987b148a9c34095b4b8c81209391ec8e4867",
       "only": [], "tactic_label": True,
       "system_info": {"system": "agent", "prompt_version": "r3", "gemini_model": "gemini-3.8-flash", "commit": "abc1234"},
       "summary": {"conversations": 4, "hit_pct": 75.0},
       "results": [_conv("V01", 1, True), _conv("V01", 2, True), _conv("V02", 1, True), _conv("V02", 2, False, ["EC254 C"])]}
check("is_sim: ไฟล์ลูกค้าจำลอง = จริง · ไฟล์ run_answer_eval = เท็จ", E.is_sim(sim) and not E.is_sim(summary))
sm = E.sim_metrics(sim)
check("บท: hit 3/4 · ผิดเงื่อนไข 1 · เป้าหมายผ่านทุกรอบ 1/2",
      sm["sim.hit"] == 3 and sm["sim.conversations"] == 4 and sm["sim.final_violation"] == 1
      and sm["goal.pass_all_runs"] == 1 and sm["goal.total"] == 2, sm)
check("โทเคนระบบกับลูกค้าแยกกัน · ต่อเทิร์นระบบ มัธยฐาน 200 รวม 1600",
      sm["system.tokens_total"] == 1600 and sm["customer.tokens_total"] == 8400
      and sm["cost.tokens_median"] == 200 and sm["cost.tokens_total"] == 1600 and sm["cost.seconds_median"] == 3.0, sm)
check("ยังไม่กรอก tactic_checked → นับ unchecked 4", sm["tactic.unchecked"] == 4 and sm["tactic.ok"] == 0, sm)
sd = Path(tempfile.mkdtemp())
sp_ = sd / "sim_v2_agent.json"
sp_.write_text(_json.dumps(sim, ensure_ascii=False), encoding="utf-8")
(sd / "sim_v2_agent.txt").write_text("=== V01#1 ===\n", encoding="utf-8")
srun = mlflow.get_run(E.log_sim(sim, json_path=str(sp_), code="sim-fair"))
sp2, st2 = srun.data.params, srun.data.tags
check("experiment sim_redteam (ไม่ปนกับ answer_eval)",
      mlflow.get_experiment(srun.info.experiment_id).name == "sim_redteam")
check("param: goals · goals_sha · customer_model · customer_source · sys.prompt_version",
      sp2.get("goals") == "training/redteam_goals_v2_truth.json" and sp2.get("goals_sha") == "e6bf3fe62a4b13c8"
      and sp2.get("customer_model") == "gemini-3.8-flash" and sp2.get("customer_source") == "separate"
      and sp2.get("sys.prompt_version") == "r3", sp2)
check("tag: kind=sim_redteam · system=agent · run_commit · human_checked=false",
      st2.get("kind") == "sim_redteam" and st2.get("system") == "agent" and st2.get("run_commit") == "abc1234"
      and st2.get("human_checked") == "false", st2)
sart = [a.path for a in mlflow.MlflowClient().list_artifacts(srun.info.run_id)]
check("ไฟล์แนบ: json + txt + goals.json + leaks.json",
      {"sim_v2_agent.json", "sim_v2_agent.txt", "goals.json", "leaks.json"} <= set(sart), sart)
check("คำต้องห้ามนับจากข้อความระบบใน transcript ('ห้าม' 4 เทิร์น)", srun.data.metrics.get("leak.turns") == 4,
      srun.data.metrics.get("leak.turns"))
check("กันบันทึกซ้ำใน sim_redteam", E.already_logged(sp_, "sim_redteam") and not E.already_logged(sp_, "answer_eval"))
chk = dict(sim, results=[_conv("V01", 1, True, tactic=True, extra={"manual_ok": True}),
                         _conv("V01", 2, True, tactic=True, extra={"manual_ok": False}),
                         _conv("V02", 1, True, tactic=True), _conv("V02", 2, False, ["EC254 C"], tactic=False)])
cm = E.sim_metrics(chk)
check("ไฟล์ _checked: tactic ok 3 · off 1 · บทที่หลุดแผนไม่นับ → V02 ผ่านทุกรอบที่ทำตามแผน",
      cm["tactic.ok"] == 3 and cm["tactic.off"] == 1 and cm["goal.pass_all_runs_tactic_ok"] == 2
      and cm["goal.pass_all_runs"] == 1 and cm["manual.ok"] == 1 and cm["manual.fail"] == 1, cm)
cp_ = sd / "sim_v2_agent_checked.json"
cp_.write_text(_json.dumps(chk, ensure_ascii=False), encoding="utf-8")
ctags = mlflow.get_run(E.log_sim(chk, json_path=str(cp_))).data.tags
cart = [a.path for a in mlflow.MlflowClient().list_artifacts(mlflow.search_runs(
    [srun.info.experiment_id], filter_string=f"tags.source_sha = '{E.file_sha(cp_)}'", output_format="list")[0].info.run_id)]
check("_checked: human_checked=true · แนบ .txt ของไฟล์ดิบ", ctags.get("human_checked") == "true"
      and "sim_v2_agent.txt" in cart, (ctags.get("human_checked"), cart))
sd2 = Path(tempfile.mkdtemp())
(sd2 / "sim_v2_qi.json").write_text(_json.dumps(dict(sim, module="assistant",
    system_info={"system": "bot", "commit": "abc1234"})), encoding="utf-8")
out2 = _sp.run([sys.executable, str(Path(E.__file__)), str(sd2 / "*.json"), "--code", "sim-fair"], capture_output=True,
               text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
check("main: ไฟล์ลูกค้าจำลองไปที่ sim_redteam · พิมพ์ hit/เป้าหมาย", "ลูกค้าจำลอง assistant" in out2
      and "sim_redteam" in out2, out2)

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
