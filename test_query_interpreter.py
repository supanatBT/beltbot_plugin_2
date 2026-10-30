"""
test_query_interpreter.py — core/query_interpreter.py + จุดเรียกใน brands/modutech/plugin.py และ brands/movex/plugin.py

ใช้ LLM ปลอม (คืน JSON ตามคำถาม) — ไม่ต้องมีโมเดล ไม่เรียก Gemini
    1) parse_query: รูปแบบถูก · ช่อง/ค่านอกรายการ · ค่าหลุดช่วง · op ผิด → ไม่เชื่อ
    2) Modutech: จุดเดา (ถามงาน · ค้นเวกเตอร์) → ค้นทั้งฐาน · อุณหภูมิ/ความกว้าง/ผลเสีย → ทางเดิม · มีรหัส/งานใช้ = ไม่เรียก
    3) Movex: จุด "ขอทราบรุ่นก่อน" → ค้นทั้งฐาน (brands/movex/search.py) · ผลเสีย → ถามรุ่นแบบเดิม
    4) ปิดตัวตีความ (None) = เส้นทางเดิมทุกข้อ

    python test_query_interpreter.py
"""
from __future__ import annotations

import json

import dialogue_state as D
from brands.modutech.router import ExploratoryQuery
from brands.movex.search import MovexSearch
from core.query_interpreter import QueryField, QueryInterpreter, QuerySpec, parse_query
from modutech_gates import Catalogue

ok = total = 0


def check(name: str, cond: bool, detail="") -> None:
    global ok, total
    total += 1
    ok += bool(cond)
    print(("✅" if cond else "❌"), name, "" if cond else f"  → {detail}")


# ── 1) parse_query ──
SPEC = QuerySpec("ทดสอบ", {"strength": QueryField("แรงดึง", 100, 200_000),
                          "pitch": QueryField("พิทช์", 5, 80, allow_eq=True)},
                 enums={"surface": ["Flat Top", "Non Slip"]})
J = lambda **d: json.dumps(d)
r = parse_query(J(intent="search", field="strength", op=">=", value=50000), SPEC)
check("ค่าปกติ", r is not None and r.is_search() and r.value == 50000)
check("ชื่อช่องไม่มีในรายการ → None", parse_query(J(intent="search", field="temp", op=">=", value=90), SPEC) is None)
check("ค่าหลุดช่วง → None", parse_query(J(intent="search", field="strength", op=">=", value=5), SPEC) is None)
check("op ผิด → None", parse_query(J(intent="search", field="strength", op=">>", value=50000), SPEC) is None)
check("'==' กับช่องที่ไม่อนุญาต → None", parse_query(J(intent="search", field="strength", op="==", value=50000), SPEC) is None)
check("'==' กับพิทช์ได้", (parse_query(J(intent="search", field="pitch", op="==", value=25.4), SPEC) or 0) and True)
check("ผิวปลอม → None", parse_query(J(intent="search", filters={"surface": "Super Grip"}), SPEC) is None)
r = parse_query(J(intent="search", filters={"surface": "non slip"}), SPEC)
check("ผิวไม่สนตัวพิมพ์ → ค่าตามฐาน", r is not None and r.filters == {"surface": "Non Slip"} and r.is_search())
r = parse_query(J(intent="search", field="strength", rank="max", value=None), SPEC)
check("rank ไม่ใช้ค่า", r is not None and r.rank == "max" and r.value is None and r.is_search())
r = parse_query(J(intent="search", field="strength"), SPEC)
check("มีช่องแต่ไม่มีเกณฑ์ = ไม่ใช่การค้น", r is not None and not r.is_search())
check("intent แปลก → None", parse_query(J(intent="buy"), SPEC) is None)
check("ไม่ใช่ JSON → None", parse_query("ไม่รู้ครับ", SPEC) is None)


