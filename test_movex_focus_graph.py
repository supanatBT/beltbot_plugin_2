"""
test_movex_focus_graph.py — Movex: รุ่นที่ระบบตัดสินแล้ว (decision.payload.pids) ต้องเป็นตัวตั้งของกราฟ

conv_r3 CONV-17 (Gemini จริง · 25 ต.ค.):
    โซ่ Movex 880 มีขนาดไหนบ้าง → ตัวที่กว้างกว่า (LF 880 TAB K450) → "ใช้สเตอร์อะไร"
    บอท: "สำหรับโซ่ LF 880 TAB K450 ไม่มีข้อมูล compatible sprocket ในระบบครับ"
    แต่กราฟมี COMPATIBLE_WITH K450 → 54901 (Z10) · 55001 (Z12)
สาเหตุ: build_turn seed กราฟจากผลค้นข้อความ "ใช้สเตอร์อะไร" (ไม่มีชื่อรุ่น) ไม่ได้ใช้รุ่นที่ระบบรู้อยู่แล้ว

ไม่ใช้โมเดล: retriever / logger ปลอม · กราฟสร้างจาก extracted_data_v3_machine_ready.json (ตัวสร้างเดียวกับ build_graph)

    python test_movex_focus_graph.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import brands.movex.runtime as R  # noqa: E402
import knowledge_graph as K  # noqa: E402
from retriever_v4 import GraphResult, RetrievalResultV4, RetrievedProduct, ViTSignal  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


d = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
PDB = {p["product_id"]: p for p in d["products"]}
MDB = {m["material_code"]: m for m in d["Materials"]}
tmp = tempfile.mkdtemp(prefix="mkg_")
KG = K.KnowledgeGraph.build_and_save(PDB, MDB, {}, os.path.join(tmp, "kg.db"))
K450, K325 = "movex_chain_LF880_TAB_K450", "movex_chain_LF880_TAB_K325"
SPR = ["movex_sprocket_54901", "movex_sprocket_55001"]

print("1) กราฟจากรุ่นในโฟกัส")
R.bind(PDB, MDB, {}, KG, None)
g = R.focus_graph([K450], KG)
ok("K450 → compatible 54901 · 55001", g.compatible == SPR, g.compatible)
ctx_txt = g.to_llm_context()
ok("to_llm_context ไม่พัง และมีวัสดุ LF", "Low Friction Acetal" in ctx_txt and "54901" in ctx_txt, ctx_txt[:200])
ok("ไม่มีโฟกัส → None", R.focus_graph([], KG) is None)


class FakeRetriever:
    """คืนผลค้นที่ไม่เกี่ยวกับ K450 (เหมือนค้นคำว่า 'ใช้สเตอร์อะไร' แล้วได้สเตอร์ซีรีส์ 820)"""

    def __init__(self, seeds):
        self.seeds = seeds
        self._vit_signal = ViTSignal()
        self._score_map_snapshot, self._ranked_snapshot, self._graph_triggered_by = {}, [], "none"
        self._text_hits_raw, self._vit_hits_raw, self._siglip_hits_raw = [], [], []
        self._vit_series, self._vit_dominant, self._vit_top_score = None, False, 0.0
        self.inner = SimpleNamespace(_graph_result_to_context=lambda gr: None)

    def search(self, query, query_image=None, query_type="general"):
        gr = GraphResult(seed_products=list(self.seeds),
                         compatible=[c for s in self.seeds for c in KG.get_compatible_products(s)])
        return RetrievalResultV4(products=[RetrievedProduct("movex_sprocket_54201", 0.5)], graph_result=gr)


class FakeInner:
    cfg = SimpleNamespace(vit_confidence_threshold=0.5)

    def rank(self, rr):
        for p in rr.products:
            p.final_score = p.rrf_score
        return SimpleNamespace(products=rr.products)


class FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


R.bind(PDB, MDB, {}, KG, FakeInner())


def build(text, pids, seeds):
    rt = R.MovexRuntime.__new__(R.MovexRuntime)
    rt.key, rt.retriever, rt.logger, rt.tool_log, rt.tools = "movex", FakeRetriever(seeds), FakeLogger(), None, []
    dec = SimpleNamespace(effective_text=text, payload={"pids": pids, "series": "880", "level": "product"},
                          reason="ต่อจากเทิร์นก่อน", sales_topics=[], action="answer")
    turn = SimpleNamespace(user_text=text, image=None, log=None, followup=True, last_image=None, last_context=None,
                           effective_text=text, image_score=None)
    return rt.build_turn(dec, turn)


print("\n2) build_turn: ผลค้นไม่เกี่ยว แต่ระบบรู้ว่าลูกค้าหมายถึง K450")
lt = build("ใช้สเตอร์อะไร", [K450], ["movex_sprocket_54201"])
sysp = lt.system_prompt
ok("กราฟใน prompt seed จาก K450 (ไม่ใช่สเตอร์ 820)", f"[Seed Products]: {K450}" in sysp, sysp[sysp.find("[Seed"):][:120])
ok("prompt มี compatible 54901 · 55001", all(s in sysp for s in SPR))
ok("ข้อมูล K450 อยู่ใน context (เพิ่มเพราะผลค้นไม่มี)", '"product_id": "movex_chain_LF880_TAB_K450"' in sysp)
ok("ถามเรื่องสเตอร์ → แนบสเปกสเตอร์ (Z_Teeth · Bore_mm)", '"Z_Teeth": 10' in sysp and '"Z_Teeth": 12' in sysp
   and '"Bore_mm": 25.0' in sysp)
ok("debug บอกว่าใช้กราฟจากโฟกัส", any("Graph (focus)" in x for x in lt.debug), lt.debug[-3:])
ok("กฎใน prompt: ตอบสเตอร์พร้อมจำนวนฟันและรูเพลา (25 ต.ค.)", "Z_Teeth" in sysp and "ขนาดรูเพลา (Bore_mm)" in sysp)

print("\n3) ไม่เปลี่ยนเมื่อไม่จำเป็น")
lt = build("ใช้สเตอร์อะไร", [K450], [K450])
ok("ผลค้น seed ตรงกับโฟกัสอยู่แล้ว → ไม่แทนกราฟ", not any("Graph (focus)" in x for x in lt.debug))
lt = build("กว้างเท่าไหร่", [K450], ["movex_sprocket_54201"])
ok("ไม่ได้ถามเรื่องสเตอร์ → ไม่แนบสเปกสเตอร์", '"Z_Teeth": 10' not in lt.system_prompt)
lt = build("ใช้สเตอร์อะไร", [], ["movex_sprocket_54201"])
ok("ไม่มีโฟกัส → พฤติกรรมเดิม (กราฟจากผลค้น)", "[Seed Products]: movex_sprocket_54201" in lt.system_prompt)

print("\n4) ทาง Graph fallback เดิม (ผลค้นไม่มี seed) ไม่พังแล้ว")
lt = build("ใช้สเตอร์อะไร", [], [])
ok("fallback rank1 → to_llm_context ไม่พัง", "[Seed Products]: movex_sprocket_54201" in lt.system_prompt,
   [x for x in lt.debug if "Graph" in x])

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
