"""
test_ops_monitoring.py — ชั้น monitor / ขยาย (28 ต.ค.) · ไม่โหลดโมเดลจริง

    python test_ops_monitoring.py

  1. core/metrics: ฟิลด์ที่ไม่อนุญาตถูกทิ้ง · ข้อความยาวถูกตัด · session เป็นแฮช
  2. METRIC จากเทิร์นจริงของ TurnEngine (รัน test_image_turns.py) — ไม่มีอักษรไทยสักตัว = ไม่มีข้อความลูกค้า/คำตอบ
  3. app: /health มี versions · /health/detail ต้องมี secret · ทุกคำขอ /api/chat มี METRIC src=api (รวมที่ถูกปฏิเสธ)
  4. core/model_lock: ไม่มีไฟล์ = {} (เท่าเดิม) · revision ไม่ใช่ commit = หยุด · pin/status
  5. resolve_collection: alias มี → ใช้ alias · ไม่มี → ชื่อสำรอง · Qdrant แบบไฟล์จริง
  6. qdrant_alias.py: ปฏิเสธ Movex · สำรอง meta.json · สลับ/ย้อนกลับ · โครงเวกเตอร์ไม่ตรง = ไม่สลับ
  7. metrics_report: อ่าน log ปน · SSE ของ HF · ตัดบรรทัดซ้ำ · นับ policy / rate limit
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["METRICS_LOG"] = "1"

from core import metrics as M  # noqa: E402

PASS = FAIL = 0
THAI = re.compile(r"[\u0E00-\u0E7F]")


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  — {detail}")


# ── 1 ──
print("1. core/metrics")
r = M.record({"src": "turn", "text": "ลูกค้าถาม HC508", "reply": "x", "ip": "1.2.3.4", "brand": "modutech",
              "err": "E" * 200, "gate": {"modutech": {"score": 0.812345678, "direct": False}}, "vit": [1, 2]})
ok("ทิ้ง text/reply/ip", not ({"text", "reply", "ip"} & set(r)), r)
ok("ตัดข้อความยาว ≤ 40", len(r["err"]) == 40)
ok("ปัดทศนิยม 4 ตำแหน่ง", r["gate"]["modutech"]["score"] == 0.8123)
ok("list ไม่พิมพ์", r["vit"] is None)
ok("มีเวลา", "at" in r)
t1, t2 = M.session_tag("sess-abc"), M.session_tag("sess-abc")
ok("แฮช session คงที่ใน process เดียว และไม่ใช่ id เดิม", t1 == t2 and "sess" not in t1 and len(t1) == 10)
ok("session ว่าง = ว่าง", M.session_tag("") == "")
ok("parse_line อ่านบรรทัดที่มีคำนำหน้า log", M.parse_line('2026-10-28 INFO x: METRIC {"src":"api"}') == {"src": "api"})
ok("parse_line ข้ามบรรทัดอื่น", M.parse_line("IMGLOG {}") is None)
ok("token_fields", M.token_fields({"prompt_token_count": 10, "total_token_count": 15, "x": 1}) == {"in": 10, "total": 15})

# ── 2 ──
print("2. METRIC จาก TurnEngine (test_image_turns.py)")
env = dict(os.environ, METRICS_LOG="1", PYTHONIOENCODING="utf-8")
env.pop("IMAGE_TEST_LOG", None)
p = subprocess.run([sys.executable, os.path.join(ROOT, "test_image_turns.py")], cwd=ROOT, env=env,
                   capture_output=True, text=True, encoding="utf-8")
lines = [ln for ln in p.stdout.splitlines() if "METRIC " in ln]
recs = [M.parse_line(ln) for ln in lines]
ok("test_image_turns ผ่าน (exit 0)", p.returncode == 0, p.stdout[-400:] + p.stderr[-400:])
ok("มี METRIC จากเทิร์น", len(recs) >= 50, len(recs))
ok("อ่านกลับได้ทุกบรรทัด", all(isinstance(x, dict) for x in recs))
ok("ทุกฟิลด์อยู่ในรายชื่อที่อนุญาต", all(set(x) <= M.ALLOWED for x in recs if x))
thai = [ln for ln in lines if THAI.search(ln.split("METRIC ", 1)[1])]
ok("ไม่มีอักษรไทยใน METRIC สักบรรทัด (ไม่มีข้อความลูกค้า/คำตอบ)", not thai, thai[:2])
img = [x for x in recs if x and x.get("image")]
ok("เทิร์นรูปมี policy", img and all(x.get("policy") for x in img), img[:1])
ok("มีคะแนนประตูในบางเทิร์นรูป", any("gate" in x for x in img))
ok("มีเทิร์นที่ตอบไม่สำเร็จถูกนับ status=error", any(x.get("status") == "error" and x.get("err") for x in recs if x))
ok("เทิร์นที่เรียก LLM มี ms_llm", any(isinstance(x.get("ms_llm"), int) for x in recs if x))
ok("ทุกเทิร์นมี ms_total", all(isinstance(x.get("ms_total"), int) for x in recs if x))

# ── 3 ──
print("3. app: /health · /health/detail · METRIC src=api")
from fastapi.testclient import TestClient  # noqa: E402

import fakebot  # noqa: E402,F401
from app import create_app  # noqa: E402
from webapi.bot import BotAdapter  # noqa: E402


@dataclass
class Cfg:
    bot_module: str = "fakebot"
    session_ttl_s: int = 3600
    max_sessions: int = 100
    rl_per_minute: int = 2
    rl_per_hour: int = 100
    rl_images_per_hour: int = 100
    global_per_day: int = 1000
    media_roots: list = field(default_factory=lambda: ["media"])
    max_concurrent: int = 2
    warm_on_start: bool = False
    allowed_origins: list = field(default_factory=list)
    proxy_secret: str = "s3cret"
    max_text_chars: int = 1000
    max_image_bytes: int = 4 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    image_max_side: int = 1024
    max_turns: int = 40
    queue_wait_s: int = 20
    scrub_internal_ids: bool = True


bot = BotAdapter("fakebot")
bot.load()
c = TestClient(create_app(Cfg(), bot))
H = {"x-proxy-secret": "s3cret"}
h = c.get("/health").json()
ok("/health ฟิลด์เดิมครบ", {"status", "bot_ready", "sessions"} <= set(h), h)
ok("/health มี versions (ฟิลด์เพิ่ม)", isinstance(h.get("versions"), dict), h)
ok("/health ไม่มีพาธเซิร์ฟเวอร์", ROOT not in json.dumps(h, ensure_ascii=False))
ok("/health/detail ไม่มี secret = 403", c.get("/health/detail").status_code == 403)
d = c.get("/health/detail", headers=H)
ok("/health/detail มี secret = 200 + models/brands", d.status_code == 200 and {"models", "brands"} <= set(d.json()), d.text[:200])
ok("/health/detail ไม่มีพาธเซิร์ฟเวอร์", ROOT not in d.text and "\\\\" not in d.text)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    codes = [c.post("/api/chat", data={"text": f"q{i}"}, headers=H).status_code for i in range(3)]
    c.post("/api/chat", data={"text": ""}, headers=H)
api = [M.parse_line(ln) for ln in buf.getvalue().splitlines() if "METRIC " in ln]
api = [x for x in api if x and x.get("src") == "api"]
ok("ส่ง 3 ครั้ง (จำกัด 2/นาที) → 200 200 429", codes == [200, 200, 429], codes)
ok("METRIC src=api ครบ 4 คำขอ", len(api) == 4, api)
ok("นับ rate limit ได้", any(x.get("code") == "per_minute" and x.get("http") == 429 for x in api), api)
ok("นับคำขอว่างได้", any(x.get("code") == "empty" for x in api), api)
ok("METRIC api ไม่มี IP/ข้อความ", not any(k in x for x in api for k in ("ip", "text")) and
   "testclient" not in buf.getvalue().split("METRIC", 1)[-1])

# ── 4 ──
print("4. core/model_lock")
from core import model_lock  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    ok("ไม่มีไฟล์ = {}", model_lock.load(os.path.join(td, "none.yaml")) == {})
    bad = os.path.join(td, "bad.yaml")
    open(bad, "w", encoding="utf-8").write("models:\n  a/b:\n    revision: main\n")
    try:
        model_lock.load(bad)
        ok("revision ลอย (main) = หยุด", False)
    except model_lock.ModelLockError:
        ok("revision ลอย (main) = หยุด", True)
    good = os.path.join(td, "models.yaml")
    sha = "a" * 40
    open(good, "w", encoding="utf-8").write(f"models:\n  a/b:\n    revision: {sha}\n")
    old_env, old_cache = os.environ.get("MODELS_LOCK"), model_lock._cache
    os.environ["MODELS_LOCK"] = good
    model_lock._cache = None
    ok("pin ตัวที่ล็อก", model_lock.pin("a/b") == {"revision": sha})
    ok("pin ตัวที่ไม่ล็อก = {}", model_lock.pin("c/d") == {})

    class _C:
        _commit_hash = sha

    class _Mdl:
        config = _C()
    model_lock.LOADED.clear()
    model_lock.note("a/b", _Mdl())
    ok("status ตรง", model_lock.status()["a/b"]["match"] is True)
    model_lock.LOADED["a/b"] = "b" * 40
    ok("status ไม่ตรง = False", model_lock.status()["a/b"]["match"] is False)
    cache = os.path.join(td, "hub")
    snap = os.path.join(cache, "models--g--sig", "snapshots", "e" * 40)
    os.makedirs(snap)
    os.makedirs(os.path.join(cache, "models--g--sig", "refs"))
    open(os.path.join(cache, "models--g--sig", "refs", "main"), "w").write("e" * 40)
    open(os.path.join(snap, "config.json"), "w").write("{}")
    ok("commit จากแคช เมื่อ config ไม่มี _commit_hash (SigLIP vision)",
       model_lock.commit_from_cache("g/sig", None, cache) == "e" * 40)
    ok("commit จากแคช: ไม่มีรีโป = None", model_lock.commit_from_cache("g/none", None, cache) is None)
    model_lock.LOADED.clear()
    model_lock._cache = old_cache
    if old_env is None:
        os.environ.pop("MODELS_LOCK", None)
    else:
        os.environ["MODELS_LOCK"] = old_env

# ── 5 / 6 ──
print("5–6. alias ของ Qdrant (ไฟล์จริงในโฟลเดอร์ชั่วคราว)")
from qdrant_client import QdrantClient, models as QM  # noqa: E402

from brands.modutech.plugin import resolve_collection  # noqa: E402
import qdrant_alias as QA  # noqa: E402


def make_db(path, cols):
    cl = QdrantClient(path=path)
    for name, dim in cols.items():
        cl.create_collection(name, vectors_config={"jina": QM.VectorParams(size=dim, distance=QM.Distance.COSINE)})
        cl.upsert(name, [QM.PointStruct(id=i, vector={"jina": [1.0] + [0.0] * (dim - 1)}) for i in range(3)])
    cl.close()


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


with tempfile.TemporaryDirectory() as td:
    db = os.path.join(td, "qdrant_modutech_db")
    make_db(db, {"modutech_belt_chunks": 4, "modutech_belt_chunks_v31": 4, "modutech_wrong": 8})
    r0 = quiet(resolve_collection, db, "modutech_live", "modutech_belt_chunks")
    ok("ยังไม่มี alias → ชื่อสำรอง (เท่าเดิม)", r0 == {"name": "modutech_belt_chunks", "target": "modutech_belt_chunks",
                                                    "via": "fallback"}, r0)
    ok("ไม่มีโฟลเดอร์ → ชื่อสำรอง", quiet(resolve_collection, os.path.join(td, "nope"), "modutech_live", "x")["name"] == "x")
    ok("ปฏิเสธโฟลเดอร์ qdrant_db ของ Movex", QA._refuse_movex(os.path.join(td, "qdrant_db")) is not None)
    ok("ปฏิเสธชื่อ movex_*", quiet(QA.set_alias, db, "modutech_live", "movex_text_chunks") == 2)
    ok("collection ไม่มี = ไม่ตั้ง", quiet(QA.set_alias, db, "modutech_live", "ไม่มี") == 2)
    ok("ตั้ง alias ครั้งแรก", quiet(QA.set_alias, db, "modutech_live", "modutech_belt_chunks") == 0)
    baks = [f for f in os.listdir(db) if f.startswith("meta.json.bak-")]
    ok("สำรอง meta.json ก่อนเขียน", len(baks) == 1, os.listdir(db))
    r1 = quiet(resolve_collection, db, "modutech_live", "modutech_belt_chunks")
    ok("มี alias → ใช้ alias", r1 == {"name": "modutech_live", "target": "modutech_belt_chunks", "via": "alias"}, r1)
    cl = QdrantClient(path=db)
    hits = cl.query_points("modutech_live", query=[1.0, 0, 0, 0], using="jina", limit=5).points
    cl.close()
    ok("ค้นผ่าน alias ได้แบบเดียวกับ retriever", len(hits) == 3)
    ok("โครงเวกเตอร์ไม่ตรง = ไม่สลับ", quiet(QA.set_alias, db, "modutech_live", "modutech_wrong") == 2)
    ok("สลับไป v31", quiet(QA.set_alias, db, "modutech_live", "modutech_belt_chunks_v31") == 0
       and quiet(resolve_collection, db, "modutech_live", "x")["target"] == "modutech_belt_chunks_v31")
    ok("ย้อนกลับ", quiet(QA.set_alias, db, "modutech_live", "modutech_belt_chunks") == 0
       and quiet(resolve_collection, db, "modutech_live", "x")["target"] == "modutech_belt_chunks")
    cl = QdrantClient(path=db)
    counts = {x.name: cl.get_collection(x.name).points_count for x in cl.get_collections().collections}
    cl.close()
    ok("ไม่มี collection ไหนถูกแก้/ลบ", counts == {"modutech_belt_chunks": 3, "modutech_belt_chunks_v31": 3,
                                                  "modutech_wrong": 3}, counts)

# ── 7 ──
print("7. metrics_report")
import metrics_report as MR  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    lg = os.path.join(td, "space.txt")
    t = '{"src":"turn","at":"2026-10-28T10:00:00","s":"aa","image":true,"policy":"%s","ms_total":%d,"ms_llm":%d,' \
        '"gate":{"modutech":{"score":0.8}},"tokens":{"total":100}}'
    rows = ["INFO junk", "METRIC " + t % ("direct", 3000, 2000), "METRIC " + t % ("direct", 3000, 2000),
            "METRIC " + t % ("ask", 5000, 1000),
            "data: " + json.dumps({"data": 'METRIC {"src":"api","at":"2026-10-28T10:01:00","code":"per_minute","http":429}'}),
            'METRIC {"src":"api","at":"2026-10-28T10:02:00","code":"ok","http":200}']
    open(lg, "w", encoding="utf-8").write("\n".join(rows))
    recs = MR.read([lg])
    ok("ตัดบรรทัดซ้ำ + อ่าน SSE", len(recs) == 4, recs)
    s = MR.summarize(recs)[0]
    ok("นับ policy", s["policy_direct"] == 1 and s["policy_ask"] == 1, s)
    ok("นับ rate limit", s["api_rate_limited"] == 1 and s["api_requests"] == 2, s)
    ok("p95 / ก่อน LLM", s["p95_total_ms"] == 5000 and s["p95_before_llm_ms"] == 4000, s)
    ok("token ต่อวัน", s["tokens_per_day"] == 200, s)

print(f"\nรวม {PASS}/{PASS + FAIL}")
sys.exit(1 if FAIL else 0)
