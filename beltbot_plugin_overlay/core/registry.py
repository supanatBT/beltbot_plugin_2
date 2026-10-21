"""
core/registry.py
================
หาแบรนด์จาก brands/*/brand.yaml แล้วตรวจก่อนโหลด — เพิ่มแบรนด์ = เพิ่มโฟลเดอร์ ไม่แก้ไฟล์ไหนเลย

ตรวจตอนเริ่ม (ผิดข้อไหนหยุดพร้อมบอกไฟล์ ช่อง และค่าทั้งสองฝั่ง)
  protocol   ต้องเท่ากับ core.protocol.PROTOCOL_VERSION
  key        ต้องเท่ากับชื่อโฟลเดอร์ · ตัวเล็ก ตัวเลข _ · ห้ามเป็น prefix "<อื่น>_" ของแบรนด์อื่น
             (สถานะส่งออกเป็น "<key>_<field>" ถ้า key ซ้อนกันจะแยกกลับไม่ได้)
  info       ครบทุกช่องของ BrandInfo · order ห้ามซ้ำ · answer_patterns ต้อง compile ได้
  enabled    true / false — false = registry ข้ามทั้งแบรนด์

ไม่ import โค้ดของแบรนด์ตอนอ่านค่า — load_plugins() เท่านั้นที่ import brands.<key>.plugin
"""
from __future__ import annotations

import importlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import yaml

from core.models import ImageStatus, resolve_image
from core.protocol import PROTOCOL_VERSION, BrandInfo, BrandPlugin, PluginContext

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brands")
KEY_RE = re.compile(r"^[a-z][a-z0-9]*$")      # ไม่มี _ — กันการแยก "<key>_<field>" กำกวม
INFO_FIELDS = ("name", "order", "kind_th", "menu_line_th", "offtopic_th", "category_th")


class RegistryError(RuntimeError):
    pass


@dataclass
class BrandConfig:
    key: str
    dir: str
    config: dict
    info: BrandInfo
    state: dict = field(default_factory=dict)       # brand.yaml › state: ชื่อช่อง → ค่าเริ่มต้น
    image: ImageStatus = field(default_factory=lambda: ImageStatus(False, "ยังไม่ได้ตรวจ"))

    def path(self, rel: Optional[str]) -> Optional[str]:
        """พาธใน brand.yaml นับจากโฟลเดอร์ของแบรนด์ ไม่ใช่จากที่สั่งรัน"""
        if not rel:
            return None
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(self.dir, rel))


def _info(key: str, where: str, raw: Any) -> BrandInfo:
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: ไม่มีหัวข้อ info")
    miss = [f for f in INFO_FIELDS if raw.get(f) in (None, "")]
    if miss:
        raise RegistryError(f"{where} › info: ขาด {', '.join(miss)}")
    if not isinstance(raw["order"], int) or raw["order"] < 1:
        raise RegistryError(f"{where} › info.order: {raw['order']!r} ต้องเป็นจำนวนเต็มตั้งแต่ 1")
    pats = tuple(str(p) for p in (raw.get("answer_patterns") or ()))
    for p in pats:
        try:
            re.compile(p)
        except re.error as e:
            raise RegistryError(f"{where} › info.answer_patterns: {p!r} ไม่ใช่ regex ที่ถูก ({e})") from e
    return BrandInfo(key=key, name=str(raw["name"]), order=raw["order"], kind_th=str(raw["kind_th"]),
                     menu_line_th=str(raw["menu_line_th"]), offtopic_th=str(raw["offtopic_th"]),
                     category_th=str(raw["category_th"]), answer_patterns=pats)


def _state(where: str, raw: Any) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RegistryError(f"{where} › state: ต้องเป็น ชื่อช่อง → ค่าเริ่มต้น")
    for fld in raw:
        if not isinstance(fld, str) or not fld.isidentifier():
            raise RegistryError(f"{where} › state: ชื่อช่อง {fld!r} ใช้ไม่ได้")
        if fld in ("brand", "pending", "pending_question"):
            raise RegistryError(f"{where} › state: ชื่อช่อง {fld!r} ชนกับช่องกลาง")
    return raw


def state_schema(configs: list[BrandConfig]) -> dict[str, dict]:
    """schema สำหรับ core.dialogue.state_class — เรียงตาม info.order"""
    return {b.key: dict(b.state) for b in configs}


