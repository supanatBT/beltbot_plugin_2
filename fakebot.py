"""ตัวแทน chatbot_v5 สำหรับทดสอบเส้นทางกู้บทสนทนา — ไม่โหลดโมเดลจริง"""
import itertools

_dialog_states: dict = {}
_ids = itertools.count(1)


class _Logger:
    def new_session(self): return f"sess{next(_ids)}"


logger = _Logger()


class _Cat:
    by_code = {"HC127 C": {}, "HC508 C": {}, "MD254 RR": {}}


modutech_cat = _Cat()
product_db = {"movex_chain_LF820_K325": {}}


def chat_interaction(text, image, history, last_pids, session_id, last_vit, last_graph):
    history = list(history or [])
    st = _dialog_states.get(session_id) or {}
    seen = st.get("modutech_codes") or []
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant",
                    "content": f"[เห็นประวัติ {len(history) - 1} ข้อความ · รุ่นในบริบท {seen}]"})
    _dialog_states[session_id] = {**st, "brand": "modutech",
                                  "modutech_codes": seen or ["HC127 C"],
                                  "modutech_slots": st.get("modutech_slots") or {}}
    return history, None, "**Decision:** answer", last_pids or [], session_id, None, None
