"""
core/models.py
==============
ทะเบียนโมเดลรูปฝั่งเสิร์ฟ — อ่านจาก brands/<key>/brand.yaml › image (HANDOFF ข้อ 5.1)

หน้าที่เดียว: ตรวจว่า "ของที่จะโหลด ตรงกับที่ประกาศ" ก่อนระบบเริ่มตอบ
ไม่ตรงให้หยุดพร้อมบอกค่าทั้งสองฝั่ง ห้ามโหลดต่อแล้วไปพังตอนตอบคำถาม
(บทเรียนจาก expand_products ที่คืนค่าว่างเงียบ ๆ)

สิ่งที่ตรวจ
  labels      จำนวนคลาสอ่านจากไฟล์ ไม่ฝังในโค้ด · id ต้องเรียง 0..n-1 ไม่ขาด
  checkpoint  จำนวนคลาสที่ checkpoint มีจริง อ่านจากหัวไฟล์ safetensors (ไม่ต้องใช้ torch)
              ต้องเท่ากับ labels
  revision    adapter ในเครื่อง → "sha256:<16 ตัวแรก>" ของไฟล์น้ำหนัก ต้องตรง
              adapter บน Hub   → ต้องระบุ tag หรือ commit ห้ามว่าง ห้าม main/master
  thresholds  ไฟล์ JSON ค่าตัวเลขอยู่ในช่วง 0..1 (ช่อง "source" เป็นข้อความได้)

ไม่ import torch / qdrant — collection ตรวจผ่านฟังก์ชันที่ผู้เรียกส่งมา
MLflow ไม่เกี่ยวกับไฟล์นี้: ฝั่งเสิร์ฟอ่านแค่ไฟล์ตั้งค่า (ข้อ 5)
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

FLOATING_REVISIONS = {"", "main", "master", "latest", "head"}
WEIGHT_FILE = "adapter_model.safetensors"


class ModelSpecError(RuntimeError):
    """ของที่ประกาศไม่ตรงกับของที่มีจริง — ข้อความต้องบอกทั้งสองค่าเสมอ"""


@dataclass(frozen=True)
class ImageModelSpec:
    brand: str
    base: str
    adapter: str                  # พาธเต็มของโฟลเดอร์ หรือชื่อ repo บน Hub
    adapter_is_local: bool
    revision: str
    labels: tuple[str, ...]       # เรียงตาม id
    thresholds: dict
    collection: str
    reject_th: str = ""
    groups_path: Optional[str] = None     # visual_groups.json ถ้ามี

    @property
    def num_labels(self) -> int:
        return len(self.labels)


@dataclass
class ImageStatus:
    """ผลการตัดสินว่าแบรนด์นี้รับรูปไหม — enabled: auto ต้องบอกเหตุผลเสมอ"""
    enabled: bool
    reason: str
    spec: Optional[ImageModelSpec] = None
    problems: list = field(default_factory=list)


# ─────────────────────────── อ่านไฟล์ ───────────────────────────

def _resolve(brand_dir: str, p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(brand_dir, p))


def read_labels(path: str) -> tuple[str, ...]:
    """รับทั้ง label_mapping.json แบบ {"id2label": {...}} และลิสต์ธรรมดา"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return tuple(str(x) for x in raw)
    id2 = raw.get("id2label") if isinstance(raw, dict) else None
    if not isinstance(id2, dict) or not id2:
        raise ModelSpecError(f"{path}: ไม่พบ id2label หรือว่าง")
    ids = sorted(int(k) for k in id2)
    if ids != list(range(len(ids))):
        raise ModelSpecError(f"{path}: id ของคลาสต้องเป็น 0..{len(ids) - 1} ต่อเนื่อง แต่ได้ {ids}")
    return tuple(str(id2[str(i)]) for i in ids)


def checkpoint_num_labels(adapter_dir: str) -> Optional[int]:
    """จำนวนคลาสใน classifier ของ checkpoint — อ่านจากหัวไฟล์ safetensors อย่างเดียว ไม่โหลดน้ำหนัก
    คืน None ถ้าไฟล์ไม่มี classifier (เช่น adapter ที่ไม่ได้ save หัวจำแนก)"""
    path = os.path.join(adapter_dir, WEIGHT_FILE)
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
    for k, v in header.items():
        if k.endswith("classifier.bias") and isinstance(v, dict):
            return int(v["shape"][0])
    for k, v in header.items():
        if k.endswith("classifier.weight") and isinstance(v, dict):
            return int(v["shape"][0])
    return None


