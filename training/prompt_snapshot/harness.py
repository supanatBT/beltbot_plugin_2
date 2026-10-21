"""
harness.py — บันทึกทุกอย่างที่บอตส่งให้ LLM ในทุกเทิร์น แล้วเทียบข้ามการย้ายโครง

    python training/prompt_snapshot/harness.py --module chatbot_v5 -o training/prompt_snapshot/baseline.json
    python training/prompt_snapshot/harness.py --module <ชื่อใหม่> -o /tmp/after.json --compare training/prompt_snapshot/baseline.json

ทำไมต้องมี — ชุดเกตทั้งห้าไม่มีตัวไหนรันผ่าน chat_interaction เลย
(ทางตอบ Movex · การเรียก Gemini · การจัดการรูป · ข้อความฝ่ายขายที่ต่อท้าย)
ชั้นที่ย้ายส่วนนี้จึงต้องมีตัววัดของตัวเอง และต้องเก็บก่อนแตะโค้ด เหตุผลเดียวกับ baseline ข้อ 5.3

ต่อหนึ่งเทิร์นบันทึก
  decision · ข้อความที่ตอบ · ทุกการเรียก Gemini (system prompt · history · parts · ชื่อ tool) ·
  ข้อความที่ส่งไปฝังเวกเตอร์ · last_pids · ViT signal · seed ของกราฟ · DialogState หลังเทิร์น
บันทึกครั้งเดียว
  ผลของ tool ทุกตัวด้วยอาร์กิวเมนต์ชุดคงที่ · docstring ของ tool (เป็นส่วนหนึ่งของ prompt) ·
  การโหลดโมเดล (num_labels ของ ViT)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import inspect
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)                                   # บอตอ้างพาธแบบ ./qdrant_db
os.environ["GEMINI_API_KEY"] = "fake-key-for-snapshot"   # Gemini เป็นของปลอม ไม่มีการเรียกออกเน็ต

import fakes  # noqa: E402

CASE_FILES = [HERE / "cases" / "testcases_v2.csv",
              ROOT / "testcases_modutech_136.csv",
              ROOT / "testcases_graph_relations.csv",
              HERE / "cases" / "snapshot_extra.csv"]

DATASHEET_WORDS = re.compile(r"datasheet|drawing|ดรออิ้ง|ขอรูป|ขอดูแบบ", re.IGNORECASE)

# อาร์กิวเมนต์คงที่สำหรับเรียก tool ตรง — ครอบทั้งทางเจอและทางไม่เจอ
TOOL_PROBES = {
    "analyze_product_database": [{}, {"category": "chain"}, {"category": "sprocket", "series": "880"},
                                 {"series": "820"}, {"category": "chain", "series": "999"}],
    "compare_specific_products": [{"product_ids": "LF820 K325, LF880 TAB K450"},
                                  {"product_ids": "movex_chain_LF820_K325,movex_sprocket_54201"},
                                  {"product_ids": "XYZ"}],
    "filter_product_specs": [{"spec_type": "Max_Working_Load_N", "condition": ">=", "target_value": 2000},
                             {"spec_type": "Plate_Width_mm", "condition": "<=", "target_value": 100,
                              "sort_by": "Plate_Width_mm", "sort_order": "desc"},
                             {"spec_type": "Weight_kg_m", "condition": ">", "target_value": 0,
                              "product_type": "Sideflexing"}],
    "generate_datasheet": [{"product_id": "movex_chain_LF820_K325"}, {"product_id": "LF880 TAB K450"},
                           {"product_id": "nope"}],
    "search_catalogue": [{"field": "strength", "op": ">=", "value": 20000},
                         {"field": "open_area", "op": ">=", "value": 40, "surface": "Flush Grid"},
                         {"pin_material": "SS"}, {"belt_material": "PE", "field": "pitch", "op": "<=", "value": 30},
                         {}],
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def image_dims(b64: str) -> str:
    """รูปที่โค้ดสร้าง (datasheet · รูปลูกค้าย่อขนาด) บันทึกเป็น ชนิด+ขนาด ไม่ใช่ hash ของไบต์
    ไบต์ของรูปขึ้นกับฟอนต์และ libjpeg ของเครื่อง (Windows ใช้ arial · Linux ใช้ DejaVu)
    ขนาดภาพขึ้นกับโค้ดอย่างเดียว — เทียบข้ามเครื่องได้"""
    import base64
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(base64.b64decode(b64)))
        return f"{im.format}:{im.size[0]}x{im.size[1]}"
    except Exception:                                   # noqa: BLE001
        return f"undecodable:{len(b64)}"


def scrub(obj):
    """ทำให้เทียบได้: base64 ยาว → hash · float → ปัด 6 ตำแหน่ง"""
    if isinstance(obj, str):
        obj = re.sub(r"data:image/[a-z]+;base64,([A-Za-z0-9+/=]{40,})",
                     lambda m: f"data:image;{image_dims(m.group(1))}", obj)
        return obj
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {str(k): scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(x) for x in obj]
    return obj


def norm_refs(refs: str) -> str:
    # บรรทัด Turn มีเลข session ที่ไม่คงที่ข้ามรอบ — นอกนั้นเก็บทั้งหมด
    return re.sub(r"\*\*Turn:\*\* `[^`]*`", "**Turn:** `<id>`", refs or "")


def make_image(name: str):
    """รูปปลอมแทนไฟล์จริง (ไฟล์รูปในเคสไม่ได้อยู่ใน repo) ชี้ไปเวกเตอร์ในคลังตามชื่อ"""
    from PIL import Image
    h = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)
    m = re.match(r"snap_(bank|random)_(\d+)(?:_n([\d.]+))?", name)
    if m:
        key = f"bank:{m.group(2)}:{m.group(3) or '0.02'}" if m.group(1) == "bank" else f"random:{m.group(2)}"
    else:
        key = f"random:{h}" if h % 4 == 0 else f"bank:{h % 91}:0.02"
    img = Image.new("RGB", (32, 32), ((h >> 16) & 255, (h >> 8) & 255, h & 255))
    img.info["snap_key"] = key
    return img


def load_bank():
    from qdrant_client import QdrantClient
    c = QdrantClient(path="./qdrant_db")
    pts, _ = c.scroll("movex_images", limit=1000, with_vectors=True, with_payload=False)
    pts = sorted(pts, key=lambda p: str(p.id))
    bank = {"vit": [p.vector["vit"] for p in pts], "siglip": [p.vector["siglip"] for p in pts]}
    c.close()
    return bank


def install_fake_tool_calls(bot_mod):
    """Gemini ปลอมเรียก generate_datasheet เมื่อผู้ใช้ขอแบบ — แทน automatic function calling ของจริง
    ทำให้ทางที่ต่อรูป datasheet ท้ายคำตอบถูกวัดด้วย"""
    orig = fakes._Chat.send_message

    def send(self, parts):
        resp = orig(self, parts)
        text = " ".join(p for p in (parts if isinstance(parts, list) else [parts]) if isinstance(p, str))
        tools = {getattr(t, "__name__", ""): t for t in (self.model.tools or [])}
        if "generate_datasheet" in tools and DATASHEET_WORDS.search(text):
            m = re.search(r'"product_id":\s*"([^"]+)"', self.model.system_instruction or "")
            if m:
                try:
                    tools["generate_datasheet"](m.group(1))
                    fakes.RECORD["gemini"][-1]["tool_called"] = ["generate_datasheet", m.group(1)]
                except Exception as e:                         # noqa: BLE001
                    fakes.RECORD["gemini"][-1]["tool_called"] = ["generate_datasheet", f"ERR {e}"]
        return resp

    fakes._Chat.send_message = send


def load_cases():
    groups: dict = defaultdict(list)
    for f in CASE_FILES:
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            groups[(f.name, r["id"])].append(r)
    for k in groups:
        groups[k].sort(key=lambda r: int(r.get("turn_number") or 1))
    return groups


def run(module: str) -> dict:
    fakes.install_all()
    import retriever_v4
    fakes.patch_retriever(retriever_v4.RetrieverV4, load_bank())
    bot = importlib.import_module(module)
    install_fake_tool_calls(bot)

    seen_tools: dict = {}
    turns_out = []
    for (fname, cid), turns in load_cases().items():
        history, last_pids, sid, vit, graph = [], [], "", None, None
        for t in turns:
            text, img_name = t.get("user_text", ""), (t.get("image") or "").strip()
            if not text and not img_name:
                continue
            image = make_image(img_name) if img_name else None
            fakes.reset_turn_record()
            before = len(history)
            rec = {"file": fname, "id": cid, "turn": t.get("turn_number", "1"),
                   "text": text, "image": img_name}
            try:
                out = bot.chat_interaction(text, image, history, last_pids, sid, vit, graph)
                history, _st, refs, last_pids, sid, vit, graph = out
                rec.update(
                    new_messages=[m.get("content", "") for m in history[before:]],
                    refs=norm_refs(refs),
                    last_pids=list(last_pids or []),
                    vit=None if vit is None else {"series": vit.series, "confidence": vit.confidence,
                                                  "dominant": vit.dominant,
                                                  "top_pid": getattr(vit, "top_pid", None)},
                    graph_seeds=None if graph is None else list(getattr(graph, "seed_products", []) or []),
                    dialog_state=bot._dialog_states.get(sid),
                    error=None)
            except Exception as e:                                  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            rec["gemini"] = list(fakes.RECORD["gemini"])
            rec["embed"] = list(fakes.RECORD["embed"])
            turns_out.append(scrub(rec))
        # เก็บตัว tool ที่บอตยื่นให้ Gemini จริง (ไม่ใช่ค้นจากชื่อในโมดูล — ชื่อโมดูลจะเปลี่ยนตอนย้าย)
        for name, fn in _tools_seen_this_case().items():
            seen_tools.setdefault(name, fn)

    tool_out = {}
    for name in sorted(seen_tools):
        fn = seen_tools[name]
        outs = []
        for args in TOOL_PROBES.get(name, [{}]):
            try:
                r = fn(**args)
                outs.append({"args": args, "result": r})
            except Exception as e:                                  # noqa: BLE001
                outs.append({"args": args, "error": f"{type(e).__name__}: {e}"})
        # cleandoc: Python 3.13 ตัดย่อหน้าของ docstring ตอนคอมไพล์ 3.10 ไม่ตัด — เนื้อความเดียวกัน
        tool_out[name] = {"doc": inspect.cleandoc(fn.__doc__) if fn.__doc__ else fn.__doc__, "probes": outs}

    return scrub({"module": module, "turns": turns_out, "tools": tool_out,
                  "model_loads": fakes.RECORD["loads"]})


_TOOL_REF: dict = {}


def _tools_seen_this_case():
    return _TOOL_REF


# จับตัว tool จาก GenerativeModel ทุกครั้งที่ถูกสร้าง
_orig_model_init = fakes._Model.__init__


def _model_init(self, model_name=None, system_instruction=None, tools=None, **k):
    _orig_model_init(self, model_name, system_instruction, tools, **k)
    for t in tools or []:
        _TOOL_REF.setdefault(getattr(t, "__name__", repr(t)), t)


fakes._Model.__init__ = _model_init


def compare(a: dict, b: dict) -> int:
    ka = {(t["file"], t["id"], t["turn"]): t for t in a["turns"]}
    kb = {(t["file"], t["id"], t["turn"]): t for t in b["turns"]}
    diffs = 0
    for k in sorted(set(ka) | set(kb)):
        if ka.get(k) != kb.get(k):
            diffs += 1
            if diffs <= 15:
                ta, tb = ka.get(k) or {}, kb.get(k) or {}
                fields = sorted(f for f in set(ta) | set(tb) if ta.get(f) != tb.get(f))
                print(f"  ✗ {k[0]} {k[1]} t{k[2]}  ต่างที่ {fields}")
    for part in ("tools", "model_loads"):
        if a.get(part) != b.get(part):
            diffs += 1
            print(f"  ✗ {part} ต่างกัน")
            if part == "tools":
                for name in sorted(set(a["tools"]) | set(b["tools"])):
                    ta, tb = a["tools"].get(name) or {}, b["tools"].get(name) or {}
                    if ta.get("doc") != tb.get("doc"):
                        print(f"      {name}: docstring ต่าง")
                    for i, (pa, pb) in enumerate(zip(ta.get("probes", []), tb.get("probes", []))):
                        if pa != pb:
                            print(f"      {name} probe {i} {pa.get('args')}:")
                            print(f"        เดิม: {str(pa.get('result', pa.get('error')))[:150]!r}")
                            print(f"        ใหม่: {str(pb.get('result', pb.get('error')))[:150]!r}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="chatbot_v5")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--compare", help="ไฟล์ snapshot ที่ใช้เทียบ")
    a = ap.parse_args()

    snap = run(a.module)
    Path(a.out).write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    n = len(snap["turns"])
    calls = sum(len(t.get("gemini", [])) for t in snap["turns"])
    errs = [t for t in snap["turns"] if t.get("error")]
    print(f"เทิร์น {n} · เรียก Gemini {calls} · tool {len(snap['tools'])} · error {len(errs)}")
    for e in errs[:5]:
        print(f"  ! {e['id']} t{e['turn']}: {e['error']}")
    if a.compare:
        ref = json.loads(Path(a.compare).read_text(encoding="utf-8"))
        d = compare(ref, json.loads(Path(a.out).read_text(encoding="utf-8")))
        print("ตรงกับ snapshot ทุกเทิร์น" if d == 0 else f"ต่าง {d} จุด")
        return 1 if d else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
