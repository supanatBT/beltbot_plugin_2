"""ชื่อเดิม — ตัวจริงย้ายไป brands/modutech/gates.py (ชั้น 1 ของ HANDOFF_brand_plugin)

ไฟล์นี้ไม่ใช่สำเนา: แทนตัวเองด้วยโมดูลตัวจริงใน sys.modules
`import modutech_gates` กับ `import brands.modutech.gates` จึงได้วัตถุเดียวกัน
ค่าที่เทสต์ monkeypatch ผ่านชื่อเดิมไปถึงโค้ดจริงเสมอ ไม่มีทางเกิด shadow copy
คงไว้เพราะชุดเกตเรียกชื่อนี้ตรง ๆ — แก้เทสต์คือเปลี่ยนเครื่องมือวัด
"""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("brands.modutech.gates")
