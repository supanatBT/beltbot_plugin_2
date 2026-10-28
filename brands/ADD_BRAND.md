# เพิ่มแบรนด์ที่ 3 — checklist

ตัวอย่างที่ใช้งานได้จริงคือ `brands/demo/` (ข้อมูลสมมติ 3 รุ่น) ให้คัดลอกโฟลเดอร์นี้ไปเป็นต้นแบบ
แกนกลาง (`core/`) ไม่รู้จักชื่อแบรนด์ใดเลย การเพิ่มแบรนด์จึงไม่ต้องแก้ `core/` · `assistant.py` · `app.py`

## 1. ข้อมูล
- [ ] ทำแคตตาล็อกเป็น JSON แล้ววางไว้ที่รากรีโป **เก็บไฟล์ดิบไว้คู่ไฟล์ที่ซ่อม** โดยตั้งชื่อตามเวอร์ชัน (`<brand>_v1.json` → `<brand>_v1_1.json`)
- [ ] ทุกการซ่อมต้องทำผ่าน `patch_*.py` และเขียน CHANGELOG ห้ามแก้ไฟล์ด้วยมือ
- [ ] เพิ่มชื่อไฟล์ลงใน `LINEAGE` หรือ `OTHER` ของ `data_manifest.py` แล้วรันใหม่เพื่อจด sha256

## 2. ฐานเวกเตอร์ (ถ้าใช้)
- [ ] build ลงโฟลเดอร์ Qdrant **แยกของแบรนด์นั้น** (`qdrant_<brand>_db`) ห้ามเขียนลง `qdrant_db` ของ Movex และห้ามใช้ `build_database.py`
- [ ] ตั้งชื่อ collection ให้มีเวอร์ชัน เช่น `<brand>_chunks_v1` แล้วตั้ง alias ดังนี้
  `qdrant_alias.py set --path qdrant_<brand>_db --alias <brand>_live --to <brand>_chunks_v1`
- [ ] ใน `brand.yaml` ใส่ `data.text_collection: <brand>_live` และ `text_collection_fallback: <brand>_chunks_v1`

## 3. ปลั๊กอิน
- [ ] `brands/<brand>/brand.yaml`: ใส่ `key` · `info` (ทุกช่อง และ `order` ต้องไม่ซ้ำกับแบรนด์อื่น) · `state` · `data` · `image`
- [ ] `brands/<brand>/plugin.py` ต้องมี `create(ctx)` และเมธอดตามสัญญาใน `core/protocol.py` ได้แก่ detect · decide · build_turn · finish_turn · sanitize_state · image_scorer
- [ ] ถ้าต้องมีปุ่มตอบเร็ว ให้เพิ่ม `reply_suggestions(pending, fields)` ซึ่งต้องเป็นแบบอ่านอย่างเดียว
- [ ] ข้อความถึงลูกค้าต้องไม่รับปากเรื่องราคา สต็อก หรือการติดต่อกลับ

## 4. รูป (ถ้ามี)
- [ ] ถ้าไม่มีโมเดลรูป ให้ตั้ง `image.enabled: false` บอทจะถามแบรนด์แทนการเดา
- [ ] ถ้ามีโมเดลรูป ให้ใส่ ViT adapter + `revision` (adapter ในเครื่องใช้ sha256 ส่วนบน Hub ใช้ commit) + labels + thresholds + collection
- [ ] เตรียมชุดรูปสำหรับตั้งเกณฑ์ แยกเป็น cal กับ eval ในรูปแบบเดียวกับ `brand_calibration_rows.csv`
  **ตั้งเกณฑ์จากชุด cal เท่านั้น** แล้วรายงานผลจาก eval
- [ ] คำนวณกฎ conflict, confirm และ direct ใหม่ เพราะเกณฑ์ของแบรนด์เดิมตั้งไว้ตอนที่มีแค่สองแบรนด์
- [ ] ถ้าใช้โมเดลจาก Hub ให้เพิ่มลงใน `MODELS` ของ `models_lock.py` แล้วรัน `--write`

## 5. ทดสอบก่อนเปิด
- [ ] รัน `BRANDS=movex,modutech` เทียบกับรันทุกแบรนด์ คำตอบของแบรนด์เดิมต้องไม่เปลี่ยน
- [ ] รันชุดเทสเดิมทั้งหมด (`run_checks.ps1`) แล้วรัน `brands/<brand>/test_*.py` ของแบรนด์ใหม่
- [ ] ทำชุดเทสรูปแบบ `run_list.csv` (สินค้าจริง · ของคล้าย · ไม่ใช่สินค้า) แล้วรันด้วย `run_images.py`
- [ ] เปิด `/health/detail` แล้วดูว่าแบรนด์ใหม่ขึ้นครบทั้ง data, collections และ gate

## 6. deploy
- [ ] อัปโหลดโฟลเดอร์แบรนด์, ไฟล์ข้อมูล, โฟลเดอร์ Qdrant, `models.yaml` และ `DATA_MANIFEST.json` ขึ้น Space
- [ ] หลัง Space เริ่มทำงาน ให้ดู `/health` ช่อง `versions` ต้องไม่มี `models_mismatch` และ `data_ok` ต้องเป็น true
