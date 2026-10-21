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
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import { prepareImage, ResizeError } from "@/lib/resize";

type Msg =
  | { id: string; role: "user"; text: string; image?: string }
  | { id: string; role: "bot"; text: string }
  | { id: string; role: "bot-image"; url: string; alt: string }
  | { id: string; role: "notice"; text: string; action?: "reset" | "retry" };

type Convo = {
  id: string;
  title: string;
  messages: Msg[];
  sessionId: string; // session ฝั่งเซิร์ฟเวอร์ — ตายได้ตลอด ถือไว้เฉย ๆ
  state: Record<string, unknown> | null; // DialogState ล่าสุดที่เซิร์ฟเวอร์ส่งกลับ
  updated: number;
};

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

/** ของที่ส่งกลับไปให้เซิร์ฟเวอร์กู้บทสนทนา — ข้อความล้วนกับ state เท่านั้น ไม่มีพาธรูป */
function resumeBody(c: Convo): string {
  const msgs = c.messages
    .filter((m): m is Extract<Msg, { role: "user" | "bot" }> => m.role === "user" || m.role === "bot")
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
    if (id === activeRef.current) {
      setActiveId(list[0].id);
      setText("");
      setImage(null);
    }
  };

  // ── ส่งข้อความ ──
  const send = useCallback(
    async (override?: string) => {
      const body = (override ?? text).trim();
      if (busy || preparing || (!body && !image)) return;

      let target = convosRef.current.find((c) => c.id === activeRef.current);
      if (!target) {
        target = newConvo();
        setConvos((cs) => [target as Convo, ...cs]);
        setActiveId(target.id);
        activeRef.current = target.id;
      }
      const cid = target.id;
      const sentSid = target.sessionId;
      const hadHistory = target.messages.some((m) => m.role === "user" || m.role === "bot");
      const resume = hadHistory ? resumeBody(target) : "";
      const sent = image;

      patch(cid, (c) => ({
        ...c,
        title: c.title === NEW_TITLE ? titleFrom(body || "ถามจากรูป") : c.title,
        messages: [...c.messages, { id: uid(), role: "user", text: body, image: sent?.url }],
      }));
      setText("");
      setImage(null);
      requestAnimationFrame(autoGrow);
      setBusy(true);

      const form = new FormData();
      form.set("text", body);
      form.set("session_id", sentSid);
      if (resume) form.set("resume", resume);
      if (sent) form.set("image", sent.file);

      try {
        const res = await fetch("/api/chat", { method: "POST", body: form });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const retryable = data.error !== "session_full" && data.error !== "resume_too_large";
          addMsgs(cid, {
            id: uid(),
            role: "notice",
            text: data.message_th || "ส่งไม่สำเร็จครับ รบกวนลองใหม่อีกครั้ง",
            action: retryable ? "retry" : "reset",
          });
          if (retryable) {
            setText(body);
            if (sent) setImage(sent);
          }
          return;
        }

        const resumed = Boolean(resume) && Boolean(sentSid) && data.session_id !== sentSid;
        const incoming: Msg[] = (data.messages || []).map((m: any) =>
          m.type === "image"
            ? { id: uid(), role: "bot-image", url: m.url, alt: m.alt || "แบบสินค้า" }
            : { id: uid(), role: "bot", text: m.text },
        );
        patch(cid, (c) => ({
          ...c,
          sessionId: data.session_id || c.sessionId,
          state: data.state && Object.keys(data.state).length ? data.state : c.state,
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
        addMsgs(cid, {
          id: uid(),
          role: "notice",
          text: "เชื่อมต่อไม่ได้ครับ ตรวจอินเทอร์เน็ตแล้วลองใหม่",
          action: "retry",
        });
        setText(body);
        if (sent) setImage(sent);
      } finally {
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [busy, preparing, text, image, patch, addMsgs],
  );

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
          </header>

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
                  <div key={m.id} className="row me">
                    <div className="bubble user">
                      {m.image && <img src={m.image} alt="รูปที่แนบ" className="thumb" />}
                      {m.text && <div className="plain">{m.text}</div>}
                      {!m.text && !m.image && <div className="plain muted">(รูปที่แนบ)</div>}
                    </div>
                  </div>
                );
              if (m.role === "bot")
                return (
                  <div key={m.id} className="row">
                    <div className="bubble bot md">
                      <ReactMarkdown remarkPlugins={[remarkBreaks]}>{m.text}</ReactMarkdown>
                    </div>
                  </div>
                );
              if (m.role === "bot-image") return <BotImage key={m.id} url={m.url} alt={m.alt} />;
              return (
                <div key={m.id} className="notice" role="status">
                  <span>{m.text}</span>
                  {m.action === "reset" && (
                    <button className="link" onClick={startNew}>
                      เริ่มแชตใหม่
                    </button>
                  )}
                  {m.action === "retry" && (
                    <button
                      className="link"
                      onClick={() => send()}
                      disabled={busy || preparing || (!text.trim() && !image)}
                    >
                      ส่งอีกครั้ง
                    </button>
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
