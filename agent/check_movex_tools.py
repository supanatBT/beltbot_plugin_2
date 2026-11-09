"""ตรวจเครื่องมือ Movex ส่วนที่ต้องโหลดโมเดล (ค้น Jina+Qdrant · ViT · กรองด้วย Qdrant) บนเครื่องจริง — ไม่เรียก Gemini

    python agent/check_movex_tools.py [รูปโซ่ Movex.jpg]

ผลที่ควรเห็น (เทียบกับบอทหลัก):
  movex_search "โซ่เลี้ยวได้"            → มี LF880/LF882 TAB ในผล
  movex_filter load สูงสุด              → บรรทัดแรกไม่มีคำว่า "fallback" ใน stderr (= ใช้ Qdrant เหมือนบอท)
  movex_match_image รูป LF820 K325      → vit_signal.series = 820 Series และ confidence ใกล้ค่าที่บอท log ไว้
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import movex_tools as M  # noqa: E402

print("movex_search:", M.movex_search("โซ่เลี้ยวได้")[:600])
print("movex_filter:", M.movex_filter("load", ">=", 0, "", "load", "desc")[:300])
print("movex_lookup 54901:", json.loads(M.movex_lookup("54901")).get("graph_context", "")[:300])
if len(sys.argv) > 1:
    os.makedirs(M.IMAGE_DIR, exist_ok=True)
    dst = os.path.join(M.IMAGE_DIR, "check_" + os.path.basename(sys.argv[1]))
    shutil.copy(sys.argv[1], dst)
    r = json.loads(M.movex_match_image(os.path.basename(dst)))
    print("movex_match_image vit_signal:", r.get("vit_signal"), "gap:", r.get("top1_top2_gap"))
    print("อันดับ:", [(x["rank"], x["product"].get("product_id"), x["final_score"]) for x in r.get("results", [])])
