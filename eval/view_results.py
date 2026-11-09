"""
view_results.py — แปลงไฟล์ผลทดสอบ (.json) เป็นหน้าแชทอ่านง่าย เปิดในเบราว์เซอร์ได้เลย

ใช้ได้กับไฟล์ผลของ run_answer_eval.py · probe_tools.py · run_answer_eval --module agent_assistant
ไม่ต้องติดตั้งอะไรเพิ่ม (Python ล้วน) · ไม่แก้ไฟล์ผลดิบ · ไม่ส่งข้อมูลออกนอกเครื่อง

ตัวอย่าง (PowerShell)
    python view_results.py ..\\movex_old_text_qi_r1.json
    python view_results.py ..\\movex_old_text_qi_r1.json ..\\movex_old_text_qi_r2.json      # เทียบสองรอบข้างกัน
    python view_results.py ..\\movex_old_text_qi_r1.json --testcases eval/cases/testcases_movex_old_text.csv   # แสดงเฉลยด้วย
    python view_results.py ..\\movex_old_text_qi_r1.json -o ..\\chat_view.html --no-open

ในหน้าเว็บ: ช่องค้นหา (คำถาม/คำตอบ/รหัสข้อ) · ปุ่มดูเฉพาะข้อที่ตก · กดหัวข้อเพื่อพับ/กาง
"""
from __future__ import annotations
import os as _os, sys as _sys  # รากของ repo: import แพ็กเกจได้ และพาธข้อมูลนับจากราก
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import argparse
import csv
import html
import json
import os
import re
import sys
import webbrowser
from collections import OrderedDict
from pathlib import Path


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, list):
        d = {"results": d}
    d["_file"] = os.path.basename(path)
    return d


def load_imglog(path: str | None) -> list:
    """บรรทัด IMGLOG {json} จาก IMAGE_TEST_LOG — หนึ่งบรรทัดต่อเทิร์นที่มีรูป เรียงตามเวลาที่รัน"""
    if not path:
        return []
    raw = open(path, "rb").read()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "replace")
    out = []
    for line in text.splitlines():
        i = line.find("IMGLOG {")
        if i >= 0:
            try:
                out.append(json.loads(line[i + 7:]))
            except ValueError:
                pass
    return out


def attach_imglog(d: dict, logs: list) -> int:
    """ผูก IMGLOG กับเทิร์นที่ส่งรูปตามลำดับ (ไฟล์ log ต้องมาจากรอบเดียวกับไฟล์ผลเท่านั้น)"""
    turns = [r for r in d.get("results", []) if r.get("used_image") and not r.get("skipped")]
    for r, im in zip(turns, logs):
        r["_imglog"] = im
    return len(turns)


def load_testcases(path: str | None) -> dict:
    if not path:
        return {}
    rows = csv.DictReader(open(path, encoding="utf-8-sig"))
    return {(r.get("id", ""), str(r.get("turn_number") or "1")): r for r in rows}


