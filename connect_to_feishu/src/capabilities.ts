import { execFile } from "node:child_process"
import os from "node:os"
import path from "node:path"
import { promisify } from "node:util"
import { findSoffice } from "./office.js"
import { createLogger } from "./logger.js"

const execFileAsync = promisify(execFile)
const log = createLogger("capabilities")

/** Python 解释器候选（按顺序探测）：兼容 PATH 未刷新的场景。 */
function pythonCandidates(): Array<{ cmd: string; args: string[] }> {
  const list: Array<{ cmd: string; args: string[] }> = []
  if (process.env.PYTHON_PATH) list.push({ cmd: process.env.PYTHON_PATH, args: [] })
  if (process.platform === "win32") {
    const local = process.env.LOCALAPPDATA ?? ""
    for (const version of ["Python313", "Python312", "Python311", "Python310"]) {
      if (local) list.push({ cmd: path.join(local, "Programs", "Python", version, "python.exe"), args: [] })
      list.push({ cmd: path.join("C:", "Program Files", version, "python.exe"), args: [] })
    }
  }
  list.push({ cmd: "python", args: [] })
  list.push({ cmd: "python3", args: [] })
  if (process.platform === "win32") list.push({ cmd: "py", args: ["-3"] })
  return list
}

const PY_LIBS = ["pptx", "docx", "openpyxl"]

let cachedPython: string | null | undefined

/** 探测可用的 Python 解释器。返回命令（可能是绝对路径）或 null。 */
export async function findPython(): Promise<string | null> {
  if (cachedPython !== undefined) return cachedPython
  for (const candidate of pythonCandidates()) {
    try {
      await execFileAsync(candidate.cmd, [...candidate.args, "--version"], { timeout: 15000 })
      cachedPython = candidate.cmd
      return cachedPython
    } catch {
      // 尝试下一个候选。
    }
  }
  cachedPython = null
  return null
}

/** 探测 Python 是否具备文件生成所需的库。 */
async function pythonLibsReady(python: string): Promise<boolean> {
  try {
    await execFileAsync(python, ["-c", `import ${PY_LIBS.join(", ")}`], { timeout: 20000 })
    return true
  } catch {
    return false
  }
}

/**
 * 启动时报告"文件生成能力"，便于部署方确认服务器依赖是否齐全。
 * 这里探测的是**服务器本机**，与用户电脑无关 —— 用户只用飞书。
 */
export async function reportCapabilities(): Promise<void> {
  const [soffice, python] = await Promise.all([findSoffice(), findPython()])

  const libs = python ? await pythonLibsReady(python) : false

  const pythonText = python
    ? `${python}${libs ? "（python-pptx/docx/openpyxl 就绪）" : "（缺少 python 库，请 pip install python-pptx python-docx openpyxl）"}`
    : "未检测到 Python（无法生成 PPT/Word/Excel/PDF）"
  const officeText = soffice
    ? soffice
    : "未检测到 LibreOffice（PDF 导出与预览渲染不可用；PPT/Word/Excel 仍可生成）"

  log.info(`文件生成能力（本机/服务器）：python=${pythonText}；LibreOffice=${officeText}`)

  if (!python || !libs) {
    log.warn("文件生成能力不完整，请参考 connect_to_feishu/deploy/README.md 安装服务器依赖")
  }
}
