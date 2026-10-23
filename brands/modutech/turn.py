"""
modutech_turn.py
================
ประกอบ context + system prompt ของฝั่ง Modutech หนึ่งเทิร์น (ไม่เรียก LLM เอง)

chatbot_v5.py เรียก build_modutech_turn() แล้วส่ง prompt เข้า Gemini
แยกออกมาเพื่อให้แชต C เทสต์ได้ว่า "LLM เห็นอะไร" โดยไม่ต้องมีโมเดล
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.protocol import Decision   # ชนิดเท่านั้น — รับทั้ง Decision ของแกนกลางและรูปเดิม
from brands.modutech.gates import Catalogue, Slots, run_gates, sprocket_gate
from brands.modutech.router import CatalogueSearch, ExploratoryQuery, NO_ABSENCE_NOTE_TH

SPROCKET_TOPIC = r"สเตอร์|เฟือง|sprocket|จำนวนฟัน"

# ถามหารุ่นอื่นในซีรีส์เดียวกัน — ตอบได้จากกราฟเท่านั้น
# record ของสายพานมีแต่ชื่อซีรีส์ ไม่มีรายชื่อสมาชิก ก่อนต่อกราฟจึงตอบคำถามนี้ไม่ได้เลย
SERIES_TOPIC = (r"ซีรีส์|series|รุ่นอื่น|รุ่นไหนอีก|ทางเลือก|แทนกันได้|ใช้แทน|"
                r"คล้ายกัน|ตระกูลเดียวกัน|พิทช์เดียวกัน|ระยะพิทช์เท่ากัน")

MAX_FULL_RECORDS = 8     # รุ่นที่แนบ record เต็ม (ที่เหลืออยู่ใน belt_codes_complete)
MAX_INDUSTRY_RECORDS = 5  # งานที่เล่มไม่มี (industry_match) — กฎให้ตอบไม่เกิน 5 รุ่น แนบเกินไปแค่ทำ prompt ยาว
MAX_SERIES_LISTED = 24   # ซีรีส์ที่ใหญ่สุดมี 21 รุ่น เผื่อไว้เล็กน้อย

# เฟส 2 (10 ต.ค.): ข้อเท็จจริงล้วน — คำสั่ง "ห้ามสรุปว่าใช้แทนกันได้" อยู่ในส่วนกฎของ prompt แล้ว
SAME_SERIES_NOTE_TH = (
    "รายชื่อนี้คือรุ่นที่แคตตาล็อกจัดอยู่ในซีรีส์เดียวกัน ใช้ระยะพิทช์เดียวกันและสเตอร์ชุดเดียวกัน "
    "แต่ผิว ความแข็งแรง พื้นที่เปิด และช่วงอุณหภูมิต่างกันในแต่ละรุ่น จึงยังสรุปไม่ได้ว่าใช้แทนกันได้ "
    "ถ้าสนใจรุ่นใดให้ดึงสเปกรุ่นนั้นมาเทียบ")

# คำในคำถาม → คำในชื่อเกรดพิเศษ (material_registry.name) ที่ควรขึ้นก่อนใน industry_match (รอบ 3 · AP-004)
_GRADE_HINTS = [(re.compile(r"ตัด|แล่|บาด|หั่น|สไลซ์|เลาะ|cut|slic", re.I), re.compile(r"cut", re.I)),
                (re.compile(r"กระแทก|impact", re.I), re.compile(r"impact", re.I)),
                (re.compile(r"ร้อน|ต้ม|ลวก|hot", re.I), re.compile(r"hot|high temperature", re.I))]


def _grade_hint(text: str):
    return next((g for q, g in _GRADE_HINTS if q.search(text or "")), None)


# คำสั่งถึง LLM ที่เคยปนอยู่ในข้อมูลสินค้า (forbidden_th ของเล่ม · gate_rules_th ของเกต)
# ย้ายออกจาก Context มาไว้ในส่วนกฎ — ข้อความใน Context LLM เล่าต่อให้ลูกค้า ส่วนกฎไม่เคยหลุด
# (FINDING_prompt_leak_sources.md)
_RULE_KEYS = ("forbidden_th", "gate_rules_th", "_gate_rules_th")


def _pull_rules(items: list, key: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in items or []:
        bucket = out.setdefault(str(it.get(key) or "?"), [])
        for k in _RULE_KEYS:
            for r in it.pop(k, None) or []:
                if r not in bucket:
                    bucket.append(r)
    return {k: v for k, v in out.items() if v}


def same_series_codes(kg, cat: Catalogue, codes: list) -> list:
    """รุ่นอื่นในซีรีส์เดียวกัน ใช้ได้กับกราฟทั้งสองแบบ (เหมือน sprocket_to_belts)"""
    out: list = []
    for c in codes:
        rec = cat.by_code.get(c)
        if getattr(kg, "accepts_belt_codes", False):        # ModutechGraph
            got = kg.get_same_series(c)
        else:                                              # KnowledgeGraph จากไฟล์ .db
            pid = (rec or {}).get("belt_code_id") or c
            try:
                ctx = kg.expand_products([pid], include_same_series=True,
                                         include_compatible=False, include_same_material=False)
            except Exception:                              # noqa: BLE001
                continue
            got = [cat.by_id[i]["belt_code"] for i in (getattr(ctx, "same_series", []) or [])
                   if i in cat.by_id]
        for b in got:
            if b not in out and b not in codes:
                out.append(b)
    return sorted(out)


def sprocket_to_belts(kg, cat: Catalogue, codes: list) -> list:
    """รหัสสเตอร์ → รหัสสายพาน ใช้ได้กับกราฟทั้งสองแบบ

    แยกชนิดด้วยธง accepts_belt_codes ไม่ใช่ hasattr เพราะ KnowledgeGraph มีเมธอดชื่อเดียวกัน
    หลายตัว การเดาจากชื่อเมธอดจะเข้าสาขาผิดแล้วคืน [] เงียบ ๆ

    ทำไมต้องมีชั้นนี้: กราฟมาได้สองทาง และคืนค่าคนละอย่าง
      · KnowledgeGraph.load_from_db("modutech_kg.db")  — แบบเดียวกับ Movex
        โหนดสายพานใช้ belt_code_id เป็น id จึงคืน belt_code_id
      · ModutechGraph.from_catalogue(cat)  — สร้างสดจาก JSON
        คืน belt_code ตรง ๆ
    ถ้าไม่แปลงให้เป็นแบบเดียวกัน cat.records() จะหารุ่นไม่เจอแล้วได้ products = []
    ซึ่งดูเหมือนว่า "เล่มไม่มีข้อมูล" ทั้งที่จริงคือคีย์ไม่ตรง
    """
    if getattr(kg, "accepts_belt_codes", False):          # ModutechGraph
        return kg.resolve_sprocket_to_belts(codes)

    out: list = []
    for c in codes:                                       # KnowledgeGraph จากไฟล์ .db
        try:
            ctx = kg.expand_products([c], include_compatible=True,
                                     include_same_series=False, include_same_material=False)
        except Exception:                                 # noqa: BLE001
            continue
        for pid in getattr(ctx, "compatible_products", []) or []:
            rec = cat.by_id.get(pid)
            code = rec["belt_code"] if rec else (pid if pid in cat.by_code else None)
            if code and code not in out:
                out.append(code)
    return out


@dataclass
class ModutechTurn:
    system_prompt: str
    user_prompt: str
    context: dict
    ask_back: list = field(default_factory=list)
    belt_codes: list = field(default_factory=list)
    debug: list = field(default_factory=list)


def build_modutech_turn(decision: Decision, cat: Catalogue, search: CatalogueSearch,
                        vector_search: Optional[Callable[[str], list[str]]] = None,
                        kg=None) -> ModutechTurn:
    """
    vector_search(query) -> [belt_code_id, ...] ใช้เมื่อไม่มีรหัสในบทสนทนา (คำถามเชิงการใช้งาน)
    kg = ModutechGraph (ไม่ส่งมาก็ทำงานได้ แค่ตอบรหัสสเตอร์เดี่ยว ๆ ไม่ได้)

    ลำดับการหารุ่น: รหัสสายพานที่พิมพ์มา → รหัสสเตอร์แปลงกลับด้วยกราฟ →
    จับจากการใช้งาน → ค้นเวกเตอร์ เรียงจากแน่นอนที่สุดไปคลุมเครือที่สุด
    """
    # แกนกลางเก็บข้อมูลของแบรนด์ใน payload · ทางเข้าชื่อเดิม (ชุดเกต) ใช้ .modutech — รับทั้งสองแบบ
    md = getattr(decision, "payload", None) or getattr(decision, "modutech", None) or {}
    slots = Slots(**{k: v for k, v in (md.get("slots") or {}).items()
                     if k in ("wet_or_dry", "material", "line_shape", "operating_temp_c")})
    debug: list[str] = []
    context: dict = {}

    # ── คำถามเชิงสำรวจ: ผลค้นครบทั้งฐาน ──
    if decision.action == "search":
        q = ExploratoryQuery(**md["search_query"])
        sr = search.search(q)
        # รอบ 5 (EX-004 · EX-006): คำถามค้นไม่มีชื่อแบรนด์ LLM ตอบ "68 รุ่นในฐานข้อมูล" ลูกค้าไม่รู้ว่าแบรนด์ไหน
        context["search_result"] = {"scope_th": f"ค้นจากสายพาน Modutech ทั้ง {sr['scanned']} รุ่น", **sr}
        if decision.sales_topics:
            context["sales_topics"] = decision.sales_topics
        debug.append(f"search: {context['search_result']['matched']}/{context['search_result']['scanned']}")
        return ModutechTurn(_system_prompt(context, {}), decision.effective_text, context, debug=debug)

    # ── รุ่นที่อยู่ในความสนใจ ──
    codes = list(md.get("codes") or [])
    from_vector = False
    full_list: list[str] = []

    # ── ลูกค้าพิมพ์รหัสสเตอร์มาเดี่ยว ๆ → ถามกลับด้วยกราฟว่าใช้กับสายพานรุ่นไหน ──
    # ก่อนมีตรงนี้ รหัสที่ลูกค้าพิมพ์หายไปทั้งตัว: router จับได้ว่าเป็นรหัสสเตอร์
    # แต่ไม่มีใครแปลงกลับ สุดท้าย products = [] และ LLM ไม่มีอะไรให้ตอบ
    spr_codes = [c for c in (md.get("sprocket_codes") or []) if c in cat.sprockets]
    if not codes and spr_codes:
        if kg is not None:
            codes = sprocket_to_belts(kg, cat, spr_codes)[:MAX_FULL_RECORDS]
            debug.append(f"sprocket→belt (graph): {spr_codes} → {len(codes)} รุ่น")
        else:
            debug.append(f"sprocket→belt: ข้ามเพราะไม่ได้ส่ง kg มา ({spr_codes})")
        context["sprocket_query"] = {
            "sprocket_codes": spr_codes,
            "resolved_belt_codes": list(codes),
            "note_th": ("ลูกค้าถามจากรหัสสเตอร์ รายชื่อสายพานนี้มาจากตารางความเข้ากันได้ในเล่ม"
                        if codes else
                        "เล่มไม่ได้ผูกรหัสสเตอร์นี้กับสายพานรุ่นใด ต้องสอบถามฝ่ายขาย"),
        }

    if not codes:
        am = search.match_application(decision.effective_text)
        if am is not None:
            full_list = am.belt_codes
            codes = am.belt_codes[:MAX_FULL_RECORDS]
            context["application_match"] = {
                "applications": am.applications,
                "industry": am.industry if am.industry_filter_applied else None,
                "belt_codes_complete": am.belt_codes,
                "materials_by_belt": am.materials_by_belt,
                **({"grade_notes_th": am.grade_notes_th} if am.grade_notes_th else {}),
                "note_th": (f"รายชื่อนี้ครบทุกรุ่น ({len(am.belt_codes)} รุ่น) ที่แคตตาล็อกระบุว่าใช้กับงานนี้"
                            + (f" ในอุตสาหกรรม {am.industry}" if am.industry_filter_applied else "")
                            + " เกรดวัสดุของแต่ละรุ่นคือเกรดที่แคตตาล็อก 2026 ระบุ"
                            + " ถ้าลูกค้าถามว่ามีรุ่นไหนบ้าง ให้ตอบครบทุกรุ่นพร้อมเกรดวัสดุ"
                            + (f" (รายละเอียดเต็มแนบมา {MAX_FULL_RECORDS} รุ่นแรก)" if len(am.belt_codes) > MAX_FULL_RECORDS else "")),
            }
            debug.append(f"application: {am.applications} → {len(am.belt_codes)} รุ่น")
        else:
            im = search.match_industry(decision.effective_text)
            if im is not None:
                industry, by_belt = im
                full_list = list(by_belt)
                # รุ่นที่ผลิตในเกรดที่ชื่อตรงกับสิ่งที่ถาม (ตัด/แล่/บาด → Cut Resistant) ขึ้นก่อน แล้วค่อยลำดับเวกเตอร์
                # รอบ 4 (11 ต.ค. · AP-004): ดูจากเกรดที่ผลิตจริงของรุ่นนั้นเท่านั้น — เลิกอ่าน key_features
                # เพราะ HC508 C เขียนถึงตัวเลือกทนการบาดของทั้งแพลตฟอร์ม (ซึ่งผลิตจริงแค่ใน HC508 C-MTW)
                # LLM จึงจัด HC508 C ไว้ใต้หัวข้อ "เกรด CR" ทั้งที่ผลิตแค่ PE/PP/POM
                hint = _grade_hint(decision.effective_text)
                names = search.grade_names(g for apps in by_belt.values() for a in apps for g in a["grades"])
                grade_match = {}
                if hint:
                    made_names = search.grade_names(g for c in full_list for g in search._made(c))
                    for c in full_list:
                        gs = [g for g in sorted(search._made(c)) if hint.search(made_names.get(g, ""))]
                        if gs:
                            grade_match[c] = [f"{g} ({made_names[g]})" for g in gs]
                hinted = list(grade_match)
                # รุ่นที่ผลิตเกรดนี้แต่เล่มไม่ได้ระบุสำหรับอุตสาหกรรมนี้ — กัน LLM สรุปว่า "แคตตาล็อกไม่มีเกรดนี้เลย"
                elsewhere = []
                if hint:
                    all_codes = [p["belt_code"] for p in cat.products if p["belt_code"] not in by_belt]
                    other_names = search.grade_names(g for c in all_codes for g in search._made(c))
                    elsewhere = [c for c in all_codes
                                 if any(hint.search(other_names.get(g, "")) for g in search._made(c))]
                ranked: list[str] = []
                if vector_search is not None:   # ใช้เวกเตอร์จัดลำดับ แต่เหลือเฉพาะรุ่นของอุตสาหกรรมนี้
                    ranked = [cat.by_id[i]["belt_code"] for i in vector_search(decision.effective_text)
                              if i in cat.by_id and cat.by_id[i]["belt_code"] in by_belt]
                order = list(dict.fromkeys(hinted + ranked + full_list))
                codes = order[:MAX_INDUSTRY_RECORDS]
                context["industry_match"] = {
                    "industry": industry,
                    "belt_codes_complete": full_list,
                    # ย่อเป็นข้อความต่อรุ่น — 34 รุ่นแบบ JSON ซ้อนกินพื้นที่ prompt เกือบ 10k ตัวอักษร
                    "applications_by_belt": {c: " · ".join(f"{a['application_th']} ({', '.join(a['grades'])})"
                                                           for a in apps) for c, apps in by_belt.items()},
                    **({"grade_names": names} if names else {}),
                    **({"grade_match": {
                        "belts": grade_match,
                        "note_th": (f"รุ่นที่ผลิตในเกรดที่ชื่อตรงกับเรื่องที่ถามมี {len(grade_match)} รุ่นตามรายการนี้ "
                                    "รุ่นอื่นในรายชื่ออุตสาหกรรมไม่มีเกรดนี้" if grade_match else
                                    "ไม่มีรุ่นใดในรายชื่ออุตสาหกรรมนี้ที่ผลิตในเกรดที่ชื่อตรงกับเรื่องที่ถาม"),
                        **({"other_industry_belts": elsewhere,
                            "other_industry_note_th": (f"รุ่นเหล่านี้ผลิตในเกรดที่ชื่อตรงกับเรื่องที่ถาม แต่แคตตาล็อกไม่ได้ระบุ"
                                                       f"สำหรับอุตสาหกรรม {industry}")} if elsewhere else {}),
                    }} if hint else {}),
                    "note_th": (f"แคตตาล็อกไม่มีงานที่ตรงกับคำถามนี้โดยตรง รายชื่อนี้คือทุกรุ่น ({len(full_list)} รุ่น) "
                                f"ที่แคตตาล็อกระบุสำหรับอุตสาหกรรม {industry} พร้อมงานใช้และเกรดตามเล่ม "
                                f"(รายละเอียดเต็มแนบมา {len(codes)} รุ่น)"),
                }
                debug.append(f"industry: {industry} → {len(full_list)} รุ่น")
    if not codes and vector_search is not None:
        ids = vector_search(decision.effective_text)
        codes = [cat.by_id[i]["belt_code"] for i in ids if i in cat.by_id]
        from_vector = True
        debug.append(f"vector: {codes}")
    records = cat.records(codes)

    gated = run_gates(records, slots)
    context["products"] = gated.products
    context["slots_known"] = {k: v for k, v in (md.get("slots") or {}).items() if v is not None}
    if decision.sales_topics:
        context["sales_topics"] = decision.sales_topics
    if gated.ask_back:
        context["slots_missing_th"] = [SLOT_TH.get(s, s) for s in gated.ask_back]
    if from_vector:
        context["retrieval_note_th"] = NO_ABSENCE_NOTE_TH.format(n=len(records), total=len(cat.products))

    # ถามด้วยคำว่าสเตอร์ หรือพิมพ์รหัสสเตอร์มาตรง ๆ ก็ต้องได้รายละเอียดสเตอร์เหมือนกัน
    # (รหัสที่พิมพ์มาอาจไม่มีคำว่า "สเตอร์" อยู่ในประโยคเลย)
    asks_sprocket = bool(re.search(SPROCKET_TOPIC, decision.effective_text, re.IGNORECASE)) \
        or bool(spr_codes)
    if asks_sprocket and codes and not full_list:
        links = [cat.links[c] for c in codes if c in cat.links]
        # สายพานหลายรุ่นในซีรีส์เดียวกันใช้สเตอร์ชุดเดียวกัน ถ้าไม่กันซ้ำ
        # สเตอร์ตัวเดียวจะถูกส่งเข้า prompt เท่าจำนวนสายพาน แล้ว LLM อาจนับว่ามีหลายตัว
        seen: set = set()
        sp = [s for l in links for c in l["sprocket_codes"]
              for s in (cat.sprockets[c],)
              if c in cat.sprockets and not (c in seen or seen.add(c))]
        # ถ้าลูกค้าระบุรหัสสเตอร์มา ให้เหลือเฉพาะตัวนั้น ไม่ต้องเทมาทั้งซีรีส์
        if spr_codes:
            sp = [s for s in sp if s["sprocket_code"] in spr_codes] or \
                 [cat.sprockets[c] for c in spr_codes]
        context["sprockets"] = sprocket_gate(sp, links).products
        if not links:
            context["sprocket_note_th"] = "เล่มไม่ได้ระบุสเตอร์ของรุ่นนี้ ต้องสอบถามฝ่ายขาย"

    # ── รุ่นอื่นในซีรีส์เดียวกัน — แนบเฉพาะเมื่อถาม ──
    # ไม่แนบทุกครั้งเพราะซีรีส์ใหญ่สุดมี 21 รุ่น จะกิน context ไปเปล่า ๆ
    # ในคำถามที่ไม่เกี่ยวและทำให้ LLM เอาไปพูดถึงโดยไม่มีใครถาม
    if kg is not None and codes and not full_list and \
            re.search(SERIES_TOPIC, decision.effective_text, re.IGNORECASE):
        sib = same_series_codes(kg, cat, codes)[:MAX_SERIES_LISTED]
        context["same_series"] = {
            "of_belt_codes": list(codes),
            "belt_codes": sib,
            "note_th": SAME_SERIES_NOTE_TH if sib else
                       "แคตตาล็อกไม่มีรุ่นอื่นในซีรีส์นี้",
        }
        debug.append(f"same_series: {len(sib)} รุ่น")

    debug += [f"{d.gate}:{d.belt_code}:{d.action}" for d in gated.decisions if d.action != "keep"][:20]
    rules = _pull_rules(context.get("products"), "belt_code")
    for k, v in _pull_rules(context.get("sprockets"), "sprocket_code").items():
        rules.setdefault(k, []).extend(v)
    return ModutechTurn(_system_prompt(context, rules), decision.effective_text, context,
                        ask_back=gated.ask_back, belt_codes=codes, debug=debug)


SLOT_TH = {"wet_or_dry": "ไลน์เปียกหรือแห้ง", "line_shape": "ไลน์ตรงหรือมีโค้ง", "material": "เกรดวัสดุ"}


def _system_prompt(context: dict, rules: dict[str, list[str]]) -> str:
    # 11 ต.ค. วัดด้วย training/latency_probe.py (20 prompt จริง): JSON ไม่เว้นวรรค prompt เล็กลง ~20% ·
    # token ที่โมเดลใช้คิดลดลง (มัธยฐาน 779 → 514) · เร็วขึ้น 0.7 วินาที (15/20 ข้อ) · คุณภาพเท่าเดิม 20/20
    ctx = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    per_belt = "".join(f"\n- {code}: {r}" for code, rs in rules.items() for r in rs)
    rules_block = (f"\n\nกฎเฉพาะรุ่นในคำถามนี้ (ใช้ตัดสินใจ ไม่ต้องยกข้อความในส่วนนี้ไปเขียนในคำตอบ){per_belt}"
                   if per_belt else "")
    return f"""
