"""
fakes.py — แทนที่ชั้นโมเดลด้วยของปลอมที่ให้ผลคงที่ เพื่อบันทึก "สิ่งที่บอตส่งให้ LLM"

ของจริงที่ยังรันอยู่ทั้งหมด: โค้ดบอตทุกบรรทัด · Qdrant (ไฟล์ local) · กราฟ · แคตตาล็อก
ของปลอม: torch · transformers · peft · gradio · google.generativeai · ตัวฝังเวกเตอร์ 4 ตัว

ข้อจำกัดที่ต้องพูดตรง ๆ
  · เวกเตอร์ข้อความเป็น hash ของข้อความ — ผลค้นคงที่แต่ไม่สะท้อนความหมาย
    ใช้พิสูจน์ "ข้อมูลเข้าเหมือนเดิม → prompt เหมือนเดิม" ไม่ใช่วัดคุณภาพการค้น
  · Gemini ปลอมไม่เรียก tool เอง — ผลของ tool บันทึกแยกด้วยการเรียกตรง (harness.tool_probe)
"""
from __future__ import annotations

import hashlib
import sys
import types

import numpy as np

RECORD: dict = {"gemini": [], "embed": [], "loads": []}


def reset_turn_record():
    RECORD["gemini"].clear()
    RECORD["embed"].clear()


# ─────────────────────────── ของอะไรก็ได้ ───────────────────────────

class Anything:
    """เรียกได้ ต่อ attribute ได้ ใช้กับ with ได้ — แทน gradio และโมเดลที่ไม่ได้ใช้จริง"""
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return Anything()
    def __getattr__(self, name): return Anything()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(())
    def __bool__(self): return True


def _mod(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    m.__getattr__ = lambda n: Anything()          # type: ignore[attr-defined]
    sys.modules[name] = m
    return m


# ─────────────────────────── torch ───────────────────────────

class _NoGrad:
    def __call__(self, fn=None):
        return fn if fn is not None else self
    def __enter__(self): return self
    def __exit__(self, *a): return False


def install_torch():
    t = _mod("torch", no_grad=lambda: _NoGrad(), float16="float16", float32="float32")
    t.cuda = types.SimpleNamespace(is_available=lambda: False)
    t.backends = types.SimpleNamespace(cudnn=types.SimpleNamespace(benchmark=False))
    nn = _mod("torch.nn")
    _mod("torch.nn.functional")
    t.nn = nn
    nn.functional = sys.modules["torch.nn.functional"]


# ─────────────────────────── transformers / peft ───────────────────────────

class _Loader:
    def __init__(self, kind): self.kind = kind

    def from_pretrained(self, *a, **k):
        RECORD["loads"].append({"kind": self.kind, "args": [str(x) for x in a if isinstance(x, str)],
                                "num_labels": k.get("num_labels")})
        return Anything()


def install_transformers():
    names = ["AutoTokenizer", "AutoModel", "ViTImageProcessor", "ViTForImageClassification",
             "SiglipProcessor", "SiglipModel", "AutoProcessor", "AutoImageProcessor", "CLIPModel",
             "CLIPProcessor"]
    _mod("transformers", **{n: _Loader(n) for n in names})
    _mod("peft", PeftModel=_Loader("PeftModel"))


def install_gradio():
    _mod("gradio")


# ─────────────────────────── Gemini ───────────────────────────

def _part(p):
    # รูปที่ส่งให้ LLM: บันทึกชนิด+ขนาด ไม่ใช่ hash — ไบต์ JPEG ขึ้นกับ libjpeg ของเครื่อง
    if isinstance(p, dict) and "data" in p:
        import io
        from PIL import Image
        try:
            im = Image.open(io.BytesIO(p["data"]))
            dims = f"{im.format}:{im.size[0]}x{im.size[1]}"
        except Exception:                               # noqa: BLE001
            dims = f"undecodable:{len(p['data'])}"
        return {"mime_type": p.get("mime_type"), "image": dims}
    return p


class _Resp:
    def __init__(self, text):
        self.text = text
        self.candidates = []


class _Chat:
    def __init__(self, model, history, afc):
        self.model, self.history, self.afc = model, history, afc

    def send_message(self, parts):
        parts = parts if isinstance(parts, list) else [parts]
        RECORD["gemini"].append({
            "model": self.model.model_name,
            "system_instruction": self.model.system_instruction,
            "tools": [getattr(t, "__name__", repr(t)) for t in (self.model.tools or [])],
            "history": self.history,
            "parts": [_part(p) for p in parts],
            "auto_function_calling": self.afc,
        })
        n = len(RECORD["gemini"])
        return _Resp(f"[คำตอบจำลองที่ {n}] รับทราบครับ")


class _Model:
    def __init__(self, model_name=None, system_instruction=None, tools=None, **_):
        self.model_name, self.system_instruction, self.tools = model_name, system_instruction, tools

    def start_chat(self, history=None, enable_automatic_function_calling=False):
        return _Chat(self, list(history or []), enable_automatic_function_calling)


def install_genai():
    import google.protobuf  # noqa: F401  — โหลด namespace จริงก่อน (qdrant_client ใช้) อย่าให้ของปลอมบัง
    import google as goog
    g = _mod("google.generativeai", configure=lambda **k: None, GenerativeModel=_Model)
    goog.generativeai = g


def install_all():
    install_torch()
    install_transformers()
    install_gradio()
    install_genai()


# ─────────────────────────── ตัวฝังเวกเตอร์ ───────────────────────────

def _rng(key: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


def _unit(v: np.ndarray) -> list[float]:
    return (v / np.linalg.norm(v)).astype(np.float32).tolist()


def patch_retriever(RetrieverV4, image_bank: dict[str, list]):
    """
    image_bank[space] = เวกเตอร์ที่เก็บอยู่ใน movex_images (อ่านจาก Qdrant ตอนเริ่ม)
    รูปปลอมมี info["snap_key"] = "bank:<i>:<noise>" หรือ "random:<seed>"
      bank   → เวกเตอร์ของจุดที่ i + noise  (ทดสอบทางที่รู้จักรูป)
      random → เวกเตอร์สุ่ม                   (ทดสอบทางปฏิเสธรูป)
    """
    def text(self, text):
        RECORD["embed"].append({"space": "jina", "text": text})
        return _unit(_rng("jina|" + text).standard_normal(1024))

    def siglip_text(self, text):
        RECORD["embed"].append({"space": "siglip_text", "text": text})
        return _unit(_rng("siglip_text|" + text).standard_normal(768))

    def img(space):
        def f(self, image):
            key = getattr(image, "info", {}).get("snap_key", "random:0")
            RECORD["embed"].append({"space": space, "image": key})
            kind, *rest = key.split(":")
            if kind == "bank" and image_bank.get(space):
                bank = image_bank[space]
                base = np.array(bank[int(rest[0]) % len(bank)])
                noise = float(rest[1]) if len(rest) > 1 else 0.0
                return _unit(base + noise * _rng(f"{space}|{key}").standard_normal(base.shape[0]))
            return _unit(_rng(f"{space}|{key}").standard_normal(768))
        return f

    RetrieverV4._embed_text = text
    RetrieverV4._embed_siglip_text = siglip_text
    RetrieverV4._embed_vit = img("vit")
    RetrieverV4._embed_siglip = img("siglip")
