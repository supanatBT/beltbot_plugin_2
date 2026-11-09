# CHANGELOG v31 (9 พ.ย. 2026)

`modutech_v31.json` สร้างจาก `modutech_v30_3.json` ด้วย `patch_v31.py` (ไม่แก้ไฟล์ต้นทาง ผลบทที่ 4 ที่รันบน v30_3 ยังอ้างอิงได้)
ตรวจรับด้วย `python test_v31.py` ทุกข้อผูกกับการตัดสินของเจ้าของ

ที่มา: เอกสาร "กฎการตอบหลังแก้ (v31) และปัญหาข้อมูล Modutech" (D1–D29 · R1–R11) และการตรวจเล่มของเจ้าของ 9 พ.ย.

## วิธีใช้

| ระบบ | ตั้งค่า |
|---|---|
| agent | `AGENT_PROMPT=r4` และ `AGENT_MODUTECH_JSON=modutech_v31.json` (ต้องตั้งคู่กัน) |
| agent รอบเดิม | `AGENT_PROMPT=r3` กับ v30_3 ได้ผลเท่าเดิมทุกตัวอักษร |
| บอท | ยังใช้ v30_3 ตามเดิม · โหลด v31 ได้โดยไม่ล้ม (gates อ่านฟิลด์เดิมที่คำนวณใหม่แล้ว) แต่ยังไม่ได้ทดสอบชุดคำตอบ |

## กฎการตอบ

`answering_policy.rules_th` เปลี่ยนจากกฎข้อความ 10 ข้อ (5 ข้อขัดกับข้อมูล) เป็น R1–R11 ที่อ่านฟิลด์โครงสร้าง
prompt r4 ของ agent จึงตัดรายการ "ถ้าขัดกันให้ใช้กฎด้านบน" ทิ้ง

## ข้อมูลที่แก้

| # | เรื่อง | v30_3 | v31 |
|---|---|---|---|
| D14 | วัสดุสายพานไม่มีค่าเปียก (PA · CR · IMPR · EHT · 8 variant) | เติมค่าเปียก = ค่าแห้ง · partial_data | `wet = null` · `wet_status = no_data` |
| D29 | IMPR หน้า 347 | −40/+93 (ไม่มีที่มา) | ไม่มีค่า · HC508 C-MTW IMPR ตอบ −20/+65 จากหน้า 217 |
| D17 | ค่ารอผู้ผลิต 6 variant | trust = ok 5 ตัว | `temperature_trust = unconfirmed` + `confirmation` ตรงกับ pending |
| D22 · D23 | แรงโค้ง EC508 R | `n_total` (N) — บอทและ agent ทำค่าหาย | `n_per_m` (ตัดสิน 9 พ.ย.) · `printed_unit = N` · ติด `confirmation` รอผู้ผลิตยืนยันหน่วย |
| D3 | lb/ft ที่เล่มพิมพ์ผิด | — | ทุก variant มี `lb_per_ft` คำนวณจาก N/m (EC508 PR11 PP = 1233 · MD508 FG POM/PP = 2056) |
| D19 | required_slots | EC508 PR11 ขาด | คำนวณจาก wet ≠ dry ทุกรุ่น |
| D21 | วัสดุแนะนำแต่ไม่อยู่ในตาราง | 3 ที่บอกต่างกัน · POM ที่เป็นพินถูกห้าม | `material_status` (not_listed · pin_only · listed_as) · `materials_recommended_not_manufactured` = not_listed เท่านั้น |
| D28 | EC508 TR ความกว้าง | 609.9 · เพิ่มทีละ 50.5 | 609.6 (24 นิ้ว) · 50.8 (2 นิ้ว) |
| D12 · D20 | ค่าเพิ่มทีละ / width_note_th | ข้อความมี "ผลิตได้ / สั่งพิเศษ" · ค่าเพิ่มทีละไม่ตรงเล่ม 12 รุ่น | `increment_status` (match 56 · mismatch 11 · single_width 1) · `printed_min_mm` · width_note_th สร้างใหม่จากฟิลด์ ไม่มีคำต้องห้าม ไม่บอกค่าเพิ่มทีละของรุ่น mismatch |
| R8 | blocking_for | ค้างจากธงเดิม | คำนวณใหม่จาก material_status · wet_status · ความกว้าง |
| N6 · R9 | สเตอร์ Di / Do | "เล่มไม่นิยาม" | Do = ปลายฟัน · Di = วงในโคนฟัน (อ่านจากภาพวาด ตัดสิน 9 พ.ย.) · A B ยังไม่นิยาม |

## ฟิลด์ที่ตัด

`answering.forbidden_th` · `answering.disqualifiers` · `variants[].temperature_note_th` · `temperature.registry_conflict_th` / `registry_dry_max_c` ·
`temperature_effective.wet_note_th_v30` · `derived.temperature_envelope` · `data_quality.blocking` และรายการว่าง 5 รายการ ·
`retrieval_card.has_blocking_issue` · `industries[].caveats_th` / `caveats` (D25 ชื่อผิวยึด surface_type_note_th · D26 เรื่องขาย 5 ประเทศ)

## ฟิลด์ที่คงชื่อไว้แต่คำนวณใหม่ (บอทยังอ่าน)

`answering.required_slots` · `specifications.width_effective.width_note_th` · `data_quality.materials_recommended_not_manufactured` ·
`data_quality.blocking_for` · `data_quality.wet_condition_unknown` · `code_parts.pitch_mm` (เพิ่ม `nominal_pitch_from_code_mm` เพราะ image_read.py ยังอ่านชื่อเดิม)

## ตัดสินแล้วว่าไม่แก้ข้อมูล

- D6 น้ำหนัก EC508 R PP/POM 7.5: ตอบตามปกติ
- D27 PA ตารางพิมพ์ −46 °C ฐานใช้ −35 °C: ตอบค่าที่เข้มกว่า ไม่เตือน (แบบเดียวกับ POM/PA)
- HC508 ค่าเพิ่มทีละ: ใช้การตัดสิน 30 ก.ย. (ไม่บอก)

## pending_vendor_confirmation

- `curve-strength-unit` เขียนใหม่: EC508 R ใช้ N/m ตามการตัดสิน รอผู้ผลิตยืนยัน
- `wet-condition-missing` เพิ่ม EHT
- เพิ่ม `pph-celsius-fahrenheit-mismatch` (MD254 RR PPH 93 °C)

## agent (r4)

- `tools_impl.py`: เมื่อ `AGENT_PROMPT=r4` ส่ง `width` (ค่าเพิ่มทีละเฉพาะ match / not_printed) · `required_slots` · `blocking_for` · `material_status` · `wet_status` · `confirmation` · lb/ft แทน answering / data_quality ดิบ · ตัดท่อนค่าเพิ่มทีละออกจาก notes ของรุ่น mismatch · `sprockets_for` คืน Do / Di
- `agent.py`: `instruction_r4()` = r3 + เขียนใหม่ 7 หมวด (อุณหภูมิ · ความแข็งแรง · blocking_for · ความกว้าง · สเตอร์ · required_slots · answering_policy)
- r1–r3 ไม่เปลี่ยน · `test_agent_baseline.py` ผ่าน 21/21 ทั้ง r3 + v30_3 และ r4 + v31
