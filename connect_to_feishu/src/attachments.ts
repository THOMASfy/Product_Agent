import mammoth from "mammoth"
import WordExtractor from "word-extractor"
import { extractText as extractPdfText, getDocumentProxy, renderPageAsImage } from "unpdf"
import { config } from "./config.js"
import { createLogger } from "./logger.js"
import { convertToPdf, findSoffice } from "./office.js"
import { extractPptx } from "./pptx.js"
import { extractWithVision, type VisionImage } from "./vision.js"

const log = createLogger("attach")

/** 连接器可以解析为文本的电子文档类型（走代码解析器）。 */
export const SUPPORTED_DOC_EXTS = [
  ".docx",
  ".doc",
  ".pdf",
  ".ppt",
  ".pptx",
  ".pptm",
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".json",
  ".log",
  ".xml",
  ".html",
  ".htm",
]

/** 图片/扫描件类型（走 vision）。 */
export const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"]

const MIME_BY_EXT: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".bmp": "image/bmp",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
}

function extOf(filename: string): string {
  const index = filename.lastIndexOf(".")
  return index >= 0 ? filename.slice(index).toLowerCase() : ""
}

export function isSupportedDocument(filename: string): boolean {
  return SUPPORTED_DOC_EXTS.includes(extOf(filename))
}

export function isImage(filename: string): boolean {
  return IMAGE_EXTS.includes(extOf(filename))
}

export function isSupportedAttachment(filename: string): boolean {
  return isSupportedDocument(filename) || isImage(filename)
}

export function mimeOfImage(filename: string): string {
  return MIME_BY_EXT[extOf(filename)] ?? "image/png"
}

export function extFromMime(mime: string): string {
  const found = Object.entries(MIME_BY_EXT).find(([, value]) => value === mime)
  return found ? found[0] : ""
}

/**
 * 把电子文档内容抽成纯文本。
 * Word/PDF 用对应的解析库，纯文本类直接按 UTF-8 读取。
 */
export async function extractDocumentText(filename: string, buffer: Buffer): Promise<string> {
  switch (extOf(filename)) {
    case ".docx": {
      const { value } = await mammoth.extractRawText({ buffer })
      return value
    }
    case ".doc": {
      const document = await new WordExtractor().extract(buffer)
      return document.getBody()
    }
    case ".pdf": {
      const pdf = await getDocumentProxy(new Uint8Array(buffer))
      const { text } = await extractPdfText(pdf, { mergePages: true })
      return Array.isArray(text) ? text.join("\n") : text
    }
    case ".pptx":
    case ".pptm":
      return extractPptx(filename, buffer)
    default:
      return buffer.toString("utf8")
  }
}

/** 把 PDF 前若干页渲染成 PNG，供 vision 识别扫描件/幻灯片。 */
export async function renderPdfToImages(buffer: Buffer, maxPages: number): Promise<VisionImage[]> {
  const pdf: any = await getDocumentProxy(new Uint8Array(buffer))
  const total = Math.min(pdf.numPages, Math.max(1, maxPages))
  const images: VisionImage[] = []
  for (let page = 1; page <= total; page += 1) {
    const rendered: any = await renderPageAsImage(pdf, page, {
      canvasImport: () => import("@napi-rs/canvas"),
      scale: 2,
    })
    const bytes = rendered instanceof ArrayBuffer ? rendered : new Uint8Array(rendered).buffer
    images.push({ mimeType: "image/png", base64: Buffer.from(bytes).toString("base64") })
  }
  log.info(`PDF 扫描件渲染 ${images.length} 页`)
  return images
}

export type ParseVia = "code" | "vision"

export interface ParsedAttachment {
  text: string
  via: ParseVia
  note?: string
}

/**
 * 解析路由：
 * - 图片 → vision；
 * - PPTX → 结构/主题/文本（纯 JS）；若装了 LibreOffice 再渲染成图走 vision 描述风格；
 * - PDF 文本层过少（扫描件）→ 渲染成图片走 vision，失败则退回文本；
 * - 其它电子文档 → 代码解析器。
 */
export async function routeParse(fileName: string, buffer: Buffer): Promise<ParsedAttachment> {
  if (isImage(fileName)) {
    const image: VisionImage = { mimeType: mimeOfImage(fileName), base64: buffer.toString("base64") }
    return { text: await extractWithVision([image]), via: "vision" }
  }

  const ext = extOf(fileName)

  if (ext === ".pptx" || ext === ".pptm" || ext === ".ppt") {
    const soffice = await findSoffice()
    let base = ""
    if (ext !== ".ppt") {
      try {
        base = extractPptx(fileName, buffer)
      } catch (error) {
        log.warn("PPTX 结构解析失败", (error as Error).message)
        base = `# PPTX 结构分析：${fileName}\n- （结构解析失败：${(error as Error).message}）`
      }
    }
    if (!soffice) {
      return {
        text: base || `# ${fileName}\n- 旧版 .ppt 需要 LibreOffice 才能解析。`,
        via: "code",
        note: "未检测到 LibreOffice，仅解析出结构/主题/文本；安装 LibreOffice 后可渲染每页做视觉复刻。",
      }
    }
    try {
      const pdf = await convertToPdf(soffice, buffer, fileName)
      const images = await renderPdfToImages(pdf, config.limits.maxVisionPdfPages)
      const visual = await extractWithVision(images, config.llm.slideVisionPrompt)
      const merged = base ? `${base}\n\n## 幻灯片视觉渲染（vision 识别）\n${visual}` : `## 幻灯片视觉渲染（vision 识别）\n${visual}`
      return { text: merged, via: "vision" }
    } catch (error) {
      log.warn("PPTX 渲染/识别失败，仅保留结构解析", (error as Error).message)
      return { text: base, via: "code", note: `渲染失败：${(error as Error).message}` }
    }
  }

  if (ext === ".pdf") {
    const text = await extractDocumentText(fileName, buffer)
    if (text.trim().length >= config.limits.scannedPdfThreshold) {
      return { text, via: "code" }
    }
    try {
      const images = await renderPdfToImages(buffer, config.limits.maxVisionPdfPages)
      const visionText = await extractWithVision(images)
      return { text: visionText, via: "vision", note: "PDF 文本层过少，已按扫描件走 vision识别" }
    } catch (error) {
      log.warn("扫描件渲染/识别失败，退回文本层", (error as Error).message)
      return { text, via: "code", note: `扫描件识别失败：${(error as Error).message}` }
    }
  }

  return { text: await extractDocumentText(fileName, buffer), via: "code" }
}