คุณคือ 'Modutech Assistant' วิศวกรฝ่ายขายสายพานโมดูลาร์ Modutech
ตอบภาษาไทย เป็นธรรมชาติ มีหางเสียง (ครับ)

[Context — ผ่านการคัดกรองจากระบบแล้ว]
{ctx}

กฎ
- ตัวเลขทุกตัวต้องมาจาก Context เท่านั้น ถ้าไม่มีใน Context แปลว่าระบบยังตอบไม่ได้ ห้ามเดาหรือใช้ความรู้ทั่วไป
- ค่าที่ขึ้นกับเกรดวัสดุ (ความแข็งแรง น้ำหนัก อุณหภูมิ) ต้องบอกเกรดกำกับทุกครั้ง ห้ามรวมเป็นค่าเดียว
- บอกหมายเหตุใน gate_notes_th และ note_th ให้ลูกค้าทราบเป็นข้อเท็จจริง ไม่ต้องเอ่ยถึง "ระบบ"
- ปฏิบัติตามกฎเฉพาะรุ่นท้ายข้อความนี้เสมอ
- temperature_answer ที่ status ไม่ใช่ "ok" ให้บอกคำเตือนใน note_th หรือบอกว่าต้องยืนยันกับพนักงานฝ่ายขาย
- temperature_answer ให้ค่าเฉพาะสภาวะใน condition ถ้าไม่มีค่าของอีกสภาวะใน Context ห้ามบอกว่าแคตตาล็อกไม่มีข้อมูลสภาวะนั้น
  condition = "dry_and_wet" แปลว่าแคตตาล็อกให้ค่าเดียวกันทั้งสภาวะแห้งและเปียก ให้บอกว่าค่านี้ใช้ได้ทั้งสองสภาวะ
  ให้บอกว่าถ้าไลน์เป็นอีกสภาวะ สอบถามเพิ่มได้
