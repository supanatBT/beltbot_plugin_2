"use client";

/*
  chat.tsx — หน้าแชตแบบหลายบทสนทนา (แถบรายการซ้ายเหมือน Claude)

  สองอย่างที่เพิ่มจากตัวเดิม
    1. เก็บหลายบทสนทนาไว้ใน localStorage ของเครื่องผู้ใช้  (เดิม sessionStorage ที่เดียว แท็บปิดก็หาย)
    2. ส่ง resume กลับไปเมื่อเซิร์ฟเวอร์ลืม session  → ถามต่อในแชตเก่าได้จริง

  ทำไมเก็บที่เบราว์เซอร์ ไม่เก็บที่เซิร์ฟเวอร์
    Hugging Face Spaces รุ่นฟรีล้างไฟล์ทุกครั้งที่ restart และหลับเมื่อไม่มีคนใช้
    Vercel เป็น stateless  → เก็บฝั่งเซิร์ฟเวอร์คือทางที่หายง่ายที่สุด
    ของในเครื่องผู้ใช้อยู่ยาวกว่า และไม่ต้องมีฐานข้อมูลผู้ใช้ให้ดูแล

  ข้อจำกัดที่บอกผู้ใช้ตรง ๆ ไม่กลบ
    · ประวัติอยู่ในเบราว์เซอร์เครื่องนี้เท่านั้น เปลี่ยนเครื่องหรือล้างข้อมูลเว็บแล้วหาย
    · รูปที่บอทส่งมาในแชตเก่าเปิดไม่ได้ เพราะ token ของ MediaRegistry หมดอายุไปกับ session
    · เมื่อเซิร์ฟเวอร์ลืม session จะกู้ได้แค่ 8 เทิร์นล่าสุด (RESUME_MAX_TURNS ใน webapi/bot.py)
      ระบบจึงขึ้นหมายเหตุให้เห็น ไม่ทำเป็นว่าจำได้ทั้งหมด

  สไตล์ของเดิม (.shell .top .list .bubble …) ไม่แตะเลย
  ของใหม่ใช้คลาสขึ้นต้น cv- ทั้งหมด และฝัง CSS ไว้ในไฟล์นี้ (โปรเจกต์ไม่มี globals.css ให้แก้)
*/

import { useCallback, useEffect, useRef, useState } from "react";
import Answer from "./components/Answer";
import { prepareImage, ResizeError } from "@/lib/resize";
import type { Convo, Msg, Vote } from "@/lib/chat-types";
import { exportFileName, toMarkdown } from "@/lib/export";

type Outgoing = { body: string; image: { file: File; url: string } | null };

/** ข้อความที่ส่งไม่สำเร็จและยังส่งใหม่ได้ — อยู่ในหน่วยความจำเท่านั้น (File ลง localStorage ไม่ได้)
    ปุ่มส่งใหม่แสดงเฉพาะที่ notice ตัวนี้ notice เก่า ๆ เหลือแค่ข้อความ */
type Failed = {
  cid: string;
  userId: string; // ฟองข้อความเดิม — ส่งใหม่ใช้ฟองเดิม ไม่เพิ่มฟองซ้ำ
  noticeId: string;
  out: Outgoing;
  code: string;
  attempt: number; // ล้มเหลวมาแล้วกี่ครั้ง
  until: number; // เวลาที่จะส่งใหม่เอง (ms) · 0 = รอผู้ใช้กด
};

/* ส่งใหม่เองได้เฉพาะ error ที่รู้แน่ว่าเซิร์ฟเวอร์ยังไม่ได้ประมวลผลเทิร์นนั้น (ยกเลิกก่อนเรียกบอท)
   upstream / หมดเวลา / เน็ตหลุด ไม่ส่งเอง เพราะ Space อาจตอบเทิร์นนั้นไปแล้ว ส่งซ้ำ = เทิร์นซ้ำใน session
   ตัวเลข = จำนวนครั้งสูงสุดที่ส่งเอง · warming_up ให้มากหน่อยเพราะโหลดโมเดลบน CPU ฟรีใช้เวลาหลายนาที */
const AUTO_RETRY: Record<string, number> = { warming_up: 8, busy: 3, per_minute: 2 };
const AUTO_MAX_WAIT_S = 90; // retry_after นานกว่านี้ไม่นับถอยหลังเอง บอกเวลาแล้วให้ผู้ใช้กดเอง
const TERMINAL = new Set(["session_full", "resume_too_large"]);
const TURNS_WARN = 10; // เหลือข้อความน้อยกว่านี้จึงขึ้นบอก

const STORE_KEY = "beltbot.chats.v2";
const OLD_KEY = "beltbot.chat.v1"; // ของเวอร์ชันเดิมใน sessionStorage
const SIDE_KEY = "beltbot.side.v1"; // จำว่าผู้ใช้พับแถบไว้หรือไม่ — แยกคีย์ ไม่ปนกับประวัติ
const WIDE = "(min-width: 821px)";
const MAX_CONVOS = 30; // เก่ากว่านี้ตัดทิ้ง กัน localStorage เต็ม (โควตาราว 5 MB)
const MAX_STORED = 120; // ข้อความต่อหนึ่งบทสนทนาที่เก็บลงเครื่อง
const RESUME_TURNS = 8; // ต้องไม่เกิน RESUME_MAX_TURNS ใน webapi/bot.py
const RESUME_CHARS = 1200; // ต้องไม่เกิน RESUME_MAX_CHARS ใน webapi/bot.py

const EXAMPLES = [
  "LF 820 K325 รับโหลดได้เท่าไหร่",
  "สายพานสำหรับไลน์เลาะกระดูกไก่ มีรุ่นไหนบ้าง",
  "MP80 C ทนอุณหภูมิได้เท่าไหร่",
];

const uid = () => Math.random().toString(36).slice(2, 10);
const NEW_TITLE = "แชตใหม่";

const newConvo = (): Convo => ({
  id: uid(),
  title: NEW_TITLE,
  messages: [],
  sessionId: "",
  state: null,
  updated: Date.now(),
});

