#!/usr/bin/env python3
"""
test_llm_thinking.py — GEMINI_THINKING (13 ต.ค. 2026) · core/llm.py

ตรวจ
  1. parse_thinking: ค่าว่าง = ไม่แตะ · ระดับ · ตัวเลข · ค่าผิดต้องหยุด
  2. extract_text: google-genai คืน .text = None (ไม่ใช่ ValueError) เมื่อมีแต่ tool call
  3. GenAIClient คุยกับเซิร์ฟเวอร์ Gemini ปลอมในเครื่อง (ไม่ใช้เน็ต ไม่ใช้โควตา):
     ส่ง thinking_level · system prompt · history · รูป (inlineData) · tool ไม่มีพารามิเตอร์เหมือน SDK เดิม
     · เรียก tool อัตโนมัติแล้วได้ข้อความ · session.send_message ส่งต่อได้
     ข้อ 3 ข้ามถ้าไม่มี google-genai (ไม่ได้ตั้ง GEMINI_THINKING ก็ไม่ต้องติดตั้ง)
    python test_llm_thinking.py
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.llm import extract_text, parse_thinking

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


print("1) parse_thinking")
ok("ว่าง = None (ใช้ของเดิม)", parse_thinking("") is None and parse_thinking(None) is None)
ok("ระดับ", parse_thinking(" LOW ") == {"level": "low"} and parse_thinking("minimal") == {"level": "minimal"})
ok("ตัวเลข = budget", parse_thinking("0") == {"budget": 0} and parse_thinking("512") == {"budget": 512})
try:
    parse_thinking("fast")
    ok("ค่าผิดต้องหยุด", False)
except ValueError:
    ok("ค่าผิดต้องหยุด", True)

print("2) extract_text")


class _R:
    def __init__(self, text, parts):
        self.text = text
        self.candidates = [type("C", (), {"content": type("X", (), {"parts": parts})()})()]


ok("text = None → อ่านจาก parts", extract_text(_R(None, [type("P", (), {"text": "ก"})()])) == "ก")
ok("text ปกติ", extract_text(_R("ข", [])) == "ข")

print("2b) ลองใหม่เมื่อ Google ไม่ว่าง (with_retry)")
from core.llm import is_transient, with_retry  # noqa: E402


class _E(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


ok("503 · 429 · UNAVAILABLE = ชั่วคราว", is_transient(_E("x", 503)) and is_transient(_E("x", 429))
   and is_transient(Exception("503 UNAVAILABLE. {'error': …}")) and is_transient(Exception("429 Resource has been exhausted")))
ok("คีย์ผิด (400) ไม่ใช่ชั่วคราว", not is_transient(_E("API_KEY_INVALID", 400)) and not is_transient(ValueError("x")))
calls, slept, log = [], [], []


def flaky():
    calls.append(1)
    log.append({"tool_name": "t"})
    if len(calls) < 3:
        raise _E("503 UNAVAILABLE", 503)
    return "ok"


ok("ล้ม 2 ครั้งแล้วผ่าน · รอ 2 และ 5 วินาที · บันทึก tool เหลือแค่ของรอบที่ผ่าน",
   with_retry(flaky, log, sleep=slept.append) == "ok" and slept == [2.0, 5.0] and len(log) == 1, f"{slept} {log}")
n = []


def always_bad():
    n.append(1)
    raise _E("503", 503)


try:
    with_retry(always_bad, sleep=lambda s: None)
    ok("ล้มครบ 3 ครั้งแล้วส่ง error ต่อ", False)
except _E:
    ok("ล้มครบ 3 ครั้งแล้วส่ง error ต่อ", len(n) == 3)
m = []


def bad_key():
    m.append(1)
    raise _E("API_KEY_INVALID", 400)


try:
    with_retry(bad_key, sleep=lambda s: None)
except _E:
    pass
ok("error ไม่ชั่วคราว ไม่ลองซ้ำ", len(m) == 1)

print("3) GenAIClient กับเซิร์ฟเวอร์ปลอม")
try:
    from google import genai as real
except Exception as e:                                   # noqa: BLE001
    print(f"  – ข้าม (ไม่มี google-genai: {type(e).__name__})")
    real = None

if real is not None:
    from core.llm import GenAIClient
    from core.protocol import LLMTurn
    from core.tools import ToolLog
    REQS, FAILED, FAIL_FIRST, CLIENT_OPTS = [], [], True, []
    import core.llm as _llm
    _llm.RETRY_DELAYS = (0.01, 0.01)               # เทสต์ไม่ต้องรอจริง

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if FAIL_FIRST and not FAILED:
                FAILED.append(1)                      # ครั้งแรกตอบ 503 — ต้องลองใหม่เองแล้วผ่าน
                b = json.dumps({"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}).encode()
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            REQS.append(body)
            parts = ([{"functionCall": {"name": "search_catalogue", "args": {}}}] if len(REQS) == 1
                     else [{"text": f"ตอบ {len(REQS)}"}])
            b = json.dumps({"candidates": [{"content": {"role": "model", "parts": parts}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    class FakeModule:
        @staticmethod
        def Client(api_key, http_options=None):
            opts = {"base_url": base}
            if http_options is not None:          # 26 ต.ค.: GenAIClient ส่ง timeout มาด้วย
                CLIENT_OPTS.append(http_options)
                opts["timeout"] = http_options.timeout
            return real.Client(api_key=api_key, http_options=opts)

    log = ToolLog()

    def search_catalogue(field: str = "", op: str = ">=", value: float = 0.0) -> str:
        """ค้นแคตตาล็อก"""
        return "ผลค้น"

    client = GenAIClient(FakeModule, "gemini-flash-latest", "k", {"level": "low"})
    turn = LLMTurn("SYS", [{"mime_type": "image/jpeg", "data": b"\xff\xd8"}, "คำถาม"],
                   tools=[log.track(search_catalogue)], debug=[])
    res = client.run(turn, [{"role": "user", "content": "<b>ก่อน</b>"}, {"role": "assistant", "content": "ครับ"}],
                     log.calls)
    first = REQS[0]
    ok("ส่ง thinking_level", json.dumps(first.get("generationConfig"), ensure_ascii=False).lower().count("low") == 1,
       str(first.get("generationConfig")))
    ok("system prompt", first["systemInstruction"]["parts"][0]["text"] == "SYS")
    ok("history ตัด HTML + รูปเป็น inlineData",
       first["contents"][0]["parts"][0]["text"] == "ก่อน"
       and [list(p)[0] for p in first["contents"][-1]["parts"]] == ["inlineData", "text"])
    decl = first["tools"][0]["functionDeclarations"][0]
    ok("tool ไม่มีพารามิเตอร์ (เหมือน SDK เดิม)", decl["name"] == "search_catalogue" and "parameters" not in decl,
       str(decl))
    ok("เรียก tool อัตโนมัติแล้วได้ข้อความ", extract_text(res.response) == "ตอบ 2"
       and [c["tool_name"] for c in log.calls] == ["search_catalogue"])
    ok("session.send_message ส่งต่อได้", extract_text(res.session.send_message("อีกที")) == "ตอบ 3")
    budget = GenAIClient(FakeModule, "m", "k", {"budget": 0}).thinking_config
    ok("ได้ 503 ครั้งแรกแล้วลองใหม่เองจนผ่าน", FAILED == [1])
    ok("budget 0", budget.thinking_budget == 0 and budget.thinking_level is None)
    ok("ส่ง timeout ให้ SDK เป็นมิลลิวินาที (ค่าเริ่มต้น 60 วิ)", CLIENT_OPTS and CLIENT_OPTS[0].timeout == 60000,
       CLIENT_OPTS[:1])
    srv.shutdown()

# ── 22 ต.ค.: บันทึกชื่อรุ่นจริงที่ Google ตอบ (alias -latest ย้ายรุ่นได้เอง) ──
from core.llm import GeminiClient, model_version_of  # noqa: E402


class _R:
    def __init__(self, **kw):
        self.__dict__.update(kw)


ok("model_version อ่านจาก response", model_version_of(_R(model_version="gemini-3.6-flash")) == "gemini-3.6-flash")
ok("ไม่มี model_version → None", model_version_of(_R()) is None and model_version_of(_R(model_version="")) is None)
ok("client เริ่มต้นไม่มีชื่อรุ่นค้าง", GeminiClient(None, "m").last_model_version is None)

print("\n5) จำกัดเวลา (26 ต.ค. · lat2_llm CONV-16 t4 ค้าง 627 วินาที)")
import time as _time  # noqa: E402
from core.llm import LLMTimeout, run_with_deadline  # noqa: E402

t0 = _time.perf_counter()
try:
    run_with_deadline(lambda: _time.sleep(3) or "ช้า", 0.2)
    got = "ไม่ตัด"
except LLMTimeout:
    got = "ตัด"
ok("งานที่เกินเวลา → LLMTimeout ภายในเวลาที่กำหนด", got == "ตัด" and _time.perf_counter() - t0 < 1.0,
   (got, _time.perf_counter() - t0))
ok("ทันเวลา → ได้ผลตามปกติ", run_with_deadline(lambda: "เร็ว", 1.0) == "เร็ว")
ok("0 / None = ไม่จำกัด", run_with_deadline(lambda: "x", 0) == "x" and run_with_deadline(lambda: "y", None) == "y")


class _HangModule:
    """SDK เดิมปลอม — send_message ค้าง"""
    class GenerativeModel:
        def __init__(self, **kw):
            pass

        def start_chat(self, **kw):
            class S:
                def send_message(self, m):
                    _time.sleep(3)
            return S()


from core.protocol import LLMTurn as _Turn  # noqa: E402
t0 = _time.perf_counter()
try:
    GeminiClient(_HangModule, "m", timeout_s=0.3).run(_Turn("SYS", ["q"], tools=[], debug=[]), [], [])
    got = "ไม่ตัด"
except LLMTimeout:
    got = "ตัด"
ok("GeminiClient ค้าง → LLMTimeout ใน ~0.3 วิ", got == "ตัด" and _time.perf_counter() - t0 < 1.5,
   (got, _time.perf_counter() - t0))
import core.turn as _ct  # noqa: E402
ok("TurnEngine มีข้อความให้ลูกค้าส่งใหม่เมื่อเกินเวลา", "ส่งคำถามเดิมอีกครั้ง" in _ct.TIMEOUT_REPLY_TH)

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
