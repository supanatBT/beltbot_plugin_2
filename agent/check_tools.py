"""ตรวจเครื่องมือส่วนที่ต้องโหลดโมเดล (ค้นเวกเตอร์ · เทียบรูป) บนเครื่องจริง — ไม่เรียก Gemini

    python agent/check_tools.py [รูปสายพานสักใบ.jpg]
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import tools_impl as T  # noqa: E402

print("vector_search:", T.vector_search("สายพานสำหรับไลน์ตัดแต่งไก่")[:300])
if len(sys.argv) > 1:
    os.makedirs(T.IMAGE_DIR, exist_ok=True)
    dst = os.path.join(T.IMAGE_DIR, "check_" + os.path.basename(sys.argv[1]))
    shutil.copy(sys.argv[1], dst)
    r = json.loads(T.match_catalogue_image(os.path.basename(dst)))
    print("match_catalogue_image:", json.dumps(r, ensure_ascii=False)[:600])
    print("มีป้ายรุ่นในแกลเลอรี:", r.get("nearest_belts") is not None)
