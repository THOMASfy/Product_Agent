import { unzipSync, strFromU8 } from "fflate"

type Zip = Record<string, Uint8Array>

function decodeXml(text: string): string {
  return text
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(Number(dec)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&")
}

function matchAll(xml: string, regex: RegExp): string[] {
  const out: string[] = []
  let match: RegExpExecArray | null
  while ((match = regex.exec(xml)) !== null) out.push(match[1])
  return out
}

function textsOf(xml: string): string[] {
  return matchAll(xml, /<a:t>([\s\S]*?)<\/a:t>/g).map((t) => decodeXml(t).trim()).filter(Boolean)
}

function unique(values: string[]): string[] {
  return [...new Set(values)]
}

function colorsOf(xml: string): string[] {
  return unique(matchAll(xml, /<a:srgbClr val="([0-9A-Fa-f]{6})"/g)).map((c) => `#${c.toUpperCase()}`)
}

function fontsOf(xml: string): string[] {
  return unique(
    matchAll(xml, /typeface="([^"]+)"/g).filter((f) => !f.startsWith("+")),
  )
}

/** 解析一个 part 的 rels 文件，返回 rId -> 目标路径（相对该 part）。 */
function relsOf(zip: Zip, partPath: string): Map<string, string> {
  const dir = partPath.slice(0, partPath.lastIndexOf("/"))
  const base = partPath.slice(partPath.lastIndexOf("/") + 1)
  const relsPath = `${dir}/_rels/${base}.rels`
  const raw = zip[relsPath]
  const map = new Map<string, string>()
  if (!raw) return map
  const xml = strFromU8(raw)
  for (const match of xml.matchAll(/<Relationship\b[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"[^>]*\/>/g)) {
    map.set(match[1], match[2])
  }
  return map
}

function resolvePath(baseDir: string, target: string): string {
  if (target.startsWith("/")) return target.slice(1)
  const segments = `${baseDir}/${target}`.split("/")
  const stack: string[] = []
  for (const segment of segments) {
    if (segment === "." || segment === "") continue
    if (segment === "..") stack.pop()
    else stack.push(segment)
  }
  return stack.join("/")
}

/** 从 slide xml 中找出引用的图片（通过 rels 解析为 ppt/media 路径）。 */
function imagesOf(zip: Zip, slidePath: string, xml: string): string[] {
  const rels = relsOf(zip, slidePath)
  const dir = slidePath.slice(0, slidePath.lastIndexOf("/"))
  const embeds = unique(matchAll(xml, /<a:blip[^>]*r:embed="([^"]+)"/g))
  return embeds
    .map((id) => rels.get(id))
    .filter((target): target is string => Boolean(target))
    .map((target) => resolvePath(dir, target))
}

/** 按 presentation.xml 的 sldIdLst 顺序返回幻灯片 part 路径。 */
function orderedSlides(zip: Zip): string[] {
  const presentation = zip["ppt/presentation.xml"]
  if (!presentation) return Object.keys(zip).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n)).sort()
  const rels = relsOf(zip, "ppt/presentation.xml")
  const order = matchAll(strFromU8(presentation), /<p:sldId\b[^>]*r:id="([^"]+)"/g)
    .map((id) => rels.get(id))
    .filter((target): target is string => Boolean(target))
    .map((target) => resolvePath("ppt", target))
  if (order.length) return order
  return Object.keys(zip).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n)).sort()
}

function emuToInch(emu: number): string {
  return (emu / 914400).toFixed(2)
}

function aspect(cx: number, cy: number): string {
  const ratio = cx / cy
  if (Math.abs(ratio - 16 / 9) < 0.05) return "16:9"
  if (Math.abs(ratio - 4 / 3) < 0.05) return "4:3"
  return ratio.toFixed(2) + ":1"
}

/**
 * 把 PPTX 解析成结构化 Markdown：
 * 画布尺寸、主题色/字体、媒体清单、逐页文本与配色/字体/图片引用。
 * 纯 JS，无需 Office/LibreOffice。
 */
