"""
agent_baseline/mcp_server.py — MCP server (stdio) ของเครื่องมือ Modutech สำหรับ agent เทียบ

มาตรฐาน: Model Context Protocol · SDK `mcp` 2.x (MCPServer) · ADK เปิดไฟล์นี้เองผ่าน stdio
รันตรวจเอง: python agent_baseline/mcp_server.py   (รอรับ JSON-RPC ทาง stdin · Ctrl+C ออก)

คำอธิบายเครื่องมือ (docstring) คือสิ่งที่ LLM เห็น — เขียนให้ตรงกับที่เครื่องมือทำจริง ไม่ชี้นำว่าต้องถามอะไรก่อน
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from agent_baseline import movex_tools as M  # noqa: E402
from agent_baseline import tools_impl as T  # noqa: E402

app = MCPServer("modutech-catalogue")


@app.tool()
def overview_catalogue() -> str:
    """จำนวนสายพาน Modutech ทั้งฐานข้อมูล แยกตามซีรีส์ ชนิดผิว และจำนวนรุ่นที่วิ่งโค้งได้"""
    return T.overview_catalogue()


@app.tool()
def compare_belts(codes: str) -> str:
    """ตารางสเปกเทียบสายพาน 2–4 รุ่น (รหัสคั่นด้วยจุลภาค เช่น "EC127 C, HC127 C")
    คืนพิทช์ ผิว พื้นที่เปิด ความหนา การวิ่งโค้ง ความกว้าง และค่าแรงดึง/น้ำหนัก/อุณหภูมิแยกตามเกรด
    พร้อม data_quality (ธง blocking_for) และ answering (ช่องข้อมูลที่ต้องรู้ก่อนตอบ · หัวข้อที่ต้องส่งฝ่ายขาย)"""
    return T.compare_belts(codes)


@app.tool()
def search_catalogue(field: str = "", op: str = ">=", value: float = 0.0, surface: str = "",
                     pin_material: str = "", belt_material: str = "", rank: str = "") -> str:
    """ค้นสายพาน Modutech ทั้ง 68 รุ่นตามเงื่อนไข คืนทุกรุ่นที่ตรง
    field: "strength" (N/m) | "weight" (kg/m²) | "open_area" (%) | "pitch" (mm) | "" ไม่กรองตัวเลข
    op: ">=" | "<=" | ">" | "<" · value: ค่าตัวเลขของเงื่อนไข
    surface: ชื่อผิวภาษาอังกฤษ เช่น "Grip Top" · pin_material เช่น "SS" · belt_material เช่น "POM"
    rank: "max" | "min" เรียงตาม field คืน 5 อันดับแรก · "overview" จำนวนรุ่นทั้งหมด · "" กรองตามเงื่อนไข"""
    return T.search_catalogue(field, op, value, surface, pin_material, belt_material, rank)


@app.tool()
def lookup_belt(code: str) -> str:
    """ข้อมูลเต็มของสายพาน 1 รุ่นจากรหัส (รับรหัสที่เขียนต่างกันได้ เช่น "MD508C")
    สเปกทุกเกรด ความกว้าง งานใช้แยกอุตสาหกรรม ความรู้การขาย data_quality และ answering
    ถ้ารหัสไม่ชัด คืน candidates ให้ถามลูกค้า"""
    return T.lookup_belt(code)


@app.tool()
def find_by_application(text: str) -> str:
    """หารุ่นสายพานจากงานใช้หรืออุตสาหกรรมที่ลูกค้าพิมพ์ (ภาษาไทยหรืออังกฤษ)
    ใช้กราฟความรู้ (งานใช้ × อุตสาหกรรม × เกรดที่แคตตาล็อกแนะนำ) คืนรายชื่อครบ"""
    return T.find_by_application(text)


@app.tool()
def sprockets_for(belt_code: str) -> str:
    """รหัสเฟืองขับที่ใช้กับสายพานรุ่นนี้ และรุ่นอื่นในซีรีส์เดียวกัน"""
    return T.sprockets_for(belt_code)


@app.tool()
def belts_for_sprocket(sprocket_code: str) -> str:
    """สายพานที่ใช้กับรหัสเฟืองขับนี้ (เช่น "EC127SQZ19*PA")"""
    return T.belts_for_sprocket(sprocket_code)


@app.tool()
def temperature(belt_code: str, belt_material: str = "", pin_material: str = "") -> str:
    """ช่วงอุณหภูมิใช้งานของสายพานแยกตามเกรด ทั้งสภาวะแห้ง (dry) และเปียก (wet)"""
    return T.temperature(belt_code, belt_material, pin_material)


@app.tool()
def vector_search(query: str, top_k: int = 5) -> str:
    """ค้นสายพานที่ความหมายใกล้กับข้อความ (embedding Jina v3 · Qdrant) คืนรุ่นที่ใกล้ที่สุดไม่กี่รุ่น"""
    return T.vector_search(query, top_k)


@app.tool()
def match_catalogue_image(image_id: str, top_k: int = 5) -> str:
    """เทียบรูปที่ลูกค้าส่ง (image_id ตามที่ระบุในข้อความ) กับภาพสายพานจากแคตตาล็อก Modutech ด้วย SigLIP
    คืนคะแนนความคล้ายสูงสุด ค่าความใกล้คำว่า "สายพาน/โซ่" เทียบกับวัตถุอื่น และรุ่นที่ใกล้ที่สุดถ้ามีป้ายรุ่น"""
    return T.match_catalogue_image(image_id, top_k)


@app.tool()
def handoff_to_sales(topic: str) -> str:
    """ข้อความส่งต่อฝ่ายขายพร้อมช่องทางติดต่อ สำหรับเรื่องที่อยู่นอกข้อมูลสเปก"""
    return T.handoff_to_sales(topic)


# ─────────────── ลักษณะผิวจากรูป → รายชื่อรุ่น (AGENT_IMAGE_SURFACE=1 · 6 พ.ย.) ───────────────
# ปิด (ค่าเริ่มต้น) = ไม่มีเครื่องมือนี้ · เครื่องมือเท่าเดิม ผลบทที่ 4 เทียบได้
if (os.environ.get("AGENT_IMAGE_SURFACE") or "").strip() == "1":
    _SURFACES = "\n".join(f'        "{k}": {v}' for k, v in T.surface_choices().items())

    def belts_by_surface(surface: str, alternatives: str = "", openness: str = "", pitch_mm: float = 0,
                         scale_visible: bool = False, confidence: str = "medium") -> str:
        return T.belts_by_surface(surface, alternatives, openness, pitch_mm, scale_visible, confidence)

    belts_by_surface.__doc__ = f"""รายชื่อสายพาน Modutech ทุกรุ่นที่ชนิดผิวตรงกับที่เห็นในรูป (คัดจากฐานข้อมูลด้วยโค้ด)
        ไม่ใช่การระบุรุ่น — รุ่นที่ผิวเดียวกันหน้าตาคล้ายกันแต่พิทช์ วัสดุ และสเปกต่างกัน
        surface: ชื่อผิวจากรายการด้านล่าง (สะกดตามนี้) · ว่างได้ถ้าบอกแค่ openness
        alternatives: ผิวอื่นจากรายการที่ยังแยกไม่ออก คั่นด้วยจุลภาค ไม่เกิน 2
        openness: "open" (มีช่อง/รูทะลุ) | "closed" (ผิวทึบ) | ว่าง
        pitch_mm: ระยะระหว่างแนวสลัก ใส่ได้เฉพาะเมื่อมีไม้บรรทัด/สเกลในรูป และต้องตั้ง scale_visible=true (ใช้เรียงลำดับ ไม่ตัดรุ่น)
        confidence: "high" | "medium" | "low" (low = ไม่คัดรุ่น)
        ผิวที่รับได้:
{_SURFACES}"""
    app.tool()(belts_by_surface)


# ─────────────── Movex (ขั้นที่ 2) — ฟังก์ชันเดิมของเทอมที่แล้วใน brands/movex/runtime.py ───────────────
# เปิดเมื่อ AGENT_PROMPT=r2m (ค่าเริ่มต้น) หรือสั่งตรงด้วย AGENT_BRANDS=modutech,movex
# prompt r1/r2 = ขั้นที่ 1 → เครื่องมือ 11 ตัวเท่าเดิม ผลรอบก่อนจึงเทียบได้
_DEFAULT_BRANDS = ("modutech,movex" if (os.environ.get("AGENT_PROMPT") or "").strip().lower() in ("r2m", "r3")
                   else "modutech")
if "movex" in (os.environ.get("AGENT_BRANDS") or _DEFAULT_BRANDS).lower():

    @app.tool()
    def movex_overview(category: str = "all", series: str = "") -> str:
        """ภาพรวมสินค้า Movex ทั้งฐาน (โซ่ท็อปเชนและสเตอร์) จำนวนรุ่นและรายชื่อ
        category: "all" | "chain" | "sprocket" · series: กรองซีรีส์ เช่น "820" "880" (ว่าง = ทั้งหมด)"""
        return M.movex_overview(category, series)

    @app.tool()
    def movex_compare(product_ids: str) -> str:
        """เทียบสเปกสินค้า Movex หลายรุ่น (รหัสคั่นด้วยจุลภาค เช่น "LF820 K325, LF820 K750")
        คืนซีรีส์ ชนิด ความกว้างแผ่น น้ำหนัก พิทช์ โหลดใช้งานสูงสุด วัสดุ รัศมีเลี้ยว · สเตอร์: จำนวนฟัน รูเพลา โซ่ที่ใช้คู่"""
        return M.movex_compare(product_ids)

    @app.tool()
    def movex_filter(spec_type: str, condition: str, target_value: float, product_type: str = "",
                     sort_by: str = "", sort_order: str = "asc") -> str:
        """กรองสินค้า Movex ตามสเปกตัวเลข (Qdrant payload filter)
        spec_type: "width" | "load" | "radius" | "pitch" | "weight" | "teeth" | "bore"
        condition: "<" | "<=" | ">" | ">=" | "==" · target_value: ค่าตัวเลข
        product_type: กรองชนิด เช่น "chain" "Sideflexing" (ว่าง = ทุกชนิด)
        sort_by: ชื่อ spec ที่ใช้เรียง (ว่าง = เรียงตามรหัส) · sort_order: asc หรือ desc"""
        return M.movex_filter(spec_type, condition, target_value, product_type, sort_by, sort_order)

    @app.tool()
    def movex_datasheet(product_id: str) -> str:
        """สร้าง datasheet (แบบ drawing + ตารางสเปก) ของสินค้า Movex แล้วแสดงให้ลูกค้า"""
        return M.movex_datasheet(product_id)

    @app.tool()
    def movex_lookup(product_id: str) -> str:
        """ข้อมูลเต็มของสินค้า Movex 1 รุ่นจากรหัส (เช่น "LF820 K325" · "LF 880 TAB K450" · "54901")
        สเปก การใช้งาน วัสดุ กระบวนการผลิต และ graph_context (สินค้าที่ใช้คู่กัน · รุ่นอื่นในซีรีส์)
        ถ้ารหัสไม่ชัด คืน candidates ให้ถามลูกค้า"""
        return M.movex_lookup(product_id)

    @app.tool()
    def movex_search(query: str, top_k: int = 5) -> str:
        """ค้นสินค้า Movex จากข้อความ (Jina v3 + keyword · Qdrant) คืนรุ่นเรียงตาม final_score พร้อมข้อมูลรุ่น
        และ graph_context ของรุ่นที่พบ"""
        return M.movex_search(query, top_k)

    @app.tool()
    def movex_match_image(image_id: str, top_k: int = 5) -> str:
        """เทียบรูปที่ลูกค้าส่ง (image_id ตามที่ระบุในข้อความ) กับโซ่ Movex ด้วย ViT LoRA + SigLIP
        คืน vit_signal (series · confidence · dominant · top_pid) ระยะห่างคะแนนอันดับ 1–2 และรุ่นที่ใกล้ที่สุด"""
        return M.movex_match_image(image_id, top_k)


if __name__ == "__main__":
    app.run()
