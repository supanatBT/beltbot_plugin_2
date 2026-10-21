"""
brands/demo/test_demo.py — หลักฐานว่าแบรนด์ที่สามเพิ่มได้โดยไม่แตะไฟล์ของแบรนด์เดิม

    python brands/demo/test_demo.py

1. registry หาเจอเอง · สร้างได้จาก brand.yaml
2. แกนกลางพาไปถึง Demo: รหัส · เลข 3 ในเมนู · ชื่อแบรนด์ · ชนกับแบรนด์อื่น → ถามกลับ
3. แบรนด์เดิมไม่เปลี่ยน: เล่นทุกบทสนทนาในทุกไฟล์เคส ด้วยแกนกลาง 2 แบรนด์ กับ 3 แบรนด์
   ต่างได้เฉพาะสิ่งที่ "ต้อง" ต่างเมื่อมีแบรนด์เพิ่ม — ข้อความที่ไล่รายชื่อแบรนด์ และช่องสถานะ demo_*
4. กู้บทสนทนาผ่าน webapi ได้ · หนึ่งเทิร์นเต็มผ่าน core/turn (LLM ปลอม)
"""
from __future__ import annotations

import csv
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core import templates as T                               # noqa: E402
from core.decide import Dialogue                              # noqa: E402
from core.dialogue import state_class                         # noqa: E402
from core.registry import discover, load_plugins, state_schema  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {str(detail)[:300]}")


print("1) registry หาเจอเอง")
cfg_all = discover(resolve_images=False)
keys = [b.key for b in cfg_all]
ok("demo อยู่ลำดับที่ 3", keys[-1] == "demo" and len(keys) == 3, keys)
plugins = load_plugins(cfg_all)                 # ไม่มีโมเดล — โหมดตัดสินอย่างเดียว
ok("สร้างปลั๊กอินครบสามแบรนด์ (ตอบสัญญาครบ)", list(plugins) == keys)
S3 = state_class(state_schema(cfg_all))
D3 = Dialogue(list(plugins.values()), S3, image_brands=("movex",))
two = [b for b in cfg_all if b.key != "demo"]
S2 = state_class(state_schema(two))
D2 = Dialogue([plugins[b.key] for b in two], S2, image_brands=("movex",))
infos3 = [p.info for p in plugins.values()]

print("\n2) แกนกลางพาไปถึง Demo")
d = D3.decide("DMX-200 รับแรงได้เท่าไหร่")
ok("รหัส → answer ของ demo", d.action == "answer" and d.brand == "demo" and d.payload["codes"] == ["DMX-200"],
   (d.action, d.brand, d.payload))
ok("พิมพ์รหัสแบบอื่นก็จับได้ (dmx 300)", D3.decide("dmx 300 ทนกี่องศา").payload.get("codes") == ["DMX-300"])
d = D3.decide("แนะนำสายพานหน่อย")
ok("เมนูถามแบรนด์มีสามบรรทัด", d.action == "ask" and "3. สายพานตัวอย่าง Demo" in d.reply_th, d.reply_th)
d2 = D3.decide("3", state=d.state)
ok("ตอบเลข 3 → เลือก demo แล้วถามรุ่น", d2.brand == "demo" and d2.action == "ask" and "DMX-100" in d2.reply_th,
   (d2.action, d2.brand, d2.reply_th))
d3 = D3.decide("DMX-100", state=d2.state)
ok("ตอบรุ่น → answer (รวมคำถามเดิม)", d3.action == "answer" and d3.effective_text.startswith("แนะนำสายพานหน่อย"),
   (d3.action, d3.effective_text))
d = D3.decide("MP80 C กับ DMX-100 ต่างกันยังไง")
ok("รหัสสองแบรนด์ → ถามกลับเฉพาะสองแบรนด์ที่ชน",
   d.action == "ask" and d.reply_th == T.clarify_conflict([plugins["modutech"].info, plugins["demo"].info]),
   d.reply_th)
d = D3.decide("HC508 C กว้างเท่าไหร่")
d = D3.decide("แล้ว DMX-200 ล่ะ", state=d.state)
ok("เปลี่ยนแบรนด์ → ล้างรุ่นของแบรนด์เดิม", d.brand == "demo" and d.state.brands["modutech"]["codes"] == [],
   d.state.to_dict())
d = D3.decide("DMX-200 ราคาเท่าไหร่")
ok("ราคา → ส่งฝ่ายขายผ่าน core/sales", d.action == "escalate" and d.brand == "demo", (d.action, d.reason))
d = D3.decide("มีรุ่นสแตนเลสไหม")
ok("สแตนเลสไม่ระบุแบรนด์ → ทุกแบรนด์ตอบส่วนตัวเอง",
   d.action == "cross_brand" and "**Demo (สายพานตัวอย่าง)**" in d.reply_th and "ทุกแบรนด์" in d.reply_th)

print("\n3) แบรนด์เดิมไม่เปลี่ยน — 2 แบรนด์ vs 3 แบรนด์ บนทุกบทสนทนา")
ALLOWED = {
    (T.ask_brand(infos3[:2]), T.ask_brand(infos3)),
    (T.offtopic(infos3[:2]), T.offtopic(infos3)),
    (T.smalltalk(infos3[:2]), T.smalltalk(infos3)),
    (T.greeting(infos3[:2]), T.greeting(infos3)),        # เฟส 2: ทักทายแยกจากขอบคุณ
}
convs: dict = {}
for f in ("testsuite_120.csv", "testcases_modutech_136.csv", "testcases_graph_relations.csv",
          "training/prompt_snapshot/cases/testcases_v2.csv", "training/prompt_snapshot/cases/snapshot_extra.csv"):
    for r in csv.DictReader(open(os.path.join(ROOT, f), encoding="utf-8-sig")):
        convs.setdefault((f, r["id"]), []).append(r)
