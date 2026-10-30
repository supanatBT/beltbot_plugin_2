"""
brands/movex/runtime.py
=======================
ส่วนที่ต้องใช้โมเดลของ Movex — ค้น · จัดอันดับ · tool · datasheet · prompt
ย้ายมาจาก chatbot_v5.py (ชั้น 5) โดยตัดฟังก์ชันออกมาทั้งก้อนด้วยสคริปต์ ไม่ได้พิมพ์ใหม่
ครอบ retriever_v4.py / knowledge_graph.py เดิม ไม่แก้สองไฟล์นั้น (HANDOFF ข้อ 6)

ที่เปลี่ยนตอนย้าย
  · ชื่อระดับโมดูลที่ฟังก์ชันเดิมอ้าง (product_db · material_db · process_db · kg ·
    _retriever_inner · _datasheet_cache) ตั้งค่าตอน bind() แทนตอน import
  · _build_system_prompt อ่าน decision.payload แทน decision.movex (สองจุด)
  · ขั้นค้น/สร้าง prompt กับขั้นหลัง LLM ตอบ แยกเป็น build_turn / finish_turn
"""
from __future__ import annotations

import base64
import json
import os
import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from core.llm import extract_text
from core.protocol import ImageScore, LLMTurn, TurnOutput
from retriever_v4 import GraphResult, RetrieverV4, ViTSignal

# ── ชื่อที่ฟังก์ชันเดิมอ้าง — bind() ตั้งค่า ──
product_db: dict = {}
material_db: dict = {}
process_db: dict = {}
kg = None
_retriever_inner = None
_datasheet_cache: dict[str, str] = {}   # resolved_pid -> base64 PNG


def bind(products: dict, materials: dict, processes: dict, graph, inner) -> None:
    global product_db, material_db, process_db, kg, _retriever_inner
    product_db, material_db, process_db, kg, _retriever_inner = products, materials, processes, graph, inner


# ================================================================
# HELPERS (ย้ายมาทั้งก้อน)
# ================================================================

def _enrich_product(p: dict) -> dict:
    p = p.copy()
    mat  = p.get("Material", "")
    proc = p.get("manufacturing_process", "")
    if mat in material_db:
        p["material_details"] = material_db[mat]
    if proc in process_db:
        p["manufacturing_details"] = process_db[proc]
    return p


SPROCKET_TOPIC_RX = re.compile(r"สเตอร์|สเตอ|เฟือง|sprocket|ฟันเฟือง|ล้อโซ่", re.IGNORECASE)
MAX_COMPAT_RECORDS = 4


def products_of(pid: str) -> dict:
    return product_db.get(pid) or {}


def focus_graph(focus: list, graph) -> "GraphResult | None":
    """กราฟจากรุ่นที่ระบบตัดสินแล้วว่าลูกค้าหมายถึง (decision.payload.pids)

    25 ต.ค. (conv_r3 CONV-17): "ใช้สเตอร์อะไร" หลังเลือก LF 880 TAB K450 → LLM ตอบว่าไม่มีข้อมูล compatible
    ทั้งที่กราฟมี 54901 · 55001 — กราฟเดิม seed จากผลค้นข้อความ "ใช้สเตอร์อะไร" ซึ่งไม่มีชื่อรุ่น
    ได้รุ่นอื่น (หรือไม่ได้อะไร) ส่วนรุ่นที่ระบบรู้ว่าลูกค้าหมายถึงไม่ถูกใช้เลย"""
    if not focus or graph is None:
        return None
    gr = GraphResult()
    gr.seed_products = list(focus)
    for f in focus:
        for c in graph.get_compatible_products(f) or []:
            if c not in gr.compatible:
                gr.compatible.append(c)
        for c in graph.get_same_series(f) or []:
            if c not in gr.same_series and c not in focus:
                gr.same_series.append(c)
    # get_material_details คืน dict ฟิลด์ของวัสดุเดียว แต่ GraphResult ต้องการ {รหัส: ฟิลด์}
    # (ทาง "Graph fallback" เดิมใส่ตรง ๆ แล้ว to_llm_context พัง — ถูกห่อ try ไว้ไม่ถึงจุดพัง จึงไม่เคยเห็น)
    mat = graph.get_material_details(focus[0]) or {}
    proc = graph.get_process_details(focus[0]) or {}
    code = (products_of(focus[0]).get("Material") or mat.get("material_code") or "material")
    gr.material_details = {code: mat} if mat else {}
    pcode = (products_of(focus[0]).get("manufacturing_process") or proc.get("process_name") or "process")
    gr.process_details = {pcode: proc} if proc else {}
    gr.hop_trace = [f"focus:{f}" for f in focus]
    return gr


def ensure_focus_context(llm_context: list, focus: list, products: dict, compatible: list,
                         asks_sprocket: bool) -> list[str]:
    """ใส่ข้อมูลรุ่นที่ลูกค้าหมายถึงไว้บนสุด (ถ้าผลค้นไม่มี) · ถามเรื่องสเตอร์ = แนบสเปกสเตอร์ที่เข้ากันได้ด้วย
    คืนรายการ pid ที่เพิ่ม (ลง debug)"""
    have = {c.get("product_id") for c in llm_context}
    added = []
    for f in reversed([f for f in focus if f in products and f not in have]):
        rec = _enrich_product(products[f])
        rec.update({"_rank": 0, "_note": "รุ่นที่ลูกค้ากำลังถามถึง (ระบบตัดสินจากบทสนทนา)"})
        llm_context.insert(0, rec)
        added.append(f)
    if asks_sprocket:
        have = {c.get("product_id") for c in llm_context}
        for c in [c for c in compatible if c in products and c not in have][:MAX_COMPAT_RECORDS]:
            rec = _enrich_product(products[c])
            rec.update({"_note": f"ใช้ร่วมกับ {', '.join(focus)} ตามกราฟความเข้ากันได้"})
            llm_context.append(rec)
            added.append(c)
    return added