export function extractPptx(filename: string, buffer: Buffer): string {
  const zip = unzipSync(new Uint8Array(buffer)) as Zip

  const lines: string[] = [`# PPTX 结构分析：${filename}`]

  // ---- 画布与页数 ----
  const presentation = zip["ppt/presentation.xml"] ? strFromU8(zip["ppt/presentation.xml"]) : ""
  const sldSz = presentation.match(/<p:sldSz[^>]*cx="(\d+)"[^>]*cy="(\d+)"/)
  if (sldSz) {
    const cx = Number(sldSz[1])
    const cy = Number(sldSz[2])
    lines.push(
      `- 画布：${cx} x ${cy} EMU（${emuToInch(cx)}" x ${emuToInch(cy)}"，比例 ${aspect(cx, cy)}）`,
    )
  }

  const slides = orderedSlides(zip)
  const layouts = Object.keys(zip).filter((n) => /^ppt\/slideLayouts\/slideLayout\d+\.xml$/.test(n)).length
  const masters = Object.keys(zip).filter((n) => /^ppt\/slideMasters\/slideMaster\d+\.xml$/.test(n)).length
  const media = Object.keys(zip).filter((n) => n.startsWith("ppt/media/"))
  lines.push(`- 幻灯片：${slides.length} 张；版式：${layouts} 个；母版：${masters} 个；媒体：${media.length} 个`)

  // ---- 文档属性 ----
  const core = zip["docProps/core.xml"] ? strFromU8(zip["docProps/core.xml"]) : ""
  const title = core.match(/<dc:title>([\s\S]*?)<\/dc:title>/)
  if (title && title[1].trim()) lines.push(`- 文档标题：${decodeXml(title[1].trim())}`)
  const app = zip["docProps/app.xml"] ? strFromU8(zip["docProps/app.xml"]) : ""
  const usedFonts = matchAll(app, /<vt:lpstr>([^<]+)<\/vt:lpstr>/g).filter((f) => /[\u4e00-\u9fa5A-Za-z]/.test(f))
  const labels = new Set(["已用的字体", "幻灯片标题", "主题", "字体", "演示文稿"])
  const fontNames = unique(usedFonts.filter((f) => !labels.has(f.trim())))

  // ---- 主题（配色/字体）----
  const theme = zip["ppt/theme/theme1.xml"] ? strFromU8(zip["ppt/theme/theme1.xml"]) : ""
  if (theme) {
    const themeName = theme.match(/<a:theme[^>]*name="([^"]*)"/)
    if (themeName) lines.push(`- 主题：${decodeXml(themeName[1])}`)
    const scheme = theme.match(/<a:clrScheme[^>]*name="([^"]*)"[\s\S]*?<\/a:clrScheme>/)
    if (scheme) {
      const named: string[] = []
      for (const tag of ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]) {
        const block = scheme[0].match(new RegExp(`<a:${tag}>[\\s\\S]*?</a:${tag}>`))
        if (!block) continue
        const srgb = block[0].match(/<a:srgbClr val="([0-9A-Fa-f]{6})"/)
        const sys = block[0].match(/<a:sysClr[^>]*lastClr="([0-9A-Fa-f]{6})"/)
        const value = srgb ? srgb[1] : sys ? sys[1] : null
        if (value) named.push(`${tag}=#${value.toUpperCase()}`)
      }
      if (named.length) lines.push(`- 主题配色：${named.join("，")}`)
    }
    const major = theme.match(/<a:majorFont>[\s\S]*?<a:latin typeface="([^"]*)"/)
    const minor = theme.match(/<a:minorFont>[\s\S]*?<a:latin typeface="([^"]*)"/)
    const eaMajor = theme.match(/<a:majorFont>[\s\S]*?<a:ea typeface="([^"]*)"/)
    const eaMinor = theme.match(/<a:minorFont>[\s\S]*?<a:ea typeface="([^"]*)"/)
    const fontLine = [
      major?.[1] ? `标题字体=${major[1]}` : null,
      eaMajor?.[1] ? `标题中文字体=${eaMajor[1]}` : null,
      minor?.[1] ? `正文字体=${minor[1]}` : null,
      eaMinor?.[1] ? `正文中文字体=${eaMinor[1]}` : null,
    ].filter(Boolean)
    if (fontLine.length) lines.push(`- 主题字体：${fontLine.join("，")}`)
  }
  if (fontNames.length) lines.push(`- 文档使用字体：${fontNames.join("，")}`)

  // ---- 媒体清单 ----
  if (media.length) {
    lines.push(`- 媒体资源：`)
    for (const name of media) {
      lines.push(`  - ${name.split("/").pop()}（${zip[name].length} 字节）`)
    }
  }

  // ---- 逐页 ----
  slides.forEach((slidePath, index) => {
    const xml = str2s(zip[slidePath])
    const texts = textsOf(xml)
    const colors = colorsOf(xml)
    const fonts = fontsOf(xml)
    const images = imagesOf(zip, slidePath, xml)
    lines.push("", `## 第 ${index + 1} 张幻灯片`)
    lines.push(`- 文本：${texts.length ? texts.join(" ｜ ") : "（无文本，可能是纯图形页）"}`)
    if (colors.length) lines.push(`- 使用颜色：${colors.join("，")}`)
    if (fonts.length) lines.push(`- 使用字体：${fonts.join("，")}`)
    if (images.length) lines.push(`- 引用图片：${images.map((p) => p.split("/").pop()).join("，")}`)
  })

  return lines.join("\n")
}

function str2s(raw: Uint8Array | undefined): string {
  return raw ? strFromU8(raw) : ""
}
