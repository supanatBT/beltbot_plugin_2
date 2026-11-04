"""
agent_baseline/movex_tools.py — เครื่องมือ Movex ของ agent เทียบ (ขั้นที่ 2 · 2 พ.ย. 2026 · ผู้ใช้เลือกแบบ ข)

ที่มา: เครื่องมือ 4 ตัวที่ LLM ของ Movex เรียกได้ตั้งแต่เทอมที่แล้ว (chatbot_v4.py → brands/movex/runtime.py)
  analyze_product_database · compare_specific_products · filter_product_specs · generate_datasheet
เรียกฟังก์ชันตัวเดิมใน runtime.py ตรง ๆ ไม่เขียนใหม่ — ต่างกันแค่ agent เลือกเรียกเอง
บวกสิ่งที่เทอมที่แล้วฉีดเข้า prompt ให้ LLM ทุกเทิร์น (ผลค้น RAG · GraphRAG · สัญญาณ ViT) ทำเป็นเครื่องมือให้ agent เรียกเอง
  movex_search (= RAG Context + GraphRAG Context) · movex_lookup (ข้อมูลรุ่นเต็ม + กราฟของรุ่นนั้น)
  movex_match_image (= ViT Signal + ผลค้นรูป)

หลักเดียวกับ tools_impl.py: คืนข้อมูลดิบ ไม่บังคับกฎ (เกณฑ์ ViT 0.90 / 0.50 อยู่ใน prompt ของ agent แบบเทอมที่แล้ว ไม่อยู่ในเครื่องมือ)
อ่านอย่างเดียว · ไม่แตะ collection ของ Movex (เปิด qdrant_db ผ่าน RetrieverV4 ตัวเดิม · ไม่เขียน)
ส่วนที่ต้องโหลดโมเดลโหลดตอนเรียกครั้งแรก ถ้าโหลดไม่ได้ คืนข้อความบอกเหตุ ไม่ล้ม
"""
from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import sys
from functools import lru_cache

from agent_baseline.tools_impl import IMAGE_DIR, ROOT, _dump, shared_models

BDIR = os.path.join(ROOT, "brands", "movex")


def _cfg() -> dict:
    import yaml
    return yaml.safe_load(open(os.path.join(BDIR, "brand.yaml"), encoding="utf-8")) or {}


def _path(rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(BDIR, rel))


@lru_cache(maxsize=1)
def _data():
    """ข้อมูล Movex ชุดเดียวกับ brands/movex/plugin.create() — extracted_data + กราฟ · ผูกเข้า runtime (bind)"""
    from knowledge_graph import KnowledgeGraph
    from brands.movex import runtime as R
    data = _cfg().get("data") or {}
    raw = json.load(open(_path(data["products"]), encoding="utf-8"))
    products = {p["product_id"]: p for p in raw.get("products", []) if "product_id" in p}
    materials = {m["material_code"]: m for m in raw.get("Materials", [])}
    processes = {p["manufacturing_process"]: p for p in raw.get("manufacturing_process", [])}
    graph = KnowledgeGraph.load_from_db(_path(data["graph_db"]))
    R.bind(products, materials, processes, graph, None)
    return R, products, graph


@lru_cache(maxsize=1)
def _vit():
    """ViT LoRA ของ Movex แบบเดียวกับ assistant.py (ตรวจ revision ตาม brand.yaml ด้วย core.models)"""
    from peft import PeftModel
    from transformers import ViTForImageClassification, ViTImageProcessor
    from core import model_lock
    from core.models import load_image_spec
    spec = load_image_spec("movex", BDIR, _cfg().get("image") or {})
    device = shared_models()["device"]
    proc = ViTImageProcessor.from_pretrained(spec.base, **model_lock.pin(spec.base))
    base = ViTForImageClassification.from_pretrained(spec.base, num_labels=spec.num_labels, **model_lock.pin(spec.base))
    vit = PeftModel.from_pretrained(base, spec.adapter, **({} if spec.adapter_is_local else {"revision": spec.revision}))
    vit.eval().to(device)
    if device == "cuda":
        vit.half()
    return proc, vit


