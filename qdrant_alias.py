"""
qdrant_alias.py — ตั้ง/ดู alias ของ collection Modutech (28 ต.ค.)

บอทเรียก collection ข้อความของ Modutech ผ่าน alias modutech_live (brands/modutech/brand.yaml)
ตั้ง alias ให้ชี้ collection จริง แล้วสลับเวอร์ชัน / ย้อนกลับได้ด้วยคำสั่งเดียว ไม่ต้องแก้โค้ด

    & $py qdrant_alias.py show
    & $py qdrant_alias.py set --to modutech_belt_chunks            # ครั้งแรก: ชี้ collection เดิม (ไม่คัดลอก ไม่สร้างใหม่)
    & $py qdrant_alias.py set --to modutech_belt_chunks_v31        # วันหน้า: สลับไปเวอร์ชันใหม่ที่ build แยกไว้แล้ว
    & $py qdrant_alias.py set --to modutech_belt_chunks            # ย้อนกลับ

กติกา
  · ปิดบอทก่อนรัน (Qdrant แบบไฟล์ล็อกโฟลเดอร์)
  · แตะเฉพาะ alias — ไม่สร้าง ไม่ลบ ไม่เขียนจุดใน collection ไหนเลย
  · ห้ามใช้กับ ./qdrant_db ของ Movex และห้ามชื่อที่ขึ้นต้นด้วย movex (สคริปต์ปฏิเสธเอง)
  · สำรอง meta.json เป็น meta.json.bak-<เวลา> ก่อนแก้ทุกครั้ง แล้วเปิดใหม่ตรวจผลหลังแก้
  · collection ปลายทางต้องมีจุด และชื่อ/ขนาดเวกเตอร์ต้องตรงกับตัวที่ alias ชี้อยู่ (ไม่ตรง = ไม่สลับ)

หลังตั้งเสร็จ meta.json ในโฟลเดอร์เปลี่ยน (ไฟล์อยู่ใน Git LFS) → commit แล้วอัปโหลดโฟลเดอร์ขึ้น Space
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(BASE, "qdrant_modutech_db")
DEFAULT_ALIAS = "modutech_live"


def _refuse_movex(path: str, *names: str) -> str | None:
    real = os.path.realpath(path)
    if os.path.basename(real.rstrip("\\/")) == "qdrant_db" or real == os.path.realpath(os.path.join(BASE, "qdrant_db")):
        return "นี่คือฐานข้อมูลของ Movex — ห้ามแตะ (กฎโปรเจกต์)"
    for n in names:
        if n and n.lower().startswith("movex"):
            return f"ชื่อ {n} เป็นของ Movex — ห้ามแตะ"
    return None


def _vectors(c, name: str) -> dict:
    """ชื่อเวกเตอร์ → (ขนาด, distance) เทียบโครงสร้างก่อนสลับ"""
    vc = c.get_collection(name).config.params.vectors
    if isinstance(vc, dict):
        return {k: (v.size, str(v.distance)) for k, v in vc.items()}
    return {"": (vc.size, str(vc.distance))}


def _open(path: str):
    from qdrant_client import QdrantClient
    if not os.path.isfile(os.path.join(path, "meta.json")):
        raise SystemExit(f"❌ ไม่พบ {os.path.join(path, 'meta.json')}")
    try:
        return QdrantClient(path=path)
    except Exception as e:                                   # noqa: BLE001 — ส่วนมากคือบอทเปิดค้างอยู่
        raise SystemExit(f"❌ เปิด {path} ไม่ได้ ({type(e).__name__}: {e}) — ปิดบอทก่อนแล้วรันใหม่")


def show(path: str) -> dict:
    c = _open(path)
    try:
        aliases = {a.alias_name: a.collection_name for a in c.get_aliases().aliases}
        print(f"โฟลเดอร์: {path}")
        for col in sorted(x.name for x in c.get_collections().collections):
            n = c.get_collection(col).points_count
            via = [a for a, t in aliases.items() if t == col]
            print(f"  collection {col}: {n} จุด · เวกเตอร์ {_vectors(c, col)}"
                  + (f" ← alias {', '.join(via)}" if via else ""))
        if not aliases:
            print("  (ยังไม่มี alias — บอทใช้ชื่อสำรองใน brand.yaml)")
        return aliases
    finally:
        c.close()


def set_alias(path: str, alias: str, to: str, dry: bool = False) -> int:
    from qdrant_client import models as M
    why = _refuse_movex(path, alias, to)
    if why:
        print(f"❌ {why}")
        return 2
    c = _open(path)
    try:
        names = {x.name for x in c.get_collections().collections}
        aliases = {a.alias_name: a.collection_name for a in c.get_aliases().aliases}
        if to not in names:
            print(f"❌ ไม่มี collection {to} (มี: {', '.join(sorted(names))})")
            return 2
        if alias in names:
            print(f"❌ {alias} เป็นชื่อ collection อยู่แล้ว ตั้งเป็น alias ซ้ำไม่ได้")
            return 2
        n = c.get_collection(to).points_count or 0
        if n <= 0:
            print(f"❌ {to} ไม่มีจุด — ไม่สลับ")
            return 2
        old = aliases.get(alias)
        if old == to:
            print(f"✅ {alias} ชี้ {to} อยู่แล้ว ไม่ต้องทำอะไร")
            return 0
        if old:
            a, b = _vectors(c, old), _vectors(c, to)
            if a != b:
                print(f"❌ โครงสร้างเวกเตอร์ไม่ตรงกัน {old} {a} ≠ {to} {b} — retriever จะค้นไม่ได้ ไม่สลับ")
                return 2
        print(f"{alias}: {old or '(ยังไม่มี)'} → {to} ({n} จุด)")
        if dry:
            print("(--dry-run ไม่ได้เขียน)")
            return 0
    finally:
        c.close()
        del c

    meta = os.path.join(path, "meta.json")
    bak = f"{meta}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(meta, bak)                                    # shadow copy ก่อนเขียน
    print(f"สำรอง → {os.path.basename(bak)}")

    c = _open(path)
    try:
        ops = []
        if old:
            ops.append(M.DeleteAliasOperation(delete_alias=M.DeleteAlias(alias_name=alias)))
        ops.append(M.CreateAliasOperation(create_alias=M.CreateAlias(collection_name=to, alias_name=alias)))
        c.update_collection_aliases(change_aliases_operations=ops)
    finally:
        c.close()
        del c

    c = _open(path)                                            # เปิดใหม่ตรวจว่าบันทึกลงไฟล์จริง
    try:
        got = {a.alias_name: a.collection_name for a in c.get_aliases().aliases}.get(alias)
        cnt = c.get_collection(alias).points_count if got else 0
    finally:
        c.close()
        del c
    if got != to or cnt != n:
        print(f"❌ ตรวจหลังเขียนไม่ผ่าน (alias → {got}, {cnt} จุด) — คืนไฟล์จาก {os.path.basename(bak)}")
        shutil.copy2(bak, meta)
        return 1
    print(f"✅ {alias} → {to} · ค้นผ่าน alias ได้ {cnt} จุด · commit qdrant_modutech_db/meta.json แล้วอัปโหลดขึ้น Space")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "set"])
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--alias", default=DEFAULT_ALIAS)
    ap.add_argument("--to", help="collection ปลายทาง (คำสั่ง set)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    why = _refuse_movex(a.path)
    if why:
        print(f"❌ {why}")
        return 2
    if a.cmd == "show":
        show(a.path)
        return 0
    if not a.to:
        print("❌ ต้องระบุ --to <collection>")
        return 2
    return set_alias(a.path, a.alias, a.to, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
