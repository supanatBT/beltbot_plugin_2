#!/usr/bin/env python3
"""สร้างชุดคำถามทดสอบชั้นงานใช้/อุตสาหกรรมของกราฟ (23 ต.ค. 2026) → testcases_graph_apps.csv

ทำแบบเดียวกับ testcases_graph.py: ค่าที่คาดอ่านจากกราฟกับ JSON ไม่เขียนมือ

หมวด
  GA-F  สายพาน → งานใช้            USED_FOR ขาไป · รุ่นที่มีงานถูกตัดด้วยตัวกรองเกรด
  GA-R  งานใช้ → สายพาน            USED_FOR ขากลับ · ห้ามเสนอรุ่นที่เกรดไม่ตรง
  GA-I  งาน × อุตสาหกรรม → สายพาน  บั๊ก 23 ต.ค. — ห้ามเอารุ่นที่ทำงานนี้ในอุตสาหกรรมอื่นมาปน
  GI-B  สายพาน → อุตสาหกรรม        USED_IN
  GI-A  อุตสาหกรรม → งานใช้         HAS_APPLICATION
  GH    งาน × อุตสาหกรรม → เฟือง    ถามสองขั้น · ห้ามบอกขนาดเฟือง · รุ่นไม่มีเฟืองต้องส่งฝ่ายขาย
  GN    คู่งาน×อุตสาหกรรมที่เล่มไม่มี ต้องบอกว่าไม่มีข้อมูล ห้ามแต่งรายชื่อ

ไฟล์ที่ได้ (สคีมาเดียวกับ testcases_graph_relations.csv · รันด้วย run_answer_eval.py ได้เลย)
  testcases_graph_apps.csv          context ของบอตตอนนี้มีคำที่ต้องตอบ และไม่มีคำที่ห้ามตอบ — วัดได้ทันที
  testcases_graph_apps_pending.csv  context ตอนนี้ยังขาดคำที่ต้องตอบ หรือยื่นคำที่ห้ามตอบให้ LLM เอง
                                    ผ่านได้ต่อเมื่อต่อชั้นงานใช้ของกราฟเข้า brands/modutech/turn.py แล้ว
                                    ใช้เป็นเกณฑ์รับงานต่อกราฟ ไม่ใช่ตัววัดบอตรุ่นที่ส่ง
                                    (ช่อง description บอกว่าขาดอะไร)

รัน: python testcases_graph_apps.py [modutech_v30_3.json] [-o testcases_graph_apps.csv]
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict

import modutech_gates as mg
import modutech_router as mr
import modutech_turn as mt
from dialogue_state import DialogueManager
from modutech_kg import ModutechGraph

FIELDS = ["id", "category", "subcategory", "turn_type", "turn_number", "user_text",
          "image", "must_contain", "must_contain_any", "must_not_contain",
          "must_ask_back", "expected_value", "expected_unit", "reply_max_length",
          "metrics", "description"]
SALES_WORDS = "ฝ่ายขาย|ติดต่อ|สอบถาม|ยืนยัน"
# ไม่ใส่ "ฝ่ายขาย" — รอบแรก (graph_apps_r1) GN-01 ผ่านเพราะคำนี้โผล่ในหมายเหตุอื่น ทั้งที่ตอบผิด
NOT_FOUND_WORDS = "ไม่มีข้อมูล|ไม่พบ|ไม่ได้ระบุ|ไม่ระบุ|ไม่มีในแคตตาล็อก"


def join_limit(tokens, limit: int = 600) -> str:
    """ต่อคำด้วย | ไม่เกิน limit ตัวอักษร โดยไม่ตัดกลางคำ"""
    out, n = [], 0
    for t in tokens:
        if out and n + len(t) + 1 > limit:
            break
        out.append(t)
        n += len(t) + 1
    return "|".join(out)


def row(**kw) -> dict:
    base = {f: "" for f in FIELDS}
    base.update(turn_type="single", turn_number="1")
    base.update(kw)
    return base


def main() -> None:
    argv = sys.argv[1:]
    out_path = "testcases_graph_apps.csv"
    if "-o" in argv:                       # ตัดค่าของ -o ออกก่อน ไม่ให้กลายเป็นชื่อไฟล์ฐานข้อมูล
        i = argv.index("-o")
        out_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    path = argv[0] if argv else "modutech_v30_3.json"

    cat = mg.Catalogue(path)
    kg = ModutechGraph.from_catalogue(cat)
    search = mr.CatalogueSearch(cat)
    data = cat.data
    codes_all = sorted(cat.by_code)

    def prefix_safe(code: str) -> bool:
        """"EC508 C" เป็นสตริงย่อยของ "EC508 C-RT" — ใช้เป็นคำห้าม/คำต้องมีไม่ได้"""
        return not any(o != code and code in o for o in codes_all)

    def decide(text: str):
        return DialogueManager({}, cat, movex_materials={}).decide(text)

    def ctx_of(text: str) -> str:
        c = mt.build_modutech_turn(decide(text), cat, search, vector_search=None, kg=kg).context
        return json.dumps(c, ensure_ascii=False)

    # ข้อความถามกลับสำเร็จรูปของบอต — คำใน must_contain_any ต้องไม่อยู่ในนี้
    # รอบแรก GI-A06 ผ่านทั้งที่บอตถามกลับ เพราะข้อความถามกลับมีคำว่า "เครื่องตรวจจับโลหะ"
    import brands.modutech.plugin as _plugin
    ask_texts = " ".join(v for k, v in vars(_plugin).items() if k.startswith("ASK_") and isinstance(v, str))

    # ชื่อไทยจาก JSON
    app_th = {v["application"]: v.get("application_th") or "" for v in data.get("application_vocabulary") or []}
    ind_th: dict[str, str] = {}
    registry = {m["material_code"]: m for m in data.get("material_registry") or []}
    dropped: dict[str, list] = defaultdict(list)         # รุ่น → [(อุตสาหกรรม, งาน)] ที่ตัวกรองเกรดตัด
    for p in data["products"]:
        made = {v.get("belt_material") for v in p["specifications"]["variants"]}
        for i in p.get("industries") or []:
            ind_th[i["industry"]] = i.get("industry_th") or ""
            for a in i.get("applications") or []:
                rec = a.get("materials") or []
                if not any(m in made or any((registry.get(x) or {}).get("base_polymer") == m for x in made)
                           for m in rec):
                    dropped[p["belt_code"]].append((i["industry"], a["application"]))

    def dim_strings(codes: list) -> list:
        out: set = set()
        for c in codes:
            for v in ((cat.sprockets.get(c) or {}).get("dimensions") or {}).values():
                mm = (v or {}).get("mm") if isinstance(v, dict) else None
                if isinstance(mm, (int, float)):
                    out.add(f"{mm:g}")
                    out.add(f"{mm:g}".replace(".", ","))
        return sorted(x for x in out if len(x) >= 5)

    rows: list[dict] = []

    # ── GA-F สายพาน → งานใช้ (เลือกรุ่นที่มีงานถูกตัดด้วยเกรด ก่อนรุ่นอื่น) ──
    picks = [b for b in sorted(dropped) if prefix_safe(b)][:4]
    picks += [b for b in ("EC127 C", "MP80 C", "HD254 C") if b not in picks and prefix_safe(b)]
    for n, b in enumerate(picks[:6], 1):
        apps = kg.applications_for_belt(b)
        cut = sorted({app_th[a] for _, a in dropped.get(b, []) if a not in apps and app_th.get(a)})
        rows.append(row(
            id=f"GA-F{n:02d}", category="graph_application", subcategory="belt_to_application",
            user_text=f"{b} ใช้กับงานอะไรได้บ้าง",
            must_contain=b,
            must_contain_any=join_limit(app_th[a] for a in apps if app_th.get(a)),
            must_not_contain="|".join(cut),
            description=f"USED_FOR ขาไป — เล่มให้ {len(apps)} งาน"
                        + (f" · ห้ามเสนอ {', '.join(cut)} เพราะรุ่นนี้ไม่มีเกรดที่เล่มแนะนำ" if cut else "")))

    # ── GA-R งานใช้ → สายพาน ──────────────────────────────────
    # ข้ามงานที่บอตต้องถามเปียก/แห้งก่อนตามออกแบบ (เช่น ไลน์แช่แข็ง → GA-R03 รอบแรก)
    # คำถามแบบนั้นต้องทดสอบเป็นสองเทิร์น ไม่ใช่คำถามเดี่ยว
    cand = ["Metal Detection", "Box Handling", "Freezing Lines", "Spiral Conveyors", "Washing Lines",
            "Checkweighers", "Raw Dough Handling", "Inspection Tables"]
    want_apps = [a for a in cand if a in app_th
                 and decide(f"สายพานสำหรับงาน{app_th[a]} ใช้รุ่นไหนได้บ้าง").reason != "ต้องรู้เปียก/แห้งก่อนตอบอุณหภูมิ"][:5]
    for n, a in enumerate(want_apps, 1):
        belts = kg.belts_for_application(a)
        banned = sorted({b for b, lst in dropped.items() for _, aa in lst if aa == a
                         and b not in belts and prefix_safe(b)})
        rows.append(row(
            id=f"GA-R{n:02d}", category="graph_application", subcategory="application_to_belt",
            user_text=f"สายพานสำหรับงาน{app_th[a]} ใช้รุ่นไหนได้บ้าง",
            must_contain_any=join_limit(b for b in belts if prefix_safe(b)),
            must_not_contain="|".join(banned),
            description=f"USED_FOR ขากลับ — {a} มี {len(belts)} รุ่น"
                        + (f" · ห้ามเสนอ {', '.join(banned)} (เกรดไม่ตรง)" if banned else "")))

    # ── GA-I งาน × อุตสาหกรรม → สายพาน (คู่ที่บั๊กเดิมตอบเกิน) ────────
    n = 0
    for ind in sorted(ind_th):
        for a in kg.applications_in_industry(ind):
            right = set(kg.belts_for_application(a, ind))
            elsewhere = set(kg.belts_for_application(a)) & set(kg.belts_in_industry(ind))
            over = sorted(b for b in elsewhere - right if prefix_safe(b))
            if not right or len(over) < 3:
                continue
            n += 1
            rows.append(row(
                id=f"GA-I{n:02d}", category="graph_application", subcategory="application_in_industry",
                user_text=f"สายพานสำหรับงาน{app_th[a]}ในอุตสาหกรรม{ind_th[ind]} ใช้รุ่นไหน",
                must_contain_any="|".join(b for b in sorted(right) if prefix_safe(b)) or "|".join(sorted(right)),
                must_not_contain="|".join(over),
                description=f"งาน×อุตสาหกรรม — เล่มให้ {len(right)} รุ่น · ห้ามเอา {', '.join(over)} มาปน "
                            f"(รุ่นเหล่านี้อยู่ในอุตสาหกรรมนี้และทำงานนี้ได้ แต่เล่มไม่ได้จับคู่ในหมวดนี้)"))
            if n >= 6:
                break
        if n >= 6:
            break

    # ── GI-B สายพาน → อุตสาหกรรม ──────────────────────────────
    for n, b in enumerate(["EC127 C", "MP80 C", "HC508 C", "XP254 C"], 1):
        if b not in cat.by_code:
            continue
        inds = kg.industries_for_belt(b)
        others = sorted(ind_th[i] for i in ind_th if i not in inds)
        rows.append(row(
            id=f"GI-B{n:02d}", category="graph_industry", subcategory="belt_to_industry",
            user_text=f"{b} ใช้ในอุตสาหกรรมไหนได้บ้าง",
            must_contain="|".join([b] + [ind_th[i] for i in inds]),
            must_not_contain="|".join(others),
            description=f"USED_IN — เล่มจัด {b} ไว้ {len(inds)} อุตสาหกรรม ต้องบอกครบ ห้ามเพิ่มอุตสาหกรรมอื่น"))

    # ── GI-A อุตสาหกรรม → งานใช้ ──────────────────────────────
    for n, ind in enumerate(sorted(ind_th), 1):
        apps = kg.applications_in_industry(ind)
        rows.append(row(
            id=f"GI-A{n:02d}", category="graph_industry", subcategory="industry_to_application",
            user_text=f"อุตสาหกรรม{ind_th[ind]}มีงานอะไรบ้างที่ใช้สายพาน Modutech",
            must_contain_any="|".join(app_th[a] for a in apps if app_th.get(a)),
            description=f"HAS_APPLICATION — {ind} มี {len(apps)} งานในเล่ม"))

    # ── GH สองขั้น: งาน × อุตสาหกรรม → เฟือง ───────────────────
    hop = [("Palletizer", "Corrugated"), ("Box Handling", "Fish & Seafood"),
           ("Metal Detection", "Poultry"), ("Box Handling", "Meat Processing"), ("Down Stacker", "Corrugated")]
    for n, (a, ind) in enumerate(hop, 1):
        res = kg.sprockets_for_application(a, ind)
        if not res:
            continue
        codes = sorted({c for v in res.values() for c in v})
        nolink = sorted(b for b, v in res.items() if not v)
        rows.append(row(
            id=f"GH-{n:02d}", category="graph_two_hop", subcategory="application_to_sprocket",
            user_text=f"งาน{app_th[a]}ในอุตสาหกรรม{ind_th[ind]} ใช้สายพานกับเฟืองตัวไหน",
            must_contain_any="|".join(codes[:6]),
            must_not_contain="|".join(dim_strings(codes)),
            description=f"สองขั้น — {len(res)} รุ่น · รหัสเฟือง {len(codes)} ตัว · ห้ามบอกขนาดเฟือง"
                        + (f" · {', '.join(nolink)} เล่มไม่ผูกเฟือง ต้องบอกให้ถามฝ่ายขาย ห้ามเดา" if nolink else "")))

    # ── GN คู่ที่เล่มไม่มี ──────────────────────────────────────
    for n, (a, ind) in enumerate([("Box Handling", "Corrugated"), ("Spiral Conveyors", "Corrugated")], 1):
        if a not in app_th or kg.belts_for_application(a, ind):
            continue
        tempting = sorted(b for b in kg.belts_for_application(a) if prefix_safe(b))[:8]
        rows.append(row(
            id=f"GN-{n:02d}", category="graph_application", subcategory="pair_not_in_catalogue",
            user_text=f"สายพานสำหรับงาน{app_th[a]}ในอุตสาหกรรม{ind_th[ind]} ใช้รุ่นไหน",
            must_contain_any=NOT_FOUND_WORDS,
            description=f"เล่มไม่มี {a} ในหมวด {ind} — ต้องบอกว่าไม่มีข้อมูลคู่นี้ "
                        f"(เสนอรุ่นจากหมวดอื่นได้ถ้าบอกชัดว่ามาจากหมวดไหน) · รุ่นที่ล่อให้ตอบ: {', '.join(tempting)}"))

    # ── จัดสถานะ: วัดได้เลย หรือรอต่อกราฟ ───────────────────────
    for r in rows:
        r["must_contain_any"] = "|".join(w for w in r["must_contain_any"].split("|") if w and w not in ask_texts)
    ready = 0
    for r in rows:
        d = decide(r["user_text"])
        blob = ctx_of(r["user_text"])
        need_all = [w for w in r["must_contain"].split("|") if w]
        need_any = [w for w in r["must_contain_any"].split("|") if w]
        bad = [w for w in r["must_not_contain"].split("|") if w and w in blob]
        miss = [w for w in need_all if w not in blob]
        any_ok = not need_any or any(w in blob for w in need_any)
        ok = not bad and not miss and any_ok
        if d.action == "ask":
            # บอตถามกลับทั้งที่คำถามระบุพอแล้ว = บั๊กของบอต ไม่ใช่ของเคส — เก็บไว้ในไฟล์หลักให้ตก
            r["description"] += f" · บอตตอนนี้ถามกลับก่อน ({d.reason}) คาดว่าข้อนี้ตกจนกว่าจะแก้"
        ready += ok
        why = "" if ok else " (" + "; ".join(filter(None, [
            f"context ยื่นคำห้าม {bad[:3]}" if bad else "",
            f"context ขาด {miss[:3]}" if miss else "",
            "context ไม่มีคำตอบที่ต้องการ" if not any_ok else ""])) + ")"
        r["description"] = ("[พร้อม] " if ok else "[รอต่อกราฟ] ") + r["description"] + why

    # ไฟล์หลักเก็บเฉพาะเคสที่วัดบอตตอนนี้ได้ — รันได้แบบเดียวกับ testcases_graph_relations.csv
    # เคสที่รอต่อกราฟแยกไฟล์ ไม่ให้ไปกดคะแนนบอตรุ่นที่ส่งด้วยงานที่ยังไม่ได้ทำ
    pending_path = out_path.replace(".csv", "_pending.csv")
    groups = {out_path: [], pending_path: []}
    for r in rows:
        ok = r["description"].startswith("[พร้อม] ")
        r = dict(r, description=r["description"].split("] ", 1)[1])
        groups[out_path if ok else pending_path].append(r)
    for path_, rs in groups.items():
        with open(path_, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(rs)

    for path_, rs in groups.items():
        cnt: dict[str, int] = defaultdict(int)
        for r in rs:
            cnt[r["subcategory"]] += 1
        print(f"เขียน {path_} — {len(rs)} เคส")
        for k in sorted(cnt):
            print(f"  {k:<26} {cnt[k]}")
    print(f"\nรันกับบอต (เกณฑ์ผ่าน: ไฟล์หลักครบทุกข้อ):")
    print(f"  python run_answer_eval.py --module assistant --testcases {out_path} -o graph_apps_r1.json")
    print(f"หลังต่อกราฟเข้า turn.py แล้ว ให้รันไฟล์ {pending_path} ด้วย")


if __name__ == "__main__":
    main()
