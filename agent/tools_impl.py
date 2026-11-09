"""
agent/tools_impl.py — เครื่องมือของ agent เทียบ (Modutech · ขั้นที่ 1)

หลักของการเทียบ (claude/… แผน agent-baseline · 1 พ.ย. 2026)
  · ข้อมูลชุดเดียวกับบอทหลัก: data/modutech_v30_3.json (r4 ใช้ data/modutech_v31.json ผ่าน AGENT_MODUTECH_JSON) · กราฟจาก JSON · คอลเลกชัน modutech_live (อ่านอย่างเดียว)
  · เครื่องมือคืน "ข้อมูลดิบ + ธง + กฎในข้อมูล" แต่ "ไม่บังคับกฎ"
      เช่น temperature() คืนทั้งค่าเปียกและแห้ง ไม่ถามก่อน · lookup_belt() คืนค่าที่ติดธงด้วย
    ถ้าเครื่องมือบังคับกฎเอง = เอาเกตของบอทหลักไปซ่อนในเครื่องมือ การเทียบจะไม่มีความหมาย
  · search_catalogue = ตัวเดียวกับที่บอทหลักให้ LLM เรียก (make_search_tool) ห้ามเสริมตัวกรองให้ agent ฝ่ายเดียว
  · ไม่แตะไฟล์ใดเลย (อ่านอย่างเดียว) · ไม่แตะ collection ของ Movex

ฟังก์ชันในไฟล์นี้เป็น Python ล้วน — mcp_server.py ห่อเป็นเครื่องมือ MCP · ทดสอบได้โดยไม่ต้องมี MCP/ADK
ส่วนที่ต้องโหลดโมเดล (ค้นเวกเตอร์ · เทียบรูป) โหลดตอนเรียกครั้งแรก ถ้าโหลดไม่ได้ คืนข้อความบอกเหตุ ไม่ล้ม
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from functools import lru_cache
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brands.modutech.gates import Catalogue                      # noqa: E402
from engine.brands.modutech.kg import ModutechGraph                       # noqa: E402
from engine.brands.modutech.router import CatalogueSearch, CodeResolver   # noqa: E402
from engine.brands.modutech.turn import graph_application_match, make_search_tool  # noqa: E402

CATALOGUE_PATH = os.environ.get("AGENT_MODUTECH_JSON", os.path.join(ROOT, "data/modutech_v30_3.json"))
IMAGE_DIR = os.environ.get("AGENT_IMAGE_DIR", os.path.join(ROOT, "agent", "_images"))


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


@lru_cache(maxsize=1)
def _state():
    cat = Catalogue(CATALOGUE_PATH)
    # ค้นทั้งฐานตัวเดียวกับบอทหลัก (brands/modutech/plugin.make_catalogue_search):
    # กรองด้วย Payload/Range Filter ของ Qdrant · MODUTECH_SEARCH_ENGINE=python = แบบเดิม · ผลเท่ากันทุกตัวอักษร
    from engine.brands.modutech.plugin import make_catalogue_search
    search = make_catalogue_search(cat)
    kg = ModutechGraph.from_catalogue(cat)
    return cat, search, kg, CodeResolver(cat), make_search_tool(search)


def _resolve_belt(code: str) -> tuple[Optional[str], list[str]]:
    cat, _s, _k, res, _t = _state()
    if code in cat.by_code:
        return code, []
    m = res.resolve(code or "")
    if m.belt_codes:
        return m.belt_codes[0], []
    return None, list(m.candidates)


def _not_found(code: str, candidates: list[str]) -> str:
    return _dump({"error": f"ไม่พบรหัสสายพาน {code!r} ในฐานข้อมูล Modutech",
                  "candidates": candidates[:12],
                  "hint": "ถ้ามี candidates ให้ถามลูกค้าว่าหมายถึงรุ่นไหน ห้ามเลือกเอง"})


def _send_conflict() -> bool:
    return (os.environ.get("AGENT_PROMPT") or "r3").strip().lower() not in ("", "r1", "r2", "r2m")


def _v31() -> bool:
    """r4 (9 พ.ย.) = ฐาน v31 · ส่งฟิลด์โครงสร้างของกฎ R1–R11 แทนกฎข้อความ (answering / data_quality ดิบ)
    r1–r3 ส่งเหมือนเดิมทุกตัวอักษร — ผลของรอบเดิมรันซ้ำได้"""
    return (os.environ.get("AGENT_PROMPT") or "r3").strip().lower() == "r4"


def _width_v31(we: dict) -> dict:
    """R5: ค่าเพิ่มทีละส่งเฉพาะเมื่อ increment_status = match / not_printed · ค่าต่ำสุดที่แคบกว่ามาตรฐานติดป้ายให้ยืนยัน"""
    out = {k: we.get(k) for k in ("standard_min_mm", "max_mm", "confidence", "increment_status", "width_note_th")}
    if we.get("increment_status") in ("match", "not_printed") and we.get("increment_mm") is not None:
        out["increment_mm"] = we["increment_mm"]
    pm, std = we.get("printed_min_mm"), we.get("standard_min_mm")
    if pm is not None and std is not None and pm < std:
        out["printed_min_mm_needs_sales_confirmation"] = pm
    if we.get("conflicting_value_mm") is not None:
        out["table_value_conflicting_needs_sales_confirmation_mm"] = we["conflicting_value_mm"]
    return out


def _variants(p: dict, with_temp: bool = True) -> list[dict]:
    out = []
    for v in p["specifications"].get("variants") or []:
        row = {"belt_material": v.get("belt_material"), "pin_material": v.get("pin_material"),
               "strength_n_per_m": (v.get("belt_strength") or {}).get("n_per_m"),
               "weight_kg_per_m2": (v.get("belt_weight") or {}).get("kg_per_m2")}
        # ค่าวิ่งโค้ง — รอบ r1 ไม่ได้ส่งค่านี้ agent จึงตอบความแข็งแรงช่วงโค้งไม่ได้ (ST-001) ทั้งที่บอทหลักเห็น
        if v.get("belt_strength_curve"):
            row["strength_curve_n_per_m"] = v["belt_strength_curve"].get("n_per_m")
        if _v31():
            # R1: lb/ft คำนวณจาก N/m ในฐาน (ไม่ใช้ lb ที่เล่มพิมพ์) · R7: ค่าที่ยังไม่ยืนยัน
            row["strength_lb_per_ft"] = (v.get("belt_strength") or {}).get("lb_per_ft")
            if v.get("belt_strength_curve"):
                row["strength_curve_lb_per_ft"] = v["belt_strength_curve"].get("lb_per_ft")
            if v.get("confirmation"):
                row["confirmation"] = v["confirmation"]
        if with_temp:
            te = v.get("temperature_effective") or {}
            row["temperature_effective"] = {k: te.get(k) for k in ("dry", "wet") if k in te}
            row["temperature_trust"] = v.get("temperature_trust")
            if _v31():
                # R3: สถานะค่าเปียกต่อเกรด (ok · partial_data · no_data · not_recommended) + เหตุผล
                row["wet_status"] = te.get("wet_status") or "ok"
                if row["wet_status"] != "ok":
                    row["wet_note_th"] = te.get("wet_note_th")
            # r3 (2 พ.ย.): ส่งข้อขัดแย้งตารางสเปก vs คุณสมบัติวัสดุ (ข้อมูลดิบในฐาน · ไม่บังคับกฎ)
            # r1/r2/r2m ไม่ส่ง — ให้ผลของรอบเดิมรันซ้ำได้เท่าเดิม
            if _send_conflict() and te.get("conflict"):
                row["temperature_conflict"] = te.get("conflict")
                row["temperature_conflict_note_th"] = te.get("conflict_note_th")
        out.append(row)
    return out


def _notes_v31(s: dict) -> list:
    """R5: รุ่นที่ค่าเพิ่มทีละในหมายเหตุไม่ตรงกับตาราง (increment_status = mismatch) ตัดท่อนที่พูดถึงค่าเพิ่มทีละออก
    ท่อนอื่นของหมายเหตุคงไว้ (แยกท่อนด้วย " - " ตามที่เล่มพิมพ์)"""
    notes = s.get("notes") or []
    if (s.get("width_effective") or {}).get("increment_status") != "mismatch":
        return notes
    out = []
    for n in notes:
        keep = [seg for seg in re.split(r"\s+-\s+", n) if "increment" not in re.sub(r"\s+", "", seg).lower()]
        if keep:
            out.append(" - ".join(keep))
    return out


def _card(p: dict, full: bool) -> dict:
    s = p["specifications"]
    d = {
        "belt_code": p["belt_code"],
        "series": p.get("belt_series"),
        "surface_type": p["retrieval_card"].get("surface_type"),
        "pitch_mm": (s.get("pitch") or {}).get("mm"),
        "open_area_pct": s.get("open_area_pct"),
        "belt_thickness": s.get("belt_thickness"),
        "curve_capable": bool(s.get("has_curve_rating")),
        "approved": s.get("approved"),
        "color": s.get("color"),
        "variants": _variants(p),
        "width_effective": s.get("width_effective"),
        "data_quality": p.get("data_quality"),
        "answering": p.get("answering"),
        "catalogue_page": s.get("page"),
    }
    if _v31():
        # v31: ไม่ส่ง answering / data_quality ดิบ — ส่งเฉพาะฟิลด์โครงสร้างที่กฎ R1–R11 อ่าน
        dq, ans = p.get("data_quality") or {}, p.get("answering") or {}
        for k in ("width_effective", "data_quality", "answering"):
            d.pop(k, None)
        d["width"] = _width_v31(s.get("width_effective") or {})
        d["required_slots"] = ans.get("required_slots") or []
        d["blocking_for"] = dq.get("blocking_for") or []
        d["escalate_to_sales"] = ans.get("escalate_to_sales") or []
        if p.get("material_status"):
            d["material_status"] = p["material_status"]
    if full:
        d.update({
            "cleanability": s.get("cleanability"),
            "min_nosebar_diameter": s.get("min_nosebar_diameter"),
            "notes": _notes_v31(s) if _v31() else s.get("notes"),
            "sales_knowledge_th": p.get("sales_knowledge_th"),
            "industries": [{"industry": i.get("industry"),
                            "applications": [{"application_th": a.get("application_th") or a.get("application"),
                                              "materials": a.get("materials")}
                                             for a in i.get("applications") or []]}
                           for i in p.get("industries") or []],
            "derived": {k: (p.get("derived") or {}).get(k)
                        for k in ("materials_manufactured", "materials_recommended", "pin_materials")},
        })
    return d


# ─────────────────────────── เครื่องมือ ───────────────────────────

def answering_policy() -> str:
    """กฎการตอบระดับฐานข้อมูล (answering_policy ใน JSON) — agent ใช้ประกอบ system prompt"""
    cat = _state()[0]
    return _dump(cat.data.get("answering_policy") or {})


def overview_catalogue() -> str:
    _cat, search, *_ = _state()
    return _dump(search.overview())


def compare_belts(codes: str) -> str:
    cat = _state()[0]
    out, missing = [], []
    for raw in [c.strip() for c in (codes or "").replace(";", ",").split(",") if c.strip()][:4]:
        code, cands = _resolve_belt(raw)
        if code:
            out.append(_card(cat.by_code[code], full=False))
        else:
            missing.append({"input": raw, "candidates": cands[:8]})
    return _dump({"belts": out, "not_found": missing,
                  "note_th": "ค่าแรงดึง น้ำหนัก และอุณหภูมิเป็นค่าของแต่ละเกรด (วัสดุสายพาน × วัสดุพิน)"})


def search_catalogue(field: str = "", op: str = ">=", value: float = 0.0, surface: str = "",
                     pin_material: str = "", belt_material: str = "", rank: str = "") -> str:
    tool = _state()[4]
    return tool(field=field, op=op, value=value, surface=surface, pin_material=pin_material,
                belt_material=belt_material, rank=rank)


def lookup_belt(code: str) -> str:
    cat = _state()[0]
    belt, cands = _resolve_belt(code)
    if not belt:
        return _not_found(code, cands)
    return _dump(_card(cat.by_code[belt], full=True))


def find_by_application(text: str) -> str:
    cat, search, kg, *_ = _state()
    g = graph_application_match(text, cat, search, kg)
    if g:
        return _dump(g)
    am = search.match_application(text)
    if am is not None:
        return _dump({"router_application_match": am.__dict__ if hasattr(am, "__dict__") else str(am)})
    ind = search.match_industry(text)
    if ind:
        industry, by_belt = ind
        return _dump({"industry": industry, "applications_by_belt": by_belt,
                      "note_th": "ไม่พบชื่องานตรงตัว รายชื่อนี้คือรุ่นทั้งหมดของอุตสาหกรรมนี้"})
    return _dump({"matches": [], "note_th": "ไม่พบงานใช้หรืออุตสาหกรรมที่ตรงกับข้อความนี้ในแคตตาล็อก"})


def sprockets_for(belt_code: str) -> str:
    cat, _s, kg, *_ = _state()
    belt, cands = _resolve_belt(belt_code)
    if not belt:
        return _not_found(belt_code, cands)
    sp = kg.sprockets_for_belt(belt)
    if _v31():
        # R9 (ตัดสิน 9 พ.ย.): Do / Di อ่านจากภาพวาดหน้าสเตอร์ได้ · รูเพลาและ A B ยังส่งฝ่ายขาย
        rows = []
        for code in sp:
            x = cat.sprockets.get(code) or {}
            dims = x.get("dimensions") or {}
            rows.append({"sprocket_code": code, "teeth": x.get("teeth"),
                         "material": x.get("material") if x.get("material_basis") == "printed_in_code" else None,
                         "Do_mm": (dims.get("Do") or {}).get("mm"), "Di_mm": (dims.get("Di") or {}).get("mm")})
        return _dump({"belt_code": belt, "sprockets": rows, "same_series": kg.get_same_series(belt),
                      "note_th": ("รหัสเฟืองอนุมานจากซีรีส์ ต้องยืนยันกับฝ่ายขาย · Do = เส้นผ่านศูนย์กลางนอกที่ปลายฟัน "
                                  "Di = เส้นผ่านศูนย์กลางวงในที่โคนฟัน · วัสดุ null = เล่มไม่ระบุ "
                                  "· ขนาดรูเพลาและระยะ A B ต้องยืนยันกับฝ่ายขาย")})
    return _dump({"belt_code": belt, "sprockets": sp, "same_series": kg.get_same_series(belt),
                  "note_th": "รหัสเฟืองอนุมานจากซีรีส์ ต้องยืนยันกับฝ่ายขาย ขนาดเฟืองและรูเพลาไม่มีในข้อมูล"})


def belts_for_sprocket(sprocket_code: str) -> str:
    cat, _s, kg, res, _t = _state()
    m = res.resolve(sprocket_code or "")
    codes = m.sprocket_codes or ([sprocket_code] if sprocket_code in cat.sprockets else [])
    if not codes:
        return _dump({"error": f"ไม่พบรหัสเฟือง {sprocket_code!r}"})
    return _dump({"sprocket_codes": codes, "belts": kg.resolve_sprocket_to_belts(codes)})


def temperature(belt_code: str, belt_material: str = "", pin_material: str = "") -> str:
    cat = _state()[0]
    belt, cands = _resolve_belt(belt_code)
    if not belt:
        return _not_found(belt_code, cands)
    rows = [v for v in _variants(cat.by_code[belt])
            if (not belt_material or v["belt_material"] == belt_material)
            and (not pin_material or v["pin_material"] == pin_material)]
    return _dump({"belt_code": belt, "variants": rows,
                  "note_th": "คืนค่าทั้งสภาวะแห้ง (dry) และเปียก (wet) ค่าเปียกมักต่ำกว่ามาก"})


@lru_cache(maxsize=1)
def shared_models() -> dict:
    """Jina v3 + SigLIP-224 ชุดเดียว ใช้ร่วมกันทั้งตัวค้น Modutech และ Movex (= assistant.py โหลดครั้งเดียว)"""
    import torch
    from transformers import AutoModel, AutoTokenizer, SiglipModel, SiglipProcessor
    from engine.core import model_lock

    jina_id, siglip_id = "jinaai/jina-embeddings-v3", "google/siglip-base-patch16-224"   # = assistant.py
    device = os.environ.get("AGENT_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
    model_lock.load()
    tok = AutoTokenizer.from_pretrained(jina_id, trust_remote_code=True, **model_lock.pin(jina_id))
    jina = AutoModel.from_pretrained(jina_id, trust_remote_code=True, **model_lock.pin(jina_id),
                                     torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                                     attn_implementation="eager").to(device).eval()
    sp = SiglipProcessor.from_pretrained(siglip_id, **model_lock.pin(siglip_id))
    sm = SiglipModel.from_pretrained(siglip_id, **model_lock.pin(siglip_id)).to(device).eval()
    if device == "cuda":
        sm.half()
    return {"device": device, "jina_tokenizer": tok, "jina_model": jina,
            "siglip_processor": sp, "siglip_model": sm}


@lru_cache(maxsize=1)
def _retriever():
    """สร้าง RetrieverV4 ฝั่ง Modutech แบบเดียวกับ brands/modutech/plugin.create() ทุกค่า
    (Jina v3 · SigLIP-224 · product_db · กราฟ · ชื่อ collection จาก alias ใน brand.yaml) — ViT ไม่ส่ง (ค้นข้อความอย่างเดียว)"""
    import yaml
    from engine.shared.retriever_v4 import RetrieverV4, RetrieverV4Config
    from engine.brands.modutech.plugin import resolve_collection
    from engine.brands.modutech.router import modutech_retriever_config_kwargs

    m = shared_models()
    device, tok, jina, sp, sm = m["device"], m["jina_tokenizer"], m["jina_model"], m["siglip_processor"], m["siglip_model"]

    cat, _search, kg, *_ = _state()
    mod_db = {p["belt_code_id"]: {"product_id": p["belt_code_id"], "Ref": p["belt_code"],
                                  "belt_series": p.get("belt_series", ""),
                                  "product_type": p["retrieval_card"].get("surface_type", ""),
                                  "Material": ",".join(p["retrieval_card"].get("materials") or [])}
              for p in cat.products}
    bdir = os.path.join(ROOT, "engine", "brands", "modutech")
    data = (yaml.safe_load(open(os.path.join(bdir, "brand.yaml"), encoding="utf-8")) or {}).get("data") or {}
    qpath = os.path.normpath(os.path.join(bdir, data.get("qdrant_path") or "../../../data/qdrant_modutech_db"))
    kw = modutech_retriever_config_kwargs()
    kw["qdrant_path"] = qpath
    info = resolve_collection(qpath, data.get("text_collection"),
                              data.get("text_collection_fallback") or kw["text_collection"])
    kw["text_collection"] = info["name"]
    return RetrieverV4(cfg=RetrieverV4Config(**kw, device=device),
                       jina_tokenizer=tok, jina_model=jina, vit_processor=None, vit_model=None,
                       siglip_processor=sp, siglip_model=sm, product_db=mod_db, kg=kg)


def vector_search(query: str, top_k: int = 5) -> str:
    cat = _state()[0]
    try:
        r = _retriever()
        ranked = r.rank(r.search(query=query, query_image=None, query_type="general"))
    except Exception as e:                                   # noqa: BLE001
        return _dump({"error": f"ค้นเวกเตอร์ไม่ได้ ({type(e).__name__}: {e})"})
    ids = [p.product_id for p in ranked.products][: max(1, min(int(top_k or 5), 10))]
    return _dump({"belt_codes": [cat.by_id[i]["belt_code"] for i in ids if i in cat.by_id],
                  "note_th": "ผลค้นเวกเตอร์เป็นเพียงรุ่นที่ใกล้เคียงที่สุดบางส่วน ไม่ใช่รายชื่อครบ"})


@lru_cache(maxsize=1)
def _gate():
    import yaml
    from engine.brands.modutech.image_gate import load_gate
    bdir = os.path.join(ROOT, "engine", "brands", "modutech")
    cfg = (yaml.safe_load(open(os.path.join(bdir, "brand.yaml"), encoding="utf-8")) or {}).get("image_gate") or {}
    try:
        return load_gate("modutech", bdir, cfg, os.environ.get("AGENT_DEVICE", "cpu"))
    except Exception as e:                                   # noqa: BLE001  (ไฟล์เป็นตัวชี้ LFS ฯลฯ)
        return None, f"{type(e).__name__}: {e}"


def match_catalogue_image(image_id: str, top_k: int = 5) -> str:
    """เทียบรูปของลูกค้ากับแกลเลอรีภาพแคตตาล็อก Modutech ด้วย SigLIP (ตัวเดียวกับประตูรูปของบอทหลัก)"""
    path = os.path.join(IMAGE_DIR, os.path.basename(image_id or ""))
    if not os.path.isfile(path):
        return _dump({"error": f"ไม่พบรูป {image_id!r}"})
    gate, why = _gate()
    if gate is None:
        return _dump({"error": f"เครื่องมือเทียบรูปไม่พร้อม ({why})"})
    import numpy as np
    from PIL import Image
    from engine.brands.modutech.image_gate import prepare
    im = Image.open(path).convert("RGB")
    V = np.asarray(gate.embed(prepare(im)), dtype=np.float32)
    sims = (V @ gate.data.G.T).max(axis=0)
    full = V[0]
    b, o = gate.data.belt_P @ full, gate.data.other_P @ full
    out = {"best_score": round(float(sims.max()), 4),
           "belt_vs_other_text_margin": round(float(b.max() - o.max()), 4),
           "nearest_non_belt_concept": gate.data.other_names[int(o.argmax())],
           "note_th": ("best_score คือความคล้ายสูงสุดกับภาพสายพาน Modutech ในแคตตาล็อก (0–1) "
                       "belt_vs_other_text_margin > 0 แปลว่าใกล้คำว่าสายพาน/โซ่มากกว่าวัตถุอื่น "
                       "ความคล้ายสูงไม่ได้แปลว่าเป็นแบรนด์ Modutech เสมอ โซ่ของแบรนด์อื่นก็อาจคล้ายได้")}
    labels = gate.data.meta.get("gallery_labels") or gate.data.meta.get("labels")
    if labels and len(labels) == len(sims):
        best: dict[str, float] = {}
        for lab, s in zip(labels, sims):
            best[lab] = max(best.get(lab, -1.0), float(s))
        out["nearest_belts"] = [{"belt_code": k, "score": round(v, 4)}
                                for k, v in sorted(best.items(), key=lambda kv: -kv[1])[: int(top_k or 5)]]
    else:
        out["nearest_belts"] = None
        out["note_th"] += " · แกลเลอรีชุดนี้ไม่มีป้ายรุ่น จึงบอกรุ่นที่ใกล้ที่สุดไม่ได้"
    return _dump(out)


def handoff_to_sales(topic: str) -> str:
    try:
        from engine.shared.sales_contact import sales_contact_line_th
        contact = sales_contact_line_th()
    except Exception:                                       # noqa: BLE001
        contact = ""
    return _dump({"topic": topic,
                  "message_th": (f"เรื่อง {topic} อยู่นอกข้อมูลที่ระบบมี ต้องสอบถามฝ่ายขายโดยตรง "
                                 "เวลาติดต่อแจ้งรุ่นสายพาน ความกว้าง ความยาว และจำนวนที่ต้องการไปด้วย"),
                  "contact_line_th": contact,
                  "note_th": "ให้ลูกค้าติดต่อเอง ห้ามรับปากว่าจะส่งเรื่องหรือให้ฝ่ายขายโทรกลับ"})


TOOLS = [overview_catalogue, compare_belts, search_catalogue, lookup_belt, find_by_application,
         sprockets_for, belts_for_sprocket, temperature, vector_search, match_catalogue_image,
         handoff_to_sales]


# ─────────────── ลักษณะผิวจากรูป → รายชื่อรุ่น (AGENT_IMAGE_SURFACE=1 · 6 พ.ย.) ───────────────
# คู่กับตัวอ่านรูปของบอท (IMAGE_INTERPRETER=llm): ตัวตรวจ (core/image_interpreter.parse_reading)
# และตัวคัด (brands/modutech/image_read.image_match) ตัวเดียวกันทุกบรรทัด
# ต่างกันแค่ใครอ่านรูป — บอทเรียก Gemini แยกอีกครั้ง · agent ดูรูปเองแล้วส่งชื่อผิวมา (ไม่เรียก LLM เพิ่ม)
def surface_choices() -> dict:
    """ชื่อผิวที่รับได้ → คำอธิบายหน้าตา (ใส่ในคำอธิบายเครื่องมือให้ LLM เลือก)"""
    from engine.brands.modutech.image_read import image_spec
    return image_spec(_state()[0]).surfaces


def belts_by_surface(surface: str, alternatives: str = "", openness: str = "",
                     pitch_mm: float = 0, scale_visible: bool = False, confidence: str = "medium") -> str:
    from engine.brands.modutech.image_read import image_match, image_spec
    from engine.core.image_interpreter import parse_reading
    cat, search, _k, _r, _t = _state()
    spec = image_spec(cat)
    raw = {
        "is_product": "yes",
        "surface": (surface or "").strip() or None,
        "surface_alternatives": [a.strip() for a in (alternatives or "").split(",") if a.strip()],
        "openness": (openness or "").strip().lower() or None,
        "scale_visible": bool(scale_visible),
        "pitch_mm": pitch_mm if pitch_mm else None,
        "confidence": (confidence or "medium").strip().lower(),
    }
    reading = parse_reading(json.dumps(raw, ensure_ascii=False), spec)
    if reading is None:
        return _dump({"error": "ค่าที่ส่งมาใช้ไม่ได้ — surface ต้องเป็นชื่อในรายการ · confidence: high | medium | low",
                      "allowed_surfaces": list(spec.surfaces)})
    match, why = image_match(reading, search, cat, spec)
    if match is None:
        return _dump({"matched": False, "reason": why,
                      "note_th": "ลักษณะนี้ใช้คัดรุ่นไม่ได้ ให้ถามลูกค้าเพิ่ม (พิทช์ · รหัสบนสายพาน · งานที่ใช้)"})
    return _dump({"matched": True, **match})
