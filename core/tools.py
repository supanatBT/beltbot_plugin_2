"""
core/tools.py — บันทึกการเรียก tool ของ LLM ในหนึ่งเทิร์น (ใช้ร่วมกันทุกแบรนด์)
ย้ายมาจาก _tracked / _tool_call_log ของ chatbot_v5.py (ชั้น 5) · พฤติกรรมเท่าเดิม
"""
from __future__ import annotations

import functools
import inspect
import typing
from typing import Callable, Optional


class ToolLog:
    def __init__(self):
        self.calls: list[dict] = []

    def reset(self) -> None:
        self.calls = []

    def track(self, fn: Callable) -> Callable:
        """ห่อ tool ให้บันทึกการเรียก โดยคงลายเซ็นของฟังก์ชันเดิมไว้

        30 ต.ค. (probe_tools r2): เดิม wrapper เป็น (*args, **kwargs) → SDK ทั้งสองตัวประกาศ tool แบบไม่มีพารามิเตอร์
        LLM เรียกได้แต่ส่งเงื่อนไขไม่ได้ (search_catalogue ได้ args {} ทุกครั้ง · ลองซ้ำ 2–3 รอบ → เทิร์นช้า 10–17 s)
        - __signature__ / __annotations__ เป็นชนิดจริง ไม่ใช่สตริง (ไฟล์ tool ใช้ from __future__ import annotations
          google-genai เรียก isinstance(value, annotation) ตอนแปลง args — สตริงทำให้ล้ม)
        - พารามิเตอร์ default None → Optional (ไม่บังคับให้ LLM ส่ง)
        """
        hints = typing.get_type_hints(fn)
        sig = inspect.signature(fn)
        params = []
        for p in sig.parameters.values():
            ann = hints.get(p.name, p.annotation)
            if p.default is None and ann is not inspect.Parameter.empty:
                ann = Optional[ann]
            params.append(p.replace(annotation=ann))
        ret = hints.get("return", sig.return_annotation)
        names = [p.name for p in params]
        log = self

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            entry = {"tool_name": fn.__name__, "args": {}, "result": "", "success": True}
            try:
                entry["args"] = {**dict(zip(names, args)), **kwargs}
                result = fn(*args, **kwargs)
                entry["result"] = result
                # คืน dict เพื่อให้ Gemini SDK ทำงานได้ (ของเดิม)
                return {"result": result}
            except Exception as e:
                entry["success"] = False
                entry["result"] = str(e)
                raise
            finally:
                log.calls.append(entry)
        wrapper.__signature__ = sig.replace(parameters=params, return_annotation=dict)
        wrapper.__annotations__ = {p.name: p.annotation for p in params
                                   if p.annotation is not inspect.Parameter.empty}
        wrapper.__annotations__["return"] = dict
        del wrapper.__wrapped__          # ให้ inspect ใช้ __signature__ ที่แก้แล้ว ไม่ย้อนไปฟังก์ชันเดิม
        return wrapper
