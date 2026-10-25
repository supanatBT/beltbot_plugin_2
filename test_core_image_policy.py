"""
test_core_image_policy.py — รูปไม่ระบุแบรนด์ (core/image_policy · core/decide · core/turn · brands/modutech/image_gate)

ไม่โหลดโมเดล: ตัวให้คะแนนรูปและประตูเป็นของปลอมที่คืนตัวเลขตามสั่ง
    1) resolve() ตามลำดับกฎในแผน + ขอบเกณฑ์
    2) Dialogue จริง (ปลั๊กอิน Movex + Modutech จริง) — ถามแบรนด์ · ตอบแบรนด์ · ใช้ผลรูปที่เก็บไว้
    3) TurnEngine — เก็บรูปเทิร์นเดียว · รูปใหม่ล้างของเก่า · ประตูพังไม่ล้ม · ทุกแบรนด์มีตัวให้คะแนน = เหมือนเดิม
    4) image_gate — เกณฑ์ · ไฟล์ผิด = ปิดไม่ล้ม · normalize ตรงกับ 21_image_eval

    python test_core_image_policy.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from brands.modutech.image_gate import (GateData, GateFileError, GateThresholds,  # noqa: E402
                                        ModutechImageGate, load_gate, normalize_image)
from core.image_policy import GateReading, ImageCarry, resolve  # noqa: E402
from core.image_router import ImageRoute  # noqa: E402
from core.protocol import ImageScore, LLMTurn  # noqa: E402

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


BRANDS = ["movex", "modutech"]


def mx(conf, accepted=None, dominant=None):
    accepted = conf >= 0.50 if accepted is None else accepted
    dominant = conf >= 0.85 if dominant is None else dominant
    return ImageScore("movex", conf, accepted, group="880" if accepted else None, dominant=dominant,
                      product_ref="movex_chain_LF880_TAB_K450" if dominant else "")


def route_of(sc):
    if not sc.accepted:
        return ImageRoute(True, ["movex"], sc, {"movex": sc})
    return ImageRoute(False, ["movex"], sc, {"movex": sc})


def gate(score, text, direct_th=0.8254):
    pl = score >= 0.65 and text >= -0.02
    return {"modutech": GateReading("modutech", pl, pl and score >= direct_th, {"score": score, "text": text})}


# ════════════════════════════ 1) resolve ════════════════════════════
print("1) core/image_policy.resolve")
r = resolve(route_of(mx(0.3)), BRANDS, ["movex", "modutech"], {}, [])
ok("ทุกแบรนด์มีตัวให้คะแนน → off (ผลเดิม)", r.kind == "off" and r.route.rejected)

r = resolve(route_of(mx(0.13)), BRANDS, ["movex"], gate(0.582, -0.124), [])
ok("IMG-003 (ViT 0.13 · 0.582 · −0.124) → not_product ปฏิเสธ", r.kind == "not_product" and r.route.rejected
   and r.route.best is None and r.route.image_brands == [])
r = resolve(route_of(mx(0.60)), BRANDS, ["movex"], gate(0.583, -0.036), [])
ok("Telrad (ViT 0.60 · ไม่ dominant) → not_product", r.kind == "not_product")
r = resolve(route_of(mx(0.19)), BRANDS, ["movex"], gate(0.6585, -0.089), [])
ok("meaow (คะแนนผ่าน · ข้อความไม่ผ่าน) → not_product", r.kind == "not_product")
r = resolve(route_of(mx(0.38)), BRANDS, ["movex"], gate(0.766, -0.026), [])
ok("near_ คะแนนสูง 0.766 แต่ข้อความ −0.026 → not_product", r.kind == "not_product")
r = resolve(route_of(mx(0.95)), BRANDS, ["movex"], gate(0.60, -0.05), [])
ok("dominant ชนะประตู (Movex ต้องไม่ถูกปฏิเสธเพิ่ม)", r.kind == "dominant" and not r.route.rejected
   and r.route.image_brands == ["movex"])
r = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.6499, 0.05), [])
ok("ขอบ: คะแนน 0.6499 → not_product", r.kind == "not_product")
r = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.65, -0.02), [])
ok("ขอบ: คะแนน 0.65 ข้อความ −0.02 พอดี → ไม่ปฏิเสธ (ถาม)", r.kind == "ask")

r = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.80, 0.05), ["modutech"])
ok("ข้อความระบุ Modutech → text_brand ไม่ใช้รูป", r.kind == "text_brand" and r.route.image_brands == []
   and not r.route.rejected and r.route.best is None)
r = resolve(route_of(mx(0.30)), BRANDS, ["movex"], gate(0.80, 0.05), ["movex"])
ok("ข้อความระบุ Movex → ผลเดิม (Movex ปฏิเสธเหมือนเดิม)", r.kind == "unchanged" and r.route.rejected)
r = resolve(route_of(mx(0.30)), BRANDS, ["movex"], gate(0.80, 0.05), ["movex", "modutech"])
ok("ข้อความระบุสองแบรนด์ → ผลเดิม", r.kind == "unchanged")
r = resolve(route_of(mx(0.30)), BRANDS, ["movex"], gate(0.50, -0.09), ["modutech"])
ok("ข้อความระบุ Modutech แต่รูปไม่ใช่สินค้า → ยังปฏิเสธ", r.kind == "not_product")

r = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.8254, 0.05), [])
ok("ขอบ direct 0.8254 → ไป Modutech", r.kind == "direct" and r.route.image_brands == ["modutech"]
   and r.route.best is None)
r = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.8253, 0.05), [])
ok("ขอบ direct 0.8253 → ถาม", r.kind == "ask")
r = resolve(route_of(mx(0.87)), BRANDS, ["movex"], gate(0.88, 0.05), [])
ok("dominant + direct → Movex (dominant มาก่อน · เคสผิดแบรนด์ 1/247 ที่ยอมรับ)", r.kind == "dominant")

r = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.79, 0.05), [])
ok("รูปสายพานทั่วไป → ask · ทุกแบรนด์อยู่ใน image_brands", r.kind == "ask" and r.asks_brand
   and r.route.image_brands == BRANDS and not r.route.rejected)
ok("ask เก็บผลเดิมไว้ (original)", r.original is not None and r.original.best.confidence == 0.70)
r = resolve(route_of(mx(0.30)), BRANDS, ["movex"], {}, [])
ok("ไม่มีประตู + Movex ปฏิเสธ → ถามแทนปฏิเสธ (ไม่เดา)", r.kind == "ask" and not r.route.rejected
   and r.original.rejected)

# ════════════════════════════ 2) Dialogue จริง ════════════════════════════
print("\n2) core/decide กับปลั๊กอินจริง")
import dialogue_state as DS  # noqa: E402
from core.decide import Dialogue  # noqa: E402

data = json.load(open(os.path.join(ROOT, "extracted_data_v3_machine_ready.json"), encoding="utf-8"))
real = {p["product_id"]: p for p in data.get("products", []) if "product_id" in p}
cat = DS.Catalogue(os.path.join(ROOT, "modutech_v30_3.json"))
mgr = DS.DialogueManager(real, cat)
core: Dialogue = mgr.core
movex_plugin = mgr.movex_plugin


def decide_with(route, text="", state=None, carry=None, has_image=True):
    core.image_brands = tuple(route.image_brands) if route is not None else core.image_brands
    return core.decide(text, has_image=has_image, image=route.best if route else None,
                       image_rejected=bool(route and route.rejected), state=state, image_carry=carry)


pol = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.79, 0.05), [])
d1 = decide_with(pol.route)
ok("รูปไม่ระบุแบรนด์ → ask แบรนด์ ข้อความ clarify_conflict", d1.action == "ask" and d1.topic == "brand"
   and "Movex" in d1.reply_th and "Modutech" in d1.reply_th, d1.reply_th)
ok("เหตุผลใน log บอกว่าเพราะรูป ไม่ใช่ 'เจอรหัส'", "รูปไม่ระบุแบรนด์" in d1.reason, d1.reason)
ok("สถานะค้าง pending=brand", d1.state.pending == "brand")
carry = ImageCarry("PIL", pol.original.best, pol.original.rejected)

d2 = decide_with(None, "1", d1.state, carry, has_image=False)
ok("ตอบ '1' (Movex) → ใช้ผลรูป ViT 0.70 = รู้ซีรีส์", d2.brand == "movex"
   and (d2.payload or {}).get("image_carried") is True and d2.action != "reject_image", (d2.action, d2.reason))
ok("… เหตุผลมาจาก ViT ของรูปเทิร์นก่อน", "ViT 0.70" in d2.reason, d2.reason)
d2b = decide_with(None, "Movex", d1.state, carry, has_image=False)
ok("ตอบชื่อ 'Movex' ได้ผลเดียวกับ '1'", d2b.brand == "movex" and d2b.reason == d2.reason)
d3 = decide_with(None, "2", d1.state, carry, has_image=False)
ok("ตอบ '2' (Modutech) → ไหลแบบข้อความ ไม่มีผลรูป", d3.brand == "modutech"
   and not (d3.payload or {}).get("image_carried"), (d3.action, d3.payload))
d3b = decide_with(None, "โมดูเทค", d1.state, carry, has_image=False)
ok("ตอบ 'โมดูเทค' → Modutech", d3b.brand == "modutech")

pol_r = resolve(route_of(mx(0.30)), BRANDS, ["movex"], gate(0.79, 0.05), [])
d1r = decide_with(pol_r.route)
carry_r = ImageCarry("PIL", pol_r.original.best, pol_r.original.rejected)
d4 = decide_with(None, "1", d1r.state, carry_r, has_image=False)
ok("Movex ปฏิเสธรูป + ตอบ Movex → reject_image ข้อความของ Movex", d4.action == "reject_image"
   and d4.brand == "movex" and d4.reply_th == movex_plugin.image_reject_th, (d4.action, d4.reply_th[:40]))
ok("… สถานะไม่ค้าง pending", d4.state.pending is None)
d5 = decide_with(None, "2", d1r.state, carry_r, has_image=False)
ok("Movex ปฏิเสธรูป + ตอบ Modutech → ไหลแบบข้อความ", d5.brand == "modutech" and d5.action != "reject_image")

d6 = decide_with(None, "1", d1.state, None, has_image=False)
ok("ไม่มีของเก็บ (เกินหนึ่งเทิร์น/รีสตาร์ต) → Movex แบบข้อความ", d6.brand == "movex"
   and not (d6.payload or {}).get("image_carried"))

pol_np = resolve(route_of(mx(0.13)), BRANDS, ["movex"], gate(0.582, -0.124), [])
d7 = decide_with(pol_np.route)
ok("not_product → reject_image ข้อความกลาง", d7.action == "reject_image" and d7.brand is None
   and "ไม่เกี่ยวข้องกับสินค้า" in d7.reply_th, (d7.action, d7.brand))
pol_d = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.84, 0.05), [])
d8 = decide_with(pol_d.route)
ok("direct → Modutech ไม่ถาม", d8.brand == "modutech" and d8.action != "ask", (d8.action, d8.reason))
pol_t = resolve(route_of(mx(0.70)), BRANDS, ["movex"], gate(0.79, 0.05), ["modutech"])
d9 = decide_with(pol_t.route, "สายพาน modutech แบบนี้รับน้ำหนักได้เท่าไร")
ok("ข้อความระบุ Modutech + รูป → Modutech (เดิมขึ้นถามชนกัน)", d9.brand == "modutech" and d9.action != "ask",
   (d9.action, d9.reason))
r_old = route_of(mx(0.70))
core.image_brands = ("movex",)
d10 = core.decide("สายพาน modutech แบบนี้รับน้ำหนักได้เท่าไร", has_image=True, image=r_old.best,
                  image_rejected=False, state=None)
ok("ควบคุม: ไม่ผ่าน policy = พฤติกรรมเดิม (ถามชนกัน · เหตุผลเดิม)", d10.action == "ask"
   and d10.reason.startswith("เจอรหัสของ"), d10.reason)

# ════════════════════════════ 3) TurnEngine ════════════════════════════
print("\n3) core/turn.TurnEngine")
from core.turn import TurnEngine  # noqa: E402


class _Log:
    def __init__(self):
        self.n = 0

    def new_session(self):
        return "s1"

    def start_turn(self, **kw):
        self.n += 1
        return SimpleNamespace(turn_id=f"t{self.n}", summary_top1_pid="", summary_tool_calls=0)

    def log_llm(self, *a, **k):
        pass

    def finish_turn(self, *a, **k):
        pass


class _Tools:
    calls = []

    def reset(self):
        pass


class _Scorer:
    def __init__(self, sc):
        self.sc, self.seen = sc, []

    def score(self, image, text):
        self.seen.append(image.size)
        return self.sc


class _Gate:
    brand = "modutech"

    def __init__(self, reading=None, boom=False):
        self.reading, self.boom, self.seen = reading, boom, []

    def read(self, image):
        self.seen.append(image.size)
        if self.boom:
            raise RuntimeError("จำลองประตูพัง")
        return self.reading


captured = {}


def _fake_build(decision, turn):
    captured["turn"] = turn
    return LLMTurn(system_prompt="", user_parts=[], direct_reply=f"ok:{decision.brand}")


movex_plugin.build_turn = _fake_build
mgr.modutech_plugin.build_turn = _fake_build


def engine(scorer, gate_obj=None, all_scored=False):
    core.image_brands = ("movex",)
    scorers = {"movex": scorer}
    if all_scored:
        scorers["modutech"] = _Scorer(ImageScore("modutech", 0.0, False))
    return TurnEngine(core, llm=None, logger=_Log(), tool_log=_Tools(), image_scorers=scorers,
                      image_gates={"modutech": gate_obj} if gate_obj else {})


def img(w=1200, h=900):
    return Image.new("RGB", (w, h), (120, 120, 120))


sc = _Scorer(mx(0.70))
g = _Gate(GateReading("modutech", True, False, {"score": 0.79, "text": 0.05}))
e = engine(sc, g)
out = e.chat("", img(), [], session_id="s1")
ok("เทิร์นรูป → ถามแบรนด์", "ขอยืนยันก่อน" in out[0][-1]["content"], out[0][-1]["content"][:60])
ok("ประตูได้รูปเต็ม (1200×900) · ViT ได้รูปย่อเหมือนเดิม", g.seen == [(1200, 900)] and max(sc.seen[0]) <= 400,
   (g.seen, sc.seen))
ok("เก็บรูปไว้ใน session", "s1" in e.image_carry)
out = e.chat("1", None, out[0], session_id="s1")
ok("ตอบ 1 → Movex ใช้ ViT 0.70 ของรูปเทิร์นก่อน (รู้ซีรีส์ → ถามความกว้าง)",
   "880" in out[0][-1]["content"] and "ViT 0.70" in out[2], out[2][-200:])
ok("ใช้แล้วลบ (เทิร์นเดียว)", "s1" not in e.image_carry)

e = engine(_Scorer(mx(0.97)), _Gate(GateReading("modutech", True, False, {})))
e.image_carry["s1"] = ImageCarry(img(), mx(0.97), False)
captured.clear()
dst = core.state_cls()
dst.pending, dst.pending_question = "brand", ""
e.dialog_states["s1"] = dst.to_dict()
out = e.chat("1", None, [], session_id="s1")
ok("เทิร์นที่ใช้รูปที่เก็บ + ไปถึงปลั๊กอิน → TurnInput ได้รูปและคะแนนเดิม",
   out[0][-1]["content"] == "ok:movex" and captured.get("turn") is not None
   and captured["turn"].image is not None and captured["turn"].image_score.confidence == 0.97,
   (out[0][-1]["content"][:80], out[2][-200:]))

e = engine(_Scorer(mx(0.70)), g)
out = e.chat("", img(), [], session_id="s1")
out = e.chat("ไม่แน่ใจ", None, out[0], session_id="s1")
ok("ตอบไม่ใช่แบรนด์ → ของเก็บหมดอายุ", "s1" not in e.image_carry)

e = engine(_Scorer(mx(0.70)), g)
out = e.chat("", img(), [], session_id="s1")
out = e.chat("", img(800, 800), out[0], session_id="s1")
ok("รูปใหม่ → ทิ้งของเก่า · เก็บของใหม่", max(e.image_carry["s1"].image.size) <= 400
   and e.image_carry["s1"].image.size[0] == e.image_carry["s1"].image.size[1])

e = engine(_Scorer(mx(0.13)), _Gate(GateReading("modutech", False, False, {"score": 0.58, "text": -0.12})))
out = e.chat("", img(), [], session_id="s1")
ok("IMG-003 ผ่านเครื่องยนต์ → ปฏิเสธทันที", "ไม่เกี่ยวข้องกับสินค้า" in out[0][-1]["content"]
   and "s1" not in e.image_carry)

e = engine(_Scorer(mx(0.70)), _Gate(boom=True))
out = e.chat("", img(), [], session_id="s1")
ok("ประตูพัง → ไม่ล้ม · ถามแบรนด์", "ขอยืนยันก่อน" in out[0][-1]["content"])

e = engine(_Scorer(mx(0.95)), g)
out = e.chat("", img(), [], session_id="s1")
ok("dominant → Movex ทันที", out[0][-1]["content"] == "ok:movex")

e = engine(_Scorer(mx(0.13)), _Gate(GateReading("modutech", True, False, {})), all_scored=True)
out = e.chat("", img(), [], session_id="s1")
ok("ทุกแบรนด์มีตัวให้คะแนน → ไม่เรียก policy (ปฏิเสธแบบเดิม)", "s1" not in e.image_carry
   and "❌" in out[0][-1]["content"] and "Image policy" not in out[2])

# ════════════════════════════ 4) image_gate ════════════════════════════
print("\n4) brands/modutech/image_gate")
th = GateThresholds()
ok("ค่าเริ่ม = แผน (0.65 · −0.02 · 0.8254)", (th.not_product_score, th.not_product_text, th.direct_score)
   == (0.65, -0.02, 0.8254))
import yaml  # noqa: E402
ycfg = yaml.safe_load(open(os.path.join(ROOT, "brands/modutech/brand.yaml"), encoding="utf-8"))["image_gate"]
ok("brand.yaml ตรงกับค่าในโค้ด", GateThresholds.from_cfg(ycfg) == th)

d = 8
rng = np.random.default_rng(0)


def unit(v):
    return v / np.linalg.norm(v)


G = np.stack([unit(rng.normal(size=d)) for _ in range(5)]).astype(np.float32)
B = np.stack([unit(rng.normal(size=d)) for _ in range(4)]).astype(np.float32)
O = np.stack([unit(rng.normal(size=d)) for _ in range(8)]).astype(np.float32)
tmp = tempfile.mkdtemp(prefix="gate_")
meta = {"model": "m-384", "other_names": [f"o{i}" for i in range(8)]}
from brands.modutech.image_gate import _sha  # noqa: E402
meta["G_sha256"] = _sha(G)
np.savez(os.path.join(tmp, "image_gate.npz"), G=G, belt_P=B, other_P=O, meta=json.dumps(meta))
data = GateData.load(os.path.join(tmp, "image_gate.npz"), "m-384")
ok("โหลดไฟล์ได้", data.G.shape == (5, d) and data.other_names[0] == "o0")
try:
    GateData.load(os.path.join(tmp, "image_gate.npz"), "อีกโมเดล")
    ok("ไฟล์คนละโมเดล → ปฏิเสธ", False)
except GateFileError:
    ok("ไฟล์คนละโมเดล → ปฏิเสธ", True)
gate_obj, why = load_gate("modutech", tmp, {"model": "m-384", "file": "ไม่มี.npz"}, "cpu",
                          embed_factory=lambda m, dv: None)
ok("ไม่มีไฟล์ → ปิด + เหตุผล ไม่ยกข้อผิดพลาด", gate_obj is None and "ไม่พบ" in why, why)
gate_obj, why = load_gate("modutech", tmp, {"enabled": False}, "cpu")
ok("enabled: false → ปิด", gate_obj is None)


def boom_factory(m, dv):
    raise OSError("ไม่มีเน็ต")


gate_obj, why = load_gate("modutech", tmp, {"model": "m-384"}, "cpu", embed_factory=boom_factory)
ok("โหลดโมเดลไม่ได้ → ปิด ไม่ล้ม", gate_obj is None and "ไม่มีเน็ต" in why)


def fixed_embed(vec_full, vec_crop):
    return lambda imgs: np.stack([vec_full] + [vec_crop] * (len(imgs) - 1))


gt = ModutechImageGate("modutech", data, fixed_embed(B[0], G[2]))
rd = gt.read(img())
s_exp = float(max((np.stack([B[0], G[2], G[2]]) @ G.T).max(), 0))
ok("คะแนน = cosine สูงสุดทุกมุมมองกับแกลเลอรี", abs(rd.detail["score"] - round(s_exp, 4)) < 1e-4)
ok("ข้อความ = ภาพเต็มเท่านั้น", abs(rd.detail["text"] - round(float((B @ B[0]).max() - (O @ B[0]).max()), 4)) < 1e-4)
gt2 = ModutechImageGate("modutech", data, fixed_embed(O[3], O[3]))
rd2 = gt2.read(img())
ok("ใกล้ข้อความของอื่น → product_like False · ชื่อกลุ่มที่ใกล้", rd2.product_like is False
   and rd2.detail["near"] == "o3", rd2.detail)

im = Image.new("RGBA", (300, 120), (255, 255, 255, 0))
im.paste((10, 20, 30, 255), (50, 30, 250, 90))
n = normalize_image(im)
ok("normalize: ตัดขอบ เติมจัตุรัส 384", n.size == (384, 384) and n.getpixel((0, 0)) == (255, 255, 255)
   and n.getpixel((192, 192)) == (10, 20, 30))
ref = os.environ.get("IMAGE_EVAL_DIR")
if ref and os.path.isdir(ref):
    sys.path.insert(0, ref)
    from imgeval.normalize import normalize_image as ref_norm, center_views as ref_cv  # noqa: E402
    from brands.modutech.image_gate import center_views  # noqa: E402
    src = Image.fromarray(np.random.default_rng(1).integers(0, 255, (700, 500, 3), dtype=np.uint8))
    a, b = normalize_image(src), ref_norm(src)
    ok("normalize พิกเซลตรงกับ 21_image_eval", np.array_equal(np.asarray(a), np.asarray(b)))
    ok("center_views ตรงกับ 21_image_eval", all(np.array_equal(np.asarray(x), np.asarray(y))
                                               for x, y in zip(center_views(a), ref_cv(b, (1.0, 0.7, 0.45)))))
else:
    print("  · ข้ามการเทียบกับ 21_image_eval (ตั้ง IMAGE_EVAL_DIR=<โฟลเดอร์ 21_image_eval> เพื่อเทียบ)")

print(f"\nรวม {passed}/{passed + failed}")
sys.exit(1 if failed else 0)
