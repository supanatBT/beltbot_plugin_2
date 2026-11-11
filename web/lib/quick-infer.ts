// quick-infer.ts — ปุ่มตอบเร็วสำรองฝั่งหน้าเว็บ (10 พ.ย. 2026)
//
// ทำไม: ปุ่มเดิมมาจาก backend (webapi/bot.py suggestions_for) ซึ่งอ่าน "pending" ใน DialogState ของบอทตัวเก่า
// ตั้งแต่ 7 พ.ย. Space ใช้ agent เป็น backend — agent ไม่มี DialogState ฟิลด์ suggestions จึงว่างเสมอ ปุ่มหาย
//
// กติกา
//   · backend ส่งปุ่มมา → ใช้ของ backend เสมอ (ไฟล์นี้ไม่ถูกเรียก)
//   · backend ไม่ส่ง → อ่านเฉพาะ "ย่อหน้าสุดท้าย" ของคำตอบล่าสุด ถ้าเป็นคำถามเลือกระหว่างสองทางที่รู้จัก จึงสร้างปุ่ม
//   · ไม่แน่ใจ = ไม่มีปุ่ม (ปุ่มเป็นของเสริม ผู้ใช้พิมพ์เองได้เสมอ) — ไม่เปลี่ยนสิ่งที่ agent ตอบ
//   · ข้อความที่ปุ่มส่ง = คำที่ผู้ใช้พิมพ์เองได้อยู่แล้ว ไม่มีชื่อฟิลด์ภายใน

import type { Suggestion } from "./chat-types";

/** "…ไลน์แห้งหรือไลน์เปียกครับ?" · "แห้ง หรือ เปียก" · "สภาวะเปียกหรือสภาวะแห้ง" */
const WET_DRY = /(แห้ง|เปียก)\s*(?:\)|ครับ|คะ)?\s*หรือ(?:ว่า)?\s*(?:เป็น\s*)?(?:ไลน์|สภาวะ|งาน|แบบ)?\s*(เปียก|แห้ง)/;
/** "Movex หรือ Modutech" · "แบรนด์ไหน" (ต้องเอ่ยทั้งสองแบรนด์ในย่อหน้าเดียวกัน) */
const BRAND_OR = /(movex|modutech)[^\n]{0,60}?หรือ[^\n]{0,60}?(modutech|movex)/i;
const BRAND_WHICH = /แบรนด์(?:ไหน|ใด)/;
/** เมนูถามแบรนด์ของระบบ (engine/core/templates.py ask_brand · agent/agent.py) — ขึ้นบรรทัดเดียว ไม่มีบรรทัดว่าง
 *  เมนูทั้งก้อนจึงเป็นย่อหน้าเดียว และชื่อสองแบรนด์อยู่คนละบรรทัด BRAND_OR จับไม่ได้ (พบบนเว็บ 11 พ.ย.) */
const BRAND_MENU = /ถามถึงสินค้าแบบไหน|ตอบเป็นเลขข้อหรือชื่อแบรนด์/;
/** ย่อหน้านั้นต้องเป็นคำถามจริง ไม่ใช่ประโยคบอกเล่า เช่น "สภาวะเปียกจะต่ำกว่าสภาวะแห้ง" */
//   ไม่นับ "…ครับ" ท้ายประโยคเป็นคำถาม — "ใช้ได้ทั้งไลน์แห้งหรือไลน์เปียกครับ" เป็นประโยคบอกเล่า
const ASKS = /[?？]|ไหม|หรือเปล่า|หรือไม่|รบกวน|ช่วยแจ้ง|ช่วยบอก|ทราบ|แจ้งด้วย/;
/** "ได้ทั้งแห้งหรือเปียก" = บอกเล่า แม้มีเครื่องหมายคำถามในย่อหน้าเดียวกัน */
const BOTH = /ทั้ง(?:ใน)?\s*(?:ไลน์|สภาวะ|งาน)?\s*(?:แห้ง|เปียก)/;

const WET_DRY_BUTTONS: Suggestion[] = [
  { label: "ไลน์แห้ง", text: "ไลน์แห้ง" },
  { label: "ไลน์เปียก", text: "ไลน์เปียก" },
  { label: "ไม่แน่ใจ", text: "ไม่แน่ใจว่าเปียกหรือแห้ง" },
];
// ป้ายเดียวกับปุ่มเดิมของ backend: "<ชื่อแบรนด์> (<ชนิดสินค้า>)" → ส่งชื่อแบรนด์
const BRAND_BUTTONS: Suggestion[] = [
  { label: "Movex (โซ่ท็อปเชน)", text: "Movex" },
  { label: "Modutech (สายพานโมดูลาร์)", text: "Modutech" },
];

/** ย่อหน้าสุดท้ายที่มีตัวอักษร — ตัด markdown ที่กระทบการจับคำ (ตัวหนา · ลิงก์) */
function lastParagraph(text: string): string {
  const parts = (text || "")
    .replace(/\*\*|__|`/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

export function inferSuggestions(lastBotText: string | undefined): Suggestion[] | undefined {
  const p = lastParagraph(lastBotText || "");
  if (!p || !ASKS.test(p)) return undefined;
  if (WET_DRY.test(p) && !BOTH.test(p)) return WET_DRY_BUTTONS;
  const both = /movex/i.test(p) && /modutech/i.test(p);
  if (BRAND_OR.test(p) || ((BRAND_WHICH.test(p) || BRAND_MENU.test(p)) && both)) return BRAND_BUTTONS;
  return undefined;
}
