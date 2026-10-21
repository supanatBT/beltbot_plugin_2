"""
core/tools.py — บันทึกการเรียก tool ของ LLM ในหนึ่งเทิร์น (ใช้ร่วมกันทุกแบรนด์)
ย้ายมาจาก _tracked / _tool_call_log ของ chatbot_v5.py (ชั้น 5) · พฤติกรรมเท่าเดิม
"""
from __future__ import annotations

import inspect
from typing import Callable


class ToolLog:
    def __init__(self):
        self.calls: list[dict] = []

    def reset(self) -> None:
        self.calls = []

    def track(self, fn: Callable) -> Callable:
        params = list(inspect.signature(fn).parameters.keys())
        log = self

        def wrapper(*args, **kwargs):
            entry = {"tool_name": fn.__name__, "args": {}, "result": "", "success": True}
            try:
                entry["args"] = {**dict(zip(params, args)), **kwargs}
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
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
