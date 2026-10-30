"""
test_modutech_search_parse.py — ตัวตรวจคำถามสำรวจของ Modutech (brands/modutech/router.py) + เลขตอบแบรนด์ (core/decide.py)

ที่มา: probe_tools r1/r2 (30 ต.ค. · results/probe_tools/FINDING.md)
    C1  "ไม่ต่ำกว่า 50%" ถูกค้นเป็น ≤ 50 → บอทตอบว่าพื้นที่เปิดสูงสุด 50% (จริง 58%)
    B4  ตอบ "2" เลือกแบรนด์ → เลข 2 กลายเป็นแรงดึง ≥ 2 N/m (68/68)
    C2  "POM สลักสแตนเลส" ไม่กรองวัสดุสายพาน
    B1/B2/D1  คำถามสูงสุด/ต่ำสุด/กี่รุ่น ไม่มีตัวเลข → วนถามงานกับพิทช์

ไม่ต้องมีโมเดล · ไม่เรียก LLM

    python test_modutech_search_parse.py
"""
from __future__ import annotations

import dialogue_state as D
from brands.modutech.router import CatalogueSearch, comparison_op, thai_number
from modutech_gates import Catalogue

CAT = Catalogue("modutech_v30_3.json")
S = CatalogueSearch(CAT)
ok = total = 0


def check(name: str, cond: bool, detail="") -> None:
    global ok, total
    total += 1
    ok += bool(cond)
    print(("✅" if cond else "❌"), name, "" if cond else f"  → {detail}")


def top(text: str, n: int = 10) -> list:
    q = S.parse(text)
    return [] if q is None else [m["belt_code"] for m in S.search(q)["matches"]][:n]


# ── ทิศของคำเปรียบเทียบ ──
for text, want in [("ไม่ต่ำกว่า 50", ">="), ("ไม่น้อยกว่า 50", ">="), ("อย่างน้อย 50", ">="), ("ขึ้นไป", ">="),
                   ("ไม่เกิน 50", "<="), ("ไม่มากกว่า 50", "<="), ("ไม่สูงกว่า 50", "<="), ("ต่ำกว่า 50", "<="),
                   ("น้อยกว่า 50", "<="), ("มากกว่า 50", ">="), ("เกิน 50", ">=")]:
    check(f"comparison_op {text!r}", comparison_op(text) == want, comparison_op(text))

# ── เลขคำ ──
for text, want in [("ห้าหมื่น", 50000), ("สองหมื่นห้าพัน", 25000), ("5 หมื่น", 50000), ("หนึ่งแสน", 100000),
                   ("สามารถรับแรง", None), ("สายพาน", None)]:
    check(f"thai_number {text!r}", thai_number(text) == want, thai_number(text))

# ── C1: ไม่ต่ำกว่า ──
q = S.parse("สายพานพื้นที่เปิดไม่ต่ำกว่า 50% มีรุ่นไหน")
check("C1 op >=", q is not None and q.op == ">=" and q.value == 50, q and q.as_dict())
check("C1 ได้ EC508 R/TR (58%)", {"EC508 R", "EC508 TR"} <= set(top("สายพานพื้นที่เปิดไม่ต่ำกว่า 50% มีรุ่นไหน")))
q = S.parse("พื้นที่เปิดร้อยละ 50 ขึ้นไป มีรุ่นไหน")
check("ร้อยละ 50 = 50 ไม่ใช่ 100", q is not None and q.value == 50, q and q.as_dict())

# ── เลขคำ / B4 ──
check("B4 เกินห้าหมื่นนิวตัน = 3 รุ่น",
      top("ขอสายพานที่ทนแรงได้เกินห้าหมื่นนิวตันต่อเมตร") == ["HD635 C", "MD508 C", "MD508 NS"],
      top("ขอสายพานที่ทนแรงได้เกินห้าหมื่นนิวตันต่อเมตร"))
check("ตัวเลขอารบิกเหมือนเดิม", top("สายพานที่รับแรงดึงอย่างน้อย 50,000 N/m มีรุ่นไหนบ้าง") ==
      ["HD635 C", "MD508 C", "MD508 NS"])