- ถ้ามี slots_missing_th และลูกค้าถามเรื่องที่ต้องใช้ข้อมูลนั้น ให้ถามกลับเฉพาะข้อนั้น
- ถ้ามี retrieval_note_th ห้ามสรุปว่า "ไม่มี" หรือ "สูงสุดคือ" และห้ามพูดราวกับว่ารายการครบ — ให้เรียก search_catalogue
- ถ้ามี application_match ใช้ belt_codes_complete เป็นรายการครบ ห้ามตัดรุ่นทิ้งเมื่อลูกค้าถามว่ามีรุ่นไหนบ้าง
  ถ้ารุ่นใดมี grade_notes_th ต้องบอกหมายเหตุนั้นกับรุ่นนั้นด้วยเสมอ
- เรื่องใดที่ Context ไม่มีข้อมูล (เช่น wet_data = "no_data") ให้บอกว่าแคตตาล็อกไม่มีข้อมูล ห้ามสรุปเองว่าเหมาะหรือไม่เหมาะ
- ห้ามอ้างคุณสมบัติหรือความเหมาะสมที่ Context ไม่ได้เขียนไว้ (เช่น ทนแรงกระแทก ทนการบาด เหมาะกับงานตัด)
  ถ้าลูกค้าถามเรื่องที่ Context ไม่มี ให้บอกว่าข้อมูลที่ตอบได้ตอนนี้ไม่ได้ระบุ แนะนำให้สอบถามฝ่ายขาย
  ห้ามบอกว่าแคตตาล็อกไม่มีข้อมูลเรื่องนั้น เพราะ Context เป็นเพียงบางส่วนของแคตตาล็อก
