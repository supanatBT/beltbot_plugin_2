"""ชื่อเดิม — ตัวบอตเปลี่ยนชื่อเป็น assistant.py แล้ว (ชั้น 5 · ผู้ใช้อนุญาต 7 ต.ค.)

ไม่ใช่สำเนา: แทนตัวเองด้วยโมดูล assistant ใน sys.modules
คงไว้เพราะ BOT_MODULE เดิม · run_answer_eval.py --module chatbot_v5 · เอกสารหลายฉบับยังใช้ชื่อนี้
"""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("assistant")
