// lib/export.ts — แปลงบทสนทนาเป็น Markdown สำหรับแนบในเล่ม (ทำในเบราว์เซอร์ทั้งหมด ไม่ส่งไปไหน)
//
// ข้อจำกัดที่เขียนลงไฟล์ตรง ๆ ไม่กลบ
//   · รูปที่ผู้ใช้แนบไม่ได้เก็บลงเครื่อง (blob url หมดอายุเมื่อปิดแท็บ) — ใส่แค่ว่ามีรูปแนบ
//   · รูปแบบสินค้าที่บอทส่งมาเปิดไม่ได้เมื่อ session หมดอายุ — ไม่ใส่ลิงก์ที่ตายแล้ว
//   · ข้อความก่อน 27 ต.ค. 2569 ไม่มีเวลากำกับ
//   · 👍/👎 เป็นความเห็นที่เก็บในเบราว์เซอร์เครื่องนี้เท่านั้น
import type { Convo, Msg } from "./chat-types";

const fmt = (ts: number) =>
  new Date(ts).toLocaleString("th-TH", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const VOTE_TH = { up: "👍 มีประโยชน์", down: "👎 ไม่มีประโยชน์" } as const;

function block(m: Msg): string {
  const when = m.at ? ` · ${fmt(m.at)}` : "";
  switch (m.role) {
    case "user": {
      const lines = [`**ผู้ใช้**${when}`, ""];
      if (m.image) lines.push("_(แนบรูป — ไฟล์รูปไม่ได้รวมในเอกสารนี้)_", "");
      if (m.text) lines.push(m.text);
      if (m.failed) lines.push("", "_(ข้อความนี้ส่งไม่สำเร็จ ยังไม่ได้รับคำตอบ)_");
      return lines.join("\n");
    }
    case "bot": {
      const lines = [`**Beltbot**${when}`, "", m.text];
      if (m.vote) lines.push("", `_ความเห็นผู้ใช้: ${VOTE_TH[m.vote]}_`);
      return lines.join("\n");
    }
    case "bot-image":
      return [`**Beltbot**${when}`, "", `_(รูปแบบสินค้า${m.alt ? ` "${m.alt}"` : ""} — ไม่ได้รวมในเอกสารนี้)_`].join("\n");
    case "notice":
      return `> หมายเหตุจากระบบ: ${m.text.replace(/\n/g, " ")}`;
  }
}

export function toMarkdown(c: Convo, now = Date.now()): string {
  const shown = c.messages;
  const votes = shown.filter((m) => m.role === "bot" && m.vote);
  const up = votes.filter((m) => m.role === "bot" && m.vote === "up").length;
  const head = [
    `# ${c.title}`,
    "",
    `ส่งออกจาก Beltbot (ผู้ช่วยสินค้า Movex · Modutech) เมื่อ ${fmt(now)}`,
    "",
    `- จำนวนข้อความ: ${shown.length}`,
    ...(votes.length
      ? [`- ความเห็นต่อคำตอบ: 👍 ${up} · 👎 ${votes.length - up} (เก็บในเบราว์เซอร์เครื่องนี้เท่านั้น)`]
      : []),
    "- คำตอบมาจากแคตตาล็อก ราคา สต็อก และระยะเวลาส่งของ ฝ่ายขายเป็นผู้ยืนยัน",
    "- รูปที่แนบและรูปแบบสินค้าไม่ได้รวมในเอกสารนี้ · ข้อความก่อน 27 ต.ค. 2569 ไม่มีเวลากำกับ",
  ];
  return [...head, "", ...shown.flatMap((m) => ["---", "", block(m), ""])].join("\n").trimEnd() + "\n";
}

/** ชื่อไฟล์: beltbot-<ชื่อบทสนทนา>-YYYYMMDD-HHmm.md · ตัดอักขระที่ Windows ไม่รับ */
export function exportFileName(c: Convo, ext: string, now = Date.now()): string {
  const d = new Date(now);
  const p = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
  const name = c.title
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "")
    .replace(/…$/, "")
    .replace(/\s+/g, "-")
    .slice(0, 40) || "chat";
  return `beltbot-${name}-${stamp}.${ext}`;
}