- ถ้ามี industry_match ให้บอกลูกค้าก่อนว่าแคตตาล็อกไม่มีงานนี้โดยตรง แล้วตอบจากรายชื่อของอุตสาหกรรมนั้น
  พร้อมงานใช้และเกรดที่เล่มระบุ (applications_by_belt) ถ้ามี grade_match ให้บอกรุ่นใน grade_match.belts พร้อมเกรดนั้นก่อน
  รุ่นอื่นแคตตาล็อก 2026 ไม่ได้ระบุเกรดนั้น ห้ามจัดรุ่นอื่นไว้ใต้หัวข้อหรือประโยคที่พูดถึงเกรดนั้น ให้แยกเป็นหัวข้อรุ่นอื่นในอุตสาหกรรมเดียวกัน
  ถ้า grade_match.belts ว่าง ให้บอกตาม note_th ห้ามสรุปเองว่ารุ่นใดเหมาะกับงานที่ถามเกินกว่าที่เล่มระบุ
  ตอบกระชับ: รุ่นที่เกี่ยวข้องที่สุดไม่เกิน 5 รุ่นพร้อมงานใช้ ที่เหลือบอกเป็นรายชื่อบรรทัดเดียว
- ถ้ามี application_match หรือ industry_match และลูกค้าไม่ได้ถามเรื่องอุณหภูมิ ไม่ต้องถามกลับเรื่องไลน์เปียกหรือแห้ง
- search_result คือผลค้นครบทั้งฐาน รายงานทุกรุ่นที่ตรง ถ้า matched = 0 บอกได้ว่าไม่มีรุ่นที่ตรงเงื่อนไข
  บอกชื่อแบรนด์ตาม scope_th ในคำตอบด้วยเสมอ (เช่น "สายพาน Modutech …")
