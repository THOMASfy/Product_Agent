#!/usr/bin/env node
/**
 * docgen 启动器：定位 Python 解释器并执行构建 / 渲染脚本。
 *
 * 为什么需要它：agent 的 shell 里不一定有 `python`（PATH 可能未刷新），
 * 而 Node 一定在 PATH 上（OpenCode 自身就运行在 Node 上）。通过 Node 统一解析，
 * 跨 Windows/Linux/macOS 都可靠。
 *
 * 用法：
 *   node .opencode/skills/docgen/scripts/run.mjs build  <spec.json>
 *   node .opencode/skills/docgen/scripts/run.mjs render <file> <out_dir> [--png]
 */
import { spawnSync } from "node:child_process"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))

function windowsCandidates() {
  const local = process.env.LOCALAPPDATA || ""
  const candidates = []
  for (const version of ["Python313", "Python312", "Python311", "Python310"]) {
    if (local) candidates.push(path.join(local, "Programs", "Python", version, "python.exe"))
    candidates.push(path.join("C:", "Program Files", version, "python.exe"))
    candidates.push(path.join("C:", "Program Files (x86)", version, "python.exe"))
  }
  return candidates
}

/** 列出候选命令，形如 { cmd, args }。 */
function pythonCandidates() {
  const list = []
  if (process.env.PYTHON_PATH) list.push({ cmd: process.env.PYTHON_PATH, args: [] })
  if (process.platform === "win32") {
    for (const exe of windowsCandidates()) list.push({ cmd: exe, args: [] })
  }
  list.push({ cmd: "python", args: [] })
  list.push({ cmd: "python3", args: [] })
  if (process.platform === "win32") list.push({ cmd: "py", args: ["-3"] })
  return list
}

function findPython() {
  for (const candidate of pythonCandidates()) {
    const probe = spawnSync(candidate.cmd, [...candidate.args, "--version"], { stdio: "ignore" })
    if (probe.status === 0) return candidate
  }
  return null
}

function fail(message) {
  console.error(message)
  process.exit(1)
}

const [command, ...rest] = process.argv.slice(2)
if (!command) fail("用法：node run.mjs build <spec.json> | render <file> <out_dir> [--png]")

const scripts = { build: "build.py", render: "render.py" }
const script = scripts[command]
if (!script) fail(`未知命令：${command}（可选 build | render）`)

const python = findPython()
if (!python) {
  fail(
    "未找到 Python 解释器。请在服务器上安装 Python 并确保可执行，\n" +
      "或设置环境变量 PYTHON_PATH 指向 python 可执行文件。",
  )
}

const args = [...python.args, path.join(here, script), ...rest]
const result = spawnSync(python.cmd, args, {
  stdio: "inherit",
  env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
})
process.exit(result.status ?? 1)
