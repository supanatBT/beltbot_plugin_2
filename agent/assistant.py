"""
agent_assistant.py — ตัวเชื่อม agent เทียบเข้ากับ run_answer_eval.py (สัญญาเดียวกับ assistant.py)

    python run_answer_eval.py --module agent_assistant --testcases eval/cases/testcases_modutech_136.csv -o agent_136_r1.json

รันด้วย venv ของ agent (requirements_agent.txt) ไม่ใช่ venv ของบอทหลัก — ADK ต้องใช้ google-genai คนละรุ่น
history == [] = บทสนทนาใหม่ → เปิด session ใหม่ของ ADK (สถานะข้ามเทิร์นอยู่ใน session ของ agent เอง)
llm.last_usage เก็บโทเคนรวม · จำนวนครั้งที่เรียก LLM · รายชื่อเครื่องมือที่ถูกเรียก (ลงในผลของ run_answer_eval)
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # รากของ repo (ไฟล์นี้อยู่ใน agent/)
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:                                            # noqa: BLE001
    pass
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from PIL import Image                                         # noqa: E402
from google.adk.runners import Runner                         # noqa: E402
from google.adk.sessions import InMemorySessionService        # noqa: E402
from google.genai import types                                # noqa: E402

from agent.agent import build_agent, enabled_brands, instruction_text, prompt_version  # noqa: E402
from agent.tools_impl import IMAGE_DIR               # noqa: E402

APP, USER = "modutech_agent_baseline", "eval"


class _LLMInfo:
    usage_scope = "every_request"          # _turn นับ usage_metadata ทุก event ของ ADK (ทุกการเรียก LLM)

    def __init__(self):
        self.last_usage = None
        self.last_model_version = None
        self.model_name = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"   # ค่าเดียวกับ build_agent

    def describe(self) -> str:
        return (f"ADK agent · {self.model_name} · "
                f"thinking {os.environ.get('GEMINI_THINKING') or 'low'} · prompt {prompt_version()} · เครื่องมือผ่าน MCP (stdio)")


DATASHEET_IMG_STYLE = "max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.15);margin:8px 0;"


def datasheet_messages(tool_calls: list, since: float) -> list[dict]:
    """AGENT_DATASHEET_FILES=1 (4 พ.ย.): รูป datasheet ที่ movex_datasheet สร้างในเทิร์นนี้ → ข้อความรูปต่อท้ายบทสนทนา
    รูปแบบเดียวกับบอท (brands/movex/runtime.py finish_turn) · ไม่ส่งเข้า session ของ ADK จึงไม่กินโทเคน
    รับเฉพาะไฟล์ที่เขียนหลังเริ่มเทิร์นนี้ — ไฟล์เก่าของรอบก่อนไม่ถูกแนบ · ปิดสวิตช์ = [] (agent เดิม)"""
    from agent import movex_tools as MT
    if not MT.datasheet_files_on():
        return []
    out, seen = [], set()
    for tc in tool_calls:
        if tc.get("tool") != "movex_datasheet":
            continue
        pid, _c = MT.resolve_product(str((tc.get("args") or {}).get("product_id") or ""))
        path = MT.datasheet_path(pid) if pid else ""
        if not pid or pid in seen or not os.path.isfile(path) or os.path.getmtime(path) < since - 1:
            continue
        seen.add(pid)
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        out.append({"role": "assistant",
                    "content": f'<img src="data:image/png;base64,{b64}" style="{DATASHEET_IMG_STYLE}" />'})
    return out


def image_max_side() -> int:
    try:
        return max(0, int((os.environ.get("AGENT_IMAGE_MAX_SIDE") or "0").strip()))
    except ValueError:
        return 0


def llm_image_bytes(image) -> tuple[bytes, str]:
    """รูปที่ส่งเข้า Gemini (อยู่ใน session จึงถูกส่งซ้ำทุกการเรียก LLM ของบทสนทนา)
    AGENT_IMAGE_MAX_SIDE=<px> (4 พ.ย.): ย่อด้านยาวไม่เกินค่านี้ + JPEG — เครื่องมือรูป (ViT · SigLIP) ยังอ่านไฟล์เต็มจาก IMAGE_DIR
    ไม่ตั้ง/0 = PNG ขนาดเต็มแบบเดิมทุกไบต์"""
    side = image_max_side()
    buf = io.BytesIO()
    if not side:
        image.convert("RGB").save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    small = image.convert("RGB")
    if max(small.size) > side:
        small = small.copy()
        small.thumbnail((side, side), Image.LANCZOS)
    small.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


def reply_guard_on() -> bool:
    return (os.environ.get("AGENT_REPLY_GUARD") or "1").strip() != "0"


def _merge_usage(a: dict, b: dict) -> dict:
    out = dict(a)
    for k in ("prompt_token_count", "candidates_token_count", "total_token_count", "llm_calls",
              "cached_content_token_count", "ms_tools", "ms_turn"):
        out[k] = (a.get(k) or 0) + (b.get(k) or 0)
    out["tool_calls"] = list(a.get("tool_calls") or []) + list(b.get("tool_calls") or [])
    return out


class _Engine:
    def __init__(self, model=None, toolset=None):
        self.llm = _LLMInfo()
        self.last_images: list[dict] = []
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self.agent = build_agent(model=model, toolset=toolset)
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name=APP, agent=self.agent, session_service=self.sessions)

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
            timeout=float(os.environ.get("AGENT_TURN_TIMEOUT", "240")))

    async def _new_session(self) -> str:
        s = await self.sessions.create_session(app_name=APP, user_id=USER)
        return s.id

    async def _turn(self, session_id: str, message: types.Content) -> tuple[str, dict, str | None]:
        text_parts, calls = [], []
        usage = {"prompt_token_count": 0, "candidates_token_count": 0, "total_token_count": 0, "llm_calls": 0}
        # บันทึกอย่างเดียว ไม่เปลี่ยนพฤติกรรม (4 พ.ย.): โทเคนที่ Gemini แคชเอง (คิดเงินถูกกว่า) และเวลาที่ใช้ในเครื่องมือ
        # เวลาเครื่องมือ = ช่วงระหว่าง event ที่ LLM สั่งเรียกเครื่องมือ ถึง event ผลของเครื่องมือ · ที่เหลือ = LLM + ส่วนอื่น
        cached = 0
        ms_tools = 0.0
        t_begin = time.perf_counter()
        t_tool = None
        model_version = None
        async for ev in self.runner.run_async(user_id=USER, session_id=session_id, new_message=message):
            now = time.perf_counter()
            um = getattr(ev, "usage_metadata", None)
            if um is not None:
                usage["llm_calls"] += 1
                for k in ("prompt_token_count", "candidates_token_count", "total_token_count"):
                    usage[k] += getattr(um, k, 0) or 0
                cached += getattr(um, "cached_content_token_count", 0) or 0
            model_version = getattr(ev, "model_version", None) or model_version
            if ev.get_function_responses() and t_tool is not None:
                ms_tools += (now - t_tool) * 1000
                t_tool = None
            if ev.get_function_calls():
                t_tool = now
            for fc in ev.get_function_calls() or []:
                calls.append({"tool": fc.name, "args": dict(fc.args or {})})
            if ev.is_final_response() and ev.content and ev.content.parts:
                text_parts += [p.text for p in ev.content.parts if getattr(p, "text", None) and not getattr(p, "thought", False)]
        usage["tool_calls"] = calls
        usage["cached_content_token_count"] = cached
        usage["ms_tools"] = round(ms_tools)
        usage["ms_turn"] = round((time.perf_counter() - t_begin) * 1000)
        return "".join(text_parts).strip(), usage, model_version

    def _guard(self, session_id: str, reply: str, usage: dict, mv):
        """AGENT_REPLY_GUARD=1 (4 พ.ย.): ตรวจคำตอบด้วยโค้ดตัวเดียวกับบอท (core/reply_guard.py · core/turn.py guard_reply)
        1) ชื่อฟิลด์/เหตุผลภายในหลุด → ขอเขียนใหม่ใน session เดิมหนึ่งครั้ง · ยังหลุดหรือเขียนไม่ได้ → ข้อความสำรอง
        2) เบอร์ · อีเมล · LINE ที่ไม่ใช่ช่องทางจริง → ลบบรรทัดนั้น แล้วแนบช่องทางจริงแทน
        ที่มา: ชุด blind v1.1 BL-009 — ผลหลังเปิดสวิตช์ต้องวัดบนชุด blind ใหม่เท่านั้น · ปิดสวิตช์ = ไม่ถูกเรียก (agent เดิม)"""
        from engine.core import reply_guard as RG
        notes = []
        leak = RG.leaks(reply)
        if leak:
            notes.append({"leak": leak[:5]})
            new = ""
            try:
                new, u2, mv2 = self._call(self._turn(
                    session_id, types.Content(role="user", parts=[types.Part(text=RG.LEAK_RETRY_TH)])))
                usage, mv = _merge_usage(usage, u2), (mv2 or mv)
            except Exception as e:                       # noqa: BLE001 — เขียนใหม่ไม่ได้ = ใช้ข้อความสำรอง
                notes.append({"retry_error": type(e).__name__})
            if new and not RG.leaks(new):
                reply = new
                notes.append({"action": "rewritten"})
            else:
                reply = RG.LEAK_FALLBACK_TH
                notes.append({"action": "fallback", "retry_leak": RG.leaks(new)[:5]})
        reply, fake = RG.scrub_contacts(reply)
        if fake:
            notes.append({"fake_contacts": fake[:5]})
            from engine.shared.sales_contact import sales_contact_line_th
            line = sales_contact_line_th()
            if line and line not in reply:
                reply = f"{reply}\n\n{line}".strip()
        if notes:
            usage = dict(usage, reply_guard=notes)
        return reply, usage, mv

    def chat(self, query: str, image, session_id: str) -> tuple[str, str]:
        if not session_id:
            session_id = self._call(self._new_session())
        parts = []
        if image is not None:
            os.makedirs(IMAGE_DIR, exist_ok=True)
            image_id = f"{uuid.uuid4().hex[:12]}.png"
            image.convert("RGB").save(os.path.join(IMAGE_DIR, image_id))
            data, mime = llm_image_bytes(image)
            parts.append(types.Part(text=f"[ลูกค้าแนบรูป image_id={image_id}]"))
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        if query:
            parts.append(types.Part(text=query))
        t_start = time.time()
        reply, usage, mv = self._call(self._turn(session_id, types.Content(role="user", parts=parts)))
        if reply_guard_on():
            reply, usage, mv = self._guard(session_id, reply, usage, mv)
        self.llm.last_usage, self.llm.last_model_version = usage, mv
        self.last_images = datasheet_messages(usage.get("tool_calls") or [], t_start)
        return reply, session_id


engine: _Engine | None = None


def _engine() -> _Engine:
    global engine
    if engine is None:
        engine = _Engine()
    return engine


def chat_interaction(user_text, image, history, last_pids, session_id, vit_signal, graph_result):
    """สัญญาเดียวกับ assistant.chat_interaction — คืน 7 ค่า"""
    eng = _engine()
    if not history:                         # บทสนทนาใหม่ (run_answer_eval รีเซ็ต history ทุกเคส)
        session_id = ""
    reply, session_id = eng.chat(user_text or "", image, session_id)
    history = list(history or []) + [{"role": "user", "content": user_text or "[รูป]"},
                                     {"role": "assistant", "content": reply}] + list(eng.last_images)
    refs = {"tool_calls": (eng.llm.last_usage or {}).get("tool_calls", [])}
    return history, None, refs, [], session_id, None, None


def system_info() -> dict:
    """ค่าตั้งของระบบสำหรับ run_answer_eval → MLflow (param + prompt ฉบับเต็ม)"""
    import hashlib
    text = instruction_text()
    return {"system": "agent", "prompt_version": prompt_version(),
            "prompt_sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], "prompt_text": text,
            "brands": ",".join(enabled_brands()), "framework": "google-adk + mcp (stdio)"}


LOCK_FILE = os.path.join(ROOT, "agent_lock.json")


def agent_config() -> dict:
    """ค่าตั้งที่มีผลจริงตอนนี้ (หลังอ่านตัวแปรแวดล้อม) — ใช้เทียบกับ agent_lock.json"""
    import hashlib
    from agent import movex_tools as MT
    from agent.agent import image_surface_enabled
    return {
        "model": os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash",
        "thinking": (os.environ.get("GEMINI_THINKING") or "low").strip().lower(),
        "prompt": prompt_version(),
        "prompt_sha": hashlib.sha256(instruction_text().encode("utf-8")).hexdigest()[:12],
        "brands": ",".join(enabled_brands()),
        "reply_guard": reply_guard_on(), "resolve_tab": MT.resolve_tab_on(),
        "datasheet_files": MT.datasheet_files_on(), "image_surface": image_surface_enabled(),
        "image_max_side": image_max_side(),
    }


def lock_status() -> dict:
    """เทียบค่าตั้งจริงกับตัวที่ล็อกไว้ (agent_lock.json) · matches=False = ตัวที่รันไม่ใช่ตัวที่ทดสอบ"""
    import json
    cfg = agent_config()
    try:
        lock = json.load(open(LOCK_FILE, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"config": cfg, "lock": None, "matches": None, "error": type(e).__name__}
    want = lock.get("config") or {}
    diff = {k: {"want": want[k], "got": cfg.get(k)} for k in want if cfg.get(k) != want[k]}
    return {"config": cfg, "tested_commit": lock.get("tested_commit"), "tag": lock.get("tag"),
            "matches": not diff, "diff": diff}


# run_answer_eval อ่าน getattr(bot, "engine").llm ก่อนเรียกเทิร์นแรก → สร้างตอน import
engine = _Engine() if os.environ.get("AGENT_LAZY") != "1" else None
