import { createCanvas } from "@napi-rs/canvas"
import { readFile, writeFile } from "node:fs/promises"
import { routeParse } from "../src/attachments.js"

const tmp = "C:/Users/NewAdmin/AppData/Local/Temp/opencode/vision-test.png"

const canvas = createCanvas(640, 220)
const ctx = canvas.getContext("2d")
ctx.fillStyle = "#ffffff"
ctx.fillRect(0, 0, 640, 220)
ctx.fillStyle = "#000000"
ctx.font = "34px sans-serif"
ctx.fillText("PLM 测试单据", 30, 80)
ctx.fillText("数量: 42   日期: 2026-10-13", 30, 140)
await writeFile(tmp, canvas.toBuffer("image/png"))

const buffer = await readFile(tmp)
const parsed = await routeParse("vision-test.png", buffer)
console.log("via:", parsed.via)
console.log("note:", parsed.note ?? "-")
console.log("text:", parsed.text)
