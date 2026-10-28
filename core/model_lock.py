"""
core/model_lock.py — ล็อก revision ของโมเดลจาก HF Hub (28 ต.ค.)
================================================================
models.yaml (รากรีโป · สร้างด้วย models_lock.py จากแคชบนเครื่องที่ผ่านชุดทดสอบแล้ว)

    models:
      jinaai/jina-embeddings-v3:
        revision: 0123abcd…        # commit เต็ม 40 ตัว

ไม่มีไฟล์ หรือไม่มีชื่อโมเดลในไฟล์ → from_pretrained แบบเดิม (ไม่ส่ง revision) พฤติกรรมเท่าเดิมทุกอย่าง
มีไฟล์ → ส่ง revision=<commit> ทุกครั้ง Space จะโหลดตัวเดียวกับที่ทดสอบบนเครื่องเสมอ แม้เจ้าของโมเดลอัปเดต main

LOADED เก็บ commit ที่โหลดจริง (config._commit_hash) ไว้ให้ /health/detail เทียบกับที่ล็อก
ไม่ import transformers — ใช้ได้ในเทสที่ไม่มีโมเดล
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SHA = re.compile(r"^[0-9a-f]{40}$")

LOADED: dict[str, Optional[str]] = {}       # model_id → commit ที่โหลดจริง (None = โฟลเดอร์ในเครื่อง/ไม่ทราบ)
_cache: Optional[dict] = None


def lock_path() -> str:
    return os.environ.get("MODELS_LOCK") or os.path.join(BASE_DIR, "models.yaml")


class ModelLockError(ValueError):
    pass


def load(path: Optional[str] = None, refresh: bool = False) -> dict:
    """{model_id: {"revision": sha, ...}} · ไม่มีไฟล์ = {} · ไฟล์ผิดรูป = หยุด (ไม่เดาว่าตั้งใจล็อกอะไร)"""
    global _cache
    if _cache is not None and not refresh and path is None:
        return _cache
    p = path or lock_path()
    if not os.path.isfile(p):
        out: dict = {}
    else:
        import yaml
        with open(p, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        models = raw.get("models") if isinstance(raw, dict) else None
        if not isinstance(models, dict):
            raise ModelLockError(f"{os.path.basename(p)}: ต้องมีหัวข้อ models:")
        out = {}
        for mid, spec in models.items():
            rev = str((spec or {}).get("revision") or "").strip() if isinstance(spec, dict) else ""
            if not _SHA.match(rev):
                raise ModelLockError(f"{os.path.basename(p)} › {mid}: revision ต้องเป็น commit 40 ตัว (ได้ '{rev}')")
            out[str(mid)] = dict(spec, revision=rev)
    if path is None:
        _cache = out
    return out


def pin(model_id: str) -> dict:
    """kwargs สำหรับ from_pretrained — {} เมื่อไม่ได้ล็อก (เท่าเดิม)"""
    spec = load().get(model_id)
    return {"revision": spec["revision"]} if spec else {}


def note(model_id: str, model: Any) -> None:
    """บันทึก commit ที่โหลดจริง · โหลดซ้ำหลายตัว (processor + model) ใช้ค่าล่าสุดที่ไม่ใช่ None"""
    commit = getattr(getattr(model, "config", None), "_commit_hash", None)
    if commit or model_id not in LOADED:
        LOADED[model_id] = commit if isinstance(commit, str) else None


def status() -> dict:
    """ต่อโมเดล: ที่ล็อก · ที่โหลดจริง · ตรงไหม (None = เทียบไม่ได้)"""
    locked = load()
    out = {}
    for mid in sorted(set(locked) | set(LOADED)):
        want = (locked.get(mid) or {}).get("revision")
        got = LOADED.get(mid)
        out[mid] = {"locked": want, "loaded": got,
                    "match": (want == got) if (want and got) else None}
    return out