# ── สูงสุด / ต่ำสุด ──
check("แรงดึงสูงสุด อันดับ 1 HD635 C", top("สายพานรุ่นไหนรับแรงดึงสูงสุด")[:1] == ["HD635 C"])
check("แข็งแรงที่สุด อันดับ 1 HD635 C", top("รุ่นไหนแข็งแรงที่สุด")[:1] == ["HD635 C"])
check("เบาที่สุด อันดับ 1 MD127 GAP50%", top("สายพานที่เบาที่สุดคือรุ่นไหน")[:1] == ["MD127 GAP50%"])
check("กันลื่นแข็งแรงสุด อันดับ 1 MD508 NS (รวม Grip Top)",
      top("สายพานกันลื่นที่แข็งแรงที่สุด")[:2] == ["MD508 NS", "XP254 EVO CR"], top("สายพานกันลื่นที่แข็งแรงที่สุด"))
check("ช่องเปิดมากสุด อันดับ 1 EC508 R/TR", set(top("ช่องเปิดมากที่สุดรุ่นไหน")[:2]) == {"EC508 R", "EC508 TR"})
check("จัดอันดับตัดเหลือ 5", len(top("สายพานรุ่นไหนรับแรงดึงสูงสุด")) == 5)
check("งานหนัก ไม่ใช่น้ำหนักสูงสุด", S.parse("งานหนัก ลำเลียงเนื้อ มีรุ่นไหน") is None)

# ── ภาพรวม ──
q = S.parse("Modutech มีสายพานทั้งหมดกี่รุ่น")
r = S.search(q) if q else {}
check("กี่รุ่น → overview 68", q is not None and r.get("overview", {}).get("total_belts") == 68, r)

# ── วัสดุสายพาน ──
check("POM สลักสแตนเลส = HD635 C (POM-NL) เท่านั้น", top("สายพาน POM สลักสแตนเลส มีรุ่นไหนบ้าง") == ["HD635 C"],
      top("สายพาน POM สลักสแตนเลส มีรุ่นไหนบ้าง"))
check("รหัสสเตอร์ *PA ไม่ใช่วัสดุสายพาน", S.parse("EC127SQZ19*PA ใช้กับสายพานรุ่นไหน") is None)
check("พิน PA ไม่ใช่วัสดุสายพาน",
      (S.parse("สายพานพิน PA มีรุ่นไหน") is None) or S.parse("สายพานพิน PA มีรุ่นไหน").belt_material is None)

# ── เส้นทาง (DialogueManager) ──
dm = D.DialogueManager({}, CAT)


def play(turns):
    st, out = None, []
    for t in turns:
        d = dm.decide(t, has_image=False, vit=None, image_rejected=False, state=st)
        st = d.state
        out.append(d)
    return out


d = play(["ขอสายพานที่ทนแรงได้เกินห้าหมื่นนิวตันต่อเมตร", "2"])[-1]
sq = (d.modutech or {}).get("search_query") or {}
check("B4 ตอบ 2 → ค้น ≥ 50000 (ไม่ใช่ ≥ 2)", d.action == "search" and sq.get("value") == 50000, sq)
check("B4 effective ไม่มีเลขเมนู", not d.effective_text.rstrip().endswith(" 2"), d.effective_text)
d = play(["สายพานรุ่นไหนรับแรงดึงสูงสุด", "2"])[-1]
check("B1 ตอบ 2 → จัดอันดับแรงดึง", d.action == "search" and ((d.modutech or {}).get("search_query") or {}).get("rank") == "max")
d = play(["Modutech มีสายพานทั้งหมดกี่รุ่น"])[-1]
check("D1 กี่รุ่น → search overview (ไม่ถามงาน)", d.action == "search")
d = play(["แนะนำสายพาน Modutech POM สำหรับไก่"])[-1]
check("วัสดุ + งาน → ไม่ค้นทั้งฐาน", d.action != "search", d.reason)
d = play(["สายพานทนร้อน 90 องศาขึ้นไปมีรุ่นไหน", "2"])[-1]
check("อุณหภูมิยังต้องถามเปียก/แห้ง", d.action == "ask" and "เปียก" in d.reason, d.reason)
d = play(["MP80 C กับ LF820 K325", "modutech"])[-1]
check("ตอบชื่อแบรนด์ (ไม่ใช่เลข) เหมือนเดิม", "modutech" in d.effective_text, d.effective_text)

print(f"\nรวม {ok}/{total}")
raise SystemExit(0 if ok == total else 1)
