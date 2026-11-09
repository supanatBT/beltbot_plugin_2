# agent เทียบ (agent-baseline)

agent ที่ใช้โมเดล ข้อมูล และชุดทดสอบเดียวกับบอทหลัก แต่ไม่มีชั้นตัดสินในโค้ด
กฎชุดเดียวกันอยู่ใน system prompt · LLM เลือกเครื่องมือ ถามกลับ ส่งฝ่ายขาย และงดตอบเอง

| ชั้น | ใช้ |
|---|---|
| agent | Google ADK 2.11 (รุ่นสุดท้ายที่รองรับ Python 3.10 เท่ากับบอทหลัก) · `LlmAgent` · session ในหน่วยความจำ |
| เครื่องมือ | MCP server (`mcp` 2.3 · stdio) 11 ตัว · `agent/mcp_server.py` |
| ข้อมูล | `data/modutech_v30_3.json` (r4: `data/modutech_v31.json`) · กราฟจาก JSON · Qdrant `modutech_live` (อ่านอย่างเดียว) · แกลเลอรีรูป `image_gate.npz` |
| โมเดล | `GEMINI_MODEL` · `GEMINI_THINKING` (ค่าเดียวกับบอทหลัก) |

ขั้นที่ 1 = Modutech (ข้อความ + รูป) · ขั้นที่ 2 = เพิ่ม Movex

ไฟล์: `tools_impl.py` (เครื่องมือ Python ล้วน) · `mcp_server.py` · `agent.py` · `assistant.py` (ตัวเชื่อมกับ `eval/run_answer_eval.py`)
· `../eval/run_image_eval_agent.py` (ชุดรูป) · `../tests/test_agent_baseline.py` (ออฟไลน์ · LLM ปลอม) · `check_tools.py`

## ขั้นที่ 2 · Movex (2 พ.ย. · branch agent-movex)
- `movex_tools.py` เครื่องมือ 7 ตัว เรียกฟังก์ชันเดิมของเทอมที่แล้วใน `brands/movex/runtime.py` ตรง ๆ
  `movex_overview` (analyze_product_database) · `movex_compare` · `movex_filter` (Qdrant payload filter เหมือนบอท) · `movex_datasheet`
  \+ สิ่งที่ prompt เทอมที่แล้วฉีดให้ LLM ทุกเทิร์น ทำเป็นเครื่องมือ: `movex_search` (RAG + GraphRAG) · `movex_lookup` · `movex_match_image` (ViT signal)
  ไม่บังคับกฎ · อ่านอย่างเดียว · ไม่แตะ collection ของ Movex · Jina/SigLIP โหลดชุดเดียวใช้ร่วมกับ Modutech
- prompt `r2m` = r2 ทุกตัวอักษรในหมวด Modutech + หมวดเลือกแบรนด์ (เมนูเดียวกับบอท) + หมวด Movex (กฎ prompt เทอมที่แล้ว · เกณฑ์ ViT จาก thresholds.json)
- เครื่องมือ Movex เปิดเมื่อ `AGENT_PROMPT=r2m` (r1/r2 ได้ 11 ตัวเท่าขั้นที่ 1) หรือ `AGENT_BRANDS=modutech,movex`
- ทดสอบ: `tests/test_agent_movex.py` (ออฟไลน์) · `agent/check_movex_tools.py <รูปโซ่>` (เครื่องที่มีโมเดล)