def sprocket_spec_lines(compatible: list, products: dict) -> list[str]:
    """บรรทัดสเปกสเตอร์สำเร็จรูป (รหัส · ฟัน · รูเพลา · ชนิด) — โค้ดเขียน ไม่ให้ LLM ไปหยิบตัวเลขจาก JSON เอง

    25 ต.ค. (conv_movex CONV-17 รอบ 2): เพิ่มกฎใน prompt ให้บอก Bore_mm แล้ว LLM ยังตอบแค่รหัส + ฟัน
    ค่าที่ไม่มีใน record ไม่ใส่ (ไม่เดา)"""
    out = []
    for c in compatible:
        p = products.get(c) or {}
        if "sprocket" not in c.lower() and "sprocket" not in str(p.get("product_type", "")).lower():
            continue
        parts = []
        if p.get("Z_Teeth") is not None:
            parts.append(f"{p['Z_Teeth']} ฟัน")
        if p.get("Bore_mm") is not None:
            parts.append(f"รูเพลา {p['Bore_mm']:g} มม.")
        # PD/OD ไม่ใส่: กฎใน prompt ให้ตอบสั้น (รหัส · ฟัน · รูเพลา) · 54901 ในข้อมูล OD 122 < PD 123.3 (รายงานผู้ใช้ 25 ต.ค.)
        if p.get("Sprocket_Type"):
            parts.append(f"ชนิด {p['Sprocket_Type']}")
        out.append(f"- {p.get('Art_Nr') or c}: " + (" · ".join(parts) if parts else "ไม่มีสเปกในข้อมูล"))
    return out


def _build_graph_summary(graph_result) -> str:
    """
    สร้าง graph summary สำหรับ LLM
    รองรับทั้ง GraphResult (v4) และ GraphContext (v3 compat)
    """
    if graph_result is None:
        return "ไม่มี graph context"

    # v4 GraphResult
    if isinstance(graph_result, GraphResult):
        summary = graph_result.to_llm_context()
        return summary if summary else "ไม่มี graph context"

    # v3 GraphContext compat (fallback)
    parts = []
    if hasattr(graph_result, 'seed_products') and graph_result.seed_products:
        parts.append(f"[Seed products]: {', '.join(graph_result.seed_products)}")
    if hasattr(graph_result, 'compatible_products') and graph_result.compatible_products:
        parts.append(
            f"[Compatible parts สำหรับ {', '.join(graph_result.seed_products)}]: "
            f"{', '.join(graph_result.compatible_products[:5])}"
        )
    if hasattr(graph_result, 'same_series') and graph_result.same_series:
        parts.append(f"[สินค้า series เดียวกัน]: {', '.join(graph_result.same_series[:5])}")
    if hasattr(graph_result, 'material_details') and graph_result.material_details:
        for mat, info in graph_result.material_details.items():
            full = info.get("full_name", mat)
            desc = info.get("description", "")
            line = f"[วัสดุของ {', '.join(graph_result.seed_products)}]: รหัส={mat}, ชื่อ={full}"
            if desc:
                line += f", คุณสมบัติ={desc[:120]}"
            parts.append(line)
    if hasattr(graph_result, 'process_details') and graph_result.process_details:
        for proc, info in graph_result.process_details.items():
            full = info.get("full_name", proc)
            desc = info.get("description", "")
            adv  = info.get("advantages", "") or info.get("best_used_for", "")
            line = f"[กระบวนการผลิตของ {', '.join(graph_result.seed_products)}]: วิธี={full}"
            if desc:
                line += f", รายละเอียด={desc[:150]}"
            if adv:
                line += f", ข้อดี={adv[:100]}"
            parts.append(line)
    return "\n".join(parts) if parts else "ไม่มี graph context"


# ================================================================
# INSTRUMENTED RETRIEVER (ย้ายมาทั้งก้อน)
# ================================================================

class InstrumentedRetriever:
    """
    Wrapper รอบ RetrieverV4 — expose internal states สำหรับ logger
    v4 ใช้ direct attribute แทน monkey-patch เพราะ v4 ออกแบบให้ inspect ได้
    """

    def __init__(self, inner: RetrieverV4):
        self.inner = inner
        self._reset()

    def _reset(self):
        self._vit_signal:        ViTSignal = ViTSignal()
        self._graph_result:      GraphResult = GraphResult()
        self._score_map_snapshot: dict = {}
        self._ranked_snapshot:   list = []
        self._graph_triggered_by: str = "none"

        # compat fields สำหรับ logger v3
        self._vit_hits_raw:     list = []
        self._siglip_hits_raw:  list = []
        self._vit_top_score:    float = 0.0
        self._vit_series:       str = ""
        self._vit_dominant:     bool = False
        self._text_hits_raw:    list = []

    def search(self, query, query_image=None, query_type="general"):
        self._reset()
        result = self.inner.search(
            query=query,
            query_image=query_image,
            query_type=query_type,
        )

        # capture v4 states
        if result.vit_signal:
            sig = result.vit_signal
            self._vit_signal     = sig
            self._vit_top_score  = sig.confidence
            self._vit_series     = sig.series or ""
            self._vit_dominant   = sig.dominant

        if result.graph_result:
            gr = result.graph_result
            self._graph_result = gr
            if gr.seed_products:
                self._graph_triggered_by = (
                    "vit" if result.vit_signal and result.vit_signal.series
                    else "keyword"
                )

        # capture score_map จาก result โดยตรง (แก้ bug seeds=[])
        self._score_map_snapshot = getattr(result, '_score_map', {})
        self._ranked_snapshot    = getattr(result, '_ranked', [])

        return result

    @property
    def cfg(self):
        return self.inner.cfg


# ================================================================
# AI TOOLS (ย้ายมาทั้งก้อน)
# ================================================================

def analyze_product_database(
    category: str = "all",
    series: str = "",
) -> str:
    """
    วิเคราะห์ฐานข้อมูลสินค้า Movex ทั้งหมด
    ใช้เมื่อลูกค้าถามภาพรวม เช่น "มีสินค้ากี่รุ่น" "มีอะไรบ้าง"

    Parameters
    ----------
    category : "all" | "chain" | "sprocket"
    series   : กรอง series เช่น "820" "880" (ว่างหมายถึงทั้งหมด)
    """
    filtered = {}
    for pid, p in product_db.items():
        if category == "chain" and "chain" not in pid.lower():
            continue
        if category == "sprocket" and "sprocket" not in pid.lower():
            continue
        if series and series not in str(p.get("series", "")):
            continue
        filtered[pid] = p

    if not filtered:
        return f"ไม่พบสินค้าในหมวด {category} series {series}"

    chains    = [pid for pid in filtered if "chain"    in pid.lower()]
    sprockets = [pid for pid in filtered if "sprocket" in pid.lower()]

    result = f"พบสินค้าทั้งหมด {len(filtered)} รุ่น\n"
    result += f"  Chain: {len(chains)} รุ่น\n"
    result += f"  Sprocket: {len(sprockets)} รุ่น\n"
    if chains:
        result += f"  Chain list: {', '.join(sorted(chains)[:15])}\n"
    if sprockets:
        result += f"  Sprocket list: {', '.join(sorted(sprockets)[:10])}\n"
    return result