const titleFrom = (s: string) => {
  const t = s.replace(/\s+/g, " ").trim();
  return t ? (t.length > 38 ? t.slice(0, 38) + "…" : t) : NEW_TITLE;
};

const dayLabel = (ts: number) => {
  const d = new Date(ts);
  const today = new Date();
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return "วันนี้";
  const y = new Date(today);
  y.setDate(y.getDate() - 1);
  if (same(d, y)) return "เมื่อวาน";
  return d.toLocaleDateString("th-TH", { day: "numeric", month: "short" });
};

/** วินาทีที่เซิร์ฟเวอร์ให้รอ → คำอ่านง่าย (ปัดขึ้น ไม่บอกเร็วกว่าความจริง) */
const waitLabel = (s: number) =>
  s < 90 ? `${Math.ceil(s)} วินาที` : s < 5400 ? `${Math.ceil(s / 60)} นาที` : `${Math.ceil(s / 3600)} ชั่วโมง`;

/** คัดลอกคำตอบเป็นข้อความอ่านง่าย: ตัดเครื่องหมายตัวหนา/หัวข้อ/โค้ดของ markdown · คงรายการ "- " ไว้ */
const plainText = (md: string) =>
  md
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/`([^`]+)`/g, "$1")
    .trim();

async function copyText(s: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(s);
    return true;
  } catch {
    // http ธรรมดา / เบราว์เซอร์เก่าไม่มี clipboard API — ใช้วิธีเลือกข้อความแทน
    try {
      const ta = document.createElement("textarea");
      ta.value = s;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

/** ของที่ส่งกลับไปให้เซิร์ฟเวอร์กู้บทสนทนา — ข้อความล้วนกับ state เท่านั้น ไม่มีพาธรูป */
function resumeBody(c: Convo): string {
  // ข้อความที่ส่งไม่สำเร็จไม่ใช่ส่วนของบทสนทนาที่บอทเห็น — ไม่ส่งกลับไปเป็นประวัติ
  const msgs = c.messages
    .filter(
      (m): m is Extract<Msg, { role: "user" | "bot" }> =>
        (m.role === "user" && !m.failed) || m.role === "bot",
    )
    .slice(-RESUME_TURNS * 2)
    .map((m) => ({
      role: m.role === "bot" ? "assistant" : "user",
      text: (m.text || "").slice(0, RESUME_CHARS),
    }))
    .filter((m) => m.text);
  return JSON.stringify({ messages: msgs, dialog_state: c.state });
}

/** ตัดของที่ไม่ควรลงเครื่อง: blob url ของรูปที่ผู้ใช้แนบ (ถูก revoke แล้ว) และข้อความเก่าเกิน */
const forStorage = (cs: Convo[]): Convo[] =>
  cs.slice(0, MAX_CONVOS).map((c) => ({
    ...c,
    messages: c.messages
      .slice(-MAX_STORED)
      .map((m) => (m.role === "user" && m.image ? { ...m, image: undefined } : m)),
  }));

export default function Chat() {
  const [convos, setConvos] = useState<Convo[]>([]);
  const [activeId, setActiveId] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [text, setText] = useState("");
  const [image, setImage] = useState<{ file: File; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [sideOpen, setSideOpen] = useState(false);
  const [renaming, setRenaming] = useState("");
  const [storeWarned, setStoreWarned] = useState(false);
  const [failed, setFailed] = useState<Failed | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // busy ใน state อัปเดตช้ากว่าหนึ่งรอบ render — ตัวจับเวลาส่งใหม่ต้องเห็นค่าทันที กันส่งซ้อน
  const busyRef = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const renameRef = useRef<HTMLInputElement>(null);

  // อ่านค่าล่าสุดใน send ได้โดยไม่ติด stale closure
  const convosRef = useRef(convos);
  convosRef.current = convos;
  const activeRef = useRef(activeId);
  activeRef.current = activeId;

  const active = convos.find((c) => c.id === activeId) || null;

  // ── โหลดจากเครื่อง (ครั้งเดียว) + ย้ายของเวอร์ชันเดิมเข้ามา ──
  useEffect(() => {
    let list: Convo[] = [];
    let act = "";
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (Array.isArray(saved?.convos)) {
        list = saved.convos.filter((c: any) => c && typeof c.id === "string" && Array.isArray(c.messages));
        act = typeof saved.activeId === "string" ? saved.activeId : "";
      }
    } catch {}
    if (!list.length) {
      try {
        const old = JSON.parse(sessionStorage.getItem(OLD_KEY) || "null");
        if (Array.isArray(old?.messages) && old.messages.length) {
          const first = old.messages.find((m: any) => m?.role === "user");
          list = [
            {
              ...newConvo(),
              title: titleFrom(first?.text || ""),
              messages: old.messages,
              sessionId: typeof old.sessionId === "string" ? old.sessionId : "",
            },
          ];
          act = list[0].id;
        }
      } catch {}
    }
    if (!list.length) list = [newConvo()];
    list.sort((a, b) => (b.updated || 0) - (a.updated || 0));
    if (!list.some((c) => c.id === act)) act = list[0].id;
    setConvos(list);
    setActiveId(act);
    setLoaded(true);

    // แถบรายการ: จอกว้างเปิดไว้ตามที่ผู้ใช้เคยเลือก · จอแคบปิดเสมอ (เป็นลิ้นชักทับเนื้อหา)
    let pref = true;
    try {
      const v = localStorage.getItem(SIDE_KEY);
      if (v !== null) pref = v === "1";
    } catch {}
    setSideOpen(pref && window.matchMedia(WIDE).matches);
  }, []);

  // ── บันทึกลงเครื่อง · โควตาเต็มแล้วตัดของเก่าทิ้งหนึ่งรอบ ถ้ายังไม่ได้ก็บอกผู้ใช้ ──
  useEffect(() => {
    if (!loaded) return;
    const write = (cs: Convo[]) =>
      localStorage.setItem(STORE_KEY, JSON.stringify({ v: 2, activeId, convos: forStorage(cs) }));
    try {
      write(convos);
    } catch {
      try {
        write(convos.slice(0, Math.max(1, Math.ceil(convos.length / 2))));
      } catch {
        if (!storeWarned) {
          setStoreWarned(true);
          console.warn("เก็บประวัติลงเบราว์เซอร์ไม่ได้ (พื้นที่เต็มหรือถูกปิดไว้)");
        }
      }
    }
  }, [convos, activeId, loaded, storeWarned]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [activeId, active?.messages.length, busy]);

  useEffect(() => {
    if (renaming) renameRef.current?.focus();
  }, [renaming]);

  /** จอแคบ แถบเป็นลิ้นชักทับเนื้อหา เลือกแชตแล้วต้องปิด · จอกว้างเป็นคอลัมน์ ปล่อยค้างไว้
      ไม่บันทึกค่านี้ลง SIDE_KEY เพราะเป็นผลจากการเลือกแชต ไม่ใช่ความตั้งใจจะพับแถบ */
  const hideDrawer = () => {
    if (!window.matchMedia(WIDE).matches) setSideOpen(false);
  };

  const toggleSide = (v: boolean) => {
    setSideOpen(v);
    try {
      localStorage.setItem(SIDE_KEY, v ? "1" : "0");
    } catch {}
  };

  const patch = useCallback((id: string, fn: (c: Convo) => Convo) => {
    setConvos((cs) => {
      const next = cs.map((c) => (c.id === id ? { ...fn(c), updated: Date.now() } : c));
      // บทสนทนาที่ขยับล่าสุดขึ้นบนสุด
      return next.sort((a, b) => b.updated - a.updated);
    });
  }, []);

  const addMsgs = useCallback((id: string, ...ms: Msg[]) => {
    patch(id, (c) => ({ ...c, messages: [...c.messages, ...ms] }));
  }, [patch]);

  const autoGrow = () => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  const pickImage = async (f: File | undefined) => {
    if (!f) return;
    setPreparing(true);
    try {
      const small = await prepareImage(f);
      setImage((old) => {
        if (old) URL.revokeObjectURL(old.url);
        return { file: small, url: URL.createObjectURL(small) };
      });
    } catch (e) {
      const msg = e instanceof ResizeError ? e.message : "เปิดรูปนี้ไม่ได้ครับ";
      if (activeRef.current) addMsgs(activeRef.current, { id: uid(), role: "notice", text: msg });
    } finally {
      setPreparing(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  // ── แชตใหม่ / สลับ / เปลี่ยนชื่อ / ลบ ──
  const startNew = () => {
    const c = newConvo();
    setConvos((cs) => [c, ...cs].slice(0, MAX_CONVOS));
    setActiveId(c.id);
    setText("");
    setImage(null);
    hideDrawer();
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const openConvo = (id: string) => {
    if (busy) return;
    setActiveId(id);
    setText("");
    setImage(null);
    hideDrawer();
  };

  const rename = (id: string, title: string) => {
    patch(id, (c) => ({ ...c, title: title.trim() ? titleFrom(title) : c.title }));
    setRenaming("");
  };

  const remove = (id: string) => {
    const c = convosRef.current.find((x) => x.id === id);
    if (c?.messages.length && !confirm("ลบบทสนทนานี้ออกจากเครื่องนี้ กู้คืนไม่ได้")) return;
    if (c?.sessionId) {
      // คืนหน่วยความจำฝั่งเซิร์ฟเวอร์ ไม่สนผลลัพธ์
      const form = new FormData();
      form.set("session_id", c.sessionId);
      fetch("/api/session/reset", { method: "POST", body: form }).catch(() => {});
    }
    // คำนวณผลลัพธ์นอก updater — ไม่ทำ side effect ข้างใน เพราะ React เรียก updater ซ้ำได้
    const next = convosRef.current.filter((x) => x.id !== id);
    const list = next.length ? next : [newConvo()];
    setConvos(list);
    setFailed((f) => (f?.cid === id ? null : f)); // ไม่ส่งใหม่เข้าแชตที่ลบไปแล้ว
    if (id === activeRef.current) {
      setActiveId(list[0].id);
      setText("");
      setImage(null);
    }
  };

  // ── ส่งข้อความ ──
  /** บันทึกความล้มเหลว: ทำเครื่องหมายฟองว่ายังไม่ได้คำตอบ + notice ที่มีปุ่มส่งใหม่
      ข้อความ error เป็นของเซิร์ฟเวอร์ (message_th) ตามเดิม หน้าเว็บเติมแค่เวลารอที่เซิร์ฟเวอร์บอกมา */
  const fail = useCallback(
    (cid: string, userId: string, out: Outgoing, code: string, text: string, retryAfter: number, attempt: number) => {
      const terminal = TERMINAL.has(code);
      const auto =
        !terminal && attempt <= (AUTO_RETRY[code] ?? 0) && retryAfter > 0 && retryAfter <= AUTO_MAX_WAIT_S;
      let full = text;
      if (!terminal && !auto && retryAfter > AUTO_MAX_WAIT_S) {
        full += ` (ลองใหม่ได้ในราว ${waitLabel(retryAfter)})`;
      }
      const noticeId = uid();
      patch(cid, (c) => ({
        ...c,
        messages: [
          ...c.messages.map((m) => (m.id === userId && m.role === "user" ? { ...m, failed: true } : m)),
          { id: noticeId, role: "notice", text: full, action: terminal ? "reset" : "retry" },
        ],
      }));
      setFailed(
        terminal
          ? null
          : { cid, userId, noticeId, out, code, attempt, until: auto ? Date.now() + retryAfter * 1000 : 0 },
      );
    },
    [patch],
  );

  /** ส่งหนึ่งครั้ง · retry = ส่งข้อความที่ล้มเหลวซ้ำ ใช้ฟองเดิม ไม่เพิ่มฟองใหม่ */
  const deliver = useCallback(
    async (out: Outgoing, retry?: Failed) => {
      if (busyRef.current) return;

      let target = convosRef.current.find((c) => c.id === (retry ? retry.cid : activeRef.current));
      if (!target) {
        if (retry) return setFailed(null); // แชตถูกลบไปแล้ว
        target = newConvo();
        setConvos((cs) => [target as Convo, ...cs]);
        setActiveId(target.id);
        activeRef.current = target.id;
      }
      const cid = target.id;
      const sentSid = target.sessionId;
      const userId = retry ? retry.userId : uid();
      // ประวัติก่อนข้อความนี้ — ตอนส่งใหม่ ฟองของข้อความนี้อยู่ในรายการแล้ว ต้องไม่ส่งไปเป็นประวัติซ้ำ
      const prior = target.messages.filter((m) => m.id !== userId);
      const hadHistory = prior.some((m) => (m.role === "user" && !m.failed) || m.role === "bot");
      const resume = hadHistory ? resumeBody({ ...target, messages: prior }) : "";
      const body = out.body;

      busyRef.current = true;
      setBusy(true);
      // ส่งเรื่องใหม่ในแชตเดียวกัน = ยกเลิกการส่งใหม่ที่ค้าง (ลำดับคำถามจะสลับ) · แชตอื่นไม่แตะ
      setFailed((f) => (f && f.cid !== cid ? f : null));
      if (retry) {
        patch(cid, (c) => ({
          ...c,
          messages: c.messages
            .filter((m) => m.id !== retry.noticeId)
            .map((m) => (m.id === userId && m.role === "user" ? { ...m, failed: undefined } : m)),
        }));
      } else {
        patch(cid, (c) => ({
          ...c,
          title: c.title === NEW_TITLE ? titleFrom(body || "ถามจากรูป") : c.title,
          messages: [...c.messages, { id: userId, role: "user", text: body, image: out.image?.url, at: Date.now() }],
        }));
        setText("");
        setImage(null);
        requestAnimationFrame(autoGrow);
      }

      const form = new FormData();
      form.set("text", body);
      form.set("session_id", sentSid);
      if (resume) form.set("resume", resume);
      if (out.image) form.set("image", out.image.file);

      const attempt = (retry?.attempt ?? 0) + 1;
      try {
        const res = await fetch("/api/chat", { method: "POST", body: form });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          // Retry-After มาทาง header (app.py) — route.ts / space.ts ส่งต่อมาให้แล้ว
          const ra = parseInt(res.headers.get("retry-after") || "", 10);
          fail(
            cid,
            userId,
            out,
            String(data.error || `http_${res.status}`),
            data.message_th || "ส่งไม่สำเร็จครับ รบกวนลองใหม่อีกครั้ง",
            Number.isFinite(ra) ? ra : 0,
            attempt,
          );
          return;
        }

        const resumed = Boolean(resume) && Boolean(sentSid) && data.session_id !== sentSid;
        const incoming: Msg[] = (data.messages || []).map((m: any) =>
          m.type === "image"
            ? { id: uid(), role: "bot-image", url: m.url, alt: m.alt || "แบบสินค้า", at: Date.now() }
            : { id: uid(), role: "bot", text: m.text, at: Date.now() },
        );
        patch(cid, (c) => ({
          ...c,
          sessionId: data.session_id || c.sessionId,
          state: data.state && Object.keys(data.state).length ? data.state : c.state,
          turnsLeft: typeof data.turns_left === "number" ? data.turns_left : c.turnsLeft,
          messages: [
            ...c.messages,
            ...(resumed
              ? ([
                  {
                    id: uid(),
                    role: "notice",
                    text:
                      "แชตนี้ค้างไว้นานจนเซิร์ฟเวอร์เริ่มต้นใหม่ ระบบส่งข้อความ " +
                      `${RESUME_TURNS} เทิร์นล่าสุดกลับไปให้บอทอ่านแล้ว ` +
                      "ถ้าคำตอบดูไม่ต่อเนื่อง รบกวนทวนรุ่นหรือเงื่อนไขอีกครั้งครับ",
                  },
                ] as Msg[])
              : []),
            ...incoming,
          ],
        }));
      } catch {
        fail(cid, userId, out, "network", "เชื่อมต่อไม่ได้ครับ ตรวจอินเทอร์เน็ตแล้วลองใหม่", 0, attempt);
      } finally {
        busyRef.current = false;
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [patch, fail],
  );

  const send = (override?: string) => {
    const body = (override ?? text).trim();
    if (busyRef.current || preparing || (!body && !image)) return;
    void deliver({ body, image });
  };

  const deliverRef = useRef(deliver);
  deliverRef.current = deliver;

  // ── นับถอยหลังแล้วส่งใหม่เอง ──
  useEffect(() => {
    if (!failed?.until) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [failed?.until]);

  useEffect(() => {
    if (failed?.until && now >= failed.until && !busy) void deliverRef.current(failed.out, failed);
  }, [now, failed, busy]);

  /** เอาข้อความที่ส่งไม่สำเร็จกลับมาไว้ในช่องพิมพ์ให้แก้ — ฟองเดิมคงเครื่องหมาย "ยังไม่ได้ส่ง" ไว้ */
  const editFailed = (f: Failed) => {
    setFailed(null);
    setText(f.out.body);
    setImage(f.out.image);
    requestAnimationFrame(() => {
      autoGrow();
      inputRef.current?.focus();
    });
  };

  // ── 👍/👎 — กดซ้ำอันเดิม = ยกเลิก · ไม่เลื่อนบทสนทนาขึ้นบนสุด (ไม่ใช่การคุยต่อ) ──
  const setVote = (cid: string, msgId: string, v: Vote) =>
    setConvos((cs) =>
      cs.map((c) =>
        c.id !== cid
          ? c
          : {
              ...c,
              messages: c.messages.map((m) =>
                m.id === msgId && m.role === "bot" ? { ...m, vote: m.vote === v ? undefined : v } : m,
              ),
            },
      ),
    );

  // ── ส่งออก ──
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node))
        setMenuOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menuOpen]);

  const exportMd = () => {
    setMenuOpen(false);
    if (!active) return;
    const blob = new Blob([toMarkdown(active)], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = exportFileName(active, "md");
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  /** PDF ผ่านหน้าพิมพ์ของเบราว์เซอร์ (เลือก "บันทึกเป็น PDF") — ไม่เพิ่ม dependency
      CSS @media print ซ่อนแถบ ช่องพิมพ์ ปุ่ม และคลี่รายการข้อความให้ยาวเต็มหน้า */
  const exportPdf = () => {
    setMenuOpen(false);
    requestAnimationFrame(() => window.print());
  };

  const messages = active?.messages || [];
  const empty = messages.length === 0;

  return (
    <div className="cv-wrap">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      {sideOpen && <div className="cv-veil" onClick={() => setSideOpen(false)} aria-hidden />}

      <aside
        className={"cv-side" + (sideOpen ? " cv-open" : "")}
        aria-label="รายการบทสนทนา"
        aria-hidden={!sideOpen}
      >
        <div className="cv-head">
          <button className="cv-new" onClick={startNew} disabled={busy}>
            <span aria-hidden>+</span> แชตใหม่
          </button>
          <button
            className="cv-ic"
            onClick={() => toggleSide(false)}
            aria-label="พับแถบรายการ"
            title="พับแถบรายการ"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
              <path
                d="M4 5.5h16v13H4zM10 5.5v13M16.5 9.5 14 12l2.5 2.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>

        <nav className="cv-items">
          {convos.map((c) => (
            <div
              key={c.id}
              className={"cv-item" + (c.id === activeId ? " cv-cur" : "")}
              onClick={() => renaming !== c.id && openConvo(c.id)}
            >
              {renaming === c.id ? (
                <input
                  ref={renameRef}
                  className="cv-rename"
                  defaultValue={c.title}
                  maxLength={60}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={(e) => rename(c.id, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") rename(c.id, (e.target as HTMLInputElement).value);
                    if (e.key === "Escape") setRenaming("");
                  }}
                />
              ) : (
                <>
                  <span className="cv-title">{c.title}</span>
                  <span className="cv-when">{dayLabel(c.updated)}</span>
                  <span className="cv-tools">
                    <button
                      title="เปลี่ยนชื่อ"
                      aria-label="เปลี่ยนชื่อบทสนทนา"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRenaming(c.id);
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
                        <path
                          d="M4 20h4l10-10-4-4L4 16zM14 6l4 4"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.7"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                    <button
                      title="ลบ"
                      aria-label="ลบบทสนทนา"
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(c.id);
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
                        <path
                          d="M5 7h14M9 7V5h6v2M7 7l1 12h8l1-12M10 10v6M14 10v6"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.7"
                          strokeLinecap="round"
                        />
                      </svg>
                    </button>
                  </span>
                </>
              )}
            </div>
          ))}
        </nav>

        <p className="cv-fine">ประวัติเก็บในเบราว์เซอร์เครื่องนี้เท่านั้น ล้างข้อมูลเว็บแล้วหาย</p>
      </aside>

      <div className="cv-main">
        <div className="shell">
          <header className="top">
            <div className="brand">
              {/* เห็นเฉพาะตอนแถบถูกพับ — ปุ่มคลี่กับปุ่มแชตใหม่ ไม่ให้เสียทางเข้าทั้งสองอย่าง */}
              {!sideOpen && (
                <>
                  <button
                    className="cv-ic cv-inhead"
                    onClick={() => toggleSide(true)}
                    aria-label="แสดงแถบรายการ"
                    title="รายการบทสนทนา"
                  >
                    <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden>
                      <path
                        d="M4 5.5h16v13H4zM10 5.5v13M13.5 9.5 16 12l-2.5 2.5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                  <button
                    className="cv-ic cv-inhead cv-plus"
                    onClick={startNew}
                    disabled={busy}
                    aria-label="แชตใหม่"
                    title="แชตใหม่"
                  >
                    <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden>
                      <path
                        d="M12 5.5v13M5.5 12h13"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                </>
              )}
              <span className="mark" aria-hidden>
                <i />
                <i />
                <i />
              </span>
              <div>
                <h1>Beltbot</h1>
                <p>Movex โซ่ท็อปเชน · Modutech สายพานโมดูลาร์</p>
              </div>
            </div>
            <div className="cv-menu" ref={menuRef}>
              <button
                className="ghost cv-export"
                onClick={() => setMenuOpen((v) => !v)}
                disabled={empty}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label="ส่งออกบทสนทนานี้"
                title="ส่งออกบทสนทนานี้"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                  <path
                    d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span className="cv-export-label">ส่งออก</span>
              </button>
              {menuOpen && (
                <div className="cv-pop" role="menu" aria-label="รูปแบบไฟล์">
                  <button role="menuitem" onClick={exportMd} autoFocus>
                    <b>Markdown (.md)</b>
                    <span>ข้อความล้วน แก้ต่อได้ · แนบในเล่ม</span>
                  </button>
                  <button role="menuitem" onClick={exportPdf}>
                    <b>PDF</b>
                    <span>เปิดหน้าพิมพ์ เลือก “บันทึกเป็น PDF”</span>
                  </button>
                  <p>รูปที่แนบและรูปแบบสินค้าไม่ได้รวมในไฟล์</p>
                </div>
              )}
            </div>
          </header>

          {/* หัวกระดาษตอนพิมพ์เท่านั้น — บอกว่าเป็นบทสนทนาไหน ส่งออกเมื่อไหร่ */}
          {active && (
            <div className="cv-print-head" aria-hidden>
              <b>{active.title}</b>
              <span>
                Beltbot · ส่งออกเมื่อ{" "}
                {new Date().toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}
              </span>
              <span>
                คำตอบมาจากแคตตาล็อก ราคา สต็อก และระยะเวลาส่งของ ฝ่ายขายเป็นผู้ยืนยัน ·
                รูปแบบสินค้าในแชตเก่าอาจไม่แสดง (ลิงก์หมดอายุ)
              </span>
            </div>
          )}

          <main className="list" ref={listRef} aria-live="polite">
            {empty && (
              <div className="empty">
                <p>ถามสเปก รหัสรุ่น หรือแนบรูปโซ่ / สายพานให้ช่วยดูรุ่นได้เลยครับ</p>
                <div className="chips">
                  {EXAMPLES.map((q) => (
                    <button key={q} onClick={() => send(q)}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => {
              if (m.role === "user")
                return (
                  <div key={m.id} className={"row me" + (m.failed ? " cv-unsent" : "")}>
                    <div className="bubble user">
                      {m.image && <img src={m.image} alt="รูปที่แนบ" className="thumb" />}
                      {m.text && <div className="plain">{m.text}</div>}
                      {!m.text && !m.image && <div className="plain muted">(รูปที่แนบ)</div>}
                    </div>
                    {m.failed && <span className="cv-unsent-tag">ยังไม่ได้รับคำตอบ</span>}
                  </div>
                );
              if (m.role === "bot")
                return (
                  <BotText
                    key={m.id}
                    text={m.text}
                    vote={m.vote}
                    onVote={(v) => active && setVote(active.id, m.id, v)}
                  />
                );
              if (m.role === "bot-image") return <BotImage key={m.id} url={m.url} alt={m.alt} />;
              const live = m.action === "retry" && failed?.noticeId === m.id ? failed : null;
              const left = live?.until ? Math.max(0, Math.ceil((live.until - now) / 1000)) : 0;
              return (
                <div key={m.id} className="notice" role="status">
                  <span>{m.text}</span>
                  {m.action === "reset" && (
                    <button className="link" onClick={startNew}>
                      เริ่มแชตใหม่
                    </button>
                  )}
                  {live && live.until > 0 && (
                    <>
                      {/* ตัวเลขเปลี่ยนทุกวินาที — ไม่ให้โปรแกรมอ่านจอประกาศซ้ำทุกวินาที */}
                      <span className="cv-count" aria-live="off">
                        ส่งใหม่อัตโนมัติใน {left} วินาที
                      </span>
                      <button className="link" onClick={() => void deliver(live.out, live)} disabled={busy}>
                        ส่งเลย
                      </button>
                      <button className="link" onClick={() => setFailed({ ...live, until: 0 })}>
                        ยกเลิก
                      </button>
                    </>
                  )}
                  {live && live.until === 0 && (
                    <>
                      <button className="link" onClick={() => void deliver(live.out, live)} disabled={busy}>
                        ส่งอีกครั้ง
                      </button>
                      <button className="link" onClick={() => editFailed(live)} disabled={busy}>
                        แก้ก่อนส่ง
                      </button>
                    </>
                  )}
                </div>
              );
            })}
            {busy && (
              <div className="row">
                <div className="bubble bot typing" aria-label="กำลังตอบ">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
          </main>

          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            {/* turns_left มาจากเซิร์ฟเวอร์ตรง ๆ · บอกเฉพาะตอนใกล้ครบ ไม่รกจอ */}
            {active?.turnsLeft !== undefined && active.turnsLeft <= TURNS_WARN && (
              <p className="cv-left" role="status">
                {active.turnsLeft > 0 ? (
                  <>บทสนทนานี้ถามต่อได้อีก {active.turnsLeft} ข้อความ จากนั้นต้องเริ่มแชตใหม่</>
                ) : (
                  <>
                    บทสนทนานี้ครบจำนวนข้อความแล้ว{" "}
                    <button type="button" className="link" onClick={startNew} disabled={busy}>
                      เริ่มแชตใหม่
                    </button>
                  </>
                )}
              </p>
            )}
            {(image || preparing) && (
              <div className="attach">
                {preparing ? (
                  <span className="muted">กำลังเตรียมรูป…</span>
                ) : (
                  image && (
                    <>
                      <img src={image.url} alt="รูปที่จะส่ง" />
                      <button type="button" className="link" onClick={() => setImage(null)}>
                        เอาออก
                      </button>
                    </>
                  )
                )}
              </div>
            )}
            <div className="bar">
              <button
                type="button"
                className="icon"
                onClick={() => fileRef.current?.click()}
                disabled={busy || preparing}
                aria-label="แนบรูป"
                title="แนบรูปสินค้า"
              >
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
                  <path
                    d="M4 7.5A2.5 2.5 0 0 1 6.5 5h1.8l1.2-1.6h5l1.2 1.6h1.8A2.5 2.5 0 0 1 20 7.5v9A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <circle cx="12" cy="12" r="3.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
                </svg>
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
                hidden
                onChange={(e) => pickImage(e.target.files?.[0])}
              />
              <textarea
                ref={inputRef}
                rows={1}
                value={text}
                maxLength={1000}
                placeholder="พิมพ์คำถาม หรือแนบรูปสินค้า"
                onChange={(e) => {
                  setText(e.target.value);
                  autoGrow();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    send();
                  }
                }}
                onPaste={(e) => {
                  const f = Array.from(e.clipboardData.files).find((x) => x.type.startsWith("image/"));
                  if (f) {
                    e.preventDefault();
                    pickImage(f);
                  }
                }}
              />
              <button type="submit" className="send" disabled={busy || preparing || (!text.trim() && !image)}>
                ส่ง
              </button>
            </div>
            <p className="fine">คำตอบมาจากแคตตาล็อก ราคา สต็อก และระยะเวลาส่งของ ฝ่ายขายเป็นผู้ยืนยัน</p>
          </form>
        </div>
      </div>
    </div>
  );
}

/** คำตอบของบอท + ปุ่มคัดลอก + 👍/👎
    ความเห็นเก็บในเบราว์เซอร์นี้เท่านั้น ไม่มีที่เก็บฝั่งเซิร์ฟเวอร์ — บอกตรง ๆ ใต้ปุ่มเมื่อกดแล้ว */
function BotText({ text, vote, onVote }: { text: string; vote?: Vote; onVote: (v: Vote) => void }) {
  const [copied, setCopied] = useState<"" | "ok" | "fail">("");
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(""), 1800);
    return () => clearTimeout(t);
  }, [copied]);
  const thumb = (v: Vote, label: string, d: string) => (
    <button
      type="button"
      className={"cv-act cv-vote" + (vote === v ? " cv-on" : "")}
      aria-label={label}
      aria-pressed={vote === v}
      title={label}
      onClick={() => onVote(v)}
    >
      <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
        <path d={d} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      </svg>
    </button>
  );
  return (
    <div className="row cv-botrow">
      <div className="bubble bot md">
        <Answer text={text} />
      </div>
      <div className="cv-acts">
        <button
          type="button"
          className="cv-act"
          aria-label="คัดลอกคำตอบ"
          title="คัดลอกคำตอบ"
          onClick={async () => setCopied((await copyText(plainText(text))) ? "ok" : "fail")}
        >
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
            <path
              d="M9 9h10v11H9zM15 9V4H5v11h4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinejoin="round"
            />
          </svg>
          <span role="status">{copied === "ok" ? "คัดลอกแล้ว" : copied === "fail" ? "คัดลอกไม่ได้" : "คัดลอก"}</span>
        </button>
        {thumb("up", "คำตอบนี้มีประโยชน์", "M7 11v9H4v-9zM7 11l4-7c1.5 0 2.5 1 2.2 2.6L12.6 10H19a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17.8 20H7")}
        {thumb("down", "คำตอบนี้ไม่มีประโยชน์", "M7 13V4H4v9zM7 13l4 7c1.5 0 2.5-1 2.2-2.6L12.6 14H19a2 2 0 0 0 2-2.3l-1.2-6A2 2 0 0 0 17.8 4H7")}
        {vote && <span className="cv-vote-note">บันทึกไว้ในเบราว์เซอร์นี้เท่านั้น ไม่ได้ส่งถึงผู้พัฒนา · ส่งออกพร้อมบทสนทนาได้</span>}
      </div>
      {vote && (
        <span className="cv-print-vote">ความเห็นผู้ใช้: {vote === "up" ? "👍 มีประโยชน์" : "👎 ไม่มีประโยชน์"}</span>
      )}
    </div>
  );
}

/** รูป drawing — token ของแชตเก่าหมดอายุไปกับ session จึงต้องบอกตรง ๆ ไม่ปล่อยเป็นรูปแตก */
function BotImage({ url, alt }: { url: string; alt: string }) {
  const [dead, setDead] = useState(false);
  if (dead)
    return (
      <div className="notice" role="status">
        <span>รูปแบบสินค้าในแชตนี้หมดอายุแล้วครับ รบกวนถามรุ่นเดิมอีกครั้งเพื่อให้ระบบส่งรูปใหม่</span>
      </div>
    );
  return (
    <div className="row">
      <a className="bubble bot drawing" href={url} target="_blank" rel="noreferrer">
        <img src={url} alt={alt} onError={() => setDead(true)} />
      </a>
    </div>
  );
}

/* ── CSS ของส่วนที่เพิ่มใหม่เท่านั้น · ไม่ทับคลาสเดิม ── */
const CSS = `
.cv-wrap{display:flex;height:100dvh;min-height:0;overflow:hidden}
.cv-main{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden}
.cv-main>.shell{flex:1;min-height:0}

