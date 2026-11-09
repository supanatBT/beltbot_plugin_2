"""ชื่อโมดูลของตัวตอบ (BOT_MODULE · --module) → โมดูลจริงหลังจัดโฟลเดอร์ 9 พ.ย. 2026

ชื่อเดิมยังรับได้ เพราะไฟล์ผลรันเก่า (archive/) · .env ของแต่ละเครื่อง · agent_lock และเอกสารบทที่ 4 อ้างชื่อนั้น
ไฟล์ shim เดิม (chatbot_v5.py ฯลฯ) ถูกลบแล้ว — ตารางนี้ทำหน้าที่แทนในที่เดียว
"""
import importlib

LEGACY = {
    "assistant": "bot.assistant",
    "chatbot_v5": "bot.assistant",
    "agent_assistant": "agent.assistant",
}


def resolve(name: str) -> str:
    return LEGACY.get(name, name)


def import_bot(name: str):
    return importlib.import_module(resolve(name))
