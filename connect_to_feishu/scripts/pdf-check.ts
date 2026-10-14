import { writeFile } from "node:fs/promises"
import { routeParse } from "../src/attachments.js"

// 构造一个“无文本层”的最小 PDF（模拟扫描件），用来自动计算 xref 偏移。
const objects: string[] = [
  "<< /Type /Catalog /Pages 2 0 R >>",
  "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
  "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << >> >>",
  "<< /Length 0 >>\nstream\n\nendstream",
]

let pdf = "%PDF-1.4\n"
const offsets: number[] = []
objects.forEach((body, index) => {
  offsets.push(pdf.length)
  pdf += `${index + 1} 0 obj\n${body}\nendobj\n`
})
const xrefStart = pdf.length
pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
for (const offset of offsets) {
  pdf += `${offset.toString().padStart(10, "0")} 00000 n \n`
}
pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF\n`

const tmp = "C:/Users/NewAdmin/AppData/Local/Temp/opencode/scanned-test.pdf"
await writeFile(tmp, pdf, "latin1")

const buffer = Buffer.from(pdf, "latin1")
const parsed = await routeParse("scanned-test.pdf", buffer)
console.log("via:", parsed.via)
console.log("note:", parsed.note ?? "-")
console.log("text length:", parsed.text.length)