/* พับแถบ: จอกว้างใช้ display เพื่อคืนพื้นที่ให้บทสนทนาเต็มจอ
   จอแคบแถบเป็นลิ้นชักลอยทับอยู่แล้ว จึงใช้ transform เพื่อให้มีจังหวะเลื่อน */
.cv-side{display:none;flex-direction:column;gap:8px;width:260px;flex:0 0 260px;
  padding:12px 10px;border-right:1px solid rgba(128,128,128,.22);overflow:hidden}
.cv-side.cv-open{display:flex}

.cv-head{display:flex;align-items:center;gap:6px}
.cv-new{display:flex;align-items:center;justify-content:center;gap:8px;flex:1;min-width:0;
  padding:9px 12px;border:1px solid rgba(128,128,128,.3);border-radius:10px;
  background:transparent;color:inherit;font:inherit;font-size:14px;cursor:pointer}
.cv-new:hover{background:rgba(128,128,128,.1)}
.cv-new:disabled{opacity:.5;cursor:default}
.cv-new span{font-size:17px;line-height:1}

.cv-ic{display:grid;place-items:center;flex:0 0 auto;width:34px;height:34px;padding:0;
  border:0;border-radius:9px;background:transparent;color:inherit;opacity:.65;cursor:pointer}
.cv-ic:hover{opacity:1;background:rgba(128,128,128,.14)}
.cv-ic:disabled{opacity:.35;cursor:default;background:transparent}
.cv-inhead{margin-right:2px}

