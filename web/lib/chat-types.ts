// lib/chat-types.ts — รูปแบบข้อมูลบทสนทนาที่เก็บใน localStorage (beltbot.chats.v2)
//
// ฟิลด์ที่มีเครื่องหมาย ? เพิ่มทีหลังแบบไม่บังคับ — ยังเป็น schema v2 (ผู้ใช้ตัดสิน 27 ต.ค.)
// ข้อมูลเก่าที่ไม่มีฟิลด์เหล่านี้อ่านได้ครบ และโค้ดรุ่นเดิมคัดลอกข้อความทั้งก้อน ({...m})
// ฟิลด์ใหม่จึงไม่หายแม้ย้อนกลับไปใช้หน้าเว็บรุ่นก่อน
//   failed     ข้อความผู้ใช้ที่ยังไม่ได้รับคำตอบ
//   at         เวลาที่ข้อความเกิด (ms) — ข้อความเก่าก่อน 27 ต.ค. ไม่มี
//   vote       ความเห็นของผู้ใช้ต่อคำตอบ เก็บในเบราว์เซอร์นี้เท่านั้น ไม่มีที่เก็บฝั่งเซิร์ฟเวอร์
//   turnsLeft  turns_left ล่าสุดจากเซิร์ฟเวอร์
//   suggest    ปุ่มตอบเร็วของคำถามที่บอทถามค้าง (suggestions จากเซิร์ฟเวอร์) — ล้างเมื่อส่งข้อความถัดไป

export type Vote = "up" | "down";

export type Suggestion = { label: string; text: string };

export type Msg =
  | { id: string; role: "user"; text: string; image?: string; failed?: boolean; at?: number }
  | { id: string; role: "bot"; text: string; vote?: Vote; at?: number }
  | { id: string; role: "bot-image"; url: string; alt: string; at?: number }
  | { id: string; role: "notice"; text: string; action?: "reset" | "retry"; at?: number };

export type Convo = {
  id: string;
  title: string;
  messages: Msg[];
  sessionId: string; // session ฝั่งเซิร์ฟเวอร์ — ตายได้ตลอด ถือไว้เฉย ๆ
  state: Record<string, unknown> | null; // DialogState ล่าสุดที่เซิร์ฟเวอร์ส่งกลับ
  updated: number;
  turnsLeft?: number;
  suggest?: Suggestion[];
};
