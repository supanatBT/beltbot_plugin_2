"""
models_lock.py — สร้าง models.yaml จากแคช HF บนเครื่องที่ผ่านชุดทดสอบแล้ว (28 ต.ค.)

    & $py models_lock.py            # ดูอย่างเดียว ไม่เขียนไฟล์
    & $py models_lock.py --write    # เขียน models.yaml (ไฟล์เดิมสำรองเป็น models.yaml.bak-<เวลา>)

หลัก: ไม่เดา — ใช้ commit ที่ refs/main ในแคชชี้อยู่ ซึ่งคือตัวที่ from_pretrained แบบไม่ระบุ revision
โหลดมาใช้ตอนทดสอบ ถ้าโมเดลไหนไม่มีในแคช หรือหา main ไม่เจอ → ไม่ล็อกตัวนั้นและบอกเหตุผล
ล็อกเองได้ด้วย --rev "<model_id>=<commit 40 ตัว>"

ไม่ต่อเน็ต ไม่ดาวน์โหลดอะไร อ่านแคชอย่างเดียว
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# โมเดลที่บอทโหลดจาก Hub (assistant.py · brands/modutech/image_gate.py) — adapter ViT อยู่ในเครื่อง ล็อกด้วย sha256 ใน brand.yaml แล้ว
MODELS = {
    "jinaai/jina-embeddings-v3": "ข้อความ → เวกเตอร์ (ค้นทั้งสองแบรนด์)",
    "google/siglip-base-patch16-224": "SigLIP ของ retriever Movex",
    "google/siglip-base-patch16-384": "ประตูรูป Modutech (เกณฑ์ 0.65 / 0.8254 ปรับกับรุ่นนี้)",
    "google/vit-base-patch16-224-in21k": "ฐานของ ViT LoRA Movex",
}
# โค้ดของ Jina v3 มาจากรีโปแยก (trust_remote_code) — revision= ของ jina ไม่ล็อกตัวนี้ จดไว้ให้รู้อย่างเดียว
CODE_REPOS = {"jinaai/xlm-roberta-flash-implementation": "โค้ดโมเดลของ Jina v3 (จดไว้ ไม่ได้ล็อก)"}
SHA = re.compile(r"^[0-9a-f]{40}$")


def cached_main(repo_id: str, info) -> tuple[str | None, str]:
    for repo in info.repos:
        if repo.repo_id == repo_id and repo.repo_type == "model":
            mains = [r for r in repo.revisions if "main" in r.refs]
            if mains:
                return mains[0].commit_hash, f"refs/main ({len(repo.revisions)} revision ในแคช)"
            others = ", ".join(r.commit_hash[:10] for r in repo.revisions)
            return None, f"มีในแคชแต่ไม่มี refs/main ({others}) — ระบุเองด้วย --rev"
    return None, "ไม่มีในแคช"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--rev", action="append", default=[], help="<model_id>=<commit> ล็อกเอง (ทับค่าจากแคช)")
    ap.add_argument("-o", default=os.path.join(BASE, "models.yaml"))
    a = ap.parse_args()

    from huggingface_hub import scan_cache_dir
    info = scan_cache_dir()
    manual = {}
    for x in a.rev:
        mid, _, sha = x.partition("=")
        if not SHA.match(sha.strip()):
            print(f"❌ --rev {x}: commit ต้องเป็น 40 ตัว")
            return 2
        manual[mid.strip()] = sha.strip()

    locked, missing = {}, []
    print(f"แคช HF: {len(info.repos)} รีโป · {info.size_on_disk_str}")
    for mid, role in {**MODELS, **CODE_REPOS}.items():
        sha, why = (manual[mid], "--rev") if mid in manual else cached_main(mid, info)
        mark = "✅" if sha else "⚠️"
        print(f"{mark} {mid}: {sha or '-'}  · {why}  · {role}")
        if mid in MODELS:
            (locked.__setitem__(mid, (sha, role)) if sha else missing.append(mid))

    if missing:
        print(f"\n⚠️ ไม่ล็อก {len(missing)} ตัว: {', '.join(missing)} — ตัวนั้นจะโหลด main ตามเดิม")
    if not a.write:
        print("\n(ดูอย่างเดียว — ใส่ --write เพื่อเขียน models.yaml)")
        return 0
    if os.path.exists(a.o):
        bak = f"{a.o}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(a.o, bak)
        print(f"สำรองไฟล์เดิม → {os.path.basename(bak)}")
    lines = [f"# สร้างด้วย models_lock.py {time.strftime('%Y-%m-%d %H:%M')} จากแคช HF บนเครื่องที่ผ่านชุดทดสอบ",
             "# เปลี่ยนโมเดลตัวไหน = ต้องรันชุดทดสอบใหม่ · เปลี่ยน SigLIP-384 = ต้องปรับเกณฑ์ประตูใหม่ด้วย brand_calibration_rows.csv",
             "models:"]
    for mid, (sha, role) in locked.items():
        lines += [f"  {mid}:", f"    revision: {sha}", f"    role: \"{role}\""]
    with open(a.o, "w", encoding="utf-8", newline="\n") as f:          # UTF-8 ไม่มี BOM
        f.write("\n".join(lines) + "\n")
    from core import model_lock
    model_lock.load(a.o)                                                # ตรวจว่าอ่านกลับได้
    print(f"✅ เขียน {os.path.basename(a.o)} · ล็อก {len(locked)} ตัว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
