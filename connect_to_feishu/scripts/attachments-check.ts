import { extractDocumentText, isSupportedDocument } from "../src/attachments.js"

console.log("supported docx/doc/pdf:", isSupportedDocument("a.docx"), isSupportedDocument("a.doc"), isSupportedDocument("a.pdf"))
console.log("supported exe:", isSupportedDocument("a.exe"))
console.log("txt:", JSON.stringify(await extractDocumentText("a.txt", Buffer.from("hello 世界"))))
console.log("md:", JSON.stringify(await extractDocumentText("a.md", Buffer.from("# 标题\n正文"))))
