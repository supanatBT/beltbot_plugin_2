"""เทียบผลค้นทั้งฐาน: กรองด้วยโค้ด (CatalogueSearch) กับกรองด้วย Qdrant (QdrantCatalogueSearch) — ต้องเหมือนกันทุกตัวอักษร

ไม่เรียก LLM · ชุดคำถาม = กริดเงื่อนไขจากค่าจริงในฐาน (รวมค่าขอบ ±0.05 ของ "==") + ทุก user_text ในไฟล์ทดสอบที่ parse ได้
ใช้: python test_variant_index_parity.py [--dump out.json]   (--dump = เก็บผลเพื่อเทียบข้ามเวอร์ชัน)
"""
import os as _os, sys as _sys  # รากของ repo: import แพ็กเกจได้ และพาธข้อมูลนับจากราก
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)
import csv, glob, itertools, json, sys

from engine.brands.modutech.router import CatalogueSearch, ExploratoryQuery
from engine.brands.modutech.gates import Catalogue

DB = "data/modutech_v30_3.json"


def grid(cat):
    """เงื่อนไขทุกแบบที่เครื่องมือรับ จากค่าที่มีจริงในฐาน"""
    vals = {"strength": set(), "weight": set(), "open_area": set(), "pitch": set()}
    surfaces, pins, mats = set(), set(), set()
    for p in cat.products:
        spec = p["specifications"]
        surfaces.add(p["retrieval_card"].get("surface_type"))
        surfaces |= {i.get("surface_type") for i in p.get("industries", [])}
        if spec.get("open_area_pct") is not None:
            vals["open_area"].add(spec["open_area_pct"])
        if (spec.get("pitch") or {}).get("mm") is not None:
            vals["pitch"].add(spec["pitch"]["mm"])
        for v in spec["variants"]:
            pins.add(v.get("pin_material")); mats.add(v.get("belt_material"))
            if (v.get("belt_strength") or {}).get("n_per_m") is not None:
                vals["strength"].add(v["belt_strength"]["n_per_m"])
            if (v.get("belt_weight") or {}).get("kg_per_m2") is not None:
                vals["weight"].add(v["belt_weight"]["kg_per_m2"])
    mats |= {r.get("base_polymer") for r in cat.data.get("material_registry") or []}
    surfaces, pins, mats = sorted(x for x in surfaces if x), sorted(x for x in pins if x), sorted(x for x in mats if x)
    qs = [ExploratoryQuery(rank="overview")]
    for fld, vs in vals.items():
        vs = sorted(vs)
        probes = sorted(set(vs[:: max(1, len(vs) // 12)] + [vs[0], vs[-1], vs[0] - 1, vs[-1] + 1]))
        for op, v in itertools.product((">=", "<=", ">", "<", "=="), probes):
            qs.append(ExploratoryQuery(field=fld, op=op, value=float(v)))
        for v in vs[:: max(1, len(vs) // 6)]:                    # ขอบของ "==" ±0.05
            for d in (-0.05, 0.05, -0.06, 0.06):
                qs.append(ExploratoryQuery(field=fld, op="==", value=float(v) + d))
        for r in ("max", "min"):
            qs.append(ExploratoryQuery(field=fld, rank=r))
        qs.append(ExploratoryQuery(field=fld, op="~", value=float(vs[0])))   # op ไม่รู้จัก → ไม่มีผล
    filters = [{}] + [{"surface": s} for s in surfaces] + [{"pin_material": x} for x in pins] \
        + [{"belt_material": x} for x in mats] + [{"belt_material": "NOPE"}] \
        + [{"surface": surfaces[0], "surface_any": tuple(surfaces[:3])}]
    base = list(qs)
    for f in filters[1:]:
        for q in base[1:: 7]:
            qs.append(ExploratoryQuery(**{**q.__dict__, **f}))
        qs.append(ExploratoryQuery(**f))
    return qs


def csv_queries(S):
    out = []
    for f in sorted(glob.glob("eval/cases/testcases*.csv") + glob.glob("eval/cases/testsuite*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                q = S.parse(row.get("user_text") or "")
                if q is not None:
                    out.append((f"{f}:{row.get('id')}", q))
    return out


def main():
    cat = Catalogue(DB)
    py = CatalogueSearch(cat)
    try:
        from engine.brands.modutech.variant_index import QdrantCatalogueSearch
        qd = QdrantCatalogueSearch(cat)
    except ImportError:                                  # ใช้ --dump บนเวอร์ชันเก่าที่ยังไม่มีไฟล์นี้ได้
        qd = None
    cases = [(f"grid:{i}", q) for i, q in enumerate(grid(cat))] + csv_queries(py)
    dump, fail = {}, 0
    for name, q in cases:
        a = py.search(q)
        dump[name] = a
        if qd is not None:
            b = qd.search(q)
            if json.dumps(a, sort_keys=True, ensure_ascii=False) != json.dumps(b, sort_keys=True, ensure_ascii=False):
                fail += 1
                if fail <= 5:
                    print("FAIL", name, q.as_dict(), a["matched"], b["matched"])
    if "--dump" in sys.argv:
        json.dump(dump, open(sys.argv[sys.argv.index("--dump") + 1], "w"), ensure_ascii=False, sort_keys=True)
    nonempty = sum(1 for v in dump.values() if v.get("matches"))
    if qd is not None:
        print(f"points={qd.index.n_points} cases={len(cases)} (มีผล {nonempty}) fail={fail}")
        sys.exit(1 if fail else 0)
    print(f"dump only · cases={len(cases)} (มีผล {nonempty})")


if __name__ == "__main__":
    main()