@lru_cache(maxsize=1)
def _retriever():
    """RetrieverV4 ฝั่ง Movex = brands/movex/plugin.create() ทุกค่า (qdrant_db · ค่าตั้งต้น RetrieverV4Config)"""
    from retriever_v4 import RetrieverV4, RetrieverV4Config
    R, products, graph = _data()
    m = shared_models()
    try:
        vproc, vmodel = _vit()
    except Exception as e:                                   # noqa: BLE001 — ค้นข้อความได้แม้ไม่มี ViT
        print(f"[movex_tools] ViT โหลดไม่ได้ ({type(e).__name__}: {e}) — ค้นรูปจะไม่มีสัญญาณ ViT")
        vproc, vmodel = None, None
    inner = RetrieverV4(cfg=RetrieverV4Config(qdrant_path=_path(_cfg()["data"]["qdrant_path"]), device=m["device"]),
                        jina_tokenizer=m["jina_tokenizer"], jina_model=m["jina_model"],
                        vit_processor=vproc, vit_model=vmodel,
                        siglip_processor=m["siglip_processor"], siglip_model=m["siglip_model"],
                        product_db=products, kg=graph)
    R.bind(R.product_db, R.material_db, R.process_db, graph, inner)   # filter_product_specs ใช้ Qdrant เหมือนบอท
    return inner


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-\.]+", "", (s or "").lower())


def resolve_product(code: str) -> tuple[str | None, list[str]]:
    """รหัสที่ลูกค้าพิมพ์ ("LF820 K325" · "lf 880 tab k450" · "54901") → product_id · ไม่ชัด = คืน candidates"""
    _R, products, _g = _data()
    if code in products:
        return code, []
    q = _norm(code)
    if not q:
        return None, []
    keys = {pid: {_norm(pid.split("_", 2)[-1]), _norm(p.get("Ref") or ""), _norm(str(p.get("Art_Nr") or ""))}
            for pid, p in products.items()}
    exact = [pid for pid, ks in keys.items() if q in ks]
    if len(exact) == 1:
        return exact[0], []
    part = exact or [pid for pid, ks in keys.items() if any(q in k for k in ks if k)]
    if len(part) == 1:
        return part[0], []
    return None, sorted(part)[:12]


def _product_card(pid: str) -> dict:
    R, products, graph = _data()
    d = R._enrich_product(products[pid])
    d.pop("search_content", None)
    d.pop("images", None)
    return d


def _graph_summary(pids: list[str]) -> str:
    R, _p, graph = _data()
    gr = R.focus_graph(pids, graph)
    return R._build_graph_summary(gr) if gr else ""


# ─────────────────────────── เครื่องมือ ───────────────────────────
# ฟังก์ชันเดิมของ runtime.py / retriever_v4 / knowledge_graph พิมพ์ log ลง stdout — ใน MCP แบบ stdio
# stdout คือช่องส่ง JSON-RPC จึงย้าย print ระหว่างเรียกเครื่องมือไป stderr · ข้อผิดพลาดคืนเป็นข้อความ ไม่ล้ม server

def _tool(fn):
    @functools.wraps(fn)
    def wrap(*a, **k):
        with contextlib.redirect_stdout(sys.stderr):
            try:
                return fn(*a, **k)
            except Exception as e:                           # noqa: BLE001
                return _dump({"error": f"{fn.__name__} ทำงานไม่ได้ ({type(e).__name__}: {e})"})
    return wrap


@_tool

def movex_overview(category: str = "all", series: str = "") -> str:
    return _data()[0].analyze_product_database(category=category or "all", series=series or "")


@_tool
def movex_compare(product_ids: str) -> str:
    R = _data()[0]
    ids = []
    for raw in [x.strip() for x in (product_ids or "").replace(";", ",").split(",") if x.strip()]:
        pid, _c = resolve_product(raw)
        ids.append(pid or raw)
    return R.compare_specific_products(",".join(ids))


@_tool
def movex_filter(spec_type: str, condition: str, target_value: float, product_type: str = "",
                 sort_by: str = "", sort_order: str = "asc") -> str:
    R = _data()[0]
    try:
        _retriever()
    except Exception as e:                                   # noqa: BLE001 — ไม่มีโมเดล → ทางสำรอง JSON ของฟังก์ชันเดิม
        print(f"[movex_tools] ตัวค้นโหลดไม่ได้ ({type(e).__name__}) — filter ใช้ทางสำรอง JSON")
    return R.filter_product_specs(spec_type, condition, float(target_value),
                                  product_type=product_type or None, sort_by=sort_by or None,
                                  sort_order=sort_order or "asc")


def datasheet_files_on() -> bool:
    """AGENT_DATASHEET_FILES=1 (4 พ.ย.) — ส่งรูป datasheet ถึงลูกค้าแบบเดียวกับบอท · ไม่ตั้ง/0 = agent เดิมทุกตัวอักษร"""
    return (os.environ.get("AGENT_DATASHEET_FILES") or "").strip() == "1"


DATASHEET_DIR = os.environ.get("AGENT_DATASHEET_DIR", os.path.join(ROOT, "agent_baseline", "_datasheets"))


def datasheet_path(pid: str) -> str:
    return os.path.join(DATASHEET_DIR, f"{os.path.basename(pid)}.png")