- รหัสสเตอร์เป็นการอนุมานจากซีรีส์ ต้องบอกให้ยืนยันกับฝ่ายขาย ขนาดสเตอร์/รูเพลาให้ส่งฝ่ายขาย
- ถ้ามี sprocket_query คือลูกค้าถามจากรหัสสเตอร์ ให้ตอบด้วย resolved_belt_codes ทุกรุ่น
  ถ้า resolved_belt_codes ว่าง ห้ามเดาจากรูปแบบรหัส ให้บอกตาม note_th แล้วส่งฝ่ายขาย
- ถ้ามี same_series ให้บอกรายชื่อใน belt_codes ตามที่มี ห้ามเพิ่มรุ่นที่ไม่อยู่ในรายการ
  และต้องปฏิบัติตาม note_th — ห้ามสรุปว่าใช้แทนกันได้ในงานของลูกค้า
- ห้ามรับปากว่าจะส่งเรื่องต่อ ประสานงาน หรือให้ฝ่ายขายติดต่อกลับ — คุณไม่มีช่องทางทำสิ่งนั้น
  หน้าที่คือให้ข้อมูลสเปกและบอกช่องทางติดต่อ ลูกค้าเป็นคนติดต่อฝ่ายขายเอง
  ห้ามขอให้ลูกค้าฝากเบอร์หรืออีเมลไว้ในแชต เพราะไม่มีใครมาอ่าน
