"""probe_model.py — ถาม Google ว่าชื่อโมเดลแต่ละชื่อตอนนี้ตอบด้วยรุ่นไหนจริง (22 ต.ค. 2026)

ทำไมต้องมี: บอตใช้ gemini-flash-latest มาตลอด ซึ่งเป็นชื่อลอยที่ Google ย้ายไปรุ่นใหม่ได้เอง
ผลทดสอบคนละวันจึงอาจมาจากคนละโมเดล และไฟล์ผลทดสอบเดิมไม่ได้บันทึกชื่อรุ่นไว้

รัน (ใช้ GEMINI_API_KEY จาก .env หรือ environment)
    python probe_model.py
    python probe_model.py gemini-flash-latest gemini-3.6-flash gemini-3.8-flash

แต่ละชื่อส่งคำถามสั้นหนึ่งครั้งด้วย thinking ระดับ low (ตรงกับที่บอตใช้)
แล้วพิมพ์ model_version ที่ API ตอบกลับ · เวลา · token คิด
ไม่แตะไฟล์อื่น ไม่เขียนอะไรลงดิสก์
"""
import os
import sys
import time

DEFAULT_NAMES = ["gemini-flash-latest", "gemini-3.6-flash", "gemini-3.8-flash"]


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main(names):
    load_env()
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("ไม่พบ GEMINI_API_KEY ใน .env หรือ environment")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    level = (os.getenv("GEMINI_THINKING") or "low").strip() or "low"
    cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=level))
    print(f"thinking_level={level}\n")
    print(f"{'ชื่อที่ส่ง':<24} {'รุ่นที่ตอบจริง (model_version)':<34} {'วินาที':>7} {'thinking':>9}")
    for name in names:
        t0 = time.perf_counter()
        try:
            r = client.models.generate_content(model=name, contents="ตอบคำว่า OK คำเดียว", config=cfg)
            dt = time.perf_counter() - t0
            u = getattr(r, "usage_metadata", None)
            th = getattr(u, "thoughts_token_count", None) if u else None
            print(f"{name:<24} {str(getattr(r, 'model_version', None)):<34} {dt:>7.2f} {str(th):>9}")
        except Exception as e:                     # noqa: BLE001 — รายงานต่อชื่อ ไม่หยุดทั้งสคริปต์
            print(f"{name:<24} ERROR {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_NAMES)