# ── LLM ปลอม ──
class Fake:
    def __init__(self, table: dict):
        self.table, self.seen = table, []

    def __call__(self, system, user, json_mode=False, temperature=None):
        q = user.split("คำถามของลูกค้า:", 1)[-1].strip()
        self.seen.append(q)
        for k, v in self.table.items():
            if k in q:
                if v == "ERROR":
                    raise RuntimeError("503")
                return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        return json.dumps({"intent": "other"})


CAT = Catalogue("modutech_v30_3.json")
data = json.load(open("extracted_data_v3_machine_ready.json", encoding="utf-8"))
real = {p["product_id"]: p for p in data["products"] if "product_id" in p}
mats = {m["material_code"]: m for m in data.get("Materials", [])}


def pl(d) -> dict:
    """payload ของแบรนด์ — shim dialogue_state แยกเป็น d.movex / d.modutech"""
    return (d.movex if d.brand == "movex" else d.modutech) or {}


def play(dm, turns):
    st, out = None, None
    for t in turns:
        out = dm.decide(t, has_image=False, vit=None, image_rejected=False, state=st)
        st = out.state
    return out


# ── 4) ปิด = เดิม ──
dm_off = D.DialogueManager(real, CAT, movex_materials=mats)
check("ปิด: Modutech รูเยอะ → ทางเดิม (ค้นตามการใช้งาน)",
      play(dm_off, ["อยากได้สายพาน Modutech รูเยอะ ๆ ระบายน้ำดี ๆ"]).action == "answer")
check("ปิด: Movex รับโหลดสูงสุด → ถามรุ่น", play(dm_off, ["Movex รุ่นไหนรับโหลดสูงสุด"]).reason == "ยังไม่รู้รุ่น")

# ── 2) Modutech ──
fake = Fake({
    "รูเยอะ": {"intent": "search", "field": "open_area", "rank": "max"},
    "แข็งแรงพิเศษ": {"intent": "search", "field": "strength", "op": ">=", "value": 50000},
    "ทนร้อน": {"intent": "search", "field": "strength", "rank": "max", "mentions_temperature": True},
    "ผิวพิเศษ": {"intent": "search", "filters": {"surface": "Super Grip"}},
    "ระบบล่ม": "ERROR",
    "ไลน์ไก่": {"intent": "need_help"},
})
dm = D.DialogueManager(real, CAT, movex_materials=mats)
dm.modutech_plugin._query_interpreter = QueryInterpreter(fake)
d = play(dm, ["อยากได้สายพาน Modutech รูเยอะ ๆ ระบายน้ำดี ๆ"])
sq = (d.modutech or {}).get("search_query") or {}
check("Modutech รูเยอะ → ค้นทั้งฐาน open_area max", d.action == "search" and sq.get("field") == "open_area"
      and sq.get("rank") == "max", f"{d.action} {sq}")
top = [m["belt_code"] for m in dm.search.search(ExploratoryQuery(**sq))["matches"]][:2] if sq else []
check("…อันดับ 1–2 = EC508 R/TR (58%)", set(top) == {"EC508 R", "EC508 TR"}, top)
d = play(dm, ["สายพาน Modutech แบบแข็งแรงพิเศษ มีไหม"])
check("Modutech แข็งแรงพิเศษ (กฎ regex จับไม่ได้) → ค้น ≥ 50000",
      d.action == "search" and ((d.modutech or {}).get("search_query") or {}).get("value") == 50000, d.reason)
