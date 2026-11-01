# agent เทียบ (agent-baseline)

agent ที่ใช้โมเดล ข้อมูล และชุดทดสอบเดียวกับบอทหลัก แต่ไม่มีชั้นตัดสินในโค้ด
กฎชุดเดียวกันอยู่ใน system prompt · LLM เลือกเครื่องมือ ถามกลับ ส่งฝ่ายขาย และงดตอบเอง

| ชั้น | ใช้ |
|---|---|
| agent | Google ADK 2.11 (รุ่นสุดท้ายที่รองรับ Python 3.10 เท่ากับบอทหลัก) · `LlmAgent` · session ในหน่วยความจำ |
| เครื่องมือ | MCP server (`mcp` 2.3 · stdio) 11 ตัว · `agent_baseline/mcp_server.py` |
| ข้อมูล | `modutech_v30_3.json` · กราฟจาก JSON · Qdrant `modutech_live` (อ่านอย่างเดียว) · แกลเลอรีรูป `image_gate.npz` |
| โมเดล | `GEMINI_MODEL` · `GEMINI_THINKING` (ค่าเดียวกับบอทหลัก) |

ขั้นที่ 1 = Modutech (ข้อความ + รูป) · ขั้นที่ 2 = เพิ่ม Movex

ไฟล์: `tools_impl.py` (เครื่องมือ Python ล้วน) · `mcp_server.py` · `agent.py` · `../agent_assistant.py` (ตัวเชื่อมกับ `run_answer_eval.py`)
· `../run_image_eval_agent.py` (ชุดรูป) · `../test_agent_baseline.py` (ออฟไลน์ · LLM ปลอม) · `check_tools.py`
