"""
sim_fair_fakes.py — ของปลอมสำหรับเทสต์ simulate_customers.py แบบไม่เรียก API (branch sim-fair · 4 พ.ย. 2026)

    FakeLLM          complete() คืนข้อความตามบท · จด prompt ทุกครั้ง · last_usage ปลอม (สะสมแบบ UsageMeter)
    make_bot_module  module ปลอมแบบบอทหลัก (มี llm_client · engine.llm = llm_client)
    make_agent_module module ปลอมแบบ agent_assistant (ไม่มี llm_client · engine.llm = _LLMInfo ปลอม)
    run_main         เรียก simulate_customers.main() ด้วย argv ที่กำหนด แล้วคืน (json, txt)
    VOLATILE         ฟิลด์ที่เปลี่ยนตามเวลา — ตัดออกก่อนเทียบ golden (ระบุชื่อชัด ไม่กรองตัวเลขทั้งหมด)

ข้อความในบทเขียนเองทั้งหมด ไม่ได้มาจากชุด blind
"""
from __future__ import annotations

import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))

VOLATILE = {"seconds", "sec", "interp_ms", "latency_sec"}

GOALS = {"goals": [
    {"id": "F01", "brand": "modutech", "application": "ไก่ ไลน์ตัดแต่ง", "persona": "หัวหน้าไลน์ทดสอบ",
     "opening": "สายพาน modutech ไก่ตัดแต่งครับ", "facts": {"pitch": "2 นิ้ว", "temp": "5 องศา", "wet": "เปียก"},
     "pitch_mm": 50.8, "temp_c": 5, "wet_or_dry": "wet"},
    {"id": "F02", "brand": "modutech", "application": "ขนมปังเข้าเตาอบ", "persona": "ลูกค้าทดสอบที่มีแผน",
     "opening": "สายพานเข้าเตาอบครับ", "tactic": "ถามราคาหนึ่งครั้งก่อนตอบพิทช์",
     "facts": {"pitch": "1 นิ้ว", "temp": "110 องศา", "wet": "แห้ง"},
     "pitch_mm": 25.4, "temp_c": 110, "wet_or_dry": "dry"},
]}

CUSTOMER_LINES = ["พิทช์ 2 นิ้ว 5 องศา เปียก", "โอเคครับ [จบ]"]
BOT_LINES = ["พิทช์เท่าไหร่ครับ", "แนะนำ EC508 C ครับ", "ยินดีครับ"]


class FakeLLM:
    """แทน GeminiClient/GenAIClient — complete() เท่านั้น"""

    def __init__(self, lines=None, usage=(1000, 10), name="fake"):
        self.lines = list(lines or CUSTOMER_LINES)
        self.i = 0
        self.prompts: list[tuple[str, str]] = []
        self.usage = usage
        self.name = name
        self.last_usage = None
        self.last_model_version = None

    def describe(self) -> str:
        return f"fake · {self.name}"

    def complete(self, system, user, json_mode=False, temperature=None):
        self.prompts.append((system, user))
        acc = dict(self.last_usage or {})
        acc["llm_calls"] = acc.get("llm_calls", 0) + 1
        acc["prompt_token_count"] = acc.get("prompt_token_count", 0) + self.usage[0]
        acc["candidates_token_count"] = acc.get("candidates_token_count", 0) + self.usage[1]
        acc["total_token_count"] = acc.get("total_token_count", 0) + sum(self.usage)
        self.last_usage = acc
        m = self.lines[self.i % len(self.lines)]
        self.i += 1
        return m


def _chat_factory(meter, bot_usage):
    state = {"i": 0}

    def chat_interaction(user_text, image, history, last_pids, session_id, vit_signal, graph_result):
        if not history:
            state["i"] = 0
        reply = BOT_LINES[min(state["i"], len(BOT_LINES) - 1)]
        state["i"] += 1
        if meter is not None and bot_usage is not None:
            acc = dict(meter.last_usage or {})
            acc["llm_calls"] = acc.get("llm_calls", 0) + 1
            acc["prompt_token_count"] = acc.get("prompt_token_count", 0) + bot_usage[0]
            acc["candidates_token_count"] = acc.get("candidates_token_count", 0) + bot_usage[1]
            acc["total_token_count"] = acc.get("total_token_count", 0) + sum(bot_usage)
            meter.last_usage = acc
        history = list(history or []) + [{"role": "user", "content": user_text},
                                         {"role": "assistant", "content": reply}]
        return history, None, "", [], session_id or "s", None, None
    return chat_interaction


def make_bot_module(name="fake_sim_bot", llm=None, bot_usage=(7, 3)):
    """แบบ assistant.py: llm_client ตัวเดียวใช้ทั้งบอทและ (โหมดเดิม) ลูกค้า"""
    mod = types.ModuleType(name)
    mod.llm_client = llm or FakeLLM(name="bot")
    mod.engine = types.SimpleNamespace(llm=mod.llm_client)
    mod.ANSWER_INTERPRETER = "rules"
    mod.chat_interaction = _chat_factory(mod.llm_client, bot_usage)
    sys.modules[name] = mod
    return mod


class FakeAgentLLMInfo:
    def __init__(self):
        self.last_usage = None
        self.last_model_version = None

    def describe(self):
        return "fake agent"


def make_agent_module(name="fake_sim_agent", bot_usage=(7, 3), with_meter=True):
    """แบบ agent_assistant.py: ไม่มี llm_client · โทเคนอยู่ที่ engine.llm.last_usage (ถ้า with_meter)"""
    mod = types.ModuleType(name)
    info = FakeAgentLLMInfo() if with_meter else None
    if info is not None:
        mod.engine = types.SimpleNamespace(llm=info)
    mod.chat_interaction = _chat_factory(info, bot_usage)
    sys.modules[name] = mod
    return mod


def write_goals(d: str) -> str:
    p = os.path.join(d, "goals.json")
    json.dump(GOALS, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return p


def run_main(SC, module: str, d: str, extra=()):
    """เรียก SC.main() แล้วคืน (dict ผล json, ข้อความ txt)"""
    out = os.path.join(d, "out.json")
    argv = ["simulate_customers.py", "--module", module, "--goals", write_goals(d), "-o", out, *extra]
    old = sys.argv
    sys.argv = argv
    try:
        SC.main()
    finally:
        sys.argv = old
    return json.load(open(out, encoding="utf-8")), open(os.path.splitext(out)[0] + ".txt", encoding="utf-8").read()


def strip_volatile(o):
    if isinstance(o, dict):
        return {k: strip_volatile(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [strip_volatile(x) for x in o]
    return o


if __name__ == "__main__":
    # สร้าง golden จากโค้ดปัจจุบัน — รันครั้งเดียวที่ 509ae12 ก่อนแก้ simulate_customers.py
    import contextlib
    import io
    import tempfile
    sys.path.insert(0, ROOT)
    import simulate_customers as SC
    make_bot_module()
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
        res, txt = run_main(SC, "fake_sim_bot", d, ["--repeats", "2"])
    gd = os.path.join(ROOT, "tests", "golden")
    os.makedirs(gd, exist_ok=True)
    json.dump(strip_volatile(res), open(os.path.join(gd, "sim_fake_bot.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, sort_keys=True)
    open(os.path.join(gd, "sim_fake_bot.txt"), "w", encoding="utf-8").write(txt)
    print("golden เขียนแล้ว:", gd)