d = play(dm, ["สายพาน Modutech ทนร้อนแบบสุด ๆ"])
check("อุณหภูมิ → ไม่ค้น (ทางเดิม)", d.action != "search", d.reason)
d = play(dm, ["สายพาน Modutech ผิวพิเศษ มีไหม"])
check("ผิวปลอม → ไม่ค้น (ทางเดิม)", d.action != "search", d.reason)
d = play(dm, ["สายพาน Modutech ระบบล่ม ทดสอบ"])
check("LLM ล่ม → ทางเดิม", d.action != "search", d.reason)
n = len(fake.seen)
play(dm, ["HC508 C แข็งแรงพิเศษไหม"])
check("มีรหัส → ไม่เรียกตัวตีความ", len(fake.seen) == n, fake.seen[n:])
n = len(fake.seen)
play(dm, ["สายพาน Modutech สำหรับการลำเลียงชิ้นไก่"])
check("จับงานใช้ได้ → ไม่เรียกตัวตีความ", len(fake.seen) == n, fake.seen[n:])
d = play(dm, ["สายพานรุ่นไหนรับแรงดึงสูงสุด", "2"])
check("กฎ regex จับได้ → ไม่ต้องเรียก (ค้นด้วยกฎเดิม)", d.action == "search" and "ตีความ" not in d.reason, d.reason)

# ── 3) Movex ──
fake_mx = Fake({
    "รับโหลดสูงสุด": {"intent": "search", "field": "load", "rank": "max"},
    "กว้างไม่เกิน 100": {"intent": "search", "field": "width", "op": "<=", "value": 100},
    "กี่รุ่น": {"intent": "overview"},
    "เลี้ยวได้และกว้างที่สุด": {"intent": "search", "field": "width", "rank": "max",
                                 "filters": {"product_type": "Sideflexing Chain"}},
    "ซีรีส์ปลอม": {"intent": "search", "filters": {"series": "999 Series"}},
})
dm.movex_plugin._query_interpreter = QueryInterpreter(fake_mx)
d = play(dm, ["Movex รุ่นไหนรับโหลดสูงสุด"])
sp = pl(d).get("search_pids") or []
check("Movex รับโหลดสูงสุด → ค้นทั้งฐาน", d.action == "answer" and "ตีความ" in d.reason, d.reason)
check("…อันดับแรก LF 882 TAB ×3 (3830 N)", sp[:3] and all("LF882" in p for p in sp[:3]), sp)
sr = pl(d).get("search_result") or {}
d = play(dm, ["โซ่ Movex ที่กว้างไม่เกิน 100 มม. มีรุ่นไหน"])
sp = pl(d).get("search_pids") or []
check("Movex กว้างไม่เกิน 100 → 3 รุ่น", sorted(sp) == sorted(["movex_chain_LF820_K325", "movex_chain_LF880_TAB_K325",
                                                                 "movex_chain_LFN_83_MFM"]), sp)
d = play(dm, ["Movex มีสินค้ากี่รุ่น"])
ov = (pl(d).get("search_result") or {}).get("overview") or {}
check("Movex กี่รุ่น → 23 (โซ่ 15 · สเตอร์ 8)", ov.get("total") == 23, ov)
d = play(dm, ["โซ่ Movex ที่เลี้ยวได้และกว้างที่สุด"])
sp = pl(d).get("search_pids") or []
check("Movex เลี้ยวได้ + กว้างสุด → LF 882 TAB K1200 (304.8)", sp[:1] == ["movex_chain_LF882_TAB_K1200"], sp)
d = play(dm, ["โซ่ Movex ซีรีส์ปลอม มีไหม"])
check("ซีรีส์ปลอม → ถามรุ่นแบบเดิม", d.reason == "ยังไม่รู้รุ่น", d.reason)

# ── ค้น Movex ตรง ๆ ──
ms = MovexSearch(real)
r = ms.search(field="weight", rank="min")
check("Movex เบาสุด = LF 820 K325 (0.89)", r["matches"][0]["product_id"] == "movex_chain_LF820_K325")
r = ms.search(field="radius", rank="min")
check("รัศมี: บอกว่ามีกี่รายการไม่มีค่า", "ไม่มีค่าช่องนี้" in r["note_th"], r["note_th"])

print(f"\nรวม {ok}/{total}")
raise SystemExit(0 if ok == total else 1)
