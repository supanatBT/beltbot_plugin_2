"""
brands/modutech/runtime.py
==========================
ส่วนที่ต้องใช้โมเดลของ Modutech — ค้นเวกเตอร์ใน collection แยก · tool ค้นทั้งฐาน · ประกอบหนึ่งเทิร์น
ย้ายมาจาก chatbot_v5.py (_modutech_vector_search · _modutech_reply · tracked_search_catalogue) ชั้น 5
"""
from __future__ import annotations

from brands.modutech.turn import build_modutech_turn, make_search_tool
from core.llm import extract_text
from core.protocol import LLMTurn, TurnOutput

EMPTY_REPLY_TH = "ขออภัยครับ ระบบไม่สามารถสร้างคำตอบได้ในขณะนี้ กรุณาลองถามใหม่อีกครั้ง"


class _NullKG:
    """คืน context ว่างให้ RetrieverV4._graph_traverse

    ไม่ได้ใช้แล้วตั้งแต่ Modutech ต่อ ModutechGraph จริง (30 ก.ย.) เก็บไว้เป็นทางถอย
    ถ้าวันไหนกราฟ raise แล้วต้องการให้ระบบขึ้นมาก่อน ให้สลับ kg=modutech_kg เป็น kg=_NullKG()
    แต่รู้ไว้ว่าคำถามรหัสสเตอร์เดี่ยว ๆ จะตอบไม่ได้
    """
    def expand_products(self, **_):
        class _Ctx:
            compatible_products, same_series, material_details, process_details = [], [], {}, {}
        return _Ctx()


class ModutechRuntime:
    def __init__(self, cat, search, kg, retriever, tool_log):
        self.cat, self.search, self.kg, self.retriever = cat, search, kg, retriever
        self.tool = make_search_tool(search, tracked=tool_log.track)

    def vector_search(self, query: str) -> list[str]:
        """คืน belt_code_id จาก collection modutech_belt_chunks (ถ้าเปิดใช้)"""
        if self.retriever is None:
            return []
        r = self.retriever.search(query=query, query_image=None, query_type="general")
        ranked = self.retriever.rank(r)
        return [p.product_id for p in ranked.products]

    def build_turn(self, decision, turn) -> LLMTurn:
        t = build_modutech_turn(decision, self.cat, self.search,
                                vector_search=self.vector_search, kg=self.kg)
        refs = "**Modutech:** " + " · ".join(t.debug[:12]) + "\n\n"
        return LLMTurn(t.system_prompt, [t.user_prompt], tools=[self.tool], debug=[refs])

    def finish_turn(self, decision, turn, llm_turn, result) -> TurnOutput:
        text = extract_text(result.response)
        # เส้น Modutech ไม่เปลี่ยนของฝากข้ามเทิร์น (ของเดิมคืน last_pids/vit/graph ตัวเดิม)
        return TurnOutput((text.strip() or EMPTY_REPLY_TH))
