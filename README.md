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
