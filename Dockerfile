# Dockerfile สำหรับ Hugging Face Space (SDK = docker, CPU ฟรี)
#
# Python 3.10 ให้ตรงกับ venv ที่พิสูจน์แล้วว่ารัน 172 เทิร์นผ่าน (3.10.0 บนเครื่อง)
# ไม่ใช้ 3.11/3.12 เพราะล้อแพ็กเกจที่ปักหมุดไว้ถูกสร้างและทดสอบกับ 3.10
FROM python:3.10-slim

# Spaces รันคอนเทนเนอร์ด้วยผู้ใช้ที่ไม่ใช่ root — ต้องสร้างเองและให้สิทธิ์ให้ครบ
# ไม่งั้นโมเดลที่ดาวน์โหลดตอนเริ่มจะเขียนแคชไม่ได้ และ Qdrant โหมดไฟล์จะล็อกไฟล์ไม่ได้
RUN useradd -m -u 1000 user

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/user/.cache/huggingface \
    PORT=7860

WORKDIR /app

# ลงไลบรารีก่อนคัดลอกโค้ด ชั้นนี้จะได้ไม่ถูก build ใหม่ทุกครั้งที่แก้โค้ด
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกทั้งโฟลเดอร์ ของที่ไม่ต้องการกันไว้ใน .dockerignore แล้ว
COPY --chown=user:user . .

# PipelineLogger เขียนลง ./logs — ต้องมีโฟลเดอร์และเขียนได้
# Qdrant โหมดไฟล์เขียนไฟล์ล็อกลงในโฟลเดอร์ฐานข้อมูล จึงต้องเป็นของ user ด้วย
RUN mkdir -p /app/logs && chown -R user:user /app

USER user
EXPOSE 7860

# พอร์ต 7860 คือค่าที่ Spaces คาดไว้ ต้องตรงกับ app_port ใน README.md
# --host 0.0.0.0 จำเป็น ถ้าเป็น 127.0.0.1 ข้างนอกคอนเทนเนอร์จะเรียกไม่ถึง
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

# หมายเหตุสองข้อ
#
# 1. รอบแรกที่ Space เริ่มจะช้าราวหนึ่งถึงสองนาที เพราะต้องดาวน์โหลด Jina v3
#    กับ SigLIP จาก HF Hub ลงแคช ระหว่างนั้น /health ตอบ "loading"
#    และ /api/chat ตอบ 503 warming_up ซึ่งหน้าเว็บแสดงข้อความรอให้ผู้ใช้อยู่แล้ว
#
# 2. ห้ามใส่คำสั่งที่รัน build_database.py ลงในไฟล์นี้เด็ดขาด
#    มันลบแล้วสร้าง collection ใหม่ ถ้าโดน ./qdrant_db คือข้อมูล Movex หายทั้งก้อน
#    และระบบไฟล์ของ Space ฟรีไม่ถาวร กู้คืนไม่ได้
#    ฐานข้อมูลที่ build เสร็จแล้วให้ขึ้นไปพร้อมรีโปอย่างเดียว
