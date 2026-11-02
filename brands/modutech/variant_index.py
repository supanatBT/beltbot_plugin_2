"""
variant_index.py — ค้นทั้งฐาน Modutech ด้วย Payload Filter + Range Filter ของ Qdrant

ที่มา (2 พ.ย. 2026 · ผู้ใช้ตัดสิน): เดิม CatalogueSearch.search() วนกรองทั้ง 68 รุ่นในหน่วยความจำ
ส่วน Movex กรองตัวเลขด้วย Range Filter ของ Qdrant — ไฟล์นี้ย้ายขั้น "คัดกรอง" ของ Modutech ไปไว้ที่ Qdrant
ให้ใช้ความสามารถของฐานข้อมูลแบบเดียวกัน

หลักที่ไม่เปลี่ยน
  · ผลลัพธ์ต้องเหมือนแบบเดิมทุกตัวอักษร (test_variant_index_parity.py เทียบทุกคำถามในชุดทดสอบ + กริดเงื่อนไข)
  · Qdrant ทำหน้าที่ "คัดกรอง" เท่านั้น — การจัดรูปผล เรียงลำดับ หมายเหตุ และสถานะสภาวะเปียก
    ยังใช้โค้ดเดิมใน CatalogueSearch และประตูข้อมูล (gates.py) ยังเป็นผู้ตัดสินสุดท้ายก่อนถึง LLM
  · ไม่มีอุณหภูมิและความกว้าง — สองค่านี้ต้องผ่านการถามเปียก/แห้งและกฎความกว้างก่อน (เหมือนเครื่องมือเดิม)
  · ไม่แตะ collection ของ Movex: ใช้ Qdrant แบบในหน่วยความจำ (":memory:") สร้างใหม่จากฐานข้อมูล
    ทุกครั้งที่ระบบเริ่มทำงาน (หลักเดียวกับกราฟความรู้) จึงไม่มีไฟล์ฐานข้อมูลใหม่และไม่ชนโฟลเดอร์เดิม

หน่วยของจุดข้อมูล (point) = ตัวเลือกวัสดุหนึ่งตัว (variant) · 68 รุ่น = 282 จุด
payload ต่อจุด
  belt_code · variant_id · order (ลำดับรุ่น , ลำดับ variant ในไฟล์ — ใช้เรียงผลให้เหมือนเดิม)
  belt_material_keys = [เกรด, base_polymer] (ลูกค้าพิมพ์ "POM" ต้องได้ POM-NL ด้วย)
  pin_material · surfaces (ผิวของรุ่น + ผิวที่โบรชัวร์รายอุตสาหกรรมเรียก)
  strength · weight (ราย variant) · open_area · pitch (ระดับรุ่น คัดลอกลงทุก variant)
ค่าที่ไม่มีในเล่มไม่ใส่ key เลย → Range Filter ไม่ผ่านโดยอัตโนมัติ (ตรงกับเดิมที่ val is None = ไม่ผ่าน)
"""
from __future__ import annotations

from typing import Optional

import warnings

from brands.modutech.router import CatalogueSearch, ExploratoryQuery, compare

COLLECTION = "modutech_variants"
_EQ_TOL = 0.05            # เท่ากับ compare() เดิม: abs(val - ref) <= 0.05