.cv-items{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:2px;
  margin:0 -4px;padding:0 4px}
.cv-item{position:relative;display:flex;align-items:center;gap:8px;
  padding:8px 10px;border-radius:9px;cursor:pointer;font-size:13.5px;line-height:1.35}
.cv-item:hover{background:rgba(128,128,128,.11)}
.cv-cur{background:rgba(128,128,128,.17)}
.cv-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cv-when{font-size:11px;opacity:.5;flex:0 0 auto}
.cv-tools{display:none;gap:2px;flex:0 0 auto}
.cv-item:hover .cv-tools,.cv-cur .cv-tools{display:flex}
.cv-item:hover .cv-when,.cv-cur .cv-when{display:none}
.cv-tools button{display:grid;place-items:center;width:24px;height:24px;padding:0;
  border:0;border-radius:6px;background:transparent;color:inherit;opacity:.6;cursor:pointer}
.cv-tools button:hover{opacity:1;background:rgba(128,128,128,.2)}
.cv-rename{width:100%;padding:3px 6px;border:1px solid rgba(128,128,128,.45);
  border-radius:6px;background:transparent;color:inherit;font:inherit;font-size:13.5px}

.cv-fine{margin:0;font-size:11px;line-height:1.5;opacity:.45}

/* ปุ่มใต้คำตอบ — จางไว้ไม่แย่งสายตาจากเนื้อหา ชี้หรือโฟกัสแล้วชัด */
.cv-botrow{flex-direction:column;align-items:flex-start;gap:2px}
.cv-acts{display:flex;flex-wrap:wrap;align-items:center;gap:4px;padding-left:4px}
.cv-act{display:inline-flex;align-items:center;gap:5px;height:28px;padding:0 8px;border:0;border-radius:7px;
  background:transparent;color:var(--ink-2);font-size:12.5px;white-space:nowrap}
