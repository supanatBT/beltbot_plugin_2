"use client";

/*
  Answer.tsx — แสดงคำตอบของบอท (markdown) ให้อ่านง่าย

  · ตาราง: remark-gfm (react-markdown ไม่แปลงตารางเอง) · ห่อด้วยกล่องเลื่อนแนวนอน ไม่ล้นจอมือถือ
  · รหัสรุ่น: เน้นเฉพาะที่บอททำตัวหนา/โค้ดมาเอง — ไม่เดารหัสจากข้อความด้วย regex
  · บรรทัด "ติดต่อฝ่ายขาย: โทร … · อีเมล …" (sales_contact.py) → ปุ่มโทร/อีเมล
    ปุ่มแสดงเบอร์และอีเมลเดิมทุกตัวอักษร ไม่เติมคำที่ฟังเหมือนรับปากว่าจะติดต่อกลับ
    จับเฉพาะบรรทัดรูปแบบตรงตัวเท่านั้น รูปแบบอื่นปล่อยเป็นข้อความตามเดิม (ไม่เดา)
  ข้อความที่คัดลอก/ส่งออกยังเป็นข้อความดิบของบอท ไม่ผ่านไฟล์นี้
*/

import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

type Contact = { phone?: string; email?: string };

const CONTACT_LINE = /^ติดต่อฝ่ายขาย:\s*(.+)$/m;

/** แยกบรรทัดติดต่อฝ่ายขายออกจากเนื้อคำตอบ — คืน contact = null ถ้าไม่ใช่รูปแบบที่รู้จัก */
export function splitContact(text: string): { body: string; contact: Contact | null } {
  const m = CONTACT_LINE.exec(text);
  if (!m) return { body: text, contact: null };
  const parts = m[1].split("·").map((s) => s.trim());
  const c: Contact = {};
  for (const p of parts) {
    const tel = /^โทร\s+([0-9][0-9\s-]{5,}[0-9])$/.exec(p);
    const mail = /^อีเมล\s+([\w.+-]+@[\w-]+(?:\.[\w-]+)+)$/.exec(p);
    if (tel) c.phone = tel[1];
    else if (mail) c.email = mail[1];
    else return { body: text, contact: null }; // มีส่วนที่ไม่รู้จัก → ไม่แตะทั้งบรรทัด
  }
  if (!c.phone && !c.email) return { body: text, contact: null };
  const body = (text.slice(0, m.index) + text.slice(m.index + m[0].length)).replace(/\n{3,}/g, "\n\n").trim();
  return { body, contact: c };
}

const PhoneIcon = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
    <path
      d="M6.6 3.5h3l1.4 4-2 1.3a11 11 0 0 0 6.2 6.2l1.3-2 4 1.4v3a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 4.6 5.7a2 2 0 0 1 2-2.2z"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

const MailIcon = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
    <path d="M3.5 6h17v12h-17zM3.5 6.5l8.5 6.5 8.5-6.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
  </svg>
);

export default function Answer({ text }: { text: string }) {
  const { body, contact } = splitContact(text);
  return (
    <>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={{
          table: ({ node: _n, ...p }) => (
            <div className="cv-table" role="region" aria-label="ตาราง (เลื่อนด้านข้างได้)" tabIndex={0}>
              <table {...p} />
            </div>
          ),
          a: ({ node: _n, href, ...p }) => (
            <a href={href} {...p} {...(href?.startsWith("http") ? { target: "_blank", rel: "noreferrer" } : {})} />
          ),
        }}
      >
        {body}
      </ReactMarkdown>
      {contact && (
        <div className="cv-contact">
          <span className="cv-contact-label">ติดต่อฝ่ายขาย:</span>
          {contact.phone && (
            <a className="cv-chip" href={`tel:${contact.phone.replace(/[^0-9+]/g, "")}`} aria-label={`โทรหาฝ่ายขาย ${contact.phone}`}>
              <PhoneIcon />
              โทร {contact.phone}
            </a>
          )}
          {contact.email && (
            <a className="cv-chip" href={`mailto:${contact.email}`} aria-label={`ส่งอีเมลถึงฝ่ายขาย ${contact.email}`}>
              <MailIcon />
              อีเมล {contact.email}
            </a>
          )}
        </div>
      )}
    </>
  );
}
