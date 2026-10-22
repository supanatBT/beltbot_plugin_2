#!/usr/bin/env python3
"""ตรวจชั้นงานใช้/อุตสาหกรรมของกราฟ Modutech แบบครบทุกคู่ (23 ต.ค. 2026)

test_modutech_kg_apps.py ตรวจแบบสุ่มหยิบตัวอย่าง ซึ่งพลาดบั๊กใหญ่ไปหนึ่งตัว:
belts_for_application(งาน, อุตสาหกรรม) เคยกรองด้วย USED_IN กับ USED_FOR แยกกัน
จึงตอบ "EC254 R ใช้จับกล่องในโรงงานเนื้อสัตว์" ทั้งที่เล่มให้ EC254 R จับกล่องเฉพาะหมวดปลา
(ผิด 26 จาก 94 คู่ งาน×อุตสาหกรรม) ไฟล์นี้จึงไล่ตรวจทุกคู่แทนการสุ่ม

ค่าที่ถูกคำนวณใหม่จาก JSON ดิบในไฟล์นี้เอง ไม่เรียกโค้ดสร้างกราฟ
ถ้าสองฝั่งเขียนผิดเหมือนกันก็ยังหลุดได้ จึงมีหมวด 9 นับจำนวนเทียบกับตัวเลขที่ตรวจมือไว้

หมวด
  1. งาน×อุตสาหกรรม → สายพาน          ทุกคู่ (94)
  2. งาน → สายพาน                      ทุกงาน (73)
  3. สายพาน → งาน                      ทุกรุ่น (68)
  4. สายพาน → อุตสาหกรรม (USED_IN)     ทุกรุ่น (68)
  5. อุตสาหกรรม → สายพาน / งาน          ทุกอุตสาหกรรม (7)
  6. ชื่อไทยหาได้เท่าชื่ออังกฤษ          ทุกงาน + ทุกอุตสาหกรรม
  7. สองขั้น งาน → สายพาน → เฟือง       ทุกคู่ · รุ่นไม่มีเฟืองต้องได้ [] · ไม่มีขนาดเฟืองหลุด
  8. ตัวกรองเกรด                        ทุกรายการที่ถูกตัด ต้องไม่มีเกรดที่เล่มแนะนำจริง
  9. ตัวเลขรวม · ไม่มีปมลอย · ชื่อที่ไม่มีต้องคืนว่าง

รัน: python test_modutech_kg_apps_full.py [modutech_v30_3.json]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from brands.modutech.kg import APPLICATION, INDUSTRY, ModutechGraph

PATH = sys.argv[1] if len(sys.argv) > 1 else "modutech_v30_3.json"
with open(PATH, encoding="utf-8") as f:
    data = json.load(f)
g = ModutechGraph(data)

groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
fails: list[str] = []


def check(group: str, name: str, cond: bool, detail: str = "") -> None:
    groups[group][0 if cond else 1] += 1
    if not cond:
        fails.append(f"[{group}] {name}  — {detail}")


# ── คำนวณค่าที่ถูกจาก JSON ดิบ ───────────────────────────────
registry = {m["material_code"]: m for m in data.get("material_registry") or []}
links = {l["belt_code"]: sorted(l.get("sprocket_codes") or []) for l in data.get("belt_sprocket_links") or []}
vocab_th = {v["application"]: v.get("application_th") or "" for v in data.get("application_vocabulary") or []}


def grade_ok(rec: list, made: set) -> bool:
    """กฎเดียวกับ router: เกรดที่แนะนำมีในตารางสเปก หรือเป็นชนิดย่อยตาม base_polymer"""
    return any(m in made or any((registry.get(x) or {}).get("base_polymer") == m for x in made) for m in rec)


kept: set[tuple] = set()        # (รุ่น, อุตสาหกรรม, งาน) ผ่านตัวกรองเกรด
dropped: list[tuple] = []       # (รุ่น, อุตสาหกรรม, งาน, เกรดที่แนะนำ, เกรดที่รุ่นมี)
belt_ind: dict[str, set] = defaultdict(set)
ind_apps: dict[str, set] = defaultdict(set)
ind_th: dict[str, str] = {}
app_th: dict[str, str] = {}
for p in data["products"]:
    made = {v.get("belt_material") for v in (p.get("specifications") or {}).get("variants") or []}
    for i in p.get("industries") or []:
        ind = i["industry"]
        belt_ind[p["belt_code"]].add(ind)
        ind_th[ind] = i.get("industry_th") or ind_th.get(ind, "")
        for a in i.get("applications") or []:
            app = a["application"]
            ind_apps[ind].add(app)
            app_th[app] = a.get("application_th") or vocab_th.get(app, "")
            rec = a.get("materials") or []
            if grade_ok(rec, made):
                kept.add((p["belt_code"], ind, app))
            else:
                dropped.append((p["belt_code"], ind, app, rec, sorted(m for m in made if m)))

all_apps = sorted(vocab_th)
pairs = sorted({(i, a) for i, apps in ind_apps.items() for a in apps})

# ── 1. งาน×อุตสาหกรรม → สายพาน ────────────────────────────────
for ind, app in pairs:
    want = sorted({b for b, i, a in kept if i == ind and a == app})
    got = g.belts_for_application(app, ind)
    check("1 งาน×อุตสาหกรรม", f"{app} × {ind}", got == want,
          f"เกิน {sorted(set(got) - set(want))} ขาด {sorted(set(want) - set(got))}")
# คู่ที่ไม่มีในเล่มต้องได้ว่าง — ตัวที่เคยหลุด
for ind in ind_apps:
    for app in all_apps:
        if (ind, app) not in pairs:
            got = g.belts_for_application(app, ind)
            check("1 งาน×อุตสาหกรรม", f"{app} × {ind} (เล่มไม่มีคู่นี้)", got == [], str(got))

# ── 2. งาน → สายพาน ───────────────────────────────────────────
for app in all_apps:
    want = sorted({b for b, _, a in kept if a == app})
    check("2 งาน→สายพาน", app, g.belts_for_application(app) == want,
          f"ได้ {g.belts_for_application(app)} ต้อง {want}")

# ── 3. สายพาน → งาน · 4. สายพาน → อุตสาหกรรม ─────────────────
for p in data["products"]:
    b = p["belt_code"]
    want = sorted({a for bb, _, a in kept if bb == b})
    check("3 สายพาน→งาน", b, g.applications_for_belt(b) == want, f"ได้ {g.applications_for_belt(b)} ต้อง {want}")
    for ind in belt_ind[b]:
        w2 = sorted({a for bb, i, a in kept if bb == b and i == ind})
        check("3 สายพาน→งาน", f"{b} ใน {ind}", g.applications_for_belt(b, ind) == w2,
              f"ได้ {g.applications_for_belt(b, ind)} ต้อง {w2}")
    check("4 สายพาน→อุตสาหกรรม", b, g.industries_for_belt(b) == sorted(belt_ind[b]),
          f"ได้ {g.industries_for_belt(b)} ต้อง {sorted(belt_ind[b])}")

# ── 5. อุตสาหกรรม → สายพาน / งาน ─────────────────────────────
for ind in sorted(ind_apps):
    want_b = sorted(b for b, inds in belt_ind.items() if ind in inds)
    check("5 อุตสาหกรรม", f"{ind} → สายพาน", g.belts_in_industry(ind) == want_b,
          f"ได้ {len(g.belts_in_industry(ind))} ต้อง {len(want_b)}")
    check("5 อุตสาหกรรม", f"{ind} → งาน", g.applications_in_industry(ind) == sorted(ind_apps[ind]),
          f"ได้ {g.applications_in_industry(ind)} ต้อง {sorted(ind_apps[ind])}")

# ── 6. ชื่อไทย ────────────────────────────────────────────────
for app in all_apps:
    th = app_th.get(app) or vocab_th.get(app)
    check("6 ชื่อไทย", f"{app} = {th}", bool(th) and g.belts_for_application(th) == g.belts_for_application(app),
          f"ไทย {th!r}")
for ind in sorted(ind_apps):
    th = ind_th.get(ind)
    check("6 ชื่อไทย", f"{ind} = {th}", bool(th) and g.belts_in_industry(th) == g.belts_in_industry(ind)
          and g.applications_in_industry(th) == g.applications_in_industry(ind), f"ไทย {th!r}")

# ── 7. สองขั้น ────────────────────────────────────────────────
dims = set()
for s in data.get("sprockets") or []:
    for v in (s.get("dimensions") or {}).values():
        mm = (v or {}).get("mm") if isinstance(v, dict) else None
        if isinstance(mm, (int, float)):
            dims.add(mm)
empty_seen = 0
for ind, app in pairs:
    res = g.sprockets_for_application(app, ind)
    want = {b: links.get(b, []) for b in sorted({b for b, i, a in kept if i == ind and a == app})}
    check("7 สองขั้น", f"{app} × {ind}", {k: sorted(v) for k, v in res.items()} == want, "รหัสเฟืองไม่ตรง belt_sprocket_links")
    empty_seen += sum(1 for v in res.values() if not v)
    flat = json.dumps(res, ensure_ascii=False)
    check("7 สองขั้น", f"{app} × {ind} ไม่มีตัวเลขขนาด", not any(isinstance(x, (int, float)) for v in res.values() for x in v),
          flat[:120])
check("7 สองขั้น", "มีกรณีรุ่นไม่มีเฟืองให้ตรวจจริง (คืน [] ไม่เดา)", empty_seen > 0, str(empty_seen))

# ── 8. ตัวกรองเกรด ────────────────────────────────────────────
for b, ind, app, rec, made in dropped:
    in_graph = b in g.belts_for_application(app, ind)
    check("8 ตัวกรองเกรด", f"{b} × {app} × {ind} (แนะนำ {rec} รุ่นมี {made})", not in_graph, "หลุดเข้ากราฟ")

# ── 9. ตัวเลขรวม ──────────────────────────────────────────────
st = g.stats()
check("9 ตัวเลขรวม", "Industry 7", st["nodes"].get(INDUSTRY) == 7, str(st["nodes"]))
check("9 ตัวเลขรวม", "Application 73", st["nodes"].get(APPLICATION) == 73, str(st["nodes"]))
check("9 ตัวเลขรวม", "USED_IN 211", st["edges"].get("USED_IN") == 211, str(st["edges"]))
check("9 ตัวเลขรวม", "USED_FOR 564", st["edges"].get("USED_FOR") == 564, str(st["edges"]))
check("9 ตัวเลขรวม", "HAS_APPLICATION 94", st["edges"].get("HAS_APPLICATION") == len(pairs) == 94, str(len(pairs)))
check("9 ตัวเลขรวม", "ทุกรุ่นมีงานใช้อย่างน้อยหนึ่งงาน",
      all(g.applications_for_belt(p["belt_code"]) for p in data["products"]))
check("9 ตัวเลขรวม", "ทุกงานมีสายพานอย่างน้อยหนึ่งรุ่น", all(g.belts_for_application(a) for a in all_apps))
for bad in ("งานที่ไม่มีจริง", "Nonexistent Industry", ""):
    check("9 ตัวเลขรวม", f"ชื่อที่ไม่มี {bad!r} → ว่าง",
          g.belts_for_application(bad) == [] and g.belts_in_industry(bad) == []
          and g.applications_in_industry(bad) == [])

# ── รายงาน ────────────────────────────────────────────────────
total_ok = total_bad = 0
for k in sorted(groups):
    okc, bad = groups[k]
    total_ok += okc
    total_bad += bad
    print(f"  {'✓' if not bad else '✗'} {k:<22} {okc}/{okc + bad}")
print(f"\n  รายการที่ตัวกรองเกรดตัดออก {len(dropped)} รายการ (รุ่น×อุตสาหกรรม×งาน) · คงไว้ {len(kept)}")
if fails:
    print("\nที่ไม่ผ่าน (แสดง 15 รายการแรก):")
    for f_ in fails[:15]:
        print("  " + f_)
print(f"\nรวม {total_ok}/{total_ok + total_bad}")
sys.exit(1 if total_bad else 0)