n = 0
unexpected, expected = [], 0
for (f, cid), turns in convs.items():
    turns.sort(key=lambda r: int(r.get("turn_number") or 1))
    s2 = s3 = None
    for t in turns:
        text, img = t.get("user_text", ""), bool((t.get("image") or "").strip())
        if not text and not img:
            continue
        a = D2.decide(text, has_image=img, state=s2)
        b = D3.decide(text, has_image=img, state=s3)
        s2, s3 = a.state, b.state
        n += 1
        fa = dict(action=a.action, brand=a.brand, reply=a.reply_th, reason=a.reason, payload=a.payload,
                  topic=a.topic, eff=a.effective_text, handoff=a.sales_handoff_th)
        fb = dict(action=b.action, brand=b.brand, reply=b.reply_th, reason=b.reason, payload=b.payload,
                  topic=b.topic, eff=b.effective_text, handoff=b.sales_handoff_th)
        st_b = {k: v for k, v in b.state.to_dict().items() if not k.startswith("demo_")}
        if fa == fb and a.state.to_dict() == st_b:
            continue
        diff = {k for k in fa if fa[k] != fb[k]}
        if a.state.to_dict() != st_b:
            diff.add("state")
        ok_reply = (diff <= {"reply"} and (fa["reply"], fb["reply"]) in ALLOWED) or \
                   (diff <= {"reply", "reason"} and fa["action"] == "cross_brand" and
                    fb["reason"] == fa["reason"].replace("ทั้งสองแบรนด์", "ทุกแบรนด์"))
        if ok_reply:
            expected += 1
        else:
            unexpected.append((f, cid, t.get("turn_number"), text, sorted(diff)))
ok(f"{n} เทิร์น: ต่างเฉพาะข้อความที่ไล่รายชื่อแบรนด์ ({expected} เทิร์น) — ไม่มีอย่างอื่นต่าง",
   not unexpected, unexpected[:5])
hit_demo = [k for k, turns in convs.items() if any(re.search(r"DMX|demo|เดโม", t.get("user_text", ""), re.I)
                                                     for t in turns)]
ok("ไม่มีเคสเดิมเรียกหา Demo (แบรนด์ใหม่ไม่แย่งคำถามของแบรนด์เดิม)", not hit_demo, hit_demo[:3])

print("\n4) กู้บทสนทนาผ่าน webapi + หนึ่งเทิร์นเต็ม")
from webapi.bot import sanitize_dialog_state, state_resumable  # noqa: E402
mod = types.SimpleNamespace(plugins=plugins, DialogState=S3)
st = sanitize_dialog_state({"brand": "demo", "demo_codes": ["DMX-100", "DMX-999", 3],
                            "modutech_codes": ["HC508 C", "x"]}, mod)
ok("demo_codes ผ่านปลั๊กอิน demo · รหัสแบรนด์อื่นผ่านปลั๊กอินของมันเอง",
   st["demo_codes"] == ["DMX-100"] and st["modutech_codes"] == ["HC508 C"] and st["brand"] == "demo", st)
ok("กู้ได้", state_resumable(st, mod))

from core.tools import ToolLog                                # noqa: E402
from core.turn import TurnEngine                              # noqa: E402


class _Resp:
    def __init__(self, t): self.text, self.candidates = t, []


class _LLM:
    def __init__(self): self.calls = []

    def run(self, turn, history, tool_calls):
        self.calls.append(turn)
        return types.SimpleNamespace(response=_Resp("DMX-200 รับแรงได้ 12000 N/m ครับ"), session=None,
                                     tool_calls=tool_calls)


class _Log:
    def new_session(self): return "s-demo"
    def start_turn(self, **k): return types.SimpleNamespace(turn_id="t1", summary_top1_pid="", summary_tool_calls=0)
    def log_llm(self, *a, **k): pass
    def finish_turn(self, *a, **k): pass


llm = _LLM()
eng = TurnEngine(D3, llm, _Log(), ToolLog(), image_scorers={})
hist, _, refs, focus, sid, _, _ = eng.chat("DMX-200 รับแรงได้เท่าไหร่", None, [])
ok("ตอบผ่าน LLM ด้วย prompt ของ demo", hist[-1]["content"].startswith("DMX-200 รับแรงได้ 12000")
   and "Demo" in llm.calls[-1].system_prompt and '"DMX-200"' in llm.calls[-1].system_prompt, hist[-1])
ok("debug บอกเส้นทาง", "**Decision:** answer · brand=demo" in refs and "**Demo:** รุ่น DMX-200" in refs, refs)
ok("สถานะเก็บรุ่น", eng.dialog_states[sid]["demo_codes"] == ["DMX-200"])

print("\n5) เขียนจากสัญญาอย่างเดียว")
here = os.path.dirname(os.path.abspath(__file__))
srcs = "".join(open(os.path.join(here, f), encoding="utf-8").read() for f in os.listdir(here) if f.endswith(".py")
               and not f.startswith("test_"))
ok("ไม่ import แบรนด์อื่น", not re.search(r"^\s*(from|import)\s+(brands\.(?!demo)|movex|modutech)", srcs, re.M))

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
