import { readFile } from "node:fs/promises"
import { routeParse } from "../src/attachments.js"

const file = "C:/Product_Agent/data/user/ou_45b70a4aeb65be1502bf582c26fc20b4/attachments/1791856607746_中国移动内部汇报PPT模板.pptx"
const buffer = await readFile(file)
const parsed = await routeParse("中国移动内部汇报PPT模板.pptx", buffer)
console.log("via:", parsed.via)
console.log("note:", parsed.note ?? "-")
console.log("----")
console.log(parsed.text)