def file_revision(adapter_dir: str) -> str:
    h = hashlib.sha256()
    with open(os.path.join(adapter_dir, WEIGHT_FILE), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()[:16]


def read_thresholds(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        th = json.load(f)
    if not isinstance(th, dict) or not th:
        raise ModelSpecError(f"{path}: ต้องเป็น object ที่มีค่าอย่างน้อยหนึ่งค่า")
    for k, v in th.items():
        if k == "source":
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v <= 1.0:
            raise ModelSpecError(f"{path}: {k} = {v!r} ต้องเป็นตัวเลข 0..1")
    return th


# ─────────────────────────── ตรวจ ───────────────────────────

def load_image_spec(brand_key: str, brand_dir: str, image_cfg: dict) -> ImageModelSpec:
    """อ่านและตรวจครบทุกข้อ — ผิดข้อไหนหยุดที่ข้อนั้นพร้อมบอกค่าทั้งสองฝั่ง"""
    vit = image_cfg.get("vit") or {}
    where = f"brands/{brand_key}/brand.yaml › image"
    missing = [k for k, v in (("vit.base", vit.get("base")), ("vit.adapter", vit.get("adapter")),
                              ("vit.revision", vit.get("revision")), ("labels", image_cfg.get("labels")),
                              ("thresholds", image_cfg.get("thresholds")),
                              ("collection", image_cfg.get("collection"))) if not v]
    if missing:
        raise ModelSpecError(f"{where}: ยังไม่ได้กำหนด {', '.join(missing)}")

    adapter = _resolve(brand_dir, vit["adapter"])
    is_local = os.path.isdir(adapter)
    revision = str(vit["revision"]).strip()
    if is_local:
        actual = file_revision(adapter)
        if revision != actual:
            raise ModelSpecError(f"{where}.vit.revision: ประกาศ {revision} แต่ไฟล์ใน {adapter} คือ {actual}")
    else:
        adapter = vit["adapter"]               # ชื่อ repo — ใช้ตามที่เขียน
        if revision.lower() in FLOATING_REVISIONS:
            raise ModelSpecError(f"{where}.vit.revision: '{revision}' เป็นค่าลอย ต้องเป็น tag หรือ commit")

    labels = read_labels(_resolve(brand_dir, image_cfg["labels"]))
    if is_local:
        ck = checkpoint_num_labels(adapter)
        if ck is not None and ck != len(labels):
            raise ModelSpecError(f"{where}: labels มี {len(labels)} คลาส แต่ checkpoint {adapter} มี {ck} คลาส")

    thresholds = read_thresholds(_resolve(brand_dir, image_cfg["thresholds"]))
    return ImageModelSpec(
        brand=brand_key, base=vit["base"], adapter=adapter, adapter_is_local=is_local,
        revision=revision, labels=labels, thresholds=thresholds,
        collection=str(image_cfg["collection"]),
        reject_th=" ".join(str(image_cfg.get("reject_th") or "").split()),
        groups_path=_resolve(brand_dir, image_cfg.get("visual_groups")),
    )


def resolve_image(brand_key: str, brand_dir: str, image_cfg: Optional[dict],
                  collection_points: Optional[Callable[[str], int]] = None) -> ImageStatus:
    """
    enabled: false → ปิด
    enabled: true  → ต้องครบทุกข้อ ไม่ครบ = ModelSpecError (หยุดระบบ)
    enabled: auto  → เปิดเมื่อโมเดลตรวจผ่าน และ collection มีข้อมูล ไม่ครบ = ปิดพร้อมเหตุผล
                     ถ้าผู้เรียกไม่ส่ง collection_points มา (เช่น ชุดเกตที่ไม่มี Qdrant)
                     ถือว่ายังยืนยันไม่ได้ → ปิด
    """
    if not image_cfg:
        return ImageStatus(False, "ไม่มีหัวข้อ image")
    mode = image_cfg.get("enabled", "auto")
    mode = {True: "true", False: "false"}.get(mode, str(mode).lower())
    if mode not in ("true", "false", "auto"):
        raise ModelSpecError(f"brands/{brand_key}/brand.yaml › image.enabled: '{mode}' ต้องเป็น true/false/auto")
    if mode == "false":
        return ImageStatus(False, "ปิดใน brand.yaml")

    try:
        spec = load_image_spec(brand_key, brand_dir, image_cfg)
    except (ModelSpecError, OSError, ValueError) as e:
        if mode == "true":
            raise ModelSpecError(str(e)) from e
        return ImageStatus(False, f"auto: โมเดลยังไม่พร้อม — {e}", problems=[str(e)])

    if collection_points is None:
        if mode == "true":
            return ImageStatus(True, "เปิดใน brand.yaml (ยังไม่ได้ตรวจ collection)", spec)
        return ImageStatus(False, "auto: ไม่ได้ตรวจ collection — ยืนยันไม่ได้ว่ามีข้อมูล", spec)
    try:
        n = int(collection_points(spec.collection))
    except Exception as e:                                        # noqa: BLE001
        n, err = 0, f"{type(e).__name__}: {e}"
    else:
        err = ""
    if n <= 0:
        msg = f"collection {spec.collection} ไม่มีข้อมูล" + (f" ({err})" if err else "")
        if mode == "true":
            raise ModelSpecError(f"brands/{brand_key}/brand.yaml › image: เปิดไว้แต่{msg}")
        return ImageStatus(False, f"auto: {msg}", spec)
    return ImageStatus(True, f"{mode}: โมเดลตรงที่ประกาศ · collection {spec.collection} มี {n} จุด", spec)
