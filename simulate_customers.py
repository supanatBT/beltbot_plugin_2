"""
simulate_customers.py — ลูกค้าจำลองด้วย LLM คุยกับบอทจริง แล้ววัดว่าคุยจนได้รุ่นที่ถูกไหม (ผู้ใช้เลือก 25 ต.ค. · ข้อ 3)

ที่มา: Davidson et al. 2023 "User Simulation with Large Language Models for Evaluating Task-Oriented Dialogue"
(arXiv 2309.13233) — ให้ LLM เล่นเป็นผู้ใช้ตามเป้าหมาย แทนการเขียนบททดสอบเอง (test_conversation_leaks.py
จับได้แค่แบบที่ผู้เขียนนึกออก)

แบ่งหน้าที่
    LLM ลูกค้าจำลอง   เขียนข้อความของลูกค้าตาม persona + ข้อเท็จจริง (training/sim_goals.json) · ไม่รู้ชื่อรุ่น
    บอท               chat_interaction() ตัวจริง (assistant.py · Gemini · Jina · Qdrant ครบ)
    ผู้ตัดสิน          โค้ด ไม่ใช่ LLM — ชุดรุ่นที่ถูกคำนวณจากแคตตาล็อก (match_application/industry → filter_by_need)

ตัวชี้วัดต่อบทสนทนา
    reached      บอทเอ่ยรหัสรุ่นอย่างน้อยหนึ่งรุ่น
    hit          รุ่นที่เอ่ยอยู่ในชุดรุ่นที่ถูก (หรือ ชุดว่าง + บอทบอกว่าไม่มี)
    violations   รุ่นที่เอ่ยแต่ผิดเงื่อนไขแข็ง (พิทช์ / อุณหภูมิ) — นี่คือ "ตอบผิด"
    offtopic     บอทปฏิเสธว่านอกเรื่องกลางบท
    repeats      บอทพูดข้อความเดิมซ้ำติดกัน (วนถาม)
    ended        done (ลูกค้าพอใจ) · giveup · max_turns · error
    turns        จำนวนเทิร์นของลูกค้า

เวลา (ผู้ใช้ขอ 25 ต.ค.: ข้อ 1 ทำให้ตอบช้าลงไหม) — วัดเฉพาะฝั่งบอท ไม่นับเวลาที่ลูกค้าจำลองคิด
    ทุกเทิร์นของบอท: sec · ตีความ (LLM / กฎ / -) · interp_ms (เวลาเรียกตัวตีความในเทิร์นนั้น)
    สรุป: เฉลี่ย · มัธยฐาน · p90 ทั้งหมด และแยก "เทิร์นที่ลูกค้าตอบคำถามค้าง" กับ "เทิร์นอื่น"
    เทียบสองรอบ: python simulate_customers.py --compare sim_rules.json sim_llm.json

รัน (ต้องมี .env แบบเดียวกับบอท · ใช้ Gemini ทั้งสองฝั่ง)
    python simulate_customers.py -o sim_r1.json                       # ทุกเป้าหมาย 1 รอบ
    python simulate_customers.py --repeats 3 -o sim_r1.json            # เป้าหมายละ 3 บท (ลูกค้าพูดต่างกันทุกรอบ)
    python simulate_customers.py --only G01,G05 -o probe.json
    $env:ANSWER_INTERPRETER="rules"; python simulate_customers.py -o sim_rules.json   # เทียบกับกฎ regex
ได้ไฟล์ .json (ผลเต็ม) และ .txt (บทสนทนาแบบแชท ลูกค้า/บอท)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DONE, GIVEUP = "[จบ]", "[ยอมแพ้]"
OFFTOPIC_TH = "ผมตอบได้เฉพาะเรื่องสินค้า"
NONE_WORDS = re.compile(r"ไม่มีรุ่นที่|ไม่มีสายพาน.*ที่ตรง|ไม่พบรุ่น|ไม่มีรุ่นใด")

SIM_SYSTEM = """คุณเล่นเป็นลูกค้าที่กำลังแชทกับบอทขายสายพาน/โซ่ลำเลียง เขียนเฉพาะข้อความของลูกค้าหนึ่งข้อความ
ลักษณะลูกค้า: {persona}
งานของลูกค้า: {application}
ข้อเท็จจริงที่ลูกค้ารู้ (บอกเมื่อบอทถาม หรือเมื่อเป็นธรรมชาติ ไม่ต้องบอกหมดในครั้งเดียว ยกเว้นลักษณะลูกค้าบอกให้ทำ):
{facts}
กฎ:
- พิมพ์แบบแชทจริง สั้น ภาษาพูด ไม่ต้องสุภาพเกิน ไม่ใช้ markdown
- ห้ามคิดชื่อรุ่นหรือรหัสสินค้าเอง พูดถึงรุ่นได้เฉพาะที่บอทเอ่ยมาก่อน
- ถ้าบอทเสนอค่าที่ตรงกับข้อเท็จจริงของคุณ ให้ยืนยัน · ถ้าไม่ตรง ให้บอกค่าที่ถูก
- ถ้าไม่รู้คำตอบ ให้บอกว่าไม่รู้
- เมื่อบอทแนะนำรุ่นแล้วและคุณพอใจ (หรือบอทบอกชัดว่าไม่มีรุ่นที่ตรง) ให้ถามต่อตามลักษณะลูกค้าถ้ามี แล้วจบด้วยข้อความที่มี {done}
- ถ้าบอทวนถามซ้ำ ตอบไม่ตรง หรือไม่เข้าใจคุณ 3 ครั้ง ให้จบด้วย {giveup}
"""


def load_goals(path: str) -> list[dict]:
    return json.load(open(path, encoding="utf-8"))["goals"]


class Judge:
    """ชุดรุ่นที่ถูก — คำนวณจากแคตตาล็อกด้วยโค้ดชุดเดียวกับบอท (need_flow.filter_by_need)"""

    def __init__(self, root: str = ROOT):
        import dialogue_state as DS
        from brands.modutech import need_flow as NF
        self.NF = NF
        self.cat = DS.Catalogue(os.path.join(root, "modutech_v30_3.json"))
        mgr = DS.DialogueManager({}, self.cat)
        self.search = mgr.modutech_plugin.search
        self.detector = mgr.modutech_plugin.detector

    def acceptable(self, g: dict) -> dict:
        t = g.get("application", "")
        am = self.search.match_application(t)
        if am is not None:
            cands, src = list(am.belt_codes), "application"
        else:
            im = self.search.match_industry(t)
            cands, src = (list(im[1]), "industry") if im else ([p["belt_code"] for p in self.cat.products], "all")
        f = self.NF.filter_by_need(self.cat, cands, g.get("pitch_mm"), g.get("temp_c"), g.get("wet_or_dry"))
        hard = self.NF.filter_by_need(self.cat, [p["belt_code"] for p in self.cat.products],
                                      g.get("pitch_mm"), g.get("temp_c"), g.get("wet_or_dry"))
        return dict(ok=f["kept"], hard_ok=hard["kept"], source=src, n_candidates=len(cands))

    def codes_in(self, text: str) -> list[str]:
        return list(self.detector.detect(text or "").parsed.belt_codes)


def score(g: dict, transcript: list[dict], judge: Judge, ended: str) -> dict:
    bot = [t["text"] for t in transcript if t["role"] == "bot"]
    offtopic = sum(OFFTOPIC_TH in b for b in bot[1:])
    repeats = sum(1 for a, b in zip(bot, bot[1:]) if a.strip() and a.strip() == b.strip())
    out = dict(ended=ended, turns=sum(t["role"] == "customer" for t in transcript),
               offtopic=offtopic, repeats=repeats)
    if g.get("brand") == "movex":
        hit = any(any(x in b for x in g.get("expect_any", [])) for b in bot)
        return {**out, "reached": hit, "hit": hit, "violations": [], "mentioned": []}
    acc = judge.acceptable(g)
    mentioned = []
    for b in bot:
        for c in judge.codes_in(b):
            if c not in mentioned:
                mentioned.append(c)
    violations = [c for c in mentioned if c not in acc["hard_ok"]]
    if acc["ok"]:
        hit = any(c in acc["ok"] for c in mentioned)
    else:
        hit = any(NONE_WORDS.search(b) for b in bot) and not [c for c in mentioned if c not in acc["hard_ok"]]
    return {**out, "reached": bool(mentioned), "hit": hit, "violations": violations, "mentioned": mentioned,
            "acceptable": acc["ok"], "acceptable_source": acc["source"]}


def sim_message(complete, g: dict, transcript: list[dict], temperature: float) -> str:
    facts = "\n".join(f"- {k}: {v}" for k, v in (g.get("facts") or {}).items())
    system = SIM_SYSTEM.format(persona=g["persona"], application=g.get("application", ""), facts=facts,
                               done=DONE, giveup=GIVEUP)
    chat = "\n".join(f"{'ลูกค้า' if t['role'] == 'customer' else 'บอท'}: {t['text']}" for t in transcript)
    user = f"บทสนทนาจนถึงตอนนี้:\n{chat}\n\nเขียนข้อความถัดไปของลูกค้า (ข้อความเดียว):"
    text = (complete(system, user, temperature=temperature) or "").strip()
    return re.sub(r"^(ลูกค้า|customer)\s*:\s*", "", text, flags=re.IGNORECASE).strip()


_INTERP_RX = re.compile(r"ตีความ: (LLM|กฎ)")


def run_goal(g: dict, chat_fn, complete, judge: Judge, max_turns: int, temperature: float,
             interpreter=None) -> dict:
    transcript: list[dict] = []
    history, last_pids, session_id, vit, graph = [], [], "", None, None
    ended = "max_turns"
    msg = g.get("opening") or ""
    t0 = time.time()
    for turn in range(max_turns):
        if turn > 0:
            try:
                msg = sim_message(complete, g, transcript, temperature)
            except Exception as e:                       # noqa: BLE001
                ended = f"sim_error: {type(e).__name__}: {e}"
                break
        clean = msg.replace(DONE, "").replace(GIVEUP, "").strip()
        if clean:
            transcript.append({"role": "customer", "text": clean})
        if DONE in msg or GIVEUP in msg:
            ended = "done" if DONE in msg else "giveup"
            if not clean:
                break
        if not clean:
            continue
        ms0 = getattr(interpreter, "total_ms", 0.0)
        tb = time.perf_counter()
        try:
            out = chat_fn(clean, None, history, last_pids, session_id, vit, graph)
            history, _s, refs, last_pids, session_id, vit, graph = out
            reply = next((m["content"] for m in reversed(history) if m["role"] == "assistant"
                          and not str(m.get("content", "")).startswith("<img")), "")
        except Exception as e:                           # noqa: BLE001
            transcript.append({"role": "bot", "text": f"[ERROR] {type(e).__name__}: {e}"})
            ended = "error"
            break
        m = _INTERP_RX.search(str(refs or ""))
        transcript.append({"role": "bot", "text": reply, "sec": round(time.perf_counter() - tb, 3),
                           "interp": m.group(1) if m else "-",
                           "interp_ms": round(getattr(interpreter, "total_ms", 0.0) - ms0, 1)})
        if ended in ("done", "giveup"):
            break
    res = score(g, transcript, judge, ended)
    return {"goal": g["id"], "brand": g.get("brand"), "application": g.get("application"),
            "seconds": round(time.time() - t0, 1), **res, "transcript": transcript}


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(round(p * (len(s) - 1))))]  # noqa: E731
    return {"n": len(s), "mean": round(sum(s) / len(s), 2), "median": round(q(0.5), 2), "p90": round(q(0.9), 2),
            "max": round(s[-1], 2)}


def latency(results: list[dict]) -> dict:
    """เวลาตอบของบอทต่อเทิร์น (วินาที) — แยกเทิร์นที่ลูกค้าตอบคำถามค้าง (มีการตีความ) กับเทิร์นอื่น"""
    bot = [t for r in results for t in r["transcript"] if t["role"] == "bot" and "sec" in t]
    ans = [t for t in bot if t.get("interp") in ("LLM", "กฎ")]
    llm = [t for t in ans if t["interp"] == "LLM"]
    return {"all_turns": _stats([t["sec"] for t in bot]),
            "answer_turns": _stats([t["sec"] for t in ans]),
            "other_turns": _stats([t["sec"] for t in bot if t not in ans]),
            "interpreter_ms": _stats([t["interp_ms"] for t in llm]),
            "answer_turns_by": dict(Counter(t["interp"] for t in ans))}


def summarize(results: list[dict]) -> dict:
    n = len(results)
    c = Counter(r["ended"] for r in results)
    pct = lambda k: round(100 * sum(bool(r[k]) for r in results) / n, 1) if n else 0.0  # noqa: E731
    return {"conversations": n, "hit_pct": pct("hit"), "reached_pct": pct("reached"),
            "with_violation_pct": pct("violations"), "with_offtopic_pct": pct("offtopic"),
            "with_repeat_pct": pct("repeats"), "ended": dict(c),
            "mean_turns": round(sum(r["turns"] for r in results) / n, 1) if n else 0.0,
            "latency_sec": latency(results)}


def compare(a_path: str, b_path: str) -> None:
    """เทียบสองรอบ (เช่น กฎ vs LLM) — คุณภาพและเวลาต่อเทิร์น"""
    A, B = (json.load(open(p, encoding="utf-8")) for p in (a_path, b_path))
    sa, sb = A["summary"], B["summary"]
    print(f"{'':28}{A.get('answer_interpreter', '?'):>14}{B.get('answer_interpreter', '?'):>14}")
    for k in ("conversations", "hit_pct", "reached_pct", "with_violation_pct", "with_offtopic_pct",
              "with_repeat_pct", "mean_turns"):
        print(f"{k:28}{sa.get(k):>14}{sb.get(k):>14}")
    for part in ("all_turns", "answer_turns", "other_turns"):
        for st in ("mean", "median", "p90"):
            va, vb = sa["latency_sec"][part].get(st), sb["latency_sec"][part].get(st)
            d = f"{vb - va:+.2f}" if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else ""
            print(f"{'เวลา ' + part + ' ' + st + ' (วิ)':28}{str(va):>14}{str(vb):>14}  {d}")
    print(f"{'เรียกตัวตีความ (มิลลิวินาที)':28}{'':>14}{str(sb['latency_sec']['interpreter_ms']):>14}")


def write_txt(path: str, results: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            flags = [k for k in ("violations", "offtopic", "repeats") if r.get(k)]
            f.write(f"\n=== {r['goal']}#{r.get('run', 1)} · {r['application']} · "
                    f"{'✓ ได้รุ่นที่ถูก' if r['hit'] else '✗ ไม่ได้รุ่นที่ถูก'} · จบแบบ {r['ended']}"
                    + (f" · ⚠ {', '.join(flags)}" if flags else "") + " ===\n")
            if r.get("violations"):
                f.write(f"รุ่นที่ผิดเงื่อนไข: {r['violations']}\n")
            for t in r["transcript"]:
                f.write(f"{'🧑 ลูกค้า' if t['role'] == 'customer' else '🤖 บอท'}: {t['text']}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="assistant")
    ap.add_argument("--goals", default=os.path.join(ROOT, "training", "sim_goals.json"))
    ap.add_argument("--only", default="")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=10)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"), help="เทียบสองรอบแล้วจบ")
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)
    if not a.out:
        sys.exit("ต้องระบุ -o ไฟล์ผล")

    goals = load_goals(a.goals)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    goals = [g for g in goals if not only or g["id"] in only]
    bot = importlib.import_module(a.module)
    complete = bot.llm_client.complete
    judge = Judge()
    results = []
    for g in goals:
        for k in range(a.repeats):
            r = run_goal(g, bot.chat_interaction, complete, judge, a.max_turns, a.temperature,
                         interpreter=getattr(bot, "answer_interpreter", None))
            r["run"] = k + 1
            results.append(r)
            print(f"  {'✓' if r['hit'] else '✗'} {g['id']}#{k + 1} {g.get('application', '')[:20]:20} "
                  f"{r['ended']:9} เทิร์น {r['turns']:2}"
                  + (f" ⚠ ผิดเงื่อนไข {r['violations']}" if r["violations"] else "")
                  + (f" ⚠ นอกเรื่อง {r['offtopic']}" if r["offtopic"] else "")
                  + (f" ⚠ ซ้ำ {r['repeats']}" if r["repeats"] else ""))
    summary = summarize(results)
    meta = {"module": a.module, "llm": getattr(bot.llm_client, "describe", lambda: "")(),
            "answer_interpreter": getattr(bot, "ANSWER_INTERPRETER", "?"), "repeats": a.repeats,
            "max_turns": a.max_turns, "temperature": a.temperature}
    json.dump({**meta, "summary": summary, "results": results}, open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    txt = os.path.splitext(a.out)[0] + ".txt"
    write_txt(txt, results)
    print(f"\nสรุป: {summary}")
    print(f"เขียนแล้ว: {a.out} · {txt}")


if __name__ == "__main__":
    main()
