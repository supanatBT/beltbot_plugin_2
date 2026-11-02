"""ทดสอบเครื่องมือ Movex ของ agent เทียบ (ขั้นที่ 2) แบบออฟไลน์ — ไม่เรียก Gemini ไม่โหลดโมเดล

    python test_agent_movex.py          (venv ของ agent)

ตรวจ: แปลงรหัส · ผลเท่าฟังก์ชันเดิมของ runtime.py · ข้อมูลกระบวนการผลิต/วัสดุ · กราฟสเตอร์ ·
      MCP server ประกาศเครื่องมือครบ 18 (Modutech 11 + Movex 7) · AGENT_BRANDS=modutech เหลือ 11
เครื่องที่ไม่มี torch/transformers/peft (เครื่องผู้ช่วย) ใส่โมดูลแทนเปล่า ๆ ให้ import ผ่าน — ทางที่ทดสอบไม่ใช้โมเดล
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

STUBBED = []


class _Any:
    """แทนชื่อใดก็ได้ในโมดูลที่ไม่มี: เรียกได้ ใช้เป็น decorator ได้ (torch.no_grad()) ใช้เป็นคลาสได้"""
    def __init__(self, *a, **k):
        pass

    def __call__(self, f=None, *a, **k):
        return f

    def __getattr__(self, attr):
        return _Any()


_MISSING = {top for top in ("torch", "transformers", "peft") if importlib.util.find_spec(top) is None}
for name in ("torch", "torch.nn", "torch.nn.functional", "transformers", "peft"):
    if name.split(".")[0] in _MISSING:
        mod = types.ModuleType(name)
        mod.__getattr__ = lambda attr: _Any
        sys.modules[name] = mod
        STUBBED.append(name)
if "torch" in STUBBED:
    sys.modules["torch"].nn = sys.modules["torch.nn"]
    sys.modules["torch.nn"].functional = sys.modules["torch.nn.functional"]
    sys.modules["torch"].cuda = types.SimpleNamespace(is_available=lambda: False)

from agent_baseline import movex_tools as M   # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  — {detail}"))


print("1) แปลงรหัสที่ลูกค้าพิมพ์")
for raw, want in [("LF820 K325", "movex_chain_LF820_K325"), ("lf 880 tab k450", "movex_chain_LF880_TAB_K450"),
                  ("54901", "movex_sprocket_54901"), ("LF 882 TAB K750", "movex_chain_LF882_TAB_K750"),
                  ("movex_chain_LF820_K400", "movex_chain_LF820_K400")]:
    got = M.resolve_product(raw)
    check(f"{raw!r} → {want}", got == (want, []), got)
pid, cands = M.resolve_product("LF820")
check("'LF820' ไม่ชัด → candidates ไม่เลือกเอง", pid is None and len(cands) == 5, (pid, cands))
check("รหัสที่ไม่มี → None", M.resolve_product("XYZ999") == (None, []))

print("2) ผลเท่าฟังก์ชันเดิมของ runtime.py (ฟังก์ชันตัวเดียวกัน ไม่เขียนใหม่)")
R = M._data()[0]
check("movex_overview = analyze_product_database", M.movex_overview() == R.analyze_product_database())
check("movex_compare รับรหัสแบบลูกค้าพิมพ์",
      M.movex_compare("LF820 K325, LF880 TAB K450")
      == R.compare_specific_products("movex_chain_LF820_K325,movex_chain_LF880_TAB_K450"))
cmp = M.movex_compare("LF820 K325")
check("compare มีความกว้าง 82.5 และโหลด 1625", "82.5" in cmp and "1625" in cmp, cmp[:200])
flt = M.movex_filter("load", ">=", 0, "", "load", "desc")
check("movex_filter ทำงาน (ไม่มีโมเดล = ทางสำรอง JSON ของฟังก์ชันเดิม)", flt.startswith("พบ"), flt[:120])
_ds = M.movex_datasheet("LF820 K325")
check("movex_datasheet สร้างได้ หรือคืนข้อความเหตุผล (เครื่องที่รูปเป็นตัวชี้ LFS)",
      "สำเร็จ" in _ds or "แสดง" in _ds or "error" in _ds, _ds)

print("3) ข้อมูลรุ่นเต็ม + กราฟ")
d = json.loads(M.movex_lookup("LF820 K325"))
check("lookup มีวัสดุพร้อมรายละเอียด", "material_details" in d["product"], list(d["product"]))
check("lookup ไม่ส่งข้อความค้นภายใน (search_content)", "search_content" not in d["product"])
s = json.loads(M.movex_lookup("54301"))
check("สเตอร์ 54301 มีรายละเอียดกระบวนการผลิต (GRAPH-003)", "manufacturing_details" in s["product"], list(s["product"]))
g = json.loads(M.movex_lookup("54901"))["graph_context"]
check("กราฟของ 54901 มีโซ่ที่ใช้คู่", "LF880" in g or "LF 880" in g, g[:300])
check("รหัสไม่ชัด → error + candidates", "candidates" in json.loads(M.movex_lookup("LF820")))

print("4) prompt r2m = r2 ทุกตัวอักษรในหมวด Modutech + หมวดเลือกแบรนด์ + หมวด Movex")
from agent_baseline import agent as AG   # noqa: E402
_t = AG.instruction_r2m()
check("หมวด Modutech = r2 ทุกตัวอักษร (ตัดแค่สองบรรทัดตัวตน)", AG.INSTRUCTION_TH_R2.split("\n", 3)[3] in _t)
check("เมนูถามแบรนด์ตรงกับบอท (1 Movex · 2 Modutech)", "1. โซ่ท็อปเชน Movex" in _t and "2. สายพานโมดูลาร์ Modutech" in _t)
check("เกณฑ์ ViT จาก thresholds.json (0.90 / 0.50)", "≥ 0.90" in _t and "≥ 0.50" in _t)
check("ไม่มีชื่อรุ่น Modutech ใหม่นอกจากที่ r2 มี", all(c not in _t.replace(AG.INSTRUCTION_TH_R2, "")
                                                        for c in ("EC127", "HC127", "MD508", "EC508", "XP254")))

print("5) MCP server ประกาศเครื่องมือ")


async def _names(env: dict) -> list[str]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    p = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "agent_baseline", "mcp_server.py")],
                              cwd=ROOT, env={**os.environ, **env})
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return sorted(t.name for t in (await s.list_tools()).tools)

try:
    both = asyncio.run(_names({"AGENT_BRANDS": "modutech,movex"}))
    only = asyncio.run(_names({"AGENT_BRANDS": "modutech"}))
    r2 = asyncio.run(_names({"AGENT_BRANDS": "", "AGENT_PROMPT": "r2"}))
    r2m = asyncio.run(_names({"AGENT_BRANDS": "", "AGENT_PROMPT": "r2m"}))
    check("prompt r2 (ขั้นที่ 1) ได้ 11 เครื่องมือเท่าเดิม · r2m ได้ 18", len(r2) == 11 and len(r2m) == 18, (len(r2), len(r2m)))
    check("สองแบรนด์ = 18 เครื่องมือ", len(both) == 18, both)
    check("AGENT_BRANDS=modutech = 11 เครื่องมือ (เท่าขั้นที่ 1)", len(only) == 11, only)
    check("ชื่อเครื่องมือ Movex ครบ 7", sorted(n for n in both if n.startswith("movex_")) ==
          sorted(f.__name__ for f in M.TOOLS))
except Exception as e:                                      # noqa: BLE001 — ไม่มี torch → server import retriever ไม่ได้
    check("MCP server เปิดได้", False, f"{type(e).__name__}: {e}")

if STUBBED:
    print(f"\n(เครื่องนี้ไม่มี {', '.join(STUBBED)} — ค้นเวกเตอร์และเทียบรูป Movex ต้องลองบนเครื่องที่มีโมเดล (check_tools))")
print(f"\nรวม {ok}/{ok + fail}")
sys.exit(1 if fail else 0)