# ── markdown แบบเบา ๆ (พอให้อ่านคำตอบบอทได้) ──
def md(text: str) -> str:
    if not text:
        return '<span class="muted">(ไม่มีข้อความ)</span>'
    lines = text.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        out.append(_inline(line))
        i += 1
    return "<br>".join(out).replace("<br><table", "<table").replace("</table><br>", "</table>")


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"^(\s*)[*-]\s+", r"\1• ", s)
    if re.fullmatch(r"\s*-{3,}\s*", s):
        return "<hr>"
    return s


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    h = "".join(f"<th>{_inline(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<table class="md"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>'


def turn_key(r: dict) -> tuple:
    return (r.get("id", ""), str(r.get("turn") or "1"))


def status(r: dict) -> tuple[str, str]:
    if r.get("skipped"):
        return "skip", "ข้าม"
    if r.get("error"):
        return "fail", "error"
    if r.get("passed") is False:
        return "fail", "ตก"
    if r.get("passed") is True:
        # ชุดที่ให้คะแนนด้วยคน (เช่น Movex เดิม manual_0_2) ตรวจอัตโนมัติได้แค่ว่าไม่ error — อย่าขึ้นว่า "ผ่าน"
        if set((r.get("checks") or {}).keys()) <= {"no_error"}:
            return "skip", "ไม่มีเกณฑ์อัตโนมัติ"
        return "pass", "ผ่าน"
    return "skip", "—"


def tools_of(r: dict) -> list:
    calls = r.get("tool_calls")
    if calls is None:
        calls = (r.get("llm_usage") or {}).get("tool_calls") or []
    return calls or []


def bot_column(r: dict | None) -> str:
    if r is None:
        return '<div class="bubble bot missing">ไม่มีเทิร์นนี้ในไฟล์</div>'
    cls, label = status(r)
    checks = r.get("checks") or {}
    failed = [k for k, v in checks.items() if v is False]
    meta = [f'<span class="tag {cls}">{label}</span>']
    if r.get("seconds") is not None:
        meta.append(f"{r['seconds']} วิ")
    u = r.get("llm_usage") or {}
    if u.get("llm_calls") is not None:
        meta.append(f"LLM {u['llm_calls']} ครั้ง")
    if failed:
        meta.append("ตกเกณฑ์: " + ", ".join(html.escape(f) for f in failed))
    if r.get("skip_reason"):
        meta.append(html.escape(r["skip_reason"]))
    tl = tools_of(r)
    tool_html = ""
    if tl:
        items = "".join(
            f"<li><code>{html.escape(str(t.get('tool') or t.get('name')))}</code> "
            f"{html.escape(json.dumps(t.get('args') or {}, ensure_ascii=False))}</li>" for t in tl)
        tool_html = f'<details class="tools"><summary>เรียกเครื่องมือ {len(tl)} ครั้ง</summary><ul>{items}</ul></details>'
    dbg = r.get("route_debug") or ""
    dec = next((l for l in dbg.split("\n") if l.startswith("**Decision")), "")
    dec_html = f'<div class="decision">{_inline(dec)}</div>' if dec else ""
    err = f'<div class="err">{html.escape(str(r.get("error")))}</div>' if r.get("error") else ""
    im = r.get("_imglog")
    if im:
        sc = "; ".join(f"{b}: {', '.join(f'{k}={v}' for k, v in (d or {}).items() if v not in (None, '', []))}"
                       for b, d in (im.get("scores") or {}).items())
        gt = "; ".join(f"{b}: {', '.join(f'{k}={v}' for k, v in (d or {}).items())}" for b, d in (im.get("gates") or {}).items())
        dec_html += (f'<details class="tools" open><summary>รูป: กฎ {html.escape(str(im.get("policy")))} → '
                     f'{html.escape(str(im.get("action")))} · แบรนด์ {html.escape(str(im.get("brand")))}</summary><ul>'
                     f'<li>{html.escape(str(im.get("policy_reason") or ""))}</li>'
                     f'<li>ตัวให้คะแนน: {html.escape(sc or "-")}</li><li>ประตู: {html.escape(gt or "-")}</li></ul></details>')
    return (f'<div class="bubble bot {cls}">{md(r.get("reply") or "")}{err}</div>'
            f'<div class="meta">{" · ".join(meta)}</div>{dec_html}{tool_html}')


def header_block(d: dict) -> str:
    si = d.get("system_info") or {}
    parts = [f"<b>{html.escape(d['_file'])}</b>"]
    for k in ("module", "testcases"):
        if d.get(k):
            parts.append(f"{k}: {html.escape(str(d[k]))}")
    for k in ("system", "prompt_version", "commit", "branch", "front_interpreter", "gemini_model", "gemini_thinking"):
        if si.get(k) not in (None, ""):
            parts.append(f"{k}: {html.escape(str(si[k]))}")
    if si.get("dirty"):
        parts.append('<span class="warn">มีโค้ดแก้ที่ยังไม่ commit</span>')
    if d.get("passed") is not None and d.get("graded") is not None:
        parts.append(f"ผ่าน {d['passed']}/{d['graded']}")
    return '<div class="filehead">' + " · ".join(parts) + "</div>"


def build(files: list[dict], cases: dict, title: str) -> str:
    index = [OrderedDict((turn_key(r), r) for r in d.get("results", [])) for d in files]
    order = list(OrderedDict.fromkeys(k for ix in index for k in ix))
    convs: "OrderedDict[str, list]" = OrderedDict()
    for k in order:
        convs.setdefault(k[0], []).append(k)
    n = len(files)
    blocks = []
    for cid, keys in convs.items():
        keys.sort(key=lambda k: int(k[1]) if k[1].isdigit() else 0)
        any_fail = any(status(ix.get(k, {}))[0] == "fail" for ix in index for k in keys if k in ix)
        first = next((ix[k] for ix in index for k in keys if k in ix), {})
        cat = first.get("category") or first.get("subcategory") or ""
        desc = first.get("description") or ""
        turns = []
        for k in keys:
            r0 = next((ix[k] for ix in index if k in ix), {})
            q = r0.get("query") or ""
            img = (cases.get(k, {}).get("image") or "").strip() or bool(r0.get("used_image"))
            user = html.escape(q) if q else '<span class="muted">(ส่งรูปอย่างเดียว)</span>'
            if img:
                user += f' <span class="tag img">รูป{": " + html.escape(img) if isinstance(img, str) else ""}</span>'
            tc = cases.get(k) or {}
            exp_bits = [f"<b>{lab}:</b> {html.escape(tc[c])}" for c, lab in
                        (("expected_answer", "เฉลย"), ("must_contain", "ต้องมี"), ("must_contain_any", "มีอย่างใดอย่างหนึ่ง"),
                         ("must_not_contain", "ห้ามมี"), ("expected_value", "ค่าที่คาด"), ("flag", "ธง"))
                        if (tc.get(c) or "").strip()]
            exp_html = f'<div class="expect">{" · ".join(exp_bits)}</div>' if exp_bits else ""
            cols = "".join(f'<div class="col">{bot_column(ix.get(k))}</div>' for ix in index)
            turns.append(f'<div class="turn"><div class="tno">เทิร์น {html.escape(k[1])}</div>'
                         f'<div class="bubble user">{user}</div>{exp_html}'
                         f'<div class="cols" style="grid-template-columns:repeat({n},1fr)">{cols}</div></div>')
        search = html.escape(" ".join([cid, cat, desc] + [
            (ix.get(k) or {}).get("query", "") + " " + (ix.get(k) or {}).get("reply", "") for ix in index for k in keys]).lower())
        blocks.append(
            f'<details class="conv{" hasfail" if any_fail else ""}" open data-s="{search}">'
            f'<summary><b>{html.escape(cid)}</b> <span class="muted">{html.escape(cat)}</span>'
            f'{" <span class=\"tag fail\">มีข้อตก</span>" if any_fail else ""}'
            f'<span class="desc">{html.escape(desc)}</span></summary>{"".join(turns)}</details>')
    heads = "".join(f'<div class="col">{header_block(d)}</div>' for d in files)
    return TEMPLATE.replace("{title}", html.escape(title)).replace("{n}", str(n)) \
        .replace("{heads}", heads).replace("{blocks}", "".join(blocks)).replace("{count}", str(len(convs)))


TEMPLATE = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2129;--muted:#6b7280;--line:#e3e6ea;--user:#2563eb;--bot:#fff;--pass:#15803d;--fail:#b91c1c;--skip:#6b7280}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1d2026;--text:#e6e8eb;--muted:#9aa1ab;--line:#30343b;--user:#3b6fe0;--bot:#23272e;--pass:#4ade80;--fail:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,"Segoe UI","Noto Sans Thai",Tahoma,sans-serif}
.top{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px}
.top h1{font-size:17px;margin:0 0 6px}.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=search]{flex:1;min-width:200px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);font:inherit}
button{padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);font:inherit;cursor:pointer}
button.on{background:var(--fail);color:#fff;border-color:var(--fail)}
.heads,.cols{display:grid;gap:12px}.heads{grid-template-columns:repeat({n},1fr);margin-top:8px}
.filehead{font-size:12.5px;color:var(--muted);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
main{padding:12px 16px 40px;max-width:1500px;margin:0 auto}
.conv{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:0 0 12px;padding:4px 14px 10px}
.conv>summary{cursor:pointer;padding:8px 0;list-style:none}.conv>summary::-webkit-details-marker{display:none}
.desc{display:block;font-size:12.5px;color:var(--muted)}
.turn{border-top:1px dashed var(--line);padding:10px 0}.tno{font-size:12px;color:var(--muted);margin-bottom:4px}
.bubble{border-radius:14px;padding:9px 13px;max-width:100%;overflow-wrap:anywhere}
.bubble.user{background:var(--user);color:#fff;margin-left:auto;width:fit-content;max-width:75%;border-bottom-right-radius:4px}
.bubble.bot{background:var(--bot);border:1px solid var(--line);border-bottom-left-radius:4px;margin-top:8px}
.bubble.bot.fail{border-color:var(--fail)}.bubble.missing{color:var(--muted);font-style:italic}
.cols{margin-top:2px}.meta{font-size:12px;color:var(--muted);margin-top:4px}
.decision{font-size:12px;color:var(--muted);margin-top:2px}
.expect{font-size:12.5px;margin:6px 0 0 auto;max-width:75%;width:fit-content;color:var(--muted);text-align:right}
.tag{display:inline-block;font-size:11.5px;padding:0 7px;border-radius:999px;border:1px solid currentColor;margin-left:4px}
.tag.pass{color:var(--pass)}.tag.fail{color:var(--fail)}.tag.skip{color:var(--skip)}.tag.img{color:inherit;opacity:.85}
.muted{color:var(--muted)}.warn{color:var(--fail);font-weight:600}.err{color:var(--fail);font-size:13px;margin-top:6px}
code{font-family:ui-monospace,Consolas,monospace;font-size:.9em;background:rgba(127,127,127,.15);padding:0 4px;border-radius:4px}
table.md{border-collapse:collapse;margin:6px 0;font-size:13.5px;display:block;overflow-x:auto}
table.md th,table.md td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
hr{border:0;border-top:1px solid var(--line);margin:6px 0}
details.tools{font-size:12.5px;margin-top:4px}details.tools ul{margin:4px 0;padding-left:18px}
@media (max-width:800px){.heads,.cols{grid-template-columns:1fr!important}.bubble.user,.expect{max-width:92%}}
</style></head><body>
<div class="top"><h1>{title}</h1>
<div class="bar"><input id="q" type="search" placeholder="ค้นหา รหัสข้อ คำถาม หรือคำตอบ"><button id="f">เฉพาะข้อที่ตก</button>
<button id="c">พับทั้งหมด</button><span class="muted" id="n">{count} บทสนทนา</span></div>
<div class="heads">{heads}</div></div>
<main>{blocks}</main>
<script>
const q=document.getElementById('q'),f=document.getElementById('f'),c=document.getElementById('c'),n=document.getElementById('n');
const convs=[...document.querySelectorAll('.conv')];let onlyFail=false,collapsed=false;
function apply(){const s=q.value.trim().toLowerCase();let k=0;
convs.forEach(e=>{const ok=(!s||e.dataset.s.includes(s))&&(!onlyFail||e.classList.contains('hasfail'));e.style.display=ok?'':'none';if(ok)k++});
n.textContent=k+' บทสนทนา'}
q.addEventListener('input',apply);
f.addEventListener('click',()=>{onlyFail=!onlyFail;f.classList.toggle('on',onlyFail);apply()});
c.addEventListener('click',()=>{collapsed=!collapsed;convs.forEach(e=>e.open=!collapsed);c.textContent=collapsed?'กางทั้งหมด':'พับทั้งหมด'});
</script></body></html>"""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="แปลงไฟล์ผลทดสอบเป็นหน้าแชท HTML")
    ap.add_argument("files", nargs="+", help="ไฟล์ผล .json (ใส่หลายไฟล์ = เทียบข้างกัน)")
    ap.add_argument("--testcases", help="ไฟล์ชุดทดสอบ .csv เพื่อแสดงเฉลย/เกณฑ์")
    ap.add_argument("-o", "--out", help="ไฟล์ HTML ที่จะเขียน (ค่าเริ่มต้น: ชื่อไฟล์แรก + _chat.html)")
    ap.add_argument("--title", help="หัวเรื่องของหน้า")
    ap.add_argument("--imglog", nargs="+", help="ไฟล์ IMAGE_TEST_LOG ของแต่ละไฟล์ผล เรียงตามลำดับไฟล์ผล (แสดงการตัดสินเรื่องรูป)")
    ap.add_argument("--no-open", action="store_true", help="ไม่เปิดเบราว์เซอร์อัตโนมัติ")
    a = ap.parse_args()

    files = [load(p) for p in a.files]
    cases = load_testcases(a.testcases)
    for d, lp in zip(files, a.imglog or []):
        logs = load_imglog(lp)
        n = attach_imglog(d, logs)
        if n != len(logs):
            print(f"⚠️ {os.path.basename(lp)} มี IMGLOG {len(logs)} บรรทัด แต่ {d['_file']} มีเทิร์นที่ส่งรูป {n} เทิร์น "
                  f"— ใช้ log คนละรอบหรือมีของเก่าปน ผลการตัดสินเรื่องรูปอาจผูกผิดเทิร์น")
    out = Path(a.out or Path(a.files[0]).with_name(Path(a.files[0]).stem + "_chat.html"))
    title = a.title or (" vs ".join(d["_file"] for d in files))
    out.write_text(build(files, cases, title), encoding="utf-8")
    print(f"เขียนแล้ว: {out.resolve()}")
    if not a.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()