def _spec(p: dict, *keys, default="-"):
    """ค่าแรกที่มีจาก key หลายแบบ — ข้อมูลใช้ตัวใหญ่ (Plate_Width_mm) payload Qdrant ใช้ตัวเล็ก"""
    for k in keys:
        if p.get(k) is not None:
            return p[k]
    return default


def compare_specific_products(product_ids: str) -> str:
    """
    เปรียบเทียบสินค้าหลายรุ่นแบบ side-by-side
    ใช้เมื่อลูกค้าต้องการเปรียบเทียบ 2 รุ่นขึ้นไป

    Parameters
    ----------
    product_ids : รหัสสินค้าคั่นด้วยจุลภาค เช่น "LF820_K325,LF820_K750"
    """
    ids = [x.strip() for x in product_ids.split(",")]
    results = []
    for pid in ids:
        # ค้นหาแบบ fuzzy ถ้าไม่เจอ exact match
        p = product_db.get(pid)
        if not p:
            for k in product_db:
                if pid.lower() in k.lower() or k.lower() in pid.lower():
                    p = product_db[k]
                    pid = k
                    break
        if not p:
            results.append(f"{pid}: ไม่พบในระบบ")
            continue
        # 30 ต.ค. (probe_movex_r1 MXT-C1–C3): เดิมอ่าน plate_width_mm / pitch_mm ตัวเล็ก แต่ข้อมูลเป็น
        # Plate_Width_mm / Pitch_mm → ความกว้างขึ้น "-" ทุกรุ่น (ไม่เคยโผล่เพราะ tool ไม่เคยได้พารามิเตอร์)
        specs = {
            "series":         p.get("series", "-"),
            "product_type":   p.get("product_type", "-"),
            "plate_width_mm": _spec(p, "Plate_Width_mm", "plate_width_mm"),
            "weight_kg_m":    _spec(p, "Weight_kg_m", "weight_kg_m"),
            "pitch_mm":       _spec(p, "Pitch_mm", "pitch_mm"),
            "max_load_n":     _spec(p, "Max_Working_Load_N", "max_load_n"),
            "material":       p.get("Material", "-"),
            "min_curve_radius_mm": _spec(p, "Min_curve_radius_mm", "Radius_min_mm"),
            "Ref":            p.get("Ref", "-"),
        }
        if "sprocket" in (p.get("product_type") or "").lower():
            specs.update({"z_teeth": _spec(p, "Z_Teeth"), "bore_mm": _spec(p, "Bore_mm"),
                          "compatible_chain": p.get("compatible_chain", "-")})
        lines = [f"=== {pid} ==="]
        for k, v in specs.items():
            lines.append(f"  {k}: {v}")
        results.append("\n".join(lines))

    return "\n\n".join(results) if results else "ไม่พบสินค้าที่ระบุ"


def filter_product_specs(
    spec_type: str,
    condition: str,
    target_value: float,
    product_type: str = None,
    sort_by: str = None,    
    sort_order: str = "asc",     
) -> str:
    """
    กรองสินค้าตาม spec — ใช้ Qdrant payload filter (v4)
    ใช้เมื่อลูกค้าระบุเงื่อนไขตัวเลข เช่น "กว้างไม่เกิน 100mm" "รับโหลดมากกว่า 5000N"

    Parameters
    ----------
    spec_type    : "width" | "load" | "radius" | "pitch" | "weight" | "teeth" | "bore"
    condition    : "<" | "<=" | ">" | ">=" | "=="
    target_value : ค่าตัวเลข เช่น 100.0
    """
    # ลอง Qdrant filter ก่อน — เร็วกว่า JSON loop มาก
    # 30 ต.ค. (probe_movex_r1 MXT-F3): เดิมทางนี้ไม่สน product_type / sort_by — "เลี้ยวได้" (Sideflexing) หลุด
    # กรองชนิดและเรียงต่อที่นี่ (ไม่แตะ retriever_v4)
    try:
        hits = _retriever_inner.filter_by_spec(spec_type, condition, target_value)
        if hits:
            seen, rows = set(), []
            for pid, val in hits:
                if pid in seen:
                    continue
                seen.add(pid)
                if product_type and product_type.lower() not in \
                        (product_db.get(pid, {}).get("product_type") or "").lower():
                    continue
                rows.append((pid, val))
            if sort_by:
                rows.sort(key=lambda x: float(x[1]), reverse=(sort_order == "desc"))
            else:
                rows.sort(key=lambda x: str(x[0]))
            if not rows:
                return f"ไม่พบสินค้าที่มี {spec_type} {condition} {target_value}" + \
                       (f" ในกลุ่ม {product_type}" if product_type else "")
            lines = [f"พบ {len(rows)} รุ่นที่ {spec_type} {condition} {target_value}"
                     + (f" (เฉพาะ {product_type})" if product_type else "") + ":"]
            for pid, val in rows:
                lines.append(f"  {pid} ({val})")
            return "\n".join(lines)
    except Exception as e:
        print(f"⚠️ Qdrant filter fallback to JSON: {e}")

    # Fallback: JSON loop (compat กับ field ที่ยังไม่ได้ index ใน Qdrant)
    # 30 ต.ค.: เพิ่มชื่อช่องตามข้อมูลจริง (ตัวใหญ่) — เดิม weight/teeth/bore/width หาไม่เจอในทางสำรองนี้
    key_map = {
        "width":   ["Plate_Width_mm", "plate_width_mm", "Width_mm"],
        "load":    ["Max_Working_Load_N", "max_load_n"],
        "radius":  ["Min_curve_radius_mm", "Radius_min_mm"],
        "pitch":   ["Pitch_mm", "pitch_mm"],
        "weight":  ["Weight_kg_m", "weight_kg_m"],
        "teeth":   ["Z_Teeth", "z_teeth"],
        "bore":    ["Bore_mm", "bore_mm"],
    }
    target_keys = key_map.get(spec_type.lower(), [spec_type])
    matched = []
    for pid, p in product_db.items():
        val = None
        for key in target_keys:
            if key in p and p[key] is not None:
                try:
                    val = float(p[key])
                except (ValueError, TypeError):
                    nums = re.findall(r'\d+\.?\d*', str(p[key]))
                    val = float(nums[0]) if nums else None
                if val is not None:
                    break
        if val is None and spec_type.lower() == "width":
            km = re.search(r'K(\d{3,4})', pid)
            if km:
                val = (float(km.group(1)) / 100) * 25.4
        if val is not None:
            if product_type and product_type.lower() not in p.get("product_type", "").lower():
                continue
            ok = (condition == "<"  and val <  target_value or
                  condition == "<=" and val <= target_value or
                  condition == ">"  and val >  target_value or
                  condition == ">=" and val >= target_value or
                  condition == "==" and val == target_value)
            if ok:
                matched.append(f"{pid} ({val})")
    if sort_by and matched:
        matched.sort(key=lambda x: float(re.search(r'[\d.]+', x.split('(')[1]).group()), 
                     reverse=(sort_order == "desc"))            
    if not matched:
        return f"ไม่พบสินค้าที่มี {spec_type} {condition} {target_value}"
    return f"พบ {len(matched)} รุ่น ได้แก่: {', '.join(matched)}"