@_tool
def movex_datasheet(product_id: str) -> str:
    R = _data()[0]
    pid, _c = resolve_product(product_id)
    if not datasheet_files_on():
        return R.generate_datasheet(pid or product_id)
    # เปิดสวิตช์: เครื่องมือรันในโปรเซส MCP แยกจาก agent_assistant — ส่งรูปผ่านไฟล์ ไม่ผ่าน context ของ LLM (ไม่กินโทเคน)
    # ล้างแคชของรุ่นนี้ก่อน: แคชอยู่ตลอดอายุโปรเซส แชทใหม่จึงเคยได้ข้อความ "แสดงบนหน้าจอเรียบร้อยแล้ว" ทั้งที่ไม่เคยแสดง
    if pid:
        R._datasheet_cache.pop(pid, None)
    out = R.generate_datasheet(pid or product_id)
    b64 = R._datasheet_cache.get(pid) if pid else None
    if b64:
        import base64
        os.makedirs(DATASHEET_DIR, exist_ok=True)
        tmp = datasheet_path(pid) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(base64.b64decode(b64))
        os.replace(tmp, datasheet_path(pid))            # เขียนเสร็จทั้งไฟล์ก่อน agent_assistant อ่าน
    return out


@_tool
def movex_lookup(product_id: str) -> str:
    pid, cands = resolve_product(product_id)
    if not pid:
        return _dump({"error": f"ไม่พบรหัสสินค้า Movex {product_id!r}", "candidates": cands,
                      "hint": "ถ้ามี candidates ให้ถามลูกค้าว่าหมายถึงรุ่นไหน ห้ามเลือกเอง"})
    return _dump({"product": _product_card(pid), "graph_context": _graph_summary([pid])})


def _ranked_rows(ranked, limit: int) -> list[dict]:
    _R, products, _g = _data()
    rows = []
    for i, p in enumerate(ranked.products[:limit], 1):
        if p.product_id not in products:
            continue
        rows.append({"rank": i, "final_score": round(float(p.final_score), 4), "product": _product_card(p.product_id),
                     "best_chunk": p.best_chunk_text})
    return rows


@_tool
def movex_search(query: str, top_k: int = 5) -> str:
    try:
        inner = _retriever()
        res = inner.search(query=query, query_image=None, query_type="general")
        ranked = inner.rank(res)
    except Exception as e:                                   # noqa: BLE001
        return _dump({"error": f"ค้น Movex ไม่ได้ ({type(e).__name__}: {e})"})
    R = _data()[0]
    return _dump({"results": _ranked_rows(ranked, max(1, min(int(top_k or 5), 10))),
                  "graph_context": R._build_graph_summary(res.graph_result) if res.graph_result else "",
                  "note_th": "ผลค้นเรียงตาม final_score สูงสุด เป็นรุ่นที่ใกล้ข้อความที่สุดบางส่วน ไม่ใช่รายชื่อครบ"})


@_tool
def movex_match_image(image_id: str, top_k: int = 5) -> str:
    path = os.path.join(IMAGE_DIR, os.path.basename(image_id or ""))
    if not os.path.isfile(path):
        return _dump({"error": f"ไม่พบรูป {image_id!r}"})
    from PIL import Image
    try:
        inner = _retriever()
        res = inner.search(query="", query_image=Image.open(path).convert("RGB"), query_type="image")
        ranked = inner.rank(res)
    except Exception as e:                                   # noqa: BLE001
        return _dump({"error": f"เทียบรูป Movex ไม่ได้ ({type(e).__name__}: {e})"})
    sig = res.vit_signal
    scores = [float(p.final_score) for p in ranked.products[:2]]
    R = _data()[0]
    return _dump({
        "vit_signal": None if sig is None else {"series": sig.series, "confidence": round(float(sig.confidence), 4),
                                                "dominant": bool(sig.dominant), "top_pid": sig.top_pid},
        "top1_top2_gap": round(scores[0] - scores[1], 4) if len(scores) == 2 else None,
        "matched": bool(ranked.products),
        "results": _ranked_rows(ranked, max(1, min(int(top_k or 5), 10))),
        "graph_context": R._build_graph_summary(res.graph_result) if res.graph_result else "",
        "note_th": ("vit_signal มาจาก ViT ที่เทรนกับรูปโซ่ Movex 10 คลาสเท่านั้น confidence คือความมั่นใจของคลาสที่ได้ "
                    "รูปที่ไม่ใช่โซ่ Movex ก็ได้คลาสใดคลาสหนึ่งเสมอ · matched=false แปลว่าไม่พบสินค้าที่ใกล้รูปนี้"),
    })


TOOLS = [movex_overview, movex_compare, movex_filter, movex_datasheet, movex_lookup, movex_search, movex_match_image]
