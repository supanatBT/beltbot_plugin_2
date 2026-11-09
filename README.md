---
title: Modutech Movex Assistant
emoji: 🔗
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# ผู้ช่วยสินค้า Movex · Modutech

API ตอบคำถามสเปกโซ่ท็อปเชน Movex และสายพานโมดูลาร์ Modutech
หน้าเว็บอยู่คนละที่ (Next.js บน Vercel) เรียกเข้ามาที่นี่ผ่าน proxy ของตัวเอง

ส่วนหนึ่งของปริญญานิพนธ์ ไม่ใช่ระบบขายจริง
ราคา ระยะเวลาส่งของ และสต็อก ฝ่ายขายเป็นผู้ยืนยัน ระบบนี้ไม่ตอบ

## Endpoints

| | |
|---|---|
| `GET /health` | สถานะ — `loading` ระหว่างโหลดโมเดลรอบแรก |
| `POST /api/chat` | multipart: `text` · `image` · `session_id` · `resume` |
| `POST /api/session/reset` | เริ่มบทสนทนาใหม่ |
| `GET /media/{token}` | รูปแบบสินค้าที่บอทส่งกลับ |

เรียกตรงไม่ได้ถ้าตั้ง `PROXY_SECRET` ไว้ — ต้องผ่าน proxy ที่แนบ header มาด้วย

## ค่าที่ต้องตั้งเป็น Secret

ตั้งที่ Settings → Variables and secrets **ห้ามใส่ในไฟล์ `.env` ที่ push ขึ้นมา**
เพราะ Space นี้เปิดสาธารณะ ใครก็เปิดดูไฟล์ในรีโปได้

| ชื่อ | คืออะไร |
|---|---|
| `GEMINI_API_KEY` | คีย์ Gemini |
| `PROXY_SECRET` | ต้องตรงกับค่าเดียวกันฝั่ง Vercel |

## รอบแรกจะช้า

ต้องดาวน์โหลด Jina v3 กับ SigLIP ลงแคชก่อน ราวหนึ่งถึงสองนาที
ระหว่างนั้น `/api/chat` ตอบ 503 `warming_up` และหน้าเว็บจะขึ้นข้อความให้รอ

Space รุ่นฟรีหลับเมื่อไม่มีคนใช้ และล้างไฟล์ทุกครั้งที่เริ่มใหม่
บทสนทนาจึงเก็บไว้ที่เบราว์เซอร์ของผู้ใช้ แล้วส่งกลับมาทาง `resume` เมื่อ session หาย

## โครงโฟลเดอร์ (จัดใหม่ 9 พ.ย. 2026)

รันทุกคำสั่งจาก **รากของ repo** — พาธข้อมูลนับจากราก (สคริปต์ในโฟลเดอร์ย่อย `cd` มาที่รากเองตอนเริ่ม)

| โฟลเดอร์ | ของ | ใช้กับ |
|---|---|---|
| `app.py` · `webapi/` | FastAPI ที่หน้าเว็บเรียก · เลือกตัวตอบด้วย `BOT_MODULE` | ทั้งสองระบบ |
| `bot/` | บอทหลัก (โค้ดตัดสินใจ + LLM เรียบเรียง): `assistant.py` · `dialogue_state.py` · `pipeline_logger.py` | `BOT_MODULE=bot.assistant` |
| `agent/` | agent (Google ADK + MCP · กฎอยู่ใน prompt): `assistant.py` · `agent.py` · `tools_impl.py` · `movex_tools.py` · `mcp_server.py` | `BOT_MODULE=agent.assistant` |
| `core/` | แกนกลางที่ไม่รู้จักชื่อแบรนด์ (router · decide · turn · reply_guard ...) | ทั้งสอง |
| `brands/` | ปลั๊กอินรายแบรนด์ (`modutech/` เกต กราฟ ตัวค้น · `movex/` กราฟ runtime · `demo/`) | ทั้งสอง — agent เรียกฐานและตัวค้นชุดเดียวกับบอทเพื่อให้เทียบกันได้ |
| `shared/` | ของใช้ร่วมที่รู้จักชื่อแบรนด์: `retriever_v4.py` (ค้นเวกเตอร์) · `sales_contact.py` | ทั้งสอง |
| `data/` | แคตตาล็อก JSON (`modutech_v30_3.json` ตัวที่ล็อก · `modutech_v31.json`) · Movex · กราฟ `.db` · Qdrant · ViT LoRA · `DATA_MANIFEST.json` | — |
| `image/` | รูปสินค้า Movex — **อยู่ที่รากต่อ** เพราะพาธ `image/...` ฝังอยู่ในข้อมูล Movex และ payload ของ Qdrant | — |
| `tests/` | เทสต์ออฟไลน์ `python tests/test_xxx.py` | — |
| `eval/` | วัดผล: `run_answer_eval.py` · `run_ch4.ps1` · `simulate_customers.py` ... · ชุดทดสอบใน `eval/cases/` | — |
| `tools/` | เครื่องมือข้อมูลและการตั้งเครื่อง: `patch_v3*.py` · `data_manifest.py` · `check_app.py` · `qdrant_alias.py` ... | — |
| `training/` | สมุดทดลอง MLflow · ชุดเกต · ฝึก ViT | — |
| `docs/` | CHANGELOG ของข้อมูล | — |
| `archive/` | ผลรันเก่า (ไม่มีโค้ดอ่าน) | — |
| `web/` | หน้าเว็บ Next.js (deploy ที่ Vercel) | — |

ชื่อโมดูลเดิม (`assistant` · `agent_assistant` · `chatbot_v5`) ยังใช้ใน `BOT_MODULE` และ `--module` ได้ — แปลงที่ `core/entrypoints.py`

คำสั่งที่ใช้บ่อย

```powershell
.\run_app.ps1 -Python <python ของบอท>                     # บอท + หน้าเว็บ
.\run_agent_app.ps1 -Python <python ของ agent>            # agent + หน้าเว็บ
powershell -ExecutionPolicy Bypass -File .\eval\run_ch4.ps1 -System agent -Python $PY -Testcases ..\blind_v2.csv -Tag blind2 [-V31]
python tests\test_v31.py                                   # ตรวจรับฐาน v31
python tools\patch_v31.py                                  # สร้าง data/modutech_v31.json จาก v30_3
```
