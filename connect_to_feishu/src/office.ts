import { execFile } from "node:child_process"
import fs from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { promisify } from "node:util"
import { config } from "./config.js"
import { createLogger } from "./logger.js"

const execFileAsync = promisify(execFile)
const log = createLogger("office")

let cachedSoffice: string | null | undefined

/** 探测 LibreOffice 的 soffice。返回可执行文件路径或 null。 */
export async function findSoffice(): Promise<string | null> {
  if (cachedSoffice !== undefined) return cachedSoffice
  if (!config.office.enabled) {
    cachedSoffice = null
    return null
  }

  const candidates = [
    config.office.sofficePath,
    "C:/Program Files/LibreOffice/program/soffice.exe",
    "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
  ].filter(Boolean)

  for (const candidate of candidates) {
    try {
      await execFileAsync(candidate, ["--version"], { timeout: 15000 })
      cachedSoffice = candidate
      log.info(`检测到 LibreOffice：${candidate}`)
      return candidate
    } catch {
      // 继续尝试下一个候选。
    }
  }

  cachedSoffice = null
  log.warn("未检测到 LibreOffice（soffice），将跳过 PPTX 视觉渲染")
  return null
}

/** 用 LibreOffice 把 Office 文档转成 PDF，返回 PDF 字节。 */
export async function convertToPdf(soffice: string, buffer: Buffer, filename: string): Promise<Buffer> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "plm-convert-"))
  const input = path.join(dir, filename.replace(/[\\/:*?"<>|]/g, "_"))
  try {
    await fs.writeFile(input, buffer)
    await execFileAsync(
      soffice,
      ["--headless", "--norestore", "--convert-to", "pdf", "--outdir", dir, input],
      { timeout: config.office.convertTimeoutMs, windowsHide: true },
    )
    const pdfName = path.basename(input).replace(/\.[^.]+$/, ".pdf")
    return await fs.readFile(path.join(dir, pdfName))
  } finally {
    await fs.rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}
