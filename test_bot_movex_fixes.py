"""ทดสอบสวิตช์แก้จุดถอยหลังของบอทฝั่ง Movex (4 พ.ย. 2026 · ชุด Movex เทอมที่แล้ว) แบบออฟไลน์ — ไม่เรียก LLM

    python test_bot_movex_fixes.py          (venv ของบอท)

BOT_DOMAIN_PRODUCT=1   คำว่า "สินค้า" นับเป็นเรื่องสินค้า (เดิมถูกตีเป็นนอกเรื่อง)
MOVEX_UNKNOWN_CODE=1   รหัสแบบ Movex ที่ไม่มีในข้อมูล → บอกว่าไม่พบ + ซีรีส์ที่มี + ช่องทางฝ่ายขาย
MOVEX_SERIES_ANSWER=1  รู้ซีรีส์ ไม่รู้ความกว้าง คำถามไม่ใช่ค่าที่ต่างตามความกว้าง → ตอบระดับซีรีส์
MOVEX_ID_SCRUB=1       รหัสภายใน movex_chain_… ในคำตอบ → ชื่อรุ่น
ปิดทุกตัว = เดิมทุกช่อง · ข้อความทดสอบเขียนเอง ไม่ใช่ข้อความจากชุดทดสอบใด ๆ
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
SWITCHES = ("BOT_DOMAIN_PRODUCT", "MOVEX_UNKNOWN_CODE", "MOVEX_SERIES_ANSWER", "MOVEX_ID_SCRUB")
for k in SWITCHES + ("FRONT_INTERPRETER",):
    os.environ.pop(k, None)

import dialogue_state as DS  # noqa: E402
from core.protocol import ImageScore, TurnOutput  # noqa: E402

data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


def turn(text, state=None, vit=None):
    """เรียกแกนกลางตรง (Decision ของ core) — แปลงผลรูปแบบเดียวกับ DialogueManager.decide"""
    mgr = DS.DialogueManager(real, cat)
    image = None
    if vit is not None:
        image = ImageScore(brand="movex", confidence=vit.confidence, accepted=vit.confidence >= mgr.VIT_SERIES,
                           label=None, group=vit.series, dominant=vit.dominant, product_ref=vit.top_pid or "")
    return mgr.core.decide(text, has_image=vit is not None, image=image, state=state)


def snap(d):
    return (d.action, d.brand, d.reply_th, d.reason, (d.state.pending if d.state is not None else None), json.dumps(d.payload or {}, sort_keys=True, default=str))


PROBES = ["อยากดูสินค้าทั้งหมดที่มีขายหน่อย", "มีรุ่น LF777 ไหมครับ", "ซีรีส์ 882 มีอะไรให้เลือกบ้าง",
          "LF 880 TAB ใช้รางแบบไหน", "880 น้ำหนักเท่าไหร่", "880 รับโหลดเท่าไหร่", "LF 820 K325 กว้างเท่าไหร่",
          "LF820 K999 น้ำหนักเท่าไหร่", "54999 ฟันกี่ซี่", "สเตอร์ 54901 ฟันกี่ซี่", "อากาศวันนี้เป็นไง",
          "สวัสดีครับ", "โซ่ movex มีกี่รุ่น", "HC508 C กว้างเท่าไหร่", "LFN 83 MFM pitch เท่าไหร่"]

print("\n=== test_bot_movex_fixes ===")
print("1) ปิดทุกสวิตช์ = เดิม")
before = {t: snap(turn(t)) for t in PROBES}
check("สินค้า → นอกเรื่อง (พฤติกรรมเดิม)", before[PROBES[0]][0] == "refuse_offtopic", before[PROBES[0]][:2])
check("LF777 → ถามรุ่นแบบเดิม ไม่มีคำว่าไม่พบ", "ไม่พบ" not in (before[PROBES[1]][2] or ""), before[PROBES[1]][2][:60])
check("ซีรีส์ 882 มีอะไรบ้าง → ถามความกว้าง (เดิม)", before[PROBES[2]][0] == "ask"
      and before[PROBES[2]][4] == "movex_width", before[PROBES[2]][:5])

print("2) BOT_DOMAIN_PRODUCT=1")
os.environ["BOT_DOMAIN_PRODUCT"] = "1"
d = turn(PROBES[0])
check("สินค้า → ไม่ใช่นอกเรื่อง (ถามแบรนด์)", d.action == "ask" and d.topic == "brand", (d.action, d.reason))
check("อากาศ → ยังนอกเรื่อง", turn("อากาศวันนี้เป็นไง").action == "refuse_offtopic")
check("สวัสดี → ยังทักทาย", turn("สวัสดีครับ").action == "smalltalk")
changed = [t for t in PROBES[1:] if t != PROBES[0] and snap(turn(t)) != before[t]]
check("ข้อความอื่นไม่เปลี่ยน", not changed, changed)
os.environ.pop("BOT_DOMAIN_PRODUCT")

print("3) MOVEX_UNKNOWN_CODE=1")
os.environ["MOVEX_UNKNOWN_CODE"] = "1"
d = turn("มีรุ่น LF777 ไหมครับ")
check("LF777 → บอกว่าไม่พบ", d.reply_th.startswith("ไม่พบรุ่น LF777"), d.reply_th[:60])
check("ยังบอกซีรีส์ที่มี", "ซีรีส์ที่มี" in d.reply_th)
from sales_contact import sales_contact_line_th  # noqa: E402
check("แนบช่องทางฝ่ายขายจริง", (not sales_contact_line_th()) or sales_contact_line_th() in d.reply_th)
check("ค้างคำถามรุ่นไว้ (ตอบรุ่นต่อได้)", d.state.pending == "movex_model", d.state.pending)
d = turn("54999 ฟันกี่ซี่")
check("สเตอร์ 54999 → ไม่พบ", "ไม่พบรุ่น 54999" in (d.reply_th or ""), (d.action, (d.reply_th or "")[:60]))
for t in ("LF 820 K325 กว้างเท่าไหร่", "LF820 K999 น้ำหนักเท่าไหร่", "สเตอร์ 54901 ฟันกี่ซี่", "LFN 83 MFM pitch เท่าไหร่"):
    check(f"{t!r} ไม่ถูกตีเป็นรหัสที่ไม่มี", snap(turn(t)) == before[t], snap(turn(t))[:5])
d = turn("", vit=DS.VitInfo(series=None, confidence=0.2, dominant=False, top_pid=""))
check("รูปที่ ViT ต่ำ → ปฏิเสธรูปเหมือนเดิม", d.action == "reject_image", d.action)
os.environ.pop("MOVEX_UNKNOWN_CODE")

print("4) MOVEX_SERIES_ANSWER=1")
os.environ["MOVEX_SERIES_ANSWER"] = "1"
for t in ("ซีรีส์ 882 มีอะไรให้เลือกบ้าง", "LF 880 TAB ใช้รางแบบไหน"):
    d = turn(t)
    check(f"{t!r} → ตอบระดับซีรีส์", d.action == "answer" and (d.payload or {}).get("level") == "series",
          (d.action, d.reason, d.payload))
d = turn("880 น้ำหนักเท่าไหร่")
check("น้ำหนัก (ต่างตามความกว้าง) → ยังถามความกว้าง", d.action == "ask" and d.state.pending == "movex_width", (d.action, d.state.pending))
check("รับโหลด (เท่ากันทั้งซีรีส์) → เท่าเดิม", snap(turn("880 รับโหลดเท่าไหร่")) == before["880 รับโหลดเท่าไหร่"])
check("รุ่นชัด → เท่าเดิม", snap(turn("LF 820 K325 กว้างเท่าไหร่")) == before["LF 820 K325 กว้างเท่าไหร่"])
d = turn("", vit=DS.VitInfo(series="821", confidence=0.70, dominant=False, top_pid=""))
check("รูปเปล่าที่รู้แค่ซีรีส์ → ยังถามความกว้าง", d.action == "ask" and d.state.pending == "movex_width", (d.action, d.state.pending))
for t in ("880", "LF 880 TAB ครับ", "โซ่ซีรีส์ 882"):
    d = turn(t)
    check(f"พิมพ์แค่ซีรีส์ {t!r} → ยังถามความกว้าง", d.state.pending == "movex_width", (d.action, d.reason))
d = turn("880 รุ่นไหนเหมาะกับขวดแก้ว")
check("ถามว่ารุ่นไหน → ยังถามความกว้าง", d.state.pending == "movex_width", (d.action, d.reason))
d = turn("โซ่ตัวนี้รุ่นอะไร", vit=DS.VitInfo(series="880", confidence=0.92, dominant=False, top_pid=""))
check("รูป + ข้อความที่รู้แค่ซีรีส์ → ยังถามความกว้าง", d.state.pending == "movex_width", (d.action, d.reason))
d0 = turn("", vit=DS.VitInfo(series="821", confidence=0.70, dominant=False, top_pid=""))
d0b = turn("82.5", state=d0.state)
check("ตอบความกว้างที่ไม่มีในซีรีส์ → ยังถามความกว้าง (ไม่ตอบระดับซีรีส์)", d0b.action == "ask", (d0b.action, d0b.reason))
d1 = turn("LF 880 กว้างเท่าไหร่")
check("ถามความกว้างของซีรีส์ → ยังถามความกว้าง", d1.state.pending == "movex_width", (d1.action, d1.state.pending))
d2 = turn("82.5", state=d1.state)
check("ตอบความกว้างหลังถาม → ได้รุ่น (ไม่ถูกดักเป็นระดับซีรีส์)", d2.action == "answer"
      and (d2.payload or {}).get("level") == "product", (d2.action, d2.payload))
os.environ.pop("MOVEX_SERIES_ANSWER")

print("5) MOVEX_ID_SCRUB=1")
mgr = DS.DialogueManager(real, cat)
P = mgr.movex_plugin
raw = "รุ่น `movex_chain_LF880_TAB_K325` กับสเตอร์ movex_sprocket_54901 · movex_chain_NOPE_X"
check("แทนรหัสโซ่/สเตอร์ด้วยชื่อรุ่น",
      P.scrub_ids(raw) == "รุ่น LF 880 TAB K325 กับสเตอร์ 54901 · movex_chain_NOPE_X", P.scrub_ids(raw))
check("ข้อความไม่มีรหัส = เท่าเดิม", P.scrub_ids("โซ่ LF 820 K325 กว้าง 82.5 มม.") == "โซ่ LF 820 K325 กว้าง 82.5 มม.")


class _RT:
    def finish_turn(self, *a):
        return TurnOutput(reply=raw)


P._rt = lambda: _RT()
check("ปิด: finish_turn คืนคำตอบเดิม", P.finish_turn(None, None, None, None).reply == raw)
os.environ["MOVEX_ID_SCRUB"] = "1"
check("เปิด: finish_turn แทนรหัส", "movex_chain_LF880" not in P.finish_turn(None, None, None, None).reply)
os.environ.pop("MOVEX_ID_SCRUB")

print("6) เปิดทุกตัวพร้อมกัน — ข้อความที่ไม่เกี่ยวยังเท่าเดิม")
for k in SWITCHES:
    os.environ[k] = "1"
same = ["880 รับโหลดเท่าไหร่", "LF 820 K325 กว้างเท่าไหร่", "สเตอร์ 54901 ฟันกี่ซี่", "อากาศวันนี้เป็นไง",
        "สวัสดีครับ", "HC508 C กว้างเท่าไหร่", "LFN 83 MFM pitch เท่าไหร่", "880 น้ำหนักเท่าไหร่"]
diff = [t for t in same if snap(turn(t)) != before[t]]
check("ไม่เปลี่ยน 8 ข้อความ", not diff, diff)

print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
