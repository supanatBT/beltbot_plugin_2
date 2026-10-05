"""test_api_resume.py — เทสต์ /api/chat ทั้งเส้นผ่าน app.py จริง โดยใช้บอตปลอม

วางไฟล์นี้กับ fakebot.py ไว้ในโฟลเดอร์เดียวกับ app.py แล้วรัน
    python test_api_resume.py

ไม่โหลด Jina / SigLIP / Qdrant / Gemini เลย — เสร็จในไม่กี่วินาที

สำคัญ: เทสต์นี้ไม่ใช้ webapi/settings.py ตัวจริง
    ตัวจริงตั้ง bot_module = "chatbot_v5" ถ้าเอามาใช้จะไปโหลดโมเดลจริง
    จึงนิยาม TestCfg ของตัวเองไว้ในไฟล์นี้ และบังคับ bot_module = "fakebot"
    (app.py อ่านค่าจาก cfg เป็น attribute เท่านั้น ไม่ได้ต้องเป็นคลาส Settings)
    ของจริงในโฟลเดอร์นี้ไม่ถูกแตะหรือทับแม้ไฟล์เดียว
"""
import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if not os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebot.py")):
    sys.exit("ไม่พบ fakebot.py ในโฟลเดอร์นี้ — เทสต์ต้องใช้บอตปลอม ไม่ใช่ chatbot_v5")

from fastapi.testclient import TestClient  # noqa: E402

import fakebot  # noqa: E402  (ต้อง import ก่อนเพื่อยืนยันว่าใช้บอตปลอมจริง)
from app import create_app  # noqa: E402
from webapi.bot import BotAdapter  # noqa: E402


@dataclass
class TestCfg:
    """ค่าที่ app.py อ่าน — ตั้งหลวมหมดเพราะเทสต์นี้สนใจแค่เส้นทาง resume"""
    bot_module: str = "fakebot"
    session_ttl_s: int = 3600
    max_sessions: int = 100
    rl_per_minute: int = 10_000
    rl_per_hour: int = 100_000
    rl_images_per_hour: int = 10_000
    global_per_day: int = 1_000_000
    media_roots: list = field(default_factory=lambda: ["media"])
    max_concurrent: int = 2
    warm_on_start: bool = False          # ห้ามอุ่นเครื่อง ไม่งั้นโหลดโมเดลจริง
    allowed_origins: list = field(default_factory=list)
    proxy_secret: str = ""               # ปิดการตรวจ proxy ในเทสต์
    max_text_chars: int = 1000
    max_image_bytes: int = 4 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    image_max_side: int = 1024
    max_turns: int = 40
    queue_wait_s: int = 20
    scrub_internal_ids: bool = True


PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  — {detail}")


def client(**over):
    cfg = TestCfg(**over)
    assert cfg.bot_module == "fakebot", "เทสต์นี้ต้องใช้บอตปลอมเท่านั้น"
    bot = BotAdapter(cfg.bot_module)
    bot.load()
    return TestClient(create_app(cfg, bot))


def post(c, **fields):
    return c.post("/api/chat", data={k: v for k, v in fields.items() if v is not None})


RESUME = json.dumps({
    "messages": [
        {"role": "user", "text": "HC508 C กว้างเท่าไหร่"},
        {"role": "assistant", "text": "508.0 มม. ครับ"},
        {"role": "notice", "text": "ข้อความนี้ต้องถูกข้าม"},
    ],
    "dialog_state": {"brand": "modutech", "modutech_codes": ["HC508 C", "ไม่มีรุ่นนี้"],
                     "modutech_slots": {"wet_or_dry": "wet"}, "pending": "ask_width"},
}, ensure_ascii=False)

print("\n1) ไม่ส่ง resume — ต้องเหมือนเดิมทุกอย่าง")
c = client()
r = post(c, text="สวัสดี")
b = r.json()
ok("ตอบ 200", r.status_code == 200, r.text)
ok("มี session_id", bool(b.get("session_id")))
ok("มีคีย์ state เพิ่มมา", "state" in b, list(b))
ok("บอทเริ่มจากประวัติเปล่า", "เห็นประวัติ 0 ข้อความ" in b["messages"][0]["text"], b["messages"])

print("\n2) session หาย + ส่ง resume → ถามต่อได้")
c = client()
r = post(c, text="แล้วหนาเท่าไหร่", session_id="ของตายไปแล้ว", resume=RESUME)
b = r.json()
ok("ตอบ 200", r.status_code == 200, r.text)
ok("ได้ session ใหม่ (เบราว์เซอร์ใช้ตรวจว่ากู้เกิดขึ้น)",
   b["session_id"] != "ของตายไปแล้ว", b.get("session_id"))
txt = b["messages"][0]["text"]
ok("บอทเห็นประวัติ 2 ข้อความ (notice ถูกข้าม)", "เห็นประวัติ 2 ข้อความ" in txt, txt)
ok("บอทเห็นรหัสในบริบท", "HC508 C" in txt, txt)
ok("รหัสปลอมถูกตัด", "ไม่มีรุ่นนี้" not in txt, txt)
st = b["state"]
ok("state กลับไปให้เบราว์เซอร์", st.get("brand") == "modutech", st)
ok("ไม่คืน pending", not st.get("pending"), st)
ok("slot ที่รู้จักยังอยู่", st.get("modutech_slots", {}).get("wet_or_dry") == "wet", st)

print("\n3) session ยังอยู่ — resume ต้องไม่ทับของฝั่งเซิร์ฟเวอร์")
c = client()
sid = post(c, text="คำถามแรก").json()["session_id"]
txt2 = post(c, text="คำถามสอง", session_id=sid, resume=RESUME).json()["messages"][0]["text"]
ok("นับต่อจากของเดิม ไม่ใช่ของใน resume", "เห็นประวัติ 2 ข้อความ" in txt2, txt2)

print("\n4) resume พัง / ใหญ่เกิน / ไม่ใช่ dict")
c = client()
r = post(c, text="ถามใหม่", session_id="ตาย", resume="{ไม่ใช่ json")
ok("JSON พัง → ไม่ล้ม ตอบปกติ", r.status_code == 200 and
   "เห็นประวัติ 0 ข้อความ" in r.json()["messages"][0]["text"], r.text[:200])

r = post(c, text="ถามใหม่", session_id="ตาย2", resume=json.dumps(["ไม่ใช่ dict"]))
ok("ไม่ใช่ dict → ไม่ล้ม", r.status_code == 200, r.text[:200])

big = json.dumps({"messages": [{"role": "user", "text": "ก" * 30000}]}, ensure_ascii=False)
r = post(c, text="ถามใหม่", session_id="ตาย3", resume=big)
ok("ใหญ่เกิน → 400 resume_too_large",
   r.status_code == 400 and r.json().get("error") == "resume_too_large", r.text[:200])

print("\n5) state ไม่หลุดพาธรูปในเครื่องเซิร์ฟเวอร์")
leak = json.dumps({"messages": [{"role": "user", "text": "ดูรูป", "path": "/app/media/x.png"}],
                   "dialog_state": {"brand": "modutech"}}, ensure_ascii=False)
c = client()
b = post(c, text="ต่อ", session_id="ตาย4", resume=leak).json()
blob = json.dumps(b, ensure_ascii=False)
ok("ไม่มีพาธเซิร์ฟเวอร์ในคำตอบ", "/app/media" not in blob, blob[:300])

print(f"\n{'─' * 46}\n{PASS}/{PASS + FAIL} ผ่าน")
sys.exit(1 if FAIL else 0)