class VariantIndex:
    """ดัชนีระดับ variant บน Qdrant (โหมดในหน่วยความจำ)"""

    def __init__(self, cat, client=None):
        from qdrant_client import QdrantClient, models
        self.models = models
        self.client = client or QdrantClient(location=":memory:")
        self.cat = cat
        self._build()

    def _build(self) -> None:
        m = self.models
        if self.client.collection_exists(COLLECTION):
            self.client.delete_collection(COLLECTION)
        # ใช้แค่ payload — เวกเตอร์ 1 มิติเป็นค่าคงที่ เพราะ Qdrant ต้องมีเวกเตอร์ต่อจุด
        self.client.create_collection(COLLECTION, vectors_config=m.VectorParams(size=1, distance=m.Distance.DOT))
        base = {r.get("material_code"): r.get("base_polymer") for r in self.cat.data.get("material_registry") or []}
        points, pid = [], 0
        for pi, p in enumerate(self.cat.products):
            spec, rc = p["specifications"], p["retrieval_card"]
            surfaces = sorted(s for s in ({rc.get("surface_type")}
                                          | {i.get("surface_type") for i in p.get("industries", [])}) if s)
            prod = {"belt_code": p["belt_code"], "surfaces": surfaces}
            if spec.get("open_area_pct") is not None:
                prod["open_area"] = float(spec["open_area_pct"])
            if (spec.get("pitch") or {}).get("mm") is not None:
                prod["pitch"] = float(spec["pitch"]["mm"])
            for vi, v in enumerate(spec["variants"]):
                pay = dict(prod, variant_id=v["variant_id"], order=pi * 1000 + vi,
                           belt_material_keys=sorted({x for x in (v.get("belt_material"),
                                                                  base.get(v.get("belt_material"))) if x}),
                           pin_material=v.get("pin_material"))
                s = (v.get("belt_strength") or {}).get("n_per_m")
                w = (v.get("belt_weight") or {}).get("kg_per_m2")
                if s is not None:
                    pay["strength"] = float(s)
                if w is not None:
                    pay["weight"] = float(w)
                points.append(m.PointStruct(id=pid, vector=[1.0], payload=pay))
                pid += 1
        self.client.upsert(COLLECTION, points=points)
        for key, schema in (("belt_code", m.PayloadSchemaType.KEYWORD),
                            ("belt_material_keys", m.PayloadSchemaType.KEYWORD),
                            ("pin_material", m.PayloadSchemaType.KEYWORD),
                            ("surfaces", m.PayloadSchemaType.KEYWORD),
                            ("strength", m.PayloadSchemaType.FLOAT), ("weight", m.PayloadSchemaType.FLOAT),
                            ("open_area", m.PayloadSchemaType.FLOAT), ("pitch", m.PayloadSchemaType.FLOAT)):
            with warnings.catch_warnings():      # โหมดในหน่วยความจำเตือนว่าดัชนีไม่มีผล — มีไว้เมื่อย้ายไป Qdrant server
                warnings.simplefilter("ignore")
                self.client.create_payload_index(COLLECTION, field_name=key, field_schema=schema)
        self.n_points = len(points)

    def _range(self, op: str, value: float):
        r = self.models.Range
        if op == ">=":
            return r(gte=value)
        if op == "<=":
            return r(lte=value)
        if op == ">":
            return r(gt=value)
        if op == "<":
            return r(lt=value)
        if op == "==":
            return r(gte=value - _EQ_TOL, lte=value + _EQ_TOL)
        return None

    def filter_for(self, q: ExploratoryQuery):
        """แปลงคำถามเป็น Filter ของ Qdrant · คืน None = ไม่มีจุดไหนผ่านแน่นอน (op ไม่รู้จัก)"""
        m = self.models
        must = []
        if q.surface:
            must.append(m.FieldCondition(key="surfaces", match=m.MatchAny(any=list(q.surface_any or (q.surface,)))))
        if q.pin_material:
            must.append(m.FieldCondition(key="pin_material", match=m.MatchValue(value=q.pin_material)))
        if q.belt_material:
            must.append(m.FieldCondition(key="belt_material_keys", match=m.MatchValue(value=q.belt_material)))
        if q.field in ("open_area", "pitch", "strength", "weight") and q.value is not None:
            if q.value == float("-inf"):         # rank max/min: ทุกค่าผ่าน แต่ต้องมีค่า
                rng = m.Range(gte=-1e300)
            else:
                rng = self._range(q.op, float(q.value))
                if rng is None:
                    return None
            must.append(m.FieldCondition(key=q.field, range=rng))
        return m.Filter(must=must)

    def matching(self, q: ExploratoryQuery) -> dict[str, list[str]]:
        """รหัสรุ่น → variant_id ที่ผ่านทุกเงื่อนไข (เรียงตามลำดับในไฟล์)"""
        flt = self.filter_for(q)
        if flt is None:
            return {}
        out, offset, rows = {}, None, []
        while True:
            pts, offset = self.client.scroll(COLLECTION, scroll_filter=flt, limit=512, offset=offset,
                                             with_payload=True, with_vectors=False)
            rows.extend(p.payload for p in pts)
            if offset is None:
                break
        if q.op == "==" and q.field in ("open_area", "pitch", "strength", "weight") and q.value is not None:
            # ขอบ ±0.05 พอดี: Range ของ Qdrant กับ abs() ของ Python ปัดเศษทศนิยมต่างกัน (2650−2649.95 = 0.0500000000002)
            # ตรวจซ้ำด้วย compare() เดิมเฉพาะ "==" เพื่อให้ผลเหมือนเดิมทุกกรณี — ไม่ใช่การกรองซ้ำทั้งชุด
            rows = [r for r in rows if compare(r[q.field], "==", float(q.value))]
        for r in sorted(rows, key=lambda r: r["order"]):
            out.setdefault(r["belt_code"], []).append(r["variant_id"])
        return out


class QdrantCatalogueSearch(CatalogueSearch):
    """CatalogueSearch ที่คัดกรองด้วย Qdrant · ส่วนอื่น (parse · match_application · จัดรูปผล) ใช้ของเดิม"""

    engine = "qdrant"

    def __init__(self, cat, client=None):
        super().__init__(cat)
        self.index = VariantIndex(cat, client=client)

    def _candidates(self, q: ExploratoryQuery):
        hit = self.index.matching(q)
        for p in self.cat.products:
            ids = hit.get(p["belt_code"])
            if not ids:
                continue
            keep = set(ids)
            yield p, [v for v in p["specifications"]["variants"] if v["variant_id"] in keep]
