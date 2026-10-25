"""
assistant.py — ตัวบอต (ชื่อใหม่ของ chatbot_v5.py · ผู้ใช้อนุญาตเปลี่ยนชื่อ 7 ต.ค.)
==========================================================================
ไม่รู้จักแบรนด์ — แบรนด์มาจาก brands/*/brand.yaml ผ่าน core/registry.py

ลำดับตอนเริ่ม
    1. registry อ่าน brand.yaml ทุกแบรนด์ · ตรวจทะเบียนโมเดลรูป (labels = checkpoint · hash = revision)
       และนับจุดใน collection รูป → ตัดสิน image.enabled: auto
    2. โหลดโมเดลที่ใช้ร่วม (Jina · SigLIP) + ViT LoRA ของแบรนด์ที่เปิดรูป
    3. สร้างปลั๊กอิน (create(ctx)) · ประกอบ core/decide + core/turn

สัญญา chat_interaction เท่าเดิมทุกตำแหน่ง — webapi/bot.py · run_answer_eval.py · Gradio เรียกได้เหมือนเดิม
ชื่อเดิม chatbot_v5 ยังใช้ได้ (ไฟล์นั้นชี้มาที่นี่)
"""
import atexit
import os

import torch
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

import gradio as gr                                        # noqa: E402
import google.generativeai as genai                        # noqa: E402
from transformers import (                                 # noqa: E402
    AutoTokenizer, AutoModel,
    ViTImageProcessor, ViTForImageClassification,
    SiglipProcessor, SiglipModel,
)
from peft import PeftModel                                 # noqa: E402

from core.decide import Dialogue                           # noqa: E402
from core.dialogue import state_class                      # noqa: E402
from core.llm import GeminiClient, GenAIClient, parse_thinking  # noqa: E402
from core.models import resolve_image                      # noqa: E402
from core.registry import discover, load_plugins, state_schema  # noqa: E402
from core.tools import ToolLog                             # noqa: E402
from core.turn import TurnEngine                           # noqa: E402
from pipeline_logger import PipelineLogger                 # noqa: E402

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("⚠️ ไม่พบ GEMINI_API_KEY")

JINA_MODEL_ID   = "jinaai/jina-embeddings-v3"
SIGLIP_MODEL_ID = "google/siglip-base-patch16-224"
# ล็อกโมเดล (22 ต.ค.): ตั้ง GEMINI_MODEL ใน .env เป็นชื่อรุ่นตายตัว
# gemini-flash-latest เป็น alias ที่ Google ย้ายไปรุ่นใหม่ได้เอง ผลทดสอบคนละวันจึงอาจมาจากคนละโมเดล
# 23 ต.ค.: ค่าตั้งต้น = gemini-3.8-flash (รุ่นที่ -latest ชี้อยู่ตอนรัน fix8–fix10 · probe_model.py ยืนยัน)
GEMINI_MODEL    = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()
if GEMINI_MODEL.endswith("-latest"):
    print(f"⚠️ GEMINI_MODEL={GEMINI_MODEL} เป็นชื่อลอย ไม่ได้ล็อกรุ่น — ตั้ง GEMINI_MODEL ใน .env ก่อนทดสอบหรือ deploy")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
if DEVICE == "cuda":
    torch.backends.cudnn.benchmark = True

# ================================================================
# 1. แบรนด์
# ================================================================
# BRANDS=a,b จำกัดแบรนด์ที่โหลด (ว่าง = ทุกแบรนด์ที่ enabled) — ใช้วัดว่าแบรนด์ใหม่ไม่เปลี่ยนพฤติกรรมของแบรนด์เดิม
_only = [b.strip() for b in os.environ.get("BRANDS", "").split(",") if b.strip()] or None
_configs = discover(resolve_images=False, only=_only)
BRAND_TITLE = " + ".join(b.info.name for b in _configs)

print("=" * 60)
print(f"  {BRAND_TITLE} Assistant — plugin core")
print(f"  Device: {DEVICE}")
print("=" * 60)


