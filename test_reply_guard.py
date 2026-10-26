"""
test_reply_guard.py — core/reply_guard + guard_reply ใน core/turn (ไม่เรียก LLM จริง)

ที่มา: sim4_llm 26 ต.ค. (โค้ด 0263f53)
  G02: LLM แต่งช่องทางติดต่อ "02-123-4567 · sales@modutech.co.th · Line @modutechthailand"
  G05: LLM เล่าเหตุผลภายใน "ดูจาก context ที่ผ่านการคัดกรอง: slots_known: pitch_mm = 5.0 ..."

    python test_reply_guard.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import core.reply_guard as RG  # noqa: E402
from core.turn import guard_reply  # noqa: E402
from sales_contact import SALES_PHONE, sales_contact_line_th  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


G02 = ("แม้จะเป็นสภาวะแห้งสนิท SM254 FG50% ทนแห้งได้สูงสุด 116 °C ครับ\n\n"
       "ท่านสามารถติดต่อวิศวกรฝ่ายขายได้ตามช่องทางนี้ครับ:\n\n"
       "- **โทรศัพท์:** 02-123-4567\n- **อีเมล:** sales@modutech.co.th\n"
       "- **Line Official:** @modutechthailand\n- **เวลาทำการ:** จันทร์ – ศุกร์\n\nยินดีให้บริการครับ")
G05 = ("ดูจาก context ที่ผ่านการคัดกรอง:\n- slots_known: pitch_mm = 5.0 (เอ๊ะ ระบบ parse 5 เซน เป็น 5.0 mm!\n"
       "\"need_filter\": {\"kept\": []}")

print("1) ช่องทางติดต่อปลอม")
out, fake = RG.scrub_contacts(G02)
ok("ลบเบอร์ อีเมล LINE ปลอมทั้งบรรทัด", "02-123-4567" not in out and "sales@modutech" not in out
   and "@modutechthailand" not in out and len(fake) == 3, (out, fake))
ok("ข้อความสเปกยังอยู่", "116 °C" in out and "ยินดีให้บริการ" in out)
real = f"ติดต่อฝ่ายขาย: โทร {SALES_PHONE}\nโทร 086-345-1403 ก็ได้"
ok("เบอร์จริง (ขีดต่างตำแหน่งก็ได้) ไม่ถูกลบ", RG.scrub_contacts(real) == (real, []), RG.scrub_contacts(real))
ok("รหัสสินค้า ตัวเลขสเปก ไม่ถูกจับเป็นเบอร์", RG.scrub_contacts("EC508 C กว้าง 152.4–1600.2 มม. แรงดึง 30,000 N/m")[1] == [])


class _Dec:
    sales_handoff_th = ""


class _Sess:
    def __init__(self, text):
        self.text, self.sent = text, []

    def send_message(self, m):
        self.sent.append(m)
        return type("R", (), {"text": self.text, "candidates": []})()


class _Res:
    def __init__(self, retry_text):
        self.session = _Sess(retry_text)


r, notes = guard_reply(G02, _Res(""), _Dec())
ok("ไม่มีข้อความส่งต่อ → ลบของปลอมแล้วแนบช่องทางจริงแทน", sales_contact_line_th() in r and "02-123" not in r, r)
d = _Dec()
d.sales_handoff_th = "ส่วนเรื่องช่องทางติดต่อ ต้องสอบถามฝ่ายขายโดยตรงครับ\n" + sales_contact_line_th()
r, _ = guard_reply(G02, _Res(""), d)
ok("มีข้อความส่งต่ออยู่แล้ว → ไม่แนบซ้ำ (turn ต่อท้ายให้)", sales_contact_line_th() not in r)

print("\n2) เหตุผลภายในหลุด")
ok("จับ context · snake_case", RG.leaks(G05) and "slots_known" in RG.leaks(G05))
ok("คำตอบปกติไม่ถูกจับ", not RG.leaks("แนะนำ EC508 C (พิทช์ 50.8 มม.) และ HC508 C ครับ ทน -40 ถึง 60 °C (เปียก)"))
res = _Res("สำหรับระยะพิทช์ 5 เซนติเมตร (50.8 มม.) แนะนำ EC508 C ครับ")
r, notes = guard_reply(G05, res, _Dec())
ok("หลุด → ขอเขียนใหม่ครั้งเดียว ได้คำตอบที่สะอาด", r.startswith("สำหรับระยะพิทช์") and len(res.session.sent) == 1
   and res.session.sent[0] == RG.LEAK_RETRY_TH, (r, notes))
r, notes = guard_reply(G05, _Res(G05), _Dec())
ok("เขียนใหม่ยังหลุด → ข้อความสำรอง", r == RG.LEAK_FALLBACK_TH, r)


class _NoSess:
    pass


r, notes = guard_reply(G05, _NoSess(), _Dec())
ok("ไม่มี session → ข้อความสำรอง ไม่ล้ม", r == RG.LEAK_FALLBACK_TH, notes)

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
