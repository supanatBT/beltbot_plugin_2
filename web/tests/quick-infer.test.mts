// node --experimental-strip-types tests/quick-infer.test.mts  (ไม่ต้องลงอะไรเพิ่ม)
import { inferSuggestions } from "../lib/quick-infer.ts";
let fail = 0;
const t = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fail++;
  console.log(`${ok ? "✓" : "✗"} ${name}${ok ? "" : `  got=${JSON.stringify(got)}`}`);
};
const labels = (s?: { label: string }[]) => s?.map((x) => x.label);
const WD = ["ไลน์แห้ง", "ไลน์เปียก", "ไม่แน่ใจ"];
const BR = ["Movex (โซ่ท็อปเชน)", "Modutech (สายพานโมดูลาร์)"];

// เคสจริงจากหน้าเว็บ 10 พ.ย. (MP80 C)
t("MP80 C ถามเปียก/แห้ง", labels(inferSuggestions(
  "ช่วงอุณหภูมิใช้งานของสายพาน Modutech รุ่น **MP80 C** จะขึ้นอยู่กับสภาวะการใช้งานและวัสดุของสลัก (Pin) ครับ\n\n" +
  "ไม่ทราบว่าใช้งานในสภาวะ**ไลน์แห้ง**หรือ**ไลน์เปียก**ครับ? เนื่องจากอุณหภูมิสูงสุดที่ทนได้ในสภาวะเปียกจะต่ำกว่าสภาวะแห้งครับ")), WD);
t("เปียกหรือแห้ง + ไหม", labels(inferSuggestions("ใช้งานแบบเปียกหรือแห้งไหมครับ")), WD);
t("สภาวะเปียกหรือสภาวะแห้ง ไม่มี ?", labels(inferSuggestions("รบกวนแจ้งว่าเป็นสภาวะเปียกหรือสภาวะแห้งครับ")), WD);
// ไม่ควรมีปุ่ม
t("บอกเล่า ใช้ได้ทั้งสองแบบ", inferSuggestions("รุ่นนี้ใช้ได้ทั้งไลน์แห้งหรือไลน์เปียกครับ"), undefined);
t("บอกเล่า เปรียบเทียบ", inferSuggestions("อุณหภูมิในสภาวะเปียกจะต่ำกว่าสภาวะแห้งครับ"), undefined);
t("รายการค่าแห้ง/เปียก แล้วถามเรื่องอื่น", inferSuggestions(
  "- สภาวะแห้ง: -40 ถึง 80 °C\n- สภาวะเปียก: -40 ถึง 65 °C\n\nต้องการ datasheet เพิ่มไหมครับ?"), undefined);
t("ถามเปียก/แห้ง แต่ไม่ใช่ย่อหน้าสุดท้าย", inferSuggestions(
  "ใช้ไลน์แห้งหรือไลน์เปียกครับ?\n\nระหว่างนี้แนบ datasheet ไว้ให้แล้วครับ"), undefined);
t("ข้อความว่าง", inferSuggestions(""), undefined);
t("undefined", inferSuggestions(undefined), undefined);
// แบรนด์
t("ถามแบรนด์", labels(inferSuggestions("หมายถึงโซ่ท็อปเชน **Movex** หรือสายพานโมดูลาร์ **Modutech** ครับ?")), BR);
t("แบรนด์ไหน", labels(inferSuggestions("ไม่ทราบว่าต้องการแบรนด์ไหนครับ ระหว่าง Movex กับ Modutech")), BR);
// เมนูจริงจาก engine/core/templates.py ask_brand (บนเว็บ 11 พ.ย. ไม่ขึ้นปุ่ม)
t("เมนูถามแบรนด์ของระบบ", labels(inferSuggestions(
  "ขอทราบก่อนนะครับว่าถามถึงสินค้าแบบไหน\n1. โซ่ท็อปเชน Movex — ลำเลียงขวด กระป๋อง ลัง ในไลน์บรรจุเครื่องดื่ม\n" +
  "2. สายพานโมดูลาร์ Modutech — งานอาหาร เช่น เนื้อสัตว์ สัตว์ปีก อาหารทะเล เบเกอรี่ ผักผลไม้\n" +
  "ตอบเป็นเลขข้อหรือชื่อแบรนด์ได้เลยครับ ถ้ามีรหัสรุ่นหรือรูปสินค้าก็ส่งมาแทนได้")), BR);
t("เอ่ยสองแบรนด์แบบบอกเล่า", inferSuggestions("ระบบนี้มีสินค้า Movex หรือ Modutech ให้เลือกครับ"), undefined);
console.log(fail ? `\n${fail} ข้อไม่ผ่าน` : "\nผ่านทุกข้อ");
process.exit(fail ? 1 : 0);