.cv-act:hover,.cv-act:focus-visible{color:var(--ink);background:rgba(128,128,128,.12)}

/* ข้อความที่ส่งไม่สำเร็จ — ฟองจางลง + ป้ายบอกตรง ๆ (คงอยู่แม้โหลดหน้าใหม่) */
.cv-unsent{flex-direction:column;align-items:flex-end;gap:3px}
.cv-unsent .bubble{opacity:.6}
.cv-unsent-tag{font-size:12px;color:var(--ink-2)}
.cv-count{color:var(--ink-2);font-variant-numeric:tabular-nums}
.cv-left{margin:0 4px 8px;font-size:13px;color:var(--ink-2);text-align:center}

/* ส่งออก — ปุ่มในหัว + เมนูเล็ก */
.cv-menu{position:relative;flex:0 0 auto}
.cv-export{display:inline-flex;align-items:center;gap:6px}
.cv-pop{position:absolute;right:0;top:calc(100% + 6px);z-index:30;width:250px;padding:6px;
  background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.14)}
.cv-pop button{display:flex;flex-direction:column;align-items:flex-start;width:100%;padding:8px 10px;border:0;
  border-radius:8px;background:transparent;color:var(--ink);text-align:left}
.cv-pop button:hover,.cv-pop button:focus-visible{background:var(--bg)}
.cv-pop b{font-weight:600;font-size:14px}
.cv-pop span{font-size:12.5px;color:var(--ink-2)}
.cv-pop p{margin:4px 10px 4px;font-size:12px;color:var(--ink-2)}
@media (max-width:520px){.cv-export-label{display:none}.cv-export{padding:6px 9px}}