def _collection_points(qdrant_path: str, collection: str) -> int:
    """นับจุดใน collection แล้วปิดทันที — Qdrant แบบไฟล์ล็อกโฟลเดอร์ เปิดค้างไว้ retriever จะเปิดซ้ำไม่ได้"""
    if not qdrant_path or not os.path.isdir(qdrant_path):
        return 0
    from qdrant_client import QdrantClient
    c = QdrantClient(path=qdrant_path)
    try:
        names = {x.name for x in c.get_collections().collections}
        return c.get_collection(collection).points_count if collection in names else 0
    finally:
        c.close()
        del c          # ทิ้งทันที — ไม่งั้น __del__ ไปปิดซ้ำตอนโปรแกรมจบแล้วขึ้น ImportError


for _b in _configs:
    _q = _b.path((_b.config.get("data") or {}).get("qdrant_path"))
    _b.image = resolve_image(_b.key, _b.dir, _b.config.get("image"),
                             collection_points=lambda col, _q=_q: _collection_points(_q, col))
    print(f"   {_b.key}: รูป {'เปิด' if _b.image.enabled else 'ปิด'} — {_b.image.reason}")

# ================================================================
# 2. โมเดล
# ================================================================
print("⏳ โหลด Jina v3...")
jina_tokenizer = AutoTokenizer.from_pretrained(JINA_MODEL_ID, trust_remote_code=True)
jina_model = AutoModel.from_pretrained(
    JINA_MODEL_ID, trust_remote_code=True,
    torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
    attn_implementation="eager"
).to(DEVICE)
jina_model.eval()
print(f"✅ Jina v3 ({'fp16' if DEVICE == 'cuda' else 'fp32'})")


def _adapter_arg(path: str) -> str:
    """พาธ adapter แบบนับจากโฟลเดอร์ที่รัน (./...) ถ้าอยู่ใต้มัน — ให้เหมือนที่ log เดิมบันทึก"""
    if not os.path.isabs(path):
        return path
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else "./" + rel.replace(os.sep, "/")


vit_models: dict = {}
for _b in _configs:
    spec = _b.image.spec if _b.image.enabled else None
    if spec is None:
        continue
    print(f"⏳ โหลด ViT LoRA ({_b.key} · {spec.num_labels} คลาส · {spec.revision})...")
    _proc = ViTImageProcessor.from_pretrained(spec.base)
    _base = ViTForImageClassification.from_pretrained(spec.base, num_labels=spec.num_labels)
    _vit = PeftModel.from_pretrained(_base, _adapter_arg(spec.adapter) if spec.adapter_is_local else spec.adapter,
                                     **({} if spec.adapter_is_local else {"revision": spec.revision}))
    _vit.eval().to(DEVICE)
    if DEVICE == "cuda":
        _vit.half()
    vit_models[_b.key] = (_proc, _vit)
    print(f"✅ ViT LoRA {_b.key} ({'fp16' if DEVICE == 'cuda' else 'fp32'})")

print("⏳ โหลด SigLIP...")
siglip_processor = SiglipProcessor.from_pretrained(SIGLIP_MODEL_ID)
siglip_model     = SiglipModel.from_pretrained(SIGLIP_MODEL_ID).to(DEVICE)
siglip_model.eval()
if DEVICE == "cuda":
    siglip_model.half()
print(f"✅ SigLIP ({'fp16' if DEVICE == 'cuda' else 'fp32'})")

