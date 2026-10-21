"""
training/train_vit.py — เทรน ViT LoRA ของหนึ่งแบรนด์ แล้ว log ครบสี่อย่างเข้า MLflow (HANDOFF ข้อ 5.2)

    # ตรวจชุดข้อมูล + log params/tags/จำนวนรูปต่อคลาส โดยไม่เทรน (ไม่ต้องมี torch)
    python training/train_vit.py --brand movex --data <โฟลเดอร์รูป> --dry-run

    # เทรนจริง (เครื่องที่มี torch + transformers + peft)
    python training/train_vit.py --brand movex --data <โฟลเดอร์รูป> --epochs 10

ผังชุดข้อมูล: <data>/<ชื่อคลาส>/*.jpg|png|jpeg   (ชื่อคลาสตรงกับ label_mapping.json เดิม เช่น movex_chain_LF820_K325)
--groups visual_groups.json  รวมคลาสที่มองด้วยตาแยกไม่ออก {"ชื่อกลุ่ม": ["คลาส", ...]} — ห้ามรวมตามเกรดวัสดุหรือสภาวะเปียก

สี่อย่างที่ log ทุกรอบ
  params     brand · base · lora r/alpha · lr · epochs · ขนาดภาพ · การรวมกลุ่ม · test split · seed
  metrics    จำนวนรูปต่อคลาส · accuracy ชุดทดสอบ · accuracy รายคลาส                       (สองตัวหลังเฉพาะเทรนจริง)
  artifacts  labels.json · dataset_manifest.json · adapter · confusion_matrix.csv · eval_report.json
  tags       commit · วันที่ · dataset_hash (hash ของรายการรูป + เนื้อไฟล์) · โฟลเดอร์ข้อมูล

thresholds.json — **ไฟล์นี้ไม่เขียน** และบอกเหตุผลไว้ใน eval_report.json
  เกณฑ์ที่ฝั่งเสิร์ฟใช้ (answer/series ใน brands/<key>/thresholds.json) ใช้กับ confidence ของ
  ViTSignal ซึ่ง RetrieverV4 คิดจากความคล้ายของเวกเตอร์รูปใน collection — ไม่ใช่ softmax ของหัวจำแนก
  ปรับเกณฑ์จาก softmax จะได้ตัวเลขคนละสเกล ต้องทำหลังสร้าง collection ใหม่ด้วย adapter ตัวนี้ (ยังไม่มีสคริปต์)

ขึ้นใช้งาน: push adapter ขึ้น HF Hub พร้อม tag → ใส่ tag ใน brand.yaml › image.vit.revision
MLflow เป็นสมุดบันทึกการทดลอง ไม่ใช่ทางที่ระบบไปหยิบโมเดล — ไม่มีขั้นไหนในนี้แก้ brand.yaml ให้เอง
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MLRUNS = HERE / "mlruns"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
TARGET_MODULES = ["key", "value", "output.dense", "dense", "intermediate.dense", "query"]  # เท่า adapter เดิม

THRESHOLDS_NOT_WRITTEN = (
    "ไม่เขียน thresholds.json: เกณฑ์ฝั่งเสิร์ฟใช้ confidence ของ ViTSignal จาก RetrieverV4 "
    "(ความคล้ายของเวกเตอร์รูปใน collection) ไม่ใช่ softmax ของหัวจำแนก — ต้องปรับเกณฑ์หลังสร้าง "
    "collection ใหม่ด้วย adapter ตัวนี้ บนสเกลเดียวกับที่ระบบใช้จริง")


# ─────────────────────────── ชุดข้อมูล ───────────────────────────

def scan(data_dir: Path, groups: dict | None) -> tuple[list[str], list[tuple[str, str]], dict]:
    """คืน (labels เรียงชื่อ, [(พาธ, label)], manifest) — manifest ใช้ทำ dataset_hash"""
    if not data_dir.is_dir():
        sys.exit(f"ไม่พบโฟลเดอร์ข้อมูล {data_dir}")
    to_group = {c: g for g, members in (groups or {}).items() for c in members}
    items, manifest = [], []
    for cls_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        label = to_group.get(cls_dir.name, cls_dir.name)
        for f in sorted(cls_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in IMG_EXT:
                items.append((str(f), label))
                manifest.append({"class_dir": cls_dir.name, "label": label,
                                 "file": str(f.relative_to(data_dir)).replace(os.sep, "/"),
                                 "sha256": hashlib.sha256(f.read_bytes()).hexdigest()[:16]})
    if not items:
        sys.exit(f"ไม่พบรูปใน {data_dir} (ต้องเป็น <data>/<คลาส>/*.jpg)")
    unknown = sorted(set(to_group) - {m["class_dir"] for m in manifest})
    if unknown:
        sys.exit(f"visual_groups อ้างคลาสที่ไม่มีในชุดข้อมูล: {unknown}")
    labels = sorted({lab for _, lab in items})
    h = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return labels, items, {"dataset_hash": h, "files": manifest}


def split(items, test_ratio: float, seed: int):
    """แบ่งรายคลาส — ทุกคลาสมีรูปในชุดทดสอบถ้ามีมากกว่า 1 รูป"""
    by = defaultdict(list)
    for it in items:
        by[it[1]].append(it)
    rng = random.Random(seed)
    train, test = [], []
    for lab, xs in sorted(by.items()):
        xs = xs[:]
        rng.shuffle(xs)
        k = max(1, round(len(xs) * test_ratio)) if len(xs) > 1 else 0
        test += xs[:k]
        train += xs[k:]
    return train, test


def labels_json(labels: list[str]) -> dict:
    return {"id2label": {str(i): l for i, l in enumerate(labels)},
            "label2id": {l: str(i) for i, l in enumerate(labels)}}


# ─────────────────────────── เทรนจริง ───────────────────────────

def train_and_eval(a, labels, train_items, test_items, out_dir: Path) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from peft import LoraConfig, get_peft_model
    from transformers import ViTForImageClassification, ViTImageProcessor

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    lid = {l: i for i, l in enumerate(labels)}
    proc = ViTImageProcessor.from_pretrained(a.base, size={"height": a.img_size, "width": a.img_size})
    base = ViTForImageClassification.from_pretrained(a.base, num_labels=len(labels),
                                                     id2label={i: l for l, i in lid.items()}, label2id=lid)
    model = get_peft_model(base, LoraConfig(r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=0.1,
                                            target_modules=TARGET_MODULES, modules_to_save=["classifier"]))
    model.to(dev)

    def batches(items, shuffle):
        xs = items[:]
        if shuffle:
            random.Random(a.seed).shuffle(xs)
        for i in range(0, len(xs), a.batch):
            chunk = xs[i:i + a.batch]
            imgs = [Image.open(p).convert("RGB") for p, _ in chunk]
            x = proc(images=imgs, return_tensors="pt")["pixel_values"].to(dev)
            y = torch.tensor([lid[l] for _, l in chunk], device=dev)
            yield x, y

    import mlflow
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    for ep in range(a.epochs):
        model.train()
        tot, n = 0.0, 0
        for x, y in batches(train_items, True):
            loss = model(pixel_values=x, labels=y).loss
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot, n = tot + float(loss) * len(y), n + len(y)
        mlflow.log_metric("train_loss", tot / max(n, 1), step=ep)

    model.eval()
    cm = np.zeros((len(labels), len(labels)), dtype=int)
    with torch.no_grad():
        for x, y in batches(test_items, False):
            pred = model(pixel_values=x).logits.argmax(-1)
            for t, p in zip(y.tolist(), pred.tolist()):
                cm[t, p] += 1
    acc = float(np.trace(cm) / cm.sum()) if cm.sum() else 0.0
    per_class = {labels[i]: (float(cm[i, i] / cm[i].sum()) if cm[i].sum() else None) for i in range(len(labels))}

    adapter_dir = out_dir / "adapter"
    model.save_pretrained(adapter_dir)
    (adapter_dir / "label_mapping.json").write_text(json.dumps(labels_json(labels), ensure_ascii=False, indent=4),
                                                    encoding="utf-8")
    with open(out_dir / "confusion_matrix.csv", "w", encoding="utf-8") as f:
        f.write("true\\pred," + ",".join(labels) + "\n")
        for i, l in enumerate(labels):
            f.write(l + "," + ",".join(str(v) for v in cm[i]) + "\n")
    return {"test_accuracy": acc, "per_class_accuracy": per_class, "test_images": int(cm.sum()),
            "adapter_dir": str(adapter_dir)}


# ─────────────────────────── main ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--brand", required=True)
    ap.add_argument("--data", required=True, help="<data>/<คลาส>/*.jpg")
    ap.add_argument("--groups", help="visual_groups.json (ไม่บังคับ)")
    ap.add_argument("--base", default="google/vit-base-patch16-224-in21k")
    ap.add_argument("--lora-r", type=int, default=64)          # เท่า adapter_config เดิม
    ap.add_argument("--lora-alpha", type=int, default=128)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--img-size", type=int, default=224)
    ap.add_argument("--test-split", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--dry-run", action="store_true", help="ตรวจข้อมูลและ log params/tags/จำนวนรูป ไม่เทรน")
    a = ap.parse_args()

    groups = json.loads(Path(a.groups).read_text(encoding="utf-8")) if a.groups else None
    data_dir = Path(a.data).resolve()
    labels, items, manifest = scan(data_dir, groups)
    train_items, test_items = split(items, a.test_split, a.seed)
    counts = Counter(l for _, l in items)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(a.out) / f"{a.brand}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "labels.json").write_text(json.dumps(labels_json(labels), ensure_ascii=False, indent=4), encoding="utf-8")
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"ชุดข้อมูล {data_dir}")
    print(f"  {len(labels)} คลาส · {len(items)} รูป (train {len(train_items)} · test {len(test_items)}) · "
          f"dataset_hash {manifest['dataset_hash']}")
    thin = [l for l, n in counts.items() if n < 5]
    if thin:
        print(f"  ⚠ {len(thin)} คลาสมีรูปน้อยกว่า 5 — accuracy รายคลาสของคลาสพวกนี้เชื่อไม่ได้: {thin[:5]}")

    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    import mlflow
    mlflow.set_tracking_uri(MLRUNS.as_uri())
    mlflow.set_experiment(f"vit-{a.brand}")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    with mlflow.start_run(run_name=f"{a.brand}-{stamp}{'-dry' if a.dry_run else ''}") as run:
        mlflow.log_params({"brand": a.brand, "base": a.base, "lora_r": a.lora_r, "lora_alpha": a.lora_alpha,
                           "lr": a.lr, "epochs": a.epochs, "batch": a.batch, "img_size": a.img_size,
                           "test_split": a.test_split, "seed": a.seed, "num_labels": len(labels),
                           "groups": json.dumps(groups, ensure_ascii=False) if groups else "none",
                           "target_modules": ",".join(TARGET_MODULES)})
        mlflow.set_tags({"commit": commit, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "dataset_hash": manifest["dataset_hash"], "data_dir": str(data_dir),
                         "dry_run": str(a.dry_run)})
        for lab, n in counts.items():
            mlflow.log_metric(f"images.{lab}", n)
        mlflow.log_metric("images.total", len(items))
        mlflow.log_artifact(str(out_dir / "labels.json"))
        mlflow.log_artifact(str(out_dir / "dataset_manifest.json"))

        report = {"brand": a.brand, "labels": labels, "dataset_hash": manifest["dataset_hash"],
                  "train_images": len(train_items), "test_images": len(test_items),
                  "thresholds": THRESHOLDS_NOT_WRITTEN, "dry_run": a.dry_run, "mlflow_run": run.info.run_id}
        if not a.dry_run:
            res = train_and_eval(a, labels, train_items, test_items, out_dir)
            mlflow.log_metric("test_accuracy", res["test_accuracy"])
            for lab, v in res["per_class_accuracy"].items():
                if v is not None:
                    mlflow.log_metric(f"acc.{lab}", v)
            mlflow.log_artifacts(res["adapter_dir"], artifact_path="adapter")
            mlflow.log_artifact(str(out_dir / "confusion_matrix.csv"))
            report.update(res)
        (out_dir / "eval_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        mlflow.log_artifact(str(out_dir / "eval_report.json"))
        print(f"  → MLflow experiment vit-{a.brand} run {run.info.run_id[:8]} · ผลอยู่ที่ {out_dir}")
    if not a.dry_run:
        print("\nขึ้นใช้งาน (ทำมือ ตั้งใจไม่ทำอัตโนมัติ):\n"
              "  1. push adapter ขึ้น HF Hub พร้อม tag เวอร์ชัน\n"
              f"  2. brands/{a.brand}/brand.yaml › image.vit.adapter = <repo> · revision = <tag> · labels = labels.json ใหม่\n"
              "  3. สร้าง collection รูปใหม่ด้วย adapter นี้ แล้วปรับ thresholds.json บนสเกล ViTSignal\n"
              "  4. รัน training/run_gates.py — core/models.py จะหยุดถ้า labels ไม่ตรง checkpoint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