def generate_datasheet(product_id: str) -> str:
    """
    สร้าง datasheet PNG (drawing + spec table) สำหรับสินค้า Movex แล้วส่งให้ลูกค้า
    ใช้ทันทีเมื่อลูกค้าพูดว่า "ขอ drawing" / "ขอ datasheet" / "ขอรูป" / "แสดงแบบ"

    Parameters
    ----------
    product_id : รหัสสินค้า เช่น "movex_chain_LF820_K325", "LF820_K325", "54201"
                 รองรับ fuzzy match — ใส่แค่บางส่วนก็ได้
    """
    pid = product_id.strip()
    if pid not in product_db:
        for k in product_db:
            if pid.lower() in k.lower() or k.lower().endswith(pid.lower()):
                pid = k
                break
    if pid not in product_db:
        return f"ไม่พบสินค้า '{product_id}' ในระบบ กรุณาตรวจสอบรหัสสินค้า"

    if pid in _datasheet_cache:
        # ตอบกลับเพื่อให้ Gemini รู้ว่า "แสดงไปแล้ว" ไม่ต้องพยายามสร้างใหม่หรือเรียก Tool ซ้ำ
        return f"ข้อมูล Datasheet ของ {pid} ได้ถูกแสดงบนหน้าจอเรียบร้อยแล้วครับ ลูกค้าสามารถดูรูปและรายละเอียดด้านบนได้เลย"

    p = product_db[pid]

    # ── หา drawing image ─────────────────────────────────────────────
    drawing_img = None
    for img_entry in p.get("images", []):
        if img_entry.get("type") == "drawing":
            img_path = img_entry["image_path"]
            if os.path.exists(img_path):
                drawing_img = Image.open(img_path).convert("RGB")
                break

    # ── Build spec rows ──────────────────────────────────────────────
    # Ref: chain ใช้ "Ref", sprocket ใช้ "Art_Nr"
    ref_val = p.get("Ref") or p.get("Art_Nr") or pid
    spec_rows = [
        ("Ref / Art.Nr", ref_val),
        ("Series",       p.get("series", "-")),
        ("Type",         p.get("product_type", "-")),
    ]
    for field, label in [
        # --- Chain fields ---
        ("Plate_Width_mm",      "Width (mm)"),
        ("Weight_kg_m",         "Weight (kg/m)"),
        ("Max_Working_Load_N",  "Max Load (N)"),
        ("Material",            "Material"),
        ("Min_curve_radius_mm", "Min Curve R (mm)"),
        ("Pitch_mm",            "Pitch (mm)"),
        # --- Sprocket fields ---
        ("Sprocket_Type",       "Sprocket Type"),
        ("manufacturing_process", "Process"),
        ("Z_Teeth",             "Teeth (Z)"),
        ("Bore_mm",             "Bore (mm)"),
        ("PD_mm",               "PD (mm)"),
        ("OD_mm",               "OD (mm)"),
        ("S_mm",                "S (mm)"),
        ("compatible_chain",    "Compatible Chain"),
    ]:
        val = p.get(field)
        if val is not None:
            spec_rows.append((label, str(val)))

    # ── Canvas setup ─────────────────────────────────────────────────
    W, H      = 920, 520
    DW        = 460        # drawing section width
    HEADER_H  = 52
    FOOTER_H  = 24
    PAD       = 18
    ROW_H     = 26

    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    draw   = ImageDraw.Draw(canvas)

    def _font(size: int):
        for path in [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    f_brand = _font(20)
    f_title = _font(16)
    f_label = _font(13)
    f_val   = _font(13)
    f_foot  = _font(11)

    # Header
    draw.rectangle([0, 0, W, HEADER_H], fill=(20, 50, 100))
    draw.text((PAD, 16),  f"Product Datasheet {p.get('Ref', pid)}",
              fill=(255, 255, 255), font=f_title)

    # Drawing area
    draw.rectangle([0, HEADER_H, DW, H - FOOTER_H], fill=(248, 248, 250))
    if drawing_img:
        max_w = DW - 2 * PAD
        max_h = H - HEADER_H - FOOTER_H - 2 * PAD
        drawing_img.thumbnail((max_w, max_h), Image.LANCZOS)
        dx = PAD + (max_w - drawing_img.width) // 2
        dy = HEADER_H + PAD + (max_h - drawing_img.height) // 2
        canvas.paste(drawing_img, (dx, dy))
    else:
        draw.text((PAD, HEADER_H + PAD), "No drawing available",
                  fill=(180, 180, 180), font=f_label)

    # Divider
    draw.line([(DW, HEADER_H), (DW, H - FOOTER_H)], fill=(180, 180, 180), width=1)

    # Spec table
    sx = DW + PAD
    y  = HEADER_H + PAD
    for i, (label, value) in enumerate(spec_rows):
        if y + ROW_H > H - FOOTER_H - PAD:
            break
        row_bg = (240, 245, 255) if i % 2 == 0 else (255, 255, 255)
        draw.rectangle([sx - 4, y - 2, W - 4, y + ROW_H - 6], fill=row_bg)
        draw.text((sx,       y), label + ":", fill=(50, 80, 130),  font=f_label)
        draw.text((sx + 155, y), value,       fill=(20, 20, 20),   font=f_val)
        y += ROW_H

    # Footer
    draw.rectangle([0, H - FOOTER_H, W, H], fill=(20, 50, 100))
    draw.text((PAD, H - FOOTER_H + 5),
              "Movex — Industrial Chain & Conveyor Solutions",
              fill=(180, 200, 230), font=f_foot)

    # Encode
    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    _datasheet_cache[pid] = base64.b64encode(buf.getvalue()).decode("utf-8")

    return f"สร้าง datasheet ของ {p.get('Ref', pid)} สำเร็จแล้ว"


# ================================================================
# SYSTEM PROMPT (ย้ายมาทั้งก้อน · decision.movex → decision.payload)
# ================================================================

def _build_system_prompt(json_context: str, graph_summary: str,vit_signal=None, decision=None) -> str:
    decision_facts = "- ไม่มีข้อมูลจากระบบ"
    if decision is not None and decision.payload:
        mx = decision.payload
        refs = [product_db[p].get("Ref") or product_db[p].get("Art_Nr") or p
                for p in (mx.get("pids") or []) if p in product_db]
        decision_facts = (f"- รุ่นที่ลูกค้าหมายถึง: {', '.join(refs) or '-'}\n"
                          f"- ซีรีส์: {mx.get('series') or '-'}\n"
                          f"- ระดับ: {mx.get('level') or '-'}\n"
                          f"- หัวข้อคำถาม: {mx.get('topic') or '-'}\n"
                          f"- เหตุผล: {decision.reason}")
    if decision is not None and decision.sales_topics:
        decision_facts += (f"\n- เรื่อง {'/'.join(decision.sales_topics)}: ระบบจะแนบข้อความส่งต่อฝ่ายขายท้ายคำตอบเอง "
                           f"ให้ตอบเฉพาะส่วนสเปก ห้ามพูดถึงเรื่องนี้ และห้ามให้ตัวเลขราคา/ระยะเวลาส่ง/สต็อก")
    vit_context = ""
    if vit_signal and vit_signal.series:
        vit_context = f"""
    [ViT Signal — ผลการวิเคราะห์รูปภาพ]
    series     : {vit_signal.series}
    confidence : {vit_signal.confidence:.3f}
    dominant   : {"✅ มั่นใจสูง (≥0.85)" if vit_signal.dominant else "⚠️ ปานกลาง (0.50–0.85)"}
    top_pid    : {vit_signal.top_pid or "-"}
    """
    return f"""
คุณคือ 'Movex Assistant' วิศวกรฝ่ายขายมืออาชีพของบริษัท Movex
ตอบภาษาไทย เป็นธรรมชาติ มีหางเสียง (ครับ/ค่ะ)

{vit_context}
[RAG Context — สินค้าที่ระบบค้นหามาได้ เรียงตาม final_score สูงสุด]
{json_context}

[GraphRAG Context — ความสัมพันธ์ของสินค้า]
{graph_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 ผลตรวจจากระบบ (ตัดสินในโค้ดแล้ว — ห้ามถามรุ่นซ้ำ)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{decision_facts}
- ระบบตรวจแล้วว่าข้อมูลพอสำหรับคำถามนี้ ให้ตอบเลย ไม่ต้องถามรุ่นหรือความกว้างซ้ำ
- ถ้าระดับ = series: ตอบเฉพาะค่าที่เหมือนกันทั้งซีรีส์ และบอกว่าเป็นค่าของทั้งซีรีส์
- ถ้าระดับ = product: ยึดรุ่นที่ระบบระบุ ถ้า rank 1 ใน RAG Context ไม่ตรงกับรุ่นนี้ ให้ใช้รุ่นที่ระบบระบุ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 ขั้นตอนที่ 3: ตอบ spec (เฉพาะเมื่อระบุรุ่นชัดแล้ว)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ยึดข้อมูลจาก rank 1 เป็นหลัก
- ห้ามมั่วตัวเลขหรือรหัสสินค้าเด็ดขาด
- "เลี้ยวได้ไหม" → ดู product_type ก่อนเสมอ (ห้ามดู radius อย่างเดียว)
  product_type = "Straight Running Chain"  → เลี้ยวไม่ได้ ตอบทันทีโดยไม่ต้องดู radius
  product_type = "Sideflexing Chain"       → เลี้ยวได้ แล้วค่อยบอก Min_curve_radius_mm
- "workload" → ดู Max_Working_Load_N
- "ใช้สเตอร์ตัวไหน" → ตอบแค่รหัสสเตอร์ที่ compatible จาก GraphRAG Context
  ห้ามอธิบาย spec ยาว ตอบแค่ชื่อรุ่น + จำนวนฟัน (Z_Teeth) + ขนาดรูเพลา (Bore_mm) ของแต่ละตัว
  เอาตัวเลขจาก record ของสเตอร์ใน RAG Context (JSON) ถ้า record ไม่มีค่านั้นให้เว้นไว้ ห้ามเดา
- "สเตอร์นั้นผลิตยังไง" → ถ้า GraphRAG มีสเตอร์ compatible หลายตัว ต้องตอบให้ครบทุกตัว
  ห้ามตอบแค่ตัวเดียวถ้า context มีมากกว่า 1
- ถ้า final_score < 0.2 ทุกรุ่น → แจ้งว่าข้อมูลไม่เพียงพอ
- ห้ามเรียก Tool เพื่อตอบ spec ที่อยู่ใน RAG Context แล้ว

🔴 กฎเด็ดขาดเรื่อง Compatible (ห้ามละเมิด):
- คำถามเรื่อง "ใช้คู่กับโซ่อะไร" / "compatible chain" / "โซ่ที่ใช้ได้" / "ใช้สเตอร์ตัวไหน"
  → ตอบจาก [GraphRAG Context] เท่านั้น ห้ามใช้ field "compatible_chain" หรือ "series" จาก RAG Context (JSON) โดยเด็ดขาด
  → ถ้า GraphRAG Context ว่างหรือไม่มี compatible → ตอบว่า "ไม่มีข้อมูล compatible ในระบบครับ" ห้ามคาดเดาหรืออ้างอิงจาก JSON field

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 กฎการใช้ Tool (เรียกเมื่อจำเป็นเท่านั้น)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ถามจำนวน/ภาพรวมทั้งหมด → Tool: analyze_product_database
2. ถามหา Sprocket คู่ → ดูจาก GraphRAG Context [Compatible parts] ก่อนเสมอ
   ห้ามใช้ Tool เพื่อหา Sprocket ถ้า GraphRAG Context มีข้อมูลอยู่แล้ว
3. เปรียบเทียบ 2 รุ่นขึ้นไป → Tool: compare_specific_products
4. กรองตาม spec ตัวเลข เช่น "กว้างไม่เกิน 100mm" → Tool: filter_product_specs
5. query มีคำต่อไปนี้ → เรียก filter_product_specs ทันทีก่อนตอบ ห้ามตอบจาก RAG Context โดยตรง:
   - "เบาสุด / น้ำหนักน้อยสุด / lightweight"  → spec_type="weight", condition=">=", target_value=0, sort_by="weight", sort_order="asc"
   - "รับโหลดสูงสุด / แข็งแรงสุด"             → spec_type="load",   condition=">=", target_value=0, sort_by="load",   sort_order="desc"
   - "กว้างสุด / กว้างมากสุด"                  → spec_type="width",  condition=">=", target_value=0, sort_by="width",  sort_order="desc"
   - "width ≥ X / กว้างอย่างน้อย X mm"         → spec_type="width",  condition=">=", target_value=X, product_type="chain"
6. ลูกค้าพูดคำต่อไปนี้ → เรียก generate_datasheet ทันที ห้ามตอบข้อความล้วน:
   - "ขอ drawing" / "drawing หน่อย" / "แสดง drawing"
   - "ขอ datasheet" / "datasheet หน่อย"
   - "ขอรูป" / "ดูรูป" / "แสดงรูป" / "รูปสินค้า"
   - "แบบ" / "แสดงแบบ" / "ขอดูแบบ"
   → ใช้ product_id ของ rank 1 ใน RAG Context หรือ product ที่ลูกค้าพูดถึง
   → หลังจากแสดง datasheet แล้ว บอก spec สั้นๆ ด้วย
   → (กฎเพิ่มเติม): ห้ามเรียก generate_datasheet ซ้ำสำหรับสินค้าเดิม 
     หากในประวัติการสนทนา (Chat History) เพิ่งมีการแสดง datasheet ของสินค้านั้นไปแล้ว 
     ยกเว้นลูกค้าจะสั่ง "ขอรูปอีกครั้ง" หรือ "ขอดูรุ่นอื่น"
"""


# ================================================================
# ขั้นค้น → prompt  /  ขั้นหลัง LLM ตอบ   (ย้ายมาจาก chat_interaction เส้น Movex)
# ================================================================

NOT_FOUND_IMAGE_TH = ("รูปนี้อาจถ่ายไกลเกินไป หรือยังไม่ชัดพอให้ระบุรุ่นโซ่ครับ "
                      "กรุณาถ่ายจากด้านบนให้เห็นแผ่นโซ่หรือสเตอร์เต็มกรอบ หรือแจ้งรหัสที่ปั๊มบนตัวสินค้าครับ")
DEFAULT_IMAGE_PROMPT = "ลูกค้าส่งรูปภาพมา ช่วยวิเคราะห์สเปกจาก RAG Context"
RETRY_PROMPT = "กรุณาสรุปคำตอบสั้นๆ ให้ลูกค้าทราบด้วยครับ"
EMPTY_REPLY_TH = "ขออภัยครับ ระบบไม่สามารถสร้างคำตอบได้ในขณะนี้ กรุณาลองถามใหม่อีกครั้ง"


class MovexRuntime:
    def __init__(self, brand_key: str, retriever: InstrumentedRetriever, logger, tool_log):
        self.key = brand_key
        self.retriever = retriever
        self.logger = logger
        self.tool_log = tool_log
        self.tools = [tool_log.track(analyze_product_database), tool_log.track(compare_specific_products),
                      tool_log.track(filter_product_specs), tool_log.track(generate_datasheet)]

    # ── รูป ──
    def score_image(self, image, text: str) -> ImageScore:
        pre = self.retriever.search(query=text, query_image=image, query_type="image")
        s = self.retriever._vit_signal
        rejected = (not pre.products) and pre.image_search_used
        return ImageScore(brand=self.key, confidence=s.confidence, accepted=not rejected,
                          label=None, group=s.series, dominant=s.dominant,
                          product_ref=s.top_pid or "", raw=pre)

    # ── ค้น → prompt ──
    def build_turn(self, decision, turn) -> LLMTurn:
        retriever, logger, dbg = self.retriever, self.logger, []
        user_text, img_input, turn_log = turn.user_text, turn.image, turn.log
        is_followup, last_vit_signal, last_graph_result = turn.followup, turn.last_image, turn.last_context
        query_type = "image" if img_input is not None else "general"

        effective_text = turn.effective_text
        if img_input is None and decision.effective_text and decision.effective_text != user_text.strip():
            effective_text = decision.effective_text      # ลูกค้าเพิ่งตอบคำถามกลับ → รวมกับคำถามเดิม

        # PHASE 3: Retrieval — ใช้ผลค้นรูปที่ทำไปแล้วตอนตัดสิน ถ้ามี
        pre_result = turn.image_score.raw if (turn.image_score is not None
                                              and turn.image_score.brand == self.key) else None
        retrieval_result = pre_result if pre_result is not None else retriever.search(
            query=effective_text,
            query_image=img_input if img_input else None,
            query_type=query_type,
        )

        # carry-over vit_signal เมื่อไม่มีรูป
        vit_sig = retriever._vit_signal
        if is_followup and not vit_sig.series and last_vit_signal:
            vit_sig = last_vit_signal
            dbg.append(f"**ViT (carry-over):** series={vit_sig.series} conf={vit_sig.confidence:.3f}\n")

        # carry-over graph_result เมื่อเป็น follow-up
        if is_followup and last_graph_result:
            if not (retrieval_result.graph_result and
                    retrieval_result.graph_result.seed_products):
                retrieval_result.graph_result = last_graph_result
                retrieval_result.graph_context = retriever.inner._graph_result_to_context(last_graph_result)
                dbg.append(f"**Graph (carry-over):** seeds={last_graph_result.seed_products}\n")
        if vit_sig.series:
            dbg.append(
                f"**ViT series:** {vit_sig.series} "
                f"(conf={vit_sig.confidence:.3f}, "
                f"dominant={'✅' if vit_sig.dominant else '❌'})\n"
            )
        if retrieval_result.graph_result and retrieval_result.graph_result.seed_products:
            gr = retrieval_result.graph_result
            dbg.append(
                f"**Graph:** seeds={gr.seed_products} | "
                f"compatible={gr.compatible[:3]} | "
                f"hop_trace={gr.hop_trace}\n"
            )
        dbg.append("\n")

        # LOG
        logger.log_keyword(turn_log, retriever._score_map_snapshot)
        if img_input is not None:
            logger.log_image(
                turn_log,
                vit_hits_raw=retriever._vit_hits_raw,
                siglip_hits_raw=retriever._siglip_hits_raw,
                vit_series=retriever._vit_series or None,
                vit_dominant=retriever._vit_dominant,
                vit_top_score=retriever._vit_top_score,
                vit_confidence_threshold=_retriever_inner.cfg.vit_confidence_threshold,
            )
        logger.log_graph(turn_log, graph_context=retrieval_result.graph_context,
                         triggered_by=retriever._graph_triggered_by)
        logger.log_text(turn_log, hits_raw=retriever._text_hits_raw, skipped=False, skip_reason="")
        logger.log_rrf(turn_log, score_map=retriever._score_map_snapshot, ranked=retriever._ranked_snapshot)

        # Image not found
        if img_input and not retrieval_result.products and retrieval_result.image_search_used:
            return LLMTurn("", [], debug=dbg, direct_reply=NOT_FOUND_IMAGE_TH)

        # PHASE 4: Rank — Keyword Boost + Final Sort
        retrieval_result.vit_signal = vit_sig
        ranked_result = _retriever_inner.rank(retrieval_result)
        dbg.append(f"**Mode:** RRF+KeywordBoost (no CE)\n")
        logger.log_reranker(turn_log, ranked_result)

        llm_context: list[dict] = []
        for rank, p in enumerate(ranked_result.products, 1):
            pid = p.product_id
            dbg.append(
                f"**{rank}. {pid}** "
                f"(final:{p.final_score:.3f} | CE:{p.cross_encoder_score:.2f} | "
                f"RRF:{p.rrf_score:.4f})\n"
            )
            if pid in product_db:
                enriched = _enrich_product(product_db[pid])
                enriched.update({
                    "_rank": rank,
                    "_final_score": round(p.final_score, 4),
                    "_best_chunk": p.best_chunk_text,
                })
                llm_context.append(enriched)
        # รุ่นที่ระบบตัดสินแล้วว่าลูกค้าหมายถึง → กราฟและข้อมูลมาจากรุ่นนั้น (ไม่ใช่จากผลค้นข้อความสั้น ๆ)
        focus = [p for p in ((decision.payload or {}).get("pids") or []) if p in product_db]
        fgr = focus_graph(focus, kg) if focus else None
        _gr0 = retrieval_result.graph_result
        if fgr is not None and not (_gr0 and set(focus) & set(_gr0.seed_products or [])):
            retrieval_result.graph_result = fgr
            dbg.append(f"**Graph (focus):** seeds={focus} compatible={fgr.compatible[:4]}\n")
        if focus:
            asks_spr = bool(SPROCKET_TOPIC_RX.search(effective_text or "") or SPROCKET_TOPIC_RX.search(user_text or ""))
            added = ensure_focus_context(llm_context, focus, product_db,
                                         (retrieval_result.graph_result.compatible
                                          if retrieval_result.graph_result else []), asks_spr)
            if added:
                dbg.append(f"**Context (focus):** เพิ่ม {added}\n")
        # 30 ต.ค.: คำถามหารุ่นที่ตัวตีความคำถามแปลงแล้ว (brands/movex/search.py) — ผลค้นทั้งฐานด้วยโค้ด
        # วางไว้บนสุด แทนผลค้นข้อความ ซึ่งตอบคำถาม "รุ่นไหนสูงสุด" ไม่ได้
        sr = (decision.payload or {}).get("search_result")
        search_block = ""
        if sr:
            spids = [p for p in ((decision.payload or {}).get("search_pids") or []) if p in product_db]
            have = {c.get("product_id") for c in llm_context}
            for i, sp in enumerate(spids):
                rec = _enrich_product(product_db[sp])
                rec.update({"_rank": 0, "_note": "ผลค้นทั้งฐานตามเงื่อนไขของลูกค้า (เรียงตามผลค้น)"})
                if sp in have:
                    llm_context[:] = [c for c in llm_context if c.get("product_id") != sp]
                llm_context.insert(i, rec)
            search_block = ("\n[ผลค้นทั้งฐานด้วยโค้ด — ใช้ตอบคำถามนี้เป็นหลัก ตอบครบทุกรายการ ห้ามตัดออก "
                            "ห้ามสรุปว่าไม่มีถ้า matched > 0]:\n" + json.dumps(sr, ensure_ascii=False))
            dbg.append(f"**Search (ตีความคำถาม):** {sr.get('query')} → {sr.get('matched')}/{sr.get('scanned')}\n")
        if not llm_context:
            dbg.append("⚠️ ไม่พบข้อมูลสินค้าที่ตรงกัน")

        # PHASE 5: prompt
        json_context = json.dumps(llm_context, ensure_ascii=False, indent=2)

        # Graph fallback: ถ้า graph ไม่มี seeds ให้ traverse จาก rank-1 โดยตรง
        _gr = retrieval_result.graph_result
        if (not _gr or not _gr.seed_products) and ranked_result.products:
            _top_pid = ranked_result.products[0].product_id
            try:
                _compatible   = kg.get_compatible_products(_top_pid)
                _same_series  = kg.get_same_series(_top_pid)
                _mat_details  = kg.get_material_details(_top_pid)
                _proc_details = kg.get_process_details(_top_pid)
                if _compatible or _same_series or _mat_details or _proc_details:
                    _fallback_gr = GraphResult()
                    _fallback_gr.seed_products    = [_top_pid]
                    _fallback_gr.compatible       = _compatible
                    _fallback_gr.same_series      = _same_series
                    # {รหัส: ฟิลด์} แบบเดียวกับ focus_graph — เดิมใส่ dict ฟิลด์ตรง ๆ แล้ว to_llm_context พัง
                    _fallback_gr.material_details = ({products_of(_top_pid).get("Material") or "material": _mat_details}
                                                     if _mat_details else {})
                    _fallback_gr.process_details  = ({products_of(_top_pid).get("manufacturing_process") or "process":
                                                      _proc_details} if _proc_details else {})
                    retrieval_result.graph_result = _fallback_gr
                    dbg.append(f"**Graph (fallback rank1):** seeds=[{_top_pid}] compatible={_compatible[:3]}\n")
            except Exception as _e:
                print(f"[WARN] graph fallback failed: {_e}")

        graph_summary = _build_graph_summary(retrieval_result.graph_result) + search_block
        _gr_final = retrieval_result.graph_result
        if _gr_final is not None and getattr(_gr_final, "compatible", None) and \
                (SPROCKET_TOPIC_RX.search(effective_text or "") or SPROCKET_TOPIC_RX.search(user_text or "")):
            spec = sprocket_spec_lines(_gr_final.compatible, product_db)
            if spec:
                graph_summary += ("\n[สเปกสเตอร์ที่ใช้ร่วมกันได้ — ตอบตามบรรทัดนี้ครบทุกตัว ทั้งจำนวนฟันและรูเพลา]:\n"
                                  + "\n".join(spec))
                dbg.append(f"**Sprocket spec:** {len(spec)} ตัว\n")
        system_instruction = _build_system_prompt(json_context, graph_summary, vit_signal=vit_sig,
                                                  decision=decision)
        img_part = None
        if img_input:
            buf = BytesIO()
            img_input.convert("RGB").save(buf, format="JPEG")
            img_part = {"mime_type": "image/jpeg", "data": buf.getvalue()}
        prompt = (decision.effective_text if decision.effective_text != user_text.strip() else user_text.strip()) \
            or DEFAULT_IMAGE_PROMPT
        return LLMTurn(system_instruction, [img_part, prompt] if img_part else [prompt],
                       tools=self.tools, debug=dbg,
                       state=dict(ranked_result=ranked_result, retrieval_result=retrieval_result,
                                  vit_sig=vit_sig))

    # ── หลัง LLM ตอบ ──
    def finish_turn(self, decision, turn, llm_turn, result) -> TurnOutput:
        tool_calls = result.tool_calls
        ai_reply = extract_text(result.response).strip()

        datasheet_b64_list = []
        for tc in tool_calls:
            if tc["tool_name"] == "generate_datasheet" and tc["success"]:
                req = tc["args"].get("product_id", "").strip()
                b64 = _datasheet_cache.get(req)
                if not b64:
                    for k, v in _datasheet_cache.items():
                        if req.lower() in k.lower() or k.lower().endswith(req.lower()):
                            b64 = v
                            break
                if b64:
                    datasheet_b64_list.append(b64)

        # กรณีที่ 1: datasheet สำเร็จ แต่ ai_reply ว่างเปล่า
        if datasheet_b64_list and not ai_reply:
            pid_label = tool_calls[-1]["args"].get("product_id", "สินค้า")
            ai_reply = f"นี่คือข้อมูล datasheet ของ **{pid_label}** ที่คุณขอครับ"
            print(f"[INFO] Auto-generated reply for datasheet: {pid_label}")
        # กรณีที่ 2: ไม่มี datasheet และ ai_reply ว่าง — retry
        if not ai_reply and not datasheet_b64_list:
            print("[WARN] Gemini returned empty response — retrying once")
            retry_response = result.session.send_message(RETRY_PROMPT)
            ai_reply = extract_text(retry_response).strip()
        # กรณีที่ 3: ยังว่างอีก
        if not ai_reply:
            ai_reply = EMPTY_REPLY_TH

        extra = [{
            "role": "assistant",
            "content": ('<img src="data:image/png;base64,' + b64 +
                        '" style="max-width:100%;border-radius:8px;'
                        'box-shadow:0 2px 8px rgba(0,0,0,.15);margin:8px 0;" />'),
        } for b64 in datasheet_b64_list]

        st = llm_turn.state
        last_vit_signal, last_graph_result = turn.last_image, turn.last_context

        def carry(final_reply: str):
            # รวมจาก 2 แหล่ง: reranked top products + pid ที่คำตอบสุดท้ายพูดถึง
            new_last_pids = []
            try:
                for p in st["ranked_result"].products[:3]:
                    if p.product_id not in new_last_pids:
                        new_last_pids.append(p.product_id)
                for m in re.finditer(r'\b(LF\s*\d+\s*(?:TAB\s*)?[A-Z]?\d+|LFN\s*\d+\s*\w+|\d{5})\b',
                                     final_reply, re.IGNORECASE):
                    pid = m.group().strip()
                    if pid not in new_last_pids:
                        new_last_pids.append(pid)
                    if len(new_last_pids) >= 5:
                        break
            except Exception:
                pass
            vit_sig = st["vit_sig"]
            new_vit_signal = vit_sig if vit_sig and vit_sig.series else last_vit_signal
            rr = st["retrieval_result"]
            new_graph_result = rr.graph_result if (rr.graph_result and rr.graph_result.seed_products) \
                else last_graph_result
            return new_last_pids, new_vit_signal, new_graph_result

        return TurnOutput(ai_reply, extra_messages=extra, carry_fn=carry)