genai.configure(api_key=GEMINI_API_KEY)
# GEMINI_THINKING (13 ต.ค.): จำกัด thinking เพื่อให้ตอบเร็วขึ้น — ต้องใช้แพ็กเกจ google-genai (core/llm.py หัวไฟล์)
# ตั้งค่าผิดหรือ import ไม่ได้ = หยุดตอนสตาร์ต ไม่ถอยไปใช้ของเดิมเงียบ ๆ (จะวัดผิดว่าเร็วขึ้นแล้ว)
GEMINI_THINKING = parse_thinking(os.getenv("GEMINI_THINKING"))
if GEMINI_THINKING:
    try:
        from google import genai as genai_new
    except Exception as e:                       # noqa: BLE001 — ImportError หรือ pydantic ไม่เข้ากัน
        raise RuntimeError(f"ตั้ง GEMINI_THINKING={os.getenv('GEMINI_THINKING')} แต่ import google-genai ไม่ได้ "
                           f"({type(e).__name__}: {e}) — ติดตั้งตามหัวไฟล์ core/llm.py หรือลบบรรทัดนี้ใน .env") from e
    llm_client = GenAIClient(genai_new, GEMINI_MODEL, GEMINI_API_KEY, GEMINI_THINKING)
    print(f"✅ Gemini configured (google-genai · {GEMINI_MODEL} · thinking {GEMINI_THINKING})")
else:
    llm_client = GeminiClient(genai, GEMINI_MODEL)
    print(f"✅ Gemini configured ({GEMINI_MODEL})")

logger = PipelineLogger(log_dir="./logs")
print(f"✅ PipelineLogger → {logger.log_paths()}")
tool_log = ToolLog()

# ================================================================
# 3. ปลั๊กอิน + แกนกลาง
# ================================================================
plugins = load_plugins(_configs, shared=dict(
    device=DEVICE, jina_tokenizer=jina_tokenizer, jina_model=jina_model,
    siglip_processor=siglip_processor, siglip_model=siglip_model,
    vit=vit_models, logger=logger, tool_log=tool_log))
DialogState = state_class(state_schema(_configs))
_scorers = {k: s for k, s in ((k, p.image_scorer()) for k, p in plugins.items()) if s is not None}
_gates = {k: g for k, g in ((k, getattr(p, "image_gate", lambda: None)()) for k, p in plugins.items())
          if g is not None}
dialogue = Dialogue(list(plugins.values()), DialogState, image_brands=tuple(_scorers))
engine = TurnEngine(dialogue, llm_client, logger, tool_log, image_scorers=_scorers, image_gates=_gates)
_dialog_states = engine.dialog_states            # session_id → DialogState.to_dict() (webapi/bot.py ใช้ชื่อนี้)


@atexit.register
def _close_plugins():
    # ปิด Qdrant แบบไฟล์ตอนโปรแกรมจบ — ไม่งั้น client ในปลั๊กอินถูกเก็บกวาดหลัง import ใช้ไม่ได้แล้ว
    for p in plugins.values():
        if hasattr(p, "close"):
            p.close()
print(f"✅ แบรนด์: {', '.join(plugins)} · รับรูป: {', '.join(_scorers) or '-'} · ประตูรูป: {', '.join(_gates) or '-'}")
print("=" * 60)


def chat_interaction(user_text: str, img_input, chat_history: list, last_pids: list = None,
                     session_id: str = "", last_vit_signal=None, last_graph_result=None):
    return engine.chat(user_text, img_input, chat_history, last_pids, session_id,
                       last_vit_signal, last_graph_result)


# ================================================================
# GRADIO UI — คงเดิมทุกอย่าง (ชื่อแบรนด์ในหัวเรื่องมาจาก brand.yaml)
# ================================================================

css = ".gradio-container {max-width: 900px !important}"
js_code = """
function() {
    document.addEventListener('keydown', function(e) {
        const textbox = document.querySelector('#chat-textbox textarea');
        if (e.target === textbox && e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            document.querySelector('#submit-button').click();
        }
    });
}
"""