.cv-vote{padding:0 7px}
.cv-on{color:var(--accent)}
.cv-on:hover{color:var(--accent)}
/* แยกบรรทัดของตัวเอง ไม่เบียดปุ่มบนจอแคบ */
.cv-vote-note{flex-basis:100%;font-size:12px;line-height:1.45;color:var(--ink-2);padding:0 4px 2px}

.cv-print-head,.cv-print-vote{display:none}

/* ── คำตอบอ่านง่าย (รอบ 3) ── */
.md h1,.md h2,.md h3,.md h4{font-size:1.02em;font-weight:600;line-height:1.4;margin:.75em 0 .3em}
.md h1:first-child,.md h2:first-child,.md h3:first-child{margin-top:0}
/* รหัสรุ่นที่บอททำตัวหนามา — สีเน้นของธีม (ผ่าน AA ทั้งสองโหมด) */
.md strong{font-weight:600;color:var(--accent)}
.md code{padding:.05em .35em;border-radius:5px;background:var(--bg);border:1px solid var(--line)}
.md li{margin:.1em 0}
.md hr{border:0;border-top:1px solid var(--line);margin:.8em 0}
.cv-table{max-width:100%;overflow-x:auto;margin:.4em 0 .7em;border:1px solid var(--line);border-radius:10px}
.cv-table:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.cv-table table{border-collapse:collapse;width:100%;font-size:.93em;font-variant-numeric:tabular-nums}
.cv-table th,.cv-table td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
.cv-table th{background:var(--bg);font-weight:600}
.cv-table tr:last-child td{border-bottom:0}
.cv-contact{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:.6em;padding-top:.6em;
  border-top:1px dashed var(--line)}
