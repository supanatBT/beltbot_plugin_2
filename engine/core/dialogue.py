"""
core/dialogue.py
================
สถานะบทสนทนา — แกนกลางถือแค่สามช่องกลาง ที่เหลือเป็นของแต่ละแบรนด์

    state.brand             แบรนด์ที่คุยอยู่
    state.pending           สิ่งที่ถามกลับค้างไว้
    state.pending_question  คำถามเดิมของลูกค้าก่อนถูกถามกลับ
    state.brands[key]       dict ของแบรนด์นั้น — แกนกลางไม่เปิดดู

ช่องของแต่ละแบรนด์ประกาศใน brands/<key>/brand.yaml › state (ชื่อช่อง → ค่าเริ่มต้น)
แกนกลางจึงไม่ต้องรู้ว่าแบรนด์ไหนเก็บอะไร

รูปแบบตอนส่งออก (to_dict / from_dict) แบนเป็น "<key>_<field>"
    brands["x"]["codes"]  ⇄  "x_codes"
ตรงกับ dict ที่เบราว์เซอร์เก็บไว้จากระบบเดิม แชตเก่ากู้ได้โดยไม่ต้องแปลง
key ของแบรนด์ไม่มี "_" (registry ตรวจ) จึงแยกกลับที่ "_" ตัวแรกได้เสมอ

อ่าน/เขียนด้วยชื่อแบนได้ด้วย (state.x_codes) — คืนวัตถุตัวเดียวกับใน brands
โค้ดที่ยังเขียนแบบเดิมจึงทำงานต่อได้ระหว่างย้ายทีละชั้น รวมถึงการแก้ในที่ (.update / .append)
"""
from __future__ import annotations

import copy
from typing import Any, Optional

CORE_FIELDS = ("brand", "pending", "pending_question")
_CORE_DEFAULTS = {"brand": None, "pending": None, "pending_question": ""}


class DialogState:
    """อย่าสร้างตรง ๆ — ใช้ state_class(schema) เพื่อผูกช่องของแต่ละแบรนด์"""

    SCHEMA: dict[str, dict] = {}            # key → {field: ค่าเริ่มต้น}

    __slots__ = ("brand", "pending", "pending_question", "brands")

    def __init__(self, **kw):
        for f in CORE_FIELDS:
            object.__setattr__(self, f, copy.deepcopy(_CORE_DEFAULTS[f]))
        object.__setattr__(self, "brands", {k: copy.deepcopy(v) for k, v in self.SCHEMA.items()})
        for name, value in kw.items():
            setattr(self, name, value)        # ชื่อที่ไม่รู้จัก → AttributeError เหมือน dataclass

    # ── ชื่อแบน "<key>_<field>" ─────────────────────────────────
    def _split(self, name: str) -> Optional[tuple[str, str]]:
        key, sep, fld = name.partition("_")
        if sep and key in self.SCHEMA and fld in self.SCHEMA[key]:
            return key, fld
        return None

    def __getattr__(self, name: str) -> Any:
        # เรียกเฉพาะเมื่อหาแบบปกติไม่เจอ — กัน recursion ตอน deepcopy (ยังไม่มี brands)
        if name.startswith("__") or name == "brands":
            raise AttributeError(name)
        kf = self._split(name)
        if kf is None:
            raise AttributeError(f"{type(self).__name__} ไม่มีช่อง {name!r}")
        return self.brands[kf[0]][kf[1]]

    def __setattr__(self, name: str, value: Any) -> None:
        if name in CORE_FIELDS or name == "brands":
            object.__setattr__(self, name, value)
            return
        kf = self._split(name)
        if kf is None:
            raise AttributeError(f"{type(self).__name__} ไม่มีช่อง {name!r}")
        self.brands[kf[0]][kf[1]] = value

    # ── ส่งออก / รับเข้า ────────────────────────────────────────
    def to_dict(self) -> dict:
        # ลำดับคีย์เท่าของเดิม: brand → ช่องของแบรนด์ → pending — JSON ที่ส่งให้เบราว์เซอร์จึงเหมือนเดิมทุกไบต์
        out = {"brand": copy.deepcopy(self.brand)}
        for key, fields in self.SCHEMA.items():
            for fld in fields:
                out[f"{key}_{fld}"] = copy.deepcopy(self.brands[key][fld])
        out["pending"] = copy.deepcopy(self.pending)
        out["pending_question"] = copy.deepcopy(self.pending_question)
        return out

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "DialogState":
        """กรองคีย์ที่ไม่รู้จักทิ้ง — state ที่บันทึกจากโค้ดรุ่นอื่นต้องไม่ทำให้พัง"""
        st = cls()
        if not d:
            return st
        for name, value in d.items():
            if not isinstance(name, str):
                continue
            if name in CORE_FIELDS or st._split(name):
                setattr(st, name, copy.deepcopy(value))
        return st

    # ── ความสะดวก ───────────────────────────────────────────────
    def __eq__(self, other) -> bool:
        return isinstance(other, DialogState) and self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.to_dict()!r})"

    def __deepcopy__(self, memo):
        new = type(self).__new__(type(self))
        for f in CORE_FIELDS:
            object.__setattr__(new, f, copy.deepcopy(getattr(self, f), memo))
        object.__setattr__(new, "brands", copy.deepcopy(self.brands, memo))
        return new

    def reset_brand(self, key: str) -> None:
        """คืนช่องของแบรนด์นี้เป็นค่าเริ่มต้น"""
        self.brands[key] = copy.deepcopy(self.SCHEMA[key])


def state_class(schema: dict[str, dict], name: str = "DialogState") -> type:
    """สร้างคลาสสถานะที่ผูกช่องของแบรนด์ตาม schema (key → {field: default})

    ตรวจ: key ไม่มี "_" · ชื่อช่องไม่ชนกับช่องกลาง
    """
    for key, fields in schema.items():
        if "_" in key:
            raise ValueError(f"key {key!r} มี _ — แยก \"<key>_<field>\" กลับไม่ได้")
        if not isinstance(fields, dict):
            raise ValueError(f"state ของ {key} ต้องเป็น dict ชื่อช่อง → ค่าเริ่มต้น")
        for fld in fields:
            if not isinstance(fld, str) or not fld.isidentifier():
                raise ValueError(f"state ของ {key}: ชื่อช่อง {fld!r} ใช้ไม่ได้")
    return type(name, (DialogState,), {"SCHEMA": copy.deepcopy(schema), "__slots__": ()})
