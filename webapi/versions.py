"""
webapi/versions.py — ตอนนี้ Space รันข้อมูลกับโมเดลชุดไหน (28 ต.ค.) · ใช้กับ /health และ /health/detail

เก็บครั้งเดียวหลังบอทโหลดเสร็จ (ก่อนมีเทิร์นแรก — Qdrant แบบไฟล์ไม่ควรถูกอ่านพร้อม retriever)
อ่านอย่างเดียวทุกอย่าง: นับจุด / อ่าน alias / hash ไฟล์ — ไม่เขียน collection ไหนเลย (Movex ก็แค่นับ)
ไม่ส่งพาธเซิร์ฟเวอร์ออกไป — ชื่อไฟล์อย่างเดียว · แต่ละส่วนพังแยกกัน ไม่ทำให้ /health ล้ม
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, is_dataclass
from typing import Any

DATA_KEYS = ("catalogue", "products", "graph_db")


def _sha12(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    except OSError:
        return None


def _retriever_parts(plugin) -> tuple[Any, list[str]]:
    """(client, [ชื่อ collection ที่ retriever ใช้]) — Movex ห่อ retriever ไว้ใน .inner"""
    rt = getattr(plugin, "runtime", None)
    r = getattr(rt, "retriever", None)
    r = getattr(r, "inner", r)
    client, cfg = getattr(r, "client", None), getattr(r, "cfg", None)
    names = [n for n in (getattr(cfg, "text_collection", None), getattr(cfg, "image_collection", None))
             if n and not str(n).endswith("__not_built")]
    return client, names


def _collections(plugin) -> list[dict]:
    client, names = _retriever_parts(plugin)
    if client is None:
        return []
    try:
        aliases = {a.alias_name: a.collection_name for a in client.get_aliases().aliases}
    except Exception:                                    # noqa: BLE001
        aliases = {}
    out = []
    for n in names:
        row: dict = {"name": n}
        if n in aliases:
            row["target"] = aliases[n]
        try:
            row["points"] = client.get_collection(n).points_count
        except Exception as e:                           # noqa: BLE001 — collection ไม่มี (เช่น รูป Movex ปิดอยู่)
            row["points"] = None
            row["error"] = type(e).__name__
        out.append(row)
    return out


def collect(mod: Any) -> dict:
    from core import model_lock
    brands: dict = {}
    plugins = getattr(mod, "plugins", {}) or {}
    gates = getattr(mod, "_gates", {}) or {}
    for b in getattr(mod, "_configs", []) or []:
        part: dict = {}
        try:
            data = b.config.get("data") or {}
            part["data"] = [{"file": os.path.basename(p), "sha256": _sha12(p)}
                            for p in (b.path(data.get(k)) for k in DATA_KEYS) if p]
        except Exception as e:                           # noqa: BLE001
            part["data_error"] = type(e).__name__
        try:
            part["collections"] = _collections(plugins.get(b.key))
        except Exception as e:                           # noqa: BLE001
            part["collections_error"] = type(e).__name__
        img = getattr(b, "image", None)
        if img is not None:
            spec = getattr(img, "spec", None)
            part["image"] = {"enabled": bool(img.enabled), "vit_revision": getattr(spec, "revision", None)}
        g = gates.get(b.key)
        if g is not None or b.config.get("image_gate"):
            th = getattr(g, "th", None)
            part["gate"] = {"loaded": g is not None,
                            "thresholds": asdict(th) if is_dataclass(th) else None,
                            "model": (b.config.get("image_gate") or {}).get("model")}
        brands[b.key] = part

    try:
        models = model_lock.status()
    except Exception as e:                               # noqa: BLE001
        models = {"error": f"{type(e).__name__}: {e}"}

    manifest: dict = {"present": False}
    try:
        import data_manifest
        if os.path.isfile(data_manifest.OUT):
            manifest = {"present": True, "problems": data_manifest.check()}
    except Exception as e:                               # noqa: BLE001
        manifest = {"present": None, "error": type(e).__name__}

    return {"brands": brands, "models": models,
            "llm": {"model": getattr(mod, "GEMINI_MODEL", None)},
            "manifest": manifest}


def summary(v: dict) -> dict:
    """ส่วนสั้นสำหรับ /health สาธารณะ — ไม่มีชื่อ collection หรือ hash ยาว"""
    if not v:
        return {}
    cats = [d["file"].rsplit(".", 1)[0] for b in v.get("brands", {}).values() for d in b.get("data", [])
            if d.get("file", "").startswith("modutech_v")]
    models = v.get("models") or {}
    locked = [m for m in models.values() if isinstance(m, dict) and m.get("locked")]
    mismatch = [k for k, m in models.items() if isinstance(m, dict) and m.get("match") is False]
    man = v.get("manifest") or {}
    return {"catalogue": cats[0] if cats else None,
            "models_locked": len(locked), "models_mismatch": len(mismatch),
            "data_ok": (not man.get("problems")) if man.get("present") else None}