.cv-contact-label{font-size:.9em;color:var(--ink-2)}
.cv-chip{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:4px 11px;border:1px solid var(--line);
  border-radius:999px;color:var(--ink);text-decoration:none;font-size:.92em;background:var(--panel)}
.cv-chip:hover,.cv-chip:focus-visible{border-color:var(--accent);color:var(--accent)}

/* พิมพ์ / บันทึกเป็น PDF — เอาเฉพาะบทสนทนา สีสว่างเสมอ (โหมดมืดพิมพ์แล้วหมึกเปลือง) */
@media print{
  :root{--bg:#fff;--panel:#fff;--ink:#111;--ink-2:#444;--line:#bbb;--user:#e9f0fa;--user-ink:#111;
    --notice:#f4f4f4;--notice-line:#ccc;color-scheme:light}
  @page{margin:14mm}
  body{background:#fff}
  .cv-side,.cv-veil,.top,.composer,.cv-acts,.typing,.notice .link,.cv-count,.empty{display:none!important}
  .cv-wrap,.cv-main,.shell,.list{height:auto!important;overflow:visible!important;max-width:none}
  .cv-wrap{display:block}
  .list{padding:0}
  .cv-print-head{display:flex;flex-direction:column;gap:2px;margin:0 0 14px;padding-bottom:10px;
    border-bottom:1px solid #999;font-size:12px;color:#444}
  .cv-print-head b{font-size:17px;color:#111}
  .cv-print-vote{display:block;font-size:12px;color:#444;padding-left:4px}
  .bubble,.notice,.drawing{break-inside:avoid}
  .cv-table{overflow:visible;border-color:#999}
  .cv-chip{border:0;padding:0;min-height:0}
  .bubble.user{border:1px solid #c5d3e6}
  .cv-unsent .bubble{opacity:1}
}
.cv-veil{display:none}

@media (max-width:820px){
  /* visibility คู่กับ transform เพื่อให้ลิ้นชักที่ปิดอยู่หลุดจากลำดับ tab ด้วย
     ไม่ใช่แค่เลื่อนออกนอกจอแต่ยังกดเข้าไปด้วยคีย์บอร์ดได้ */
  .cv-side{display:flex;position:fixed;inset:0 auto 0 0;z-index:40;width:82vw;max-width:300px;
    transform:translateX(-102%);visibility:hidden;
    transition:transform .18s ease,visibility .18s;
    background:var(--panel,#fff);box-shadow:0 0 40px rgba(0,0,0,.18)}
  .cv-side.cv-open{transform:none;visibility:visible}
  .cv-veil{display:block;position:fixed;inset:0;z-index:35;background:rgba(0,0,0,.35)}
}
/* จอมือถือแคบ ๆ หัวข้อมีที่น้อย ตัดปุ่มแชตใหม่ในหัวทิ้ง
   ไม่ได้เสียทางเข้า เพราะกดปุ่มแรกเปิดลิ้นชักแล้วมีปุ่มเต็มอยู่บนสุด */
@media (max-width:520px){.cv-plus{display:none}}
@media (prefers-reduced-motion:reduce){.cv-side{transition:none}}
`;