with gr.Blocks(css=css, js=js_code, title=f"{BRAND_TITLE} Sales AI Assistant v5") as demo:
    chat_state          = gr.State([])
    last_pids_state     = gr.State([])        # ของฝากข้ามเทิร์น: รหัสในโฟกัส
    session_state       = gr.State("")
    last_vit_state      = gr.State(None)      # ของฝากข้ามเทิร์น: สัญญาณรูป
    last_graph_state    = gr.State(None)      # ของฝากข้ามเทิร์น: บริบทกราฟ

    gr.Markdown(f"<h1 style='text-align:center;'>🔗 {BRAND_TITLE} Sales AI Assistant v5</h1>")
    gr.Markdown(
        "<p style='text-align:center;color:#666;'>"
        "Jina v3 + ViT LoRA + SigLIP + Multi-hop GraphRAG + "
        "Confidence-Weighted RRF + Enriched Reranker + Gemini"
        "</p>"
    )

    chatbot_ui = gr.Chatbot(height=600, type="messages", show_label=False)

    with gr.Row():
        img_input_ui = gr.Image(
            type="pil", label="รูปสินค้า", show_label=True, container=True,
            scale=0, height=140, width=140, min_width=140,
            sources=["upload", "clipboard"], interactive=True,
        )
        txt_input = gr.Textbox(
            elem_id="chat-textbox", show_label=False,
            placeholder="พิมพ์ข้อความ · แนบรูปได้ที่กล่องซ้าย หรือปุ่ม 📷 ด้านล่าง",
            scale=10, container=False, lines=1, max_lines=5,
        )
        submit_btn = gr.Button("➤", elem_id="submit-button", variant="primary", scale=0)

    with gr.Row():
        upload_btn = gr.UploadButton("📷 เลือกรูปจากเครื่อง", file_types=["image"],
                                     type="filepath", size="sm")
        clear_btn = gr.Button("🗑️ ล้างประวัติ", variant="secondary", size="sm")

    def _load_uploaded(path):
        if not path:
            return None
        path = path if isinstance(path, str) else getattr(path, "name", path)
        return Image.open(path).convert("RGB")

    upload_btn.upload(fn=_load_uploaded, inputs=upload_btn, outputs=img_input_ui)

    with gr.Accordion("🔍 ข้อมูลอ้างอิง + Log Info", open=False):
        raw_refs = gr.Markdown()
        gr.Markdown(
            f"📋 **Log files (rotate รายวัน):**\n"
            f"- `{logger.log_paths()['jsonl']}` — full structured log (JSONL)\n"
            f"- `{logger.log_paths()['csv']}` — summary spreadsheet (CSV)\n"
            f"- `{logger.log_paths()['txt']}` — human-readable debug (TXT)"
        )

    def reset_inputs():
        return None, ""

    _inputs  = [txt_input, img_input_ui, chat_state,
                last_pids_state, session_state, last_vit_state, last_graph_state]
    _outputs = [chatbot_ui, chat_state, raw_refs,
                last_pids_state, session_state, last_vit_state, last_graph_state]

    submit_btn.click(fn=chat_interaction, inputs=_inputs, outputs=_outputs
                     ).then(fn=reset_inputs, outputs=[img_input_ui, txt_input])
    txt_input.submit(fn=chat_interaction, inputs=_inputs, outputs=_outputs
                     ).then(fn=reset_inputs, outputs=[img_input_ui, txt_input])

    def _clear(old_session=""):
        _dialog_states.pop(old_session, None)
        return [], [], "", [], logger.new_session(), None, None

    clear_btn.click(fn=_clear, inputs=[session_state],
                    outputs=[chatbot_ui, chat_state, raw_refs,
                             last_pids_state, session_state, last_vit_state, last_graph_state])

if __name__ == "__main__":
    # เปิดที่ 127.0.0.1 — Windows เปิด http://0.0.0.0:7860 ในเบราว์เซอร์ไม่ได้
    SERVER_HOST, SERVER_PORT = "127.0.0.1", 7860
    print(f"\n🌐 เปิดเบราว์เซอร์ที่: http://{SERVER_HOST}:{SERVER_PORT}\n")
    demo.launch(share=True, debug=True, server_name=SERVER_HOST, server_port=SERVER_PORT)
