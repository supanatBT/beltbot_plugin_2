"""
core/metrics.py — บรรทัดตัวเลขสำหรับ monitor (28 ต.ค.)
=====================================================
หนึ่งบรรทัดต่อเหตุการณ์ พิมพ์ลง stdout → ดูได้ใน Logs ของ HF Space · สรุปด้วย metrics_report.py

    METRIC {"src": "turn", ...}   หนึ่งเทิร์นที่บอทตอบ (core/turn.py)
    METRIC {"src": "api",  ...}   หนึ่งคำขอ /api/chat รวมที่ถูกปฏิเสธก่อนถึงบอท (app.py)

ไม่มีข้อมูลส่วนบุคคล — บังคับด้วยรายชื่อฟิลด์ที่อนุญาต (ALLOWED) ฟิลด์อื่นถูกทิ้งก่อนพิมพ์เสมอ
  · ไม่มีข้อความลูกค้า · คำตอบบอท · รูป · IP
  · session เก็บเป็นแฮชที่มีเกลือ (เกลือสุ่มใหม่ทุกครั้งที่ Space เริ่ม ถ้าไม่ตั้ง METRICS_SALT)
    นับได้ว่ากี่เทิร์นต่อบทสนทนา แต่ย้อนกลับเป็น session id ไม่ได้

METRICS_LOG=0 ปิด · ค่าเริ่มต้นเปิด (ต่างจาก IMAGE_TEST_LOG ซึ่งมีข้อความลูกค้า จึงปิดไว้)
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from typing import Any, Optional

PREFIX = "METRIC "
ENABLED = os.environ.get("METRICS_LOG", "1").strip() != "0"
_SALT = (os.environ.get("METRICS_SALT") or "").strip() or secrets.token_hex(8)

# ฟิลด์ที่พิมพ์ได้ — เพิ่มฟิลด์ใหม่ต้องเพิ่มที่นี่ และต้องไม่ใช่ข้อความอิสระจากลูกค้าหรือบอท
ALLOWED = {
    "src", "at", "s", "image",
    # เทิร์น
    "brand", "action", "policy", "vit", "gate", "guard",
    "ms_total", "ms_llm", "tokens", "model", "status", "err",
    # api
    "code", "http", "ms",
}
# ค่าที่เป็นข้อความได้ต้องสั้นและมาจากชุดคำของโค้ด (ชื่อแบรนด์ · action · policy · ชื่อคลาส error)
_MAX_STR = 40


def session_tag(session_id: str) -> str:
    if not session_id:
        return ""
    return hashlib.sha256((_SALT + session_id).encode("utf-8")).hexdigest()[:10]


def _clean(v: Any, depth: int = 0) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, str):
        return v[:_MAX_STR]
    if isinstance(v, dict) and depth < 2:
        return {str(k)[:_MAX_STR]: _clean(x, depth + 1) for k, x in v.items()}
    return None                                          # list/วัตถุอื่น ไม่พิมพ์


def record(rec: dict) -> dict:
    """กรองเหลือเฉพาะฟิลด์ที่อนุญาต + เติมเวลา — แยกจาก emit เพื่อให้เทสตรวจได้โดยไม่ต้องจับ stdout"""
    out = {k: _clean(v) for k, v in rec.items() if k in ALLOWED}
    out.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return out


def emit(rec: dict) -> Optional[str]:
    """พิมพ์หนึ่งบรรทัด · ผิดพลาดอะไรก็ไม่ล้มเทิร์น"""
    if not ENABLED:
        return None
    try:
        line = PREFIX + json.dumps(record(rec), ensure_ascii=False, separators=(",", ":"))
        print(line, flush=True)
        return line
    except Exception as e:                               # noqa: BLE001
        print(f"⚠️ METRIC เขียนไม่ได้: {type(e).__name__}")
        return None


def parse_line(line: str) -> Optional[dict]:
    """อ่านกลับ (metrics_report.py) — บรรทัดที่มีคำนำหน้าเวลา/ระดับ log ก็อ่านได้"""
    i = line.find(PREFIX)
    if i < 0:
        return None
    try:
        d = json.loads(line[i + len(PREFIX):].strip())
    except (json.JSONDecodeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def image_fields(policy, route) -> dict:
    """คะแนนรูปของเทิร์น (ตัวเลขล้วน) — คะแนน ViT ต่อแบรนด์ · ประตูต่อแบรนด์ · policy"""
    out: dict = {"policy": policy.kind if policy is not None else ("off" if route is not None else None)}
    raw = policy.original if (policy is not None and getattr(policy, "original", None) is not None) else route
    scores = (getattr(raw, "scores", None) or {}) if raw is not None else {}
    vit = {b: getattr(sc, "confidence", None) for b, sc in scores.items()}
    if vit:
        out["vit"] = vit
    readings = (getattr(policy, "readings", None) or {}) if policy is not None else {}
    gate = {}
    for b, r in readings.items():
        d = dict(getattr(r, "detail", None) or {})
        gate[b] = {"score": d.get("score"), "text": d.get("text"), "direct": bool(getattr(r, "direct", False)),
                   "product": bool(getattr(r, "product_like", False))}
    if gate:
        out["gate"] = gate
    return out


def token_fields(usage: Optional[dict]) -> Optional[dict]:
    """usage_metadata ของ Gemini → ชื่อสั้น"""
    if not usage:
        return None
    names = {"prompt_token_count": "in", "candidates_token_count": "out",
             "thoughts_token_count": "think", "total_token_count": "total"}
    t = {names[k]: v for k, v in usage.items() if k in names and isinstance(v, int)}
    return t or None
