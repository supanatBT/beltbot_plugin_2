"""
test_core_decide.py — core/decide.py + brands/*/plugin.py (ชั้น 4)

หลักฐานหลัก: DialogueManager ตัวเดิม (git e261bf9 รันในโปรเซสแยก) กับตัวใหม่ เล่นบทสนทนาชุดเดียวกัน
ทุกเทิร์นต้องได้ Decision เท่ากันทุกช่อง รวมสถานะหลังเทิร์น
    บทสนทนา  ทุกเคสในทุกไฟล์ (เรียงตาม turn_number ต่อเนื่องในเคส)
    รูป       เทิร์นที่มีรูป เล่นซ้ำ 5 แบบ: ViT 0.97 dominant · 0.92 ไม่ dominant · 0.70 · 0.30 · ระบบปฏิเสธรูป
    ฐาน Movex  ว่าง ({} แบบชุดเกต) และของจริง (แบบ chatbot_v5)

    python test_core_decide.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CASES = ["testsuite_120.csv", "testcases_modutech_136.csv", "testcases_graph_relations.csv",
         "training/prompt_snapshot/cases/testcases_v2.csv",
         "training/prompt_snapshot/cases/snapshot_extra.csv"]
OLD_FILES = ["dialogue_state.py", "modutech_gates.py", "modutech_router.py", "sales_contact.py"]

DRIVER = r'''
import csv, json, sys
from collections import defaultdict
sys.path.insert(0, sys.argv[1])
import dialogue_state as D
from modutech_gates import Catalogue

root, out_path = sys.argv[2], sys.argv[3]
cat = Catalogue(root + "/modutech_v30_3.json")
data = json.load(open(root + "/extracted_data_v3_machine_ready.json", encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
mats = {m["material_code"]: m for m in data.get("Materials", [])}

VITS = [("hi", dict(series="880", confidence=0.97, dominant=True, top_pid="movex_chain_LF880_TAB_K450"), False),
        ("hi_nodom", dict(series="820", confidence=0.92, dominant=False, top_pid="movex_chain_LF820_K325"), False),
        ("mid", dict(series="821", confidence=0.70, dominant=False, top_pid=""), False),
        ("low", dict(series="83", confidence=0.30, dominant=False, top_pid=""), False),
        ("rej", dict(series=None, confidence=0.0, dominant=False, top_pid=""), True)]

convs = defaultdict(list)
for f in json.loads(sys.argv[4]):
    for r in csv.DictReader(open(root + "/" + f, encoding="utf-8-sig")):
        convs[(f, r["id"])].append(r)

# บทสนทนาขอบเขต — จุดที่เคสในไฟล์ไม่แตะ (พบจาก mutation test: ตัดคำ "นิ้ว" · FOLLOWUP 40→39 ไม่มีใครจับได้)
EXTRA = [
    ["HC508 C กว้างเท่าไหร่", "ตอบเป็นนิ้วได้ไหม"], ["ตอบเป็นนิ้วได้ไหม"],
    ["HC508 C กว้างเท่าไหร่", "อยากให้แสดงค่าทุกตัวที่บอกมาเมื่อสักครู่นี้เป็นนิ้วแทนได้หรือเปล่าครับ"],
    ["HC508 C กว้างเท่าไหร่", "x" * 40], ["HC508 C กว้างเท่าไหร่", "x" * 41],
    ["HC508 C กว้างเท่าไหร่", "ก" * 40 + " ตัวนั้น"],
    ["LF820 K325 กว้างเท่าไหร่", "y" * 40], ["LF820 K325 กว้างเท่าไหร่", "y" * 41],
    ["อันนั้นล่ะ"], ["HC508 C", "อันนั้นล่ะ"],
    ["แนะนำหน่อย", "1"], ["แนะนำหน่อย", "2"], ["แนะนำหน่อย", "3"], ["แนะนำหน่อย", "โซ่"],
    ["แนะนำหน่อย", "โมดูลาร์"], ["แนะนำหน่อย", "top chain"], ["MP80 C กับ LF820 K325", "modutech"],
    ["MP80 C กับ LF820 K325", "1"], ["HC508 C", "LF820 K325", "MP80 C", "กว้างเท่าไหร่"],
    ["880", "82.5", "ราคาเท่าไหร่"], ["880 กว้าง 82.5 มม. รับแรงเท่าไหร่"], ["LFN 83 MFM วัสดุอะไร"],
    ["HC508", "HC508 C"], ["EC127SQZ24*PA"], ["SS"], ["stainless", "2"], ["ขอบคุณ"], ["hello"],
    ["ขอเบอร์", "LF820 K325 ราคา"], ["HC127 C สั่งทำความกว้าง 700 ได้ไหม"],
    ["สายพานอะไรดี", "ไก่", "แช่แข็ง -20 องศา"],
]
for i, turns in enumerate(EXTRA):
    for j, t in enumerate(turns, 1):
        convs[("extra", f"X{i:02d}")].append({"user_text": t, "turn_number": str(j), "image": ""})

def dump(d):
    return dict(action=d.action, brand=d.brand, reply_th=d.reply_th, reason=d.reason, topic=d.topic,
                effective_text=d.effective_text, movex=d.movex, modutech=d.modutech,
                sales_handoff_th=d.sales_handoff_th, sales_topics=d.sales_topics,
                needs_llm=d.needs_llm, state=d.state.to_dict())

out = {}
for dbname, db in (("empty", {}), ("real", real)):
    dm = D.DialogueManager(db, cat, movex_materials=mats if db else None)
    for (f, cid), turns in sorted(convs.items()):
        turns.sort(key=lambda r: int(r.get("turn_number") or 1))
        has_img = any((t.get("image") or "").strip() for t in turns)
        for vname, vit, rejected in (VITS if has_img else [("none", None, False)]):
            st = None
            for t in turns:
                text, img = t.get("user_text", ""), bool((t.get("image") or "").strip())
                if not text and not img:
                    continue
                key = f"{dbname}|{f}|{cid}|{vname}|t{t.get('turn_number', '1')}"
                try:
                    d = dm.decide(text, has_image=img, vit=D.VitInfo(**vit) if (img and vit) else None,
                                  image_rejected=rejected and img, state=st)
                except Exception as e:      # ต้องพังที่จุดเดียวกันด้วยข้อผิดพลาดเดียวกัน
                    out[key] = {"action": "EXCEPTION", "error": f"{type(e).__name__}: {e}"}
                    break
                st = d.state
                out[key] = dump(d)
    out[f"{dbname}|stainless"] = dm.stainless_both_brands_th()
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True)
print(len(out))
'''


def run(code_dir: str, out: str, tmp: str) -> int:
    drv = os.path.join(tmp, "driver.py")
    with open(drv, "w", encoding="utf-8") as f:
        f.write(DRIVER)
    p = subprocess.run([sys.executable, drv, code_dir, ROOT, out, json.dumps(CASES)],
                       cwd=tmp, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(p.stderr[-2000:])
        sys.exit(1)
    return int(p.stdout.strip().splitlines()[-1])


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="decide_eq_")
    old_dir = os.path.join(tmp, "old")
    os.makedirs(old_dir)
    # ดึงทีละไฟล์ด้วย git show — ไม่ใช้ tar (tar ของ Windows ไม่อ่าน stdin ถ้าไม่สั่ง -f -)
    for f in OLD_FILES:
        blob = subprocess.run(["git", "show", f"e261bf9:{f}"], cwd=ROOT, capture_output=True, check=True).stdout
        with open(os.path.join(old_dir, f), "wb") as fh:
            fh.write(blob)

    n_old = run(old_dir, os.path.join(tmp, "old.json"), tmp)
    n_new = run(ROOT, os.path.join(tmp, "new.json"), tmp)
    a = json.load(open(os.path.join(tmp, "old.json"), encoding="utf-8"))
    b = json.load(open(os.path.join(tmp, "new.json"), encoding="utf-8"))
    shutil.rmtree(tmp, ignore_errors=True)

    passed = failed = 0

    def ok(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}  {detail}")

    print("1) DialogueManager เดิม (e261bf9) กับใหม่")
    ok(f"จำนวนเทิร์นเท่ากัน ({n_old})", n_old == n_new and set(a) == set(b))
    # เฟส 2: แปลงผลของเดิมด้วยความต่างที่ตั้งใจก่อนเทียบ (training/phase2_expected.py)
    # ข้อความที่ตั้งใจให้เลือกแบรนด์ต่าง (พื้นที่เปิด · kg/m²) ทั้งบทสนทนานั้นนับแยก ไม่เทียบ
    sys.path.insert(0, os.path.join(ROOT, "training"))
    from phase2_expected import expected_reply, expected_search_query, need_flow_changed, routing_changed
    texts = {}
    for k in a:
        if isinstance(a[k], dict) and "effective_text" in a[k]:
            texts[k] = a[k]["effective_text"]
    conv_changed = {k.rsplit("|", 1)[0] for k, t in texts.items() if routing_changed(t)}
    _mx = {p["product_id"]: p for p in json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"),
                                                       encoding="utf-8"))["products"]}
    for k, v in a.items():
        if isinstance(v, dict) and "reply_th" in v:
            v["reply_th"] = expected_reply(v["reply_th"], v.get("effective_text", ""), v.get("action", ""),
                                         {} if k.startswith("empty|") else _mx)   # ชุด empty ไม่มีสินค้า Movex
            md = v.get("modutech")
            if isinstance(md, dict) and "search_query" in md:
                md["search_query"] = expected_search_query(md["search_query"], v.get("effective_text", ""))
            if (v.get("state") or {}).get("pending_question"):
                v["state"]["pending_question"] = expected_reply(v["state"]["pending_question"],
                                                                v.get("effective_text", ""), "",
                                                                {} if k.startswith("empty|") else _mx)
    cross_turns = [k for k, v in a.items() if isinstance(v, dict) and v.get("action") == "cross_brand"]
    bad_cross = [k for k in cross_turns if not (isinstance(b.get(k), dict) and b[k].get("action") == "cross_brand"
                                                and (b[k].get("state") or {}).get("pending") == "brand")]
    conv_changed = conv_changed | {k.rsplit("|", 1)[0] for k in cross_turns}
    need_turns = [k for k, v in a.items() if isinstance(v, dict) and need_flow_changed(v.get("reply_th", ""))]
    conv_need = {k.rsplit("|", 1)[0] for k in need_turns} - conv_changed
    from brands.modutech.need_flow import ASK_NEED_TH
    bad_need = [k for k in need_turns if not (isinstance(b.get(k), dict) and b[k].get("reply_th") == ASK_NEED_TH)]
    conv_changed = conv_changed | conv_need
    skipped_need_flow = set(need_turns)
    # 26 ต.ค.: slot _need_text (ข้อความที่บอกงานล่าสุด · plugin._remember_need) เป็นสถานะภายในใหม่
    # ไม่เปลี่ยน action · reply · reason — ตัดออกจากฝั่งใหม่ก่อนเทียบ (นับไว้ว่ามีกี่เทิร์น)
    def _drop_need(o):
        if isinstance(o, dict):
            o.pop("_need_text", None)
            o.pop("_esc_last", None)       # 27 ต.ค. หัวข้อส่งฝ่ายขายของเทิร์นก่อน (redteam r4) — สถานะภายใน
            for x in o.values():
                _drop_need(x)
        elif isinstance(o, list):
            for x in o:
                _drop_need(x)
    n_need = sum(1 for v in b.values() if "_need_text" in json.dumps(v, ensure_ascii=False))
    _drop_need(b)
    print(f"      26 ต.ค.: slot _need_text ใหม่ {n_need} เทิร์น (ตัดออกก่อนเทียบ)")
    # 26 ต.ค. (ผู้ใช้เลือกข้อ 2 ก): บอกงาน + ขอให้ช่วยเลือก ("ใช้รุ่นไหนดี") → ถามพิทช์/อุณหภูมิต่อ
    # ของเดิมตอบรายชื่อทันที — ทั้งบทสนทนาหลังจากนี้ต่างโดยตั้งใจ
    from brands.modutech.need_flow import ASK_PITCH_TH, ASK_TEMP_TH
    pick_turns = [k for k in a if isinstance(a[k], dict) and a[k].get("action") == "answer"
                  and isinstance(b.get(k), dict) and b[k].get("reply_th") in (ASK_PITCH_TH, ASK_TEMP_TH)
                  and k not in skipped_need_flow]
    conv_pick = {k.rsplit("|", 1)[0] for k in pick_turns} - conv_changed
    print(f"      26 ต.ค.: บอกงานแล้วขอให้ช่วยเลือก → ถามพิทช์/อุณหภูมิ {len(conv_pick)} บท ({len(pick_turns)} เทิร์น)"
          f" {sorted({k.split('|')[2] for k in pick_turns})}")
    conv_changed = conv_changed | conv_pick
    # 26 ต.ค. (redteam R08): ของเดิมวนถามแบรนด์ซ้ำ — ลูกค้าตอบแบรนด์แล้ว (modutech · 1 · 2) หรือพิมพ์รหัสแบรนด์เดียว
    # หลังคำถามค้างของอีกแบรนด์ ยังได้ "ขอยืนยันก่อน…" ซ้ำ · ของใหม่ตอบแบรนด์ที่เลือก (เทิร์นแรกที่ชนจริงยังถามเหมือนเดิม)
    loop_turns = [k for k in a if isinstance(a[k], dict) and not k.endswith("|t1")
                  and a[k].get("reason") == "เจอรหัสของทั้งสองแบรนด์" and (a[k].get("state") or {}).get("pending") == "brand"
                  and isinstance(b.get(k), dict) and b[k].get("brand") and (b[k].get("state") or {}).get("pending") != "brand"]
    conv_loop = {k.rsplit("|", 1)[0] for k in loop_turns} - conv_changed
    print(f"      26 ต.ค.: เลิกวนถามแบรนด์ซ้ำ {len(conv_loop)} บท ({len(loop_turns)} เทิร์น)"
          f" {sorted({k.split('|')[2] for k in loop_turns})}")
    conv_changed = conv_changed | conv_loop
    # 27 ต.ค. (redteam r4 R09#2): ถามเรื่องการค้าเดิมซ้ำทันที → ข้อความส่งฝ่ายขายอีกแบบ (ของเดิมตอบประโยคเดิมซ้ำ)
    again_turns = [k for k in a if isinstance(a[k], dict) and a[k].get("action") == "escalate"
                   and isinstance(b.get(k), dict) and str(b[k].get("reason", "")).endswith("(ถามซ้ำ)")]
    conv_again = {k.rsplit("|", 1)[0] for k in again_turns} - conv_changed
    print(f"      27 ต.ค.: ถามการค้าเดิมซ้ำ → ข้อความอีกแบบ {len(conv_again)} บท ({len(again_turns)} เทิร์น)")
    conv_changed = conv_changed | conv_again
    skipped =[k for k in a if k.rsplit("|", 1)[0] in conv_changed]
    diff = [k for k in sorted(set(a) & set(b)) if a[k] != b[k] and k not in skipped]
    # 27 ต.ค. (ผู้ใช้เลือกถ้อยคำทางการ): ข้อความปฏิเสธรูปเปลี่ยน — ต่างได้เฉพาะ reply_th ของ reject_image
    # และต้องเป็นข้อความใหม่ของแบรนด์นั้นหรือข้อความกลาง (action · reason · payload · สถานะเท่าเดิม)
    from core.decide import GENERIC_REJECT_IMAGE_TH as _GEN
    import yaml
    from brands.movex.plugin import reject_text as _mx_reject
    _mx_cfg = yaml.safe_load(open(os.path.join(ROOT, "brands", "movex", "brand.yaml"), encoding="utf-8"))
    _new_rej = {_GEN, _mx_reject(_mx_cfg)}
    reword = [k for k in diff if isinstance(a[k], dict) and isinstance(b[k], dict)
              and a[k].get("action") == b[k].get("action") == "reject_image"
              and [f for f in a[k] if a[k].get(f) != b[k].get(f)] == ["reply_th"]
              and b[k]["reply_th"] in _new_rej]
    diff = [k for k in diff if k not in reword]
    print(f"      27 ต.ค.: ข้อความปฏิเสธรูปเป็นถ้อยคำทางการ {len(reword)} เทิร์น (ต่างเฉพาะ reply_th)")
    print(f"      เฟส 2: ข้ามบทสนทนาที่ตั้งใจเลือกแบรนด์ต่าง {len(conv_changed)} บท ({len(skipped)} เทิร์น)")
    bad_skip = [k for k in skipped if isinstance(b.get(k), dict) and routing_changed(b[k].get("effective_text", ""))
                and b[k]["brand"] not in ("modutech", None)]
    ok("บทสนทนาที่ตั้งใจเปลี่ยน ได้ Modutech ทุกเทิร์นที่มีคำคุณสมบัติ", not bad_skip, bad_skip[:3])
    print(f"      25 ต.ค.: ถามงานทีละข้อ {len(conv_need)} บท ({len(need_turns)} เทิร์นที่ของเดิมถามงาน)")
    ok("เทิร์นที่ของเดิมถามงาน ของใหม่ได้คำถามข้อแรก (งาน) ทุกเทิร์น", not bad_need, bad_need[:3])
    print(f"      25 ต.ค.: สแตนเลสข้ามแบรนด์ค้างคำถามแบรนด์ {len(cross_turns)} เทิร์น")
    ok("cross_brand ของใหม่ค้าง pending=brand ทุกเทิร์น", not bad_cross, bad_cross[:3])
    for k in diff[:5]:
        fields = [f for f in a[k] if a[k].get(f) != b[k].get(f)] if isinstance(a[k], dict) else ["text"]
        print(f"      {k}: {fields}")
        for f in fields[:2]:
            print(f"        old: {str(a[k][f] if isinstance(a[k], dict) else a[k])[:160]}")
            print(f"        new: {str(b[k][f] if isinstance(b[k], dict) else b[k])[:160]}")
    ok("ทุกเทิร์นเท่ากันทุกช่อง (action · reply · reason · payload · สถานะ)", not diff, f"ต่าง {len(diff)} เทิร์น")
    actions = {}
    for k, v in a.items():
        if isinstance(v, dict):
            actions[v["action"]] = actions.get(v["action"], 0) + 1
    exc = sorted({v["error"] for v in a.values() if isinstance(v, dict) and v["action"] == "EXCEPTION"})
    if exc:
        print(f"      หมายเหตุ: ของเดิมพัง {sum(1 for v in a.values() if isinstance(v, dict) and v['action'] == 'EXCEPTION')}"
              f" เทิร์น ด้วย {exc} — ของใหม่ต้องพังเหมือนกัน (ไม่แก้พฤติกรรมในเฟส 1)")
    ok(f"ครอบทุก action ({', '.join(f'{k} {v}' for k, v in sorted(actions.items()))})",
       {"reject_image", "smalltalk", "refuse_offtopic", "ask", "escalate", "cross_brand", "search",
        "answer"} <= set(actions))

    print("\n2) แกนกลางไม่รู้จักแบรนด์")
    sys.path.insert(0, ROOT)
    import re
    for f in sorted(os.listdir(os.path.join(ROOT, "core"))):
        if f.endswith(".py"):
            src = open(os.path.join(ROOT, "core", f), encoding="utf-8").read()
            ok(f"core/{f}", not re.search(r"movex|modutech", src, re.I))
    for b_ in ("movex", "modutech"):
        other = "modutech" if b_ == "movex" else "movex"
        bad = [f for f in os.listdir(os.path.join(ROOT, "brands", b_)) if f.endswith(".py")
               and re.search(rf"^\s*(from|import)\s+brands\.{other}\b|^\s*(from|import)\s+{other}_",
                             open(os.path.join(ROOT, "brands", b_, f), encoding="utf-8").read(), re.M)]
        ok(f"brands/{b_} ไม่ import แบรนด์อื่น", not bad, bad)

    print(f"\nรวม {passed}/{passed + failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
