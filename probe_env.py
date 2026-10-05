"""probe_env.py — ดูว่าอินเทอร์พรีเตอร์ตัวที่รันไฟล์นี้มีของที่ chatbot_v5 ต้องใช้ครบไหม

รันหนึ่งตัวต่อหนึ่งครั้ง
    & "E:\\Project2\\saleschatbot\\venv\\Scripts\\python.exe" probe_env.py

อ่านเวอร์ชันด้วย importlib.metadata ไม่ใช่ __version__
เพราะบางแพ็กเกจ (qdrant_client เป็นต้น) ไม่มีแอตทริบิวต์ __version__
ถ้าเช็กด้วย __version__ ใน try/except กว้าง ๆ จะได้ผลว่า "ไม่ได้ติดตั้ง" ทั้งที่ติดตั้งแล้ว
— เป็นบั๊กที่เคยทำให้ check_app.py รายงานผิดมาแล้วครั้งหนึ่ง

แยกสองคำถามให้ชัด
    installed  มีแพ็กเกจอยู่ใน site-packages ของอินเทอร์พรีเตอร์นี้ไหม
    imports    import ได้จริงไหม (บางตัวมีแต่พัง เช่น torch ที่ DLL ไม่ครบ)
"""
import importlib
import importlib.metadata as md
import sys

# (ชื่อที่ pip รู้จัก, ชื่อที่ใช้ import)
NEEDED = [
    ("transformers", "transformers"),
    ("torch", "torch"),
    ("qdrant-client", "qdrant_client"),
    ("google-generativeai", "google.generativeai"),
    ("sentence-transformers", "sentence_transformers"),
    ("einops", "einops"),
    ("pillow", "PIL"),
    ("numpy", "numpy"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("python-multipart", "multipart"),
    ("python-dotenv", "dotenv"),
]


def version(dist):
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return ""
    except Exception as e:                       # noqa: BLE001
        return f"? {type(e).__name__}"


def importable(name):
    try:
        importlib.import_module(name)
        return "ok", ""
    except ImportError:
        return "ไม่ได้", "import ไม่เจอ"
    except Exception as e:                       # noqa: BLE001
        return "พัง", f"{type(e).__name__}: {str(e)[:60]}"


print(f"python      {sys.version.split()[0]}")
print(f"executable  {sys.executable}")
print()
print(f"{'แพ็กเกจ':<24}{'เวอร์ชัน':<14}{'import':<8}หมายเหตุ")
print("─" * 78)

missing = []
for dist, mod in NEEDED:
    ver = version(dist)
    if not ver:
        missing.append(dist)
        print(f"{dist:<24}{'—':<14}{'-':<8}ไม่ได้ติดตั้ง")
        continue
    state, note = importable(mod)
    print(f"{dist:<24}{ver:<14}{state:<8}{note}")

print("─" * 78)

tv = version("transformers")
if not tv:
    print("transformers ไม่มี — อินเทอร์พรีเตอร์นี้รัน chatbot_v5 ไม่ได้")
else:
    try:
        major, minor = (int(x) for x in tv.split(".")[:2])
        if (major, minor) >= (4, 57):
            print(f"transformers {tv} — สูงเกิน Jina v3 จะพังที่ hasattr(torch, torch_dtype)")
            print("  ต้องต่ำกว่า 4.57 ในอินเทอร์พรีเตอร์ที่ใช้รันแอป")
        else:
            print(f"transformers {tv} — อยู่ในช่วงที่ Jina v3 ใช้ได้")
    except ValueError:
        print(f"transformers {tv} — อ่านเวอร์ชันเป็นตัวเลขไม่ได้ ต้องดูด้วยตา")

if missing:
    print(f"\nขาด {len(missing)} ตัว: {', '.join(missing)}")
else:
    print("\nมีครบทุกตัวที่ต้องใช้")
