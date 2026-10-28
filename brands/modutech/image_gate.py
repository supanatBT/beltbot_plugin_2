"""
brands/modutech/image_gate.py — ประตูรูปของ Modutech (claude/PLAN_image_brand_ask.md)

ไม่ใช่ตัวให้คะแนนรูป (ImageScorer): ไม่บอกรุ่น ไม่บอกกลุ่มผิว — หลักฐานยังไม่พอ (RESULTS_field_eval.md)
ตอบแค่สองคำถาม
    product_like  รูปนี้หน้าตาเป็นสายพาน/โซ่/สเตอร์ หรือไม่     → ไม่ใช่ = ปฏิเสธรูปทันที
    direct        มั่นใจพอให้ไป Modutech โดยไม่ต้องถามแบรนด์     → ใช่ = ไม่ถาม

ตัวเลขสองตัว (คำนวณแบบเดียวกับ 21_image_eval/05_brand_calibration.py ทุกขั้น)
    score        cosine ดิบสูงสุดของ SigLIP base-patch16-384 (ภาพเต็ม · 70% · 45% กลางภาพ)
                 เทียบแกลเลอรี modutech_images 204 จุด (เก็บเป็นไฟล์ ไม่เปิด Qdrant)
    text_margin  ภาพเต็มใกล้ข้อความฝั่งสายพานที่สุด ลบ ฝั่งของอื่นที่สุด (ต้นแบบข้อความเก็บในไฟล์เดียวกัน)

เกณฑ์ (brand.yaml › image_gate) วัด 2026-10-25 · รูป Modutech 247 · Movex 72 · ไม่ใช่สายพาน 30
    product_like = score ≥ 0.65 และ text_margin ≥ −0.02
    direct       = product_like และ score ≥ 0.8254   (= คะแนน Movex สูงสุดฝั่ง cal + 0.005 · ตั้งก่อนเห็นผล)

ไฟล์ image_gate.npz สร้างด้วย 21_image_eval/06_export_gate.py (อ่านแกลเลอรีแบบอ่านอย่างเดียว)
ไม่มีไฟล์ หรือไฟล์ไม่ตรงโมเดล = ปิดประตู + เตือน · บอททำงานต่อ (รูปไม่ระบุแบรนด์ = ถามแบรนด์)
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np
from PIL import Image, ImageChops, ImageOps

from core.image_policy import GateReading

SIZE = 384
VIEW_SCALES = (1.00, 0.70, 0.45)
FILE_KEYS = ("G", "belt_P", "other_P", "meta")


class GateFileError(ValueError):
    pass


# ── ปรับรูป: คัดลอกตรงจาก 21_image_eval/imgeval/normalize.py (= 16_image_processing/prepare_dataset.normalize) ──

def normalize_image(im, size=SIZE):
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bg = Image.new('RGB', im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel('A'))
        im = bg
    else:
        im = im.convert('RGB')

    g = im.convert('L')
    box = ImageChops.difference(g, Image.new('L', g.size, 255)) \
        .point(lambda p: 255 if p > 10 else 0).getbbox()
    if box:
        im = im.crop(box)

    side = max(im.size)
    sq = Image.new('RGB', (side, side), (255, 255, 255))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return sq.resize((size, size), Image.LANCZOS)


def center_views(im, scales=VIEW_SCALES):
    w, h = im.size
    out = []
    for f in scales:
        if f >= 1.0:
            out.append(im)
        else:
            cw, ch = int(w * f), int(h * f)
            out.append(im.crop(((w - cw) // 2, (h - ch) // 2,
                                (w + cw) // 2, (h + ch) // 2)).resize((w, h)))
    return out


def prepare(image) -> list:
    """รูปจากหน้าเว็บ → สามมุมมองขนาด 384 (หมุนตาม EXIF ก่อน เหมือน open_oriented)"""
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:                                    # noqa: BLE001 — รูปไม่มี EXIF ที่อ่านได้
        pass
    return center_views(normalize_image(image))


# ── ข้อมูลประตู ──

@dataclass
class GateData:
    G: np.ndarray                 # แกลเลอรี (n × d) normalize แล้ว
    belt_P: np.ndarray            # ต้นแบบข้อความฝั่งสายพาน (k × d)
    other_P: np.ndarray           # ต้นแบบข้อความฝั่งของอื่น (m × d)
    other_names: list
    meta: dict

    @classmethod
    def load(cls, path: str, model_id: str) -> "GateData":
        if not os.path.isfile(path):
            raise GateFileError(f"ไม่พบ {path} — สร้างด้วย 21_image_eval/06_export_gate.py")
        z = np.load(path, allow_pickle=False)
        missing = [k for k in FILE_KEYS if k not in z.files]
        if missing:
            raise GateFileError(f"{path} ขาด {missing}")
        meta = json.loads(str(z["meta"]))
        if meta.get("model") != model_id:
            raise GateFileError(f"{path} สร้างจาก {meta.get('model')} แต่ brand.yaml ใช้ {model_id}")
        G, B, O = (np.asarray(z[k], dtype=np.float32) for k in ("G", "belt_P", "other_P"))
        if not (G.shape[1] == B.shape[1] == O.shape[1]):
            raise GateFileError(f"{path} มิติไม่ตรงกัน {G.shape} {B.shape} {O.shape}")
        if meta.get("G_sha256") and meta["G_sha256"] != _sha(z["G"]):
            raise GateFileError(f"{path} แกลเลอรีไม่ตรงลายนิ้วมือใน meta")
        names = list(meta.get("other_names") or [str(i) for i in range(len(O))])
        return cls(G, B, O, names, meta)


def _sha(a) -> str:
    return "sha256:" + hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


@dataclass(frozen=True)
class GateThresholds:
    not_product_score: float = 0.65
    not_product_text: float = -0.02
    direct_score: float = 0.8254

    @classmethod
    def from_cfg(cls, cfg: dict) -> "GateThresholds":
        d = cls()
        return cls(float(cfg.get("not_product_score", d.not_product_score)),
                   float(cfg.get("not_product_text", d.not_product_text)),
                   float(cfg.get("direct_score", d.direct_score)))


class ModutechImageGate:
    """embed(list[PIL 384]) → np.ndarray (n × d) normalize แล้ว — ตัวจริงคือ siglip_embedder()"""

    def __init__(self, brand: str, data: GateData, embed: Callable[[Sequence], np.ndarray],
                 th: GateThresholds = GateThresholds()):
        self.brand, self.data, self.embed, self.th = brand, data, embed, th

    def measure(self, image) -> tuple[float, float, str]:
        V = np.asarray(self.embed(prepare(image)), dtype=np.float32)
        score = float((V @ self.data.G.T).max())
        full = V[0]                                       # VIEW_SCALES[0] = ภาพเต็ม
        b, o = self.data.belt_P @ full, self.data.other_P @ full
        return score, float(b.max() - o.max()), self.data.other_names[int(o.argmax())]

    def read(self, image) -> GateReading:
        score, margin, near = self.measure(image)
        th = self.th
        product_like = score >= th.not_product_score and margin >= th.not_product_text
        direct = product_like and score >= th.direct_score
        return GateReading(self.brand, product_like, direct,
                           {"score": round(score, 4), "text": round(margin, 4), "near": near})


def siglip_embedder(model_id: str, device: str) -> Callable[[Sequence], np.ndarray]:
    """ส่วนภาพของ SigLIP อย่างเดียว (ไม่โหลดส่วนข้อความ — ต้นแบบข้อความอยู่ในไฟล์แล้ว) · fp32 ทุกอุปกรณ์

    SiglipModel.get_image_features = vision_model(...).pooler_output → ได้เวกเตอร์เดียวกับ
    21_image_eval/imgeval/embed.py::SiglipEmbedder · 06_export_gate.py ตรวจตัวเลขเทียบ 05 ทุกครั้งที่ส่งออก
    """
    import torch
    from transformers import AutoProcessor, SiglipVisionModel
    from core import model_lock                       # 28 ต.ค.: revision จาก models.yaml (ไม่มี = เท่าเดิม)
    proc = AutoProcessor.from_pretrained(model_id, **model_lock.pin(model_id))
    model = SiglipVisionModel.from_pretrained(model_id, **model_lock.pin(model_id)).eval().to(device)
    model_lock.note(model_id, model)

    def embed(imgs):
        with torch.no_grad():
            inp = proc(images=list(imgs), return_tensors="pt").to(device)
            f = model(pixel_values=inp["pixel_values"]).pooler_output
            return torch.nn.functional.normalize(f, dim=-1).float().cpu().numpy()
    return embed


def load_gate(brand: str, brand_dir: str, cfg: Optional[dict], device: str,
              embed_factory=siglip_embedder) -> tuple[Optional[ModutechImageGate], str]:
    """คืน (ประตู หรือ None, เหตุผล) — ไม่ยกข้อผิดพลาดออกไป บอทต้องสตาร์ตได้เสมอ"""
    cfg = cfg or {}
    if cfg.get("enabled") is False:
        return None, "ปิดใน brand.yaml"
    model_id = cfg.get("model") or "google/siglip-base-patch16-384"
    rel = cfg.get("file") or "image_gate.npz"
    path = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(brand_dir, rel))
    try:
        data = GateData.load(path, model_id)
    except GateFileError as e:
        return None, str(e)
    try:
        embed = embed_factory(model_id, device)
    except Exception as e:                               # noqa: BLE001
        return None, f"โหลด {model_id} ไม่ได้ ({type(e).__name__}: {e})"
    th = GateThresholds.from_cfg(cfg)
    return (ModutechImageGate(brand, data, embed, th),
            f"{model_id} · แกลเลอรี {len(data.G)} จุด · เกณฑ์ {th}")