- ราคา lead time MOQ สต็อก อะไหล่ ความกว้างนอกมาตรฐาน รัศมีวงเลี้ยว: ห้ามให้ตัวเลขหรือรับปาก
  ถ้าชวนลูกค้าถามความกว้างที่ไม่อยู่ในรายการ ต้องบอกว่าต้องสอบถามฝ่ายขาย
  ถ้ามี sales_topics ใน Context ระบบจะแนบข้อความส่งต่อฝ่ายขายท้ายคำตอบเอง ให้ตอบเฉพาะส่วนสเปก ไม่ต้องพูดถึงเรื่องนั้น
- ตอบกระชับ ถ้าหลายรุ่นให้ทำเป็นรายการสั้น{rules_block}
"""


def make_search_tool(search: CatalogueSearch, tracked: Optional[Callable] = None):
    """เครื่องมือให้ Gemini เรียกค้นทั้งฐานเอง (function calling)"""
    def search_catalogue(field: str = "", op: str = ">=", value: float = 0.0,
                         surface: str = "", pin_material: str = "", belt_material: str = "") -> str:
        """
        ค้นสายพาน Modutech ทั้ง 68 รุ่นตามเงื่อนไข คืนทุกรุ่นที่ตรง (ไม่ใช่แค่ 5 อันดับ)

        Parameters
        ----------
        field         : "strength" (N/m) | "weight" (kg/m²) | "open_area" (%) | "pitch" (mm) | "" ไม่กรองตัวเลข
        op            : ">=" | "<="
        value         : ค่าตัวเลขของเงื่อนไข
        surface       : ชื่อผิวภาษาอังกฤษ เช่น "Roller Top", "Flush Grid" ("" = ไม่กรอง)
        pin_material  : เช่น "SS" ("" = ไม่กรอง)
        belt_material : เช่น "POM", "PP", "PE" ("" = ไม่กรอง)
        """
        q = ExploratoryQuery(field=field or None, op=op or ">=",
                             value=value if field else None, surface=surface or None,
                             pin_material=pin_material or None, belt_material=belt_material or None)
        if q.is_empty():
            return "ต้องระบุเงื่อนไขอย่างน้อยหนึ่งข้อ"
        return json.dumps(search.search(q), ensure_ascii=False)
    return tracked(search_catalogue) if tracked else search_catalogue