def discover(root: str = DEFAULT_ROOT, only: Optional[list[str]] = None,
             include_disabled: bool = False, resolve_images: bool = True,
             collection_points: Optional[Callable[[str, str], int]] = None) -> list[BrandConfig]:
    """
    คืนแบรนด์เรียงตาม info.order
    only               จำกัดเฉพาะ key ที่ระบุ (เทสต์ใช้ — ระบบจริงไม่ส่ง)
    collection_points  (brand_key, collection) -> จำนวนจุด ใช้ตัดสิน image.enabled: auto
    resolve_images     False = ไม่ตรวจโมเดลรูป (ไม่ hash ไฟล์น้ำหนัก) — ใช้เมื่อต้องการแค่ info/state
    """
    if not os.path.isdir(root):
        raise RegistryError(f"ไม่พบโฟลเดอร์แบรนด์ {root}")
    out: list[BrandConfig] = []
    for name in sorted(os.listdir(root)):
        bdir = os.path.join(root, name)
        ypath = os.path.join(bdir, "brand.yaml")
        if not os.path.isfile(ypath):
            continue
        where = f"brands/{name}/brand.yaml"
        with open(ypath, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if cfg.get("protocol") != PROTOCOL_VERSION:
            raise RegistryError(f"{where}: protocol {cfg.get('protocol')!r} แต่แกนกลางรองรับ {PROTOCOL_VERSION}")
        key = cfg.get("key")
        if key != name:
            raise RegistryError(f"{where}: key {key!r} ต้องเท่ากับชื่อโฟลเดอร์ {name!r}")
        if not KEY_RE.match(key):
            raise RegistryError(f"{where}: key {key!r} ใช้ได้เฉพาะ a-z และ 0-9 ขึ้นต้นด้วยตัวอักษร")
        if only is not None and key not in only:
            continue
        enabled = cfg.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RegistryError(f"{where}: enabled {enabled!r} ต้องเป็น true หรือ false")
        if not enabled and not include_disabled:
            continue
        bc = BrandConfig(key=key, dir=bdir, config=cfg, info=_info(key, where, cfg.get("info")),
                         state=_state(where, cfg.get("state")))
        if resolve_images:
            cp = (lambda col, _k=key: collection_points(_k, col)) if collection_points else None
            bc.image = resolve_image(key, bdir, cfg.get("image"), cp)
        out.append(bc)

    orders: dict[int, str] = {}
    for b in out:
        if b.info.order in orders:
            raise RegistryError(f"info.order {b.info.order} ซ้ำกันระหว่าง {orders[b.info.order]} กับ {b.key}")
        orders[b.info.order] = b.key
    if only is not None:
        missing = sorted(set(only) - {b.key for b in out})
        if missing:
            raise RegistryError(f"ไม่พบแบรนด์ {', '.join(missing)} (หรือถูกปิดไว้)")
    return sorted(out, key=lambda b: b.info.order)


def load_plugins(configs: list[BrandConfig], shared: Optional[dict] = None) -> dict[str, BrandPlugin]:
    """import brands.<key>.plugin แล้วเรียก create(ctx) — ตรวจว่าตอบสัญญาครบ"""
    plugins: dict[str, BrandPlugin] = {}
    for b in configs:
        try:
            mod = importlib.import_module(f"brands.{b.key}.plugin")
        except ModuleNotFoundError as e:
            raise RegistryError(f"brands/{b.key}/plugin.py: โหลดไม่ได้ ({e})") from e
        if not hasattr(mod, "create"):
            raise RegistryError(f"brands/{b.key}/plugin.py: ไม่มีฟังก์ชัน create(ctx)")
        p = mod.create(PluginContext(brand_dir=b.dir, config=b.config,
                                     image_model=b.image.spec if b.image.enabled else None,
                                     shared=dict(shared or {})))
        if not isinstance(p, BrandPlugin):
            need = [m for m in BrandPlugin.__dict__ if not m.startswith("_") and not hasattr(p, m)]
            raise RegistryError(f"brands/{b.key}/plugin.py: ตอบสัญญาไม่ครบ ขาด {need}")
        if p.info.key != b.key:
            raise RegistryError(f"brands/{b.key}/plugin.py: info.key {p.info.key!r} ไม่ตรงกับโฟลเดอร์")
        plugins[b.key] = p
    return plugins
