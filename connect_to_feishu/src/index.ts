import fs from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { extFromMime, isSupportedAttachment, SUPPORTED_DOC_EXTS, IMAGE_EXTS, routeParse } from "./attachments.js"
import { config } from "./config.js"
import { reportCapabilities } from "./capabilities.js"
import {
  downloadMessageResource,
  replyText,
  resolveUser,
  sendFile,
  sendImage,
  startFeishuBot,
  type IncomingMessage,
} from "./feishu.js"
import { createLogger } from "./logger.js"
import * as memory from "./memory.js"
import { askSupervisor } from "./opencode.js"
import { chunkText, truncate } from "./text.js"
import * as userStore from "./user-store.js"

const log = createLogger("app")

/** 把用户档案与长期记忆塞进提示词，让 supervisor 知道“谁在说话”“记得什么”。 */
function buildPrompt(profile: userStore.Profile, userText: string, memoryBlock = ""): string {
  const who = [
    `open_id: ${profile.open_id}`,
    profile.name ? `姓名: ${profile.name}` : null,
    profile.department ? `部门: ${profile.department}` : null,
    `身份: ${profile.identity}`,
  ]
    .filter(Boolean)
    .join("，")

  return [
    `【当前飞书用户】${who}`,
    "（该身份信息来自飞书，用于判断权限；管理员才可发起管理类操作。）",
    ...(memoryBlock
      ? ["", "【长期记忆（此前对话的要点摘要，供参考）】", memoryBlock]
      : []),
    "",
    "【用户消息】",
    userText,
    "",
    "请作为 PLM supervisor 处理：拆解需求，按需调度 plm-* 子智能体，",
    "最后用简洁的中文给出整合后的结论。回复会直接发到飞书，请使用纯文本、避免超长表格。",
  ].join("\n")
}

interface TurnInput {
  promptText: string
  ackText: string
  historyText: string
}

/* ------------------------------------------------------------------ *
 * 出站文件：识别回复里的标记并回发文件/图片。
 *   [[send-file: C:\path\to\file.pptx]]
 *   [[send-image: C:\path\to\pic.png]]
 * 仅允许白名单目录内的路径。
 * ------------------------------------------------------------------ */

function outboundRoots(): string[] {
  const configured = config.files.outboundRoots
  if (configured.length) return configured.map((root) => path.resolve(root))
  return [config.opencode.directory, config.store.userRoot, os.tmpdir()].map((root) => path.resolve(root))
}

function isOutboundAllowed(filePath: string): boolean {
  const resolved = path.resolve(filePath).toLowerCase()
  return outboundRoots().some((root) => resolved === root.toLowerCase() || resolved.startsWith(root.toLowerCase() + path.sep))
}

const FILE_MARKER = /\[\[\s*send-(file|image)\s*:\s*([^\]]+?)\s*\]\]/gi

/** 抽出回复中的文件标记，逐个上传发送，并返回去掉标记后的文本。 */
async function deliverMarkedFiles(openId: string, answer: string): Promise<string> {
  const matches = [...answer.matchAll(FILE_MARKER)]
  if (matches.length === 0) return answer

  let text = answer
  for (const match of matches) {
    const kind = match[1].toLowerCase()
    const rawPath = match[2].trim().replace(/^["']|["']$/g, "")
    text = text.replace(match[0], "")

    if (!isOutboundAllowed(rawPath)) {
      log.warn(`拒绝发送白名单外的文件：${rawPath}`)
      continue
    }
    try {
      const ok = kind === "image" ? await sendImage(openId, rawPath) : await sendFile(openId, rawPath)
      log.info(`出站${kind === "image" ? "图片" : "文件"} ${rawPath}：${ok ? "成功" : "失败"}`)
    } catch (error) {
      log.error(`出站文件失败 ${rawPath}`, (error as Error).stack ?? error)
    }
  }
  return text.replace(/\n{3,}/g, "\n\n").trim()
}

/** 记录用户档案、发确认、交给 supervisor、记录并回发。 */
async function processTurn(message: IncomingMessage, input: TurnInput): Promise<void> {
  const feishuUser = await resolveUser(message.openId)
  const { profile } = await userStore.ensureProfile({
    open_id: feishuUser.openId,
    name: feishuUser.name,
    department: feishuUser.department,
    identity: feishuUser.isAdmin ? "管理员" : "普通用户",
  })
  await userStore.appendHistory(profile.open_id, [
    { ts: new Date().toISOString(), role: "user", content: input.historyText },
  ])
  await userStore.updateIndex(profile, 1)

  await replyText(message.messageId, input.ackText)

  let rawAnswer: string
  try {
    const memoryBlock = await memory.readMemoryBlock(profile.open_id)
    rawAnswer = await askSupervisor(profile.open_id, buildPrompt(profile, input.promptText, memoryBlock))
  } catch (error) {
    log.error("supervisor 处理失败", (error as Error).stack ?? error)
    rawAnswer = "处理时出现异常，请稍后重试。"
  }

  // 若回复里带了 [[send-file: ...]] / [[send-image: ...]] 标记，则回发文件并从文本里去掉。
  const answer = await deliverMarkedFiles(profile.open_id, rawAnswer)

  await userStore.appendHistory(profile.open_id, [
    { ts: new Date().toISOString(), role: "assistant", agent: config.opencode.agent, content: answer || "（已发送文件）" },
  ])
  await userStore.updateIndex(profile, 0)

  if (answer) {
    for (const chunk of chunkText(answer)) {
      await replyText(message.messageId, chunk)
    }
  }

  // 产出文件已回发飞书，不再保留（output 不长期留存）。
  await userStore.clearOutput(profile.open_id).catch(() => {})

  // 累计达到阈值时，异步更新长期记忆（不阻塞本轮）。
  memory.maybeSummarize(profile.open_id)
}

/* ------------------------------------------------------------------ *
 * 路径 A：仅收到文件/图片 —— 只存储，不调用 OpenCode，不解析、不摘要。
 * ------------------------------------------------------------------ */

async function storeAttachmentOnly(message: IncomingMessage): Promise<void> {
  const isImageKind = message.kind === "image"
  const key = isImageKind ? message.imageKey : message.file?.key
  if (!key) return

  const dir = userStore.attachmentsDir(message.openId)
  await fs.mkdir(dir, { recursive: true })

  if (!isImageKind && !isSupportedAttachment(message.file?.name ?? "")) {
    log.warn(`附件类型可能无法解析，仍先存储：${message.file?.name}`)
  }

  const resource = await downloadMessageResource(
    message.messageId,
    key,
    isImageKind ? "image" : "file",
  )
  const contentType = String(resource.headers?.["content-type"] ?? "")
    .split(";")[0]
    .trim()

  // 飞书图片消息没有文件名，用 content-type 推断扩展名。
  let name = isImageKind ? "" : (message.file?.name ?? "file")
  if (!name) {
    const ext = extFromMime(contentType) || ".png"
    name = `image_${Date.now()}${ext}`
  }
  const safeName = name.replace(/[\\/:*?"<>|]/g, "_")
  const storedName = `${Date.now()}_${safeName}`
  await resource.writeFile(path.join(dir, storedName))

  await userStore.addPending(message.openId, {
    key,
    name: safeName,
    kind: isImageKind ? "image" : "file",
    path: storedName,
    message_id: message.messageId,
    ts: new Date().toISOString(),
  })

  log.info(`已暂存附件 ${safeName}（等待文本指令，不触发推理）`)
}

/* ------------------------------------------------------------------ *
 * 路径 B：收到文本指令 —— 检查暂存 → 解析器路由 → 拼装联合上下文 → supervisor。
 * ------------------------------------------------------------------ */

interface ContextSection {
  name: string
  content: string
  /** 原始文件的绝对路径，供文件生成类子智能体复用模板。 */
  path?: string
}

/** 按约定的 Payload 模板拼装：上下文数据 + 用户执行指令。 */
function buildCombinedPayload(sections: ContextSection[], instruction: string): string {
  const blocks = sections.map((section) =>
    [
      `【关联文件】: ${section.name}`,
      ...(section.path ? [`【原始文件路径】: ${section.path}`] : []),
      "【文档/表格解析内容】:",
      section.content,
    ].join("\n"),
  )

  return [
    "### 待处理上下文数据",
    blocks.join("\n\n"),
    "",
    "---",
    "### 用户执行指令",
    instruction,
  ].join("\n")
}

async function handleInstruction(message: IncomingMessage, instruction: string): Promise<void> {
  const pending = await userStore.readPending(message.openId)

  // 没有暂存附件：按普通文本处理。
  if (pending.length === 0) {
    await processTurn(message, {
      promptText: instruction,
      ackText: "收到，正在交给 PLM supervisor 处理，请稍候…",
      historyText: instruction,
    })
    return
  }

  await replyText(message.messageId, `检测到 ${pending.length} 个待处理文件，正在解析，请稍候…`)

  const dir = userStore.attachmentsDir(message.openId)
  const sections: ContextSection[] = []
  let anyText = false

  for (const item of pending) {
    try {
      const buffer = await fs.readFile(path.join(dir, item.path))
      const parsed = await routeParse(item.name, buffer)
      const body = parsed.text.trim()
      if (body) anyText = true
      const note = parsed.note ? `\n> 说明：${parsed.note}（via ${parsed.via}）` : ""
      sections.push({
        name: item.name,
        path: path.resolve(dir, item.path),
        content: truncate(body, config.limits.maxAttachmentChars) || "（未能提取到文本）",
      })
      if (note) sections[sections.length - 1].content += `\n${note}`
      log.info(`已解析 ${item.name}（via ${parsed.via}，${body.length} 字）`)
    } catch (error) {
      log.error(`解析附件失败 ${item.name}`, (error as Error).stack ?? error)
      sections.push({
        name: item.name,
        content: `（解析失败：${(error as Error).message}）`,
      })
    }
  }

  // 指令已消费暂存，清空避免重复解析。
  await userStore.clearPending(message.openId)

  if (!anyText) {
    await replyText(message.messageId, "附件未能提取到任何文本内容（可能是空白或格式无法识别）。")
    return
  }

  const payload = buildCombinedPayload(sections, instruction)
  const historyText = `${instruction}\n【关联文件】${sections.map((s) => s.name).join("、")}`

  await processTurn(message, {
    promptText: payload,
    ackText: "已解析暂存文件，正在交给 PLM supervisor 处理，请稍候…",
    historyText,
  })

  // 上传文件已解析并参与本轮处理，不再备份。
  await userStore.clearAttachments(message.openId).catch(() => {})
}

/* ------------------------------------------------------------------ */

async function handleMessage(message: IncomingMessage): Promise<void> {
  // 群聊里默认只在 @机器人 时响应。
  if (message.chatType !== "p2p" && config.policy.groupMentionOnly && !message.mentioned) {
    log.debug(`忽略未 @机器人 的群消息 ${message.chatId}`)
    return
  }

  log.info(
    `收到消息 user=${message.openId} chat=${message.chatType} kind=${message.kind}: ` +
      (message.kind === "file" ? message.file?.name : message.text.slice(0, 80)),
  )

  switch (message.kind) {
    // 路径 A：仅附件 → 只存储。
    case "file":
    case "image":
      await storeAttachmentOnly(message)
      return

    // 路径 B：文本指令 → 检查暂存并解析。
    case "text":
    case "post":
      if (!message.text.trim()) return
      await handleInstruction(message, message.text.trim())
      return

    default:
      await replyText(message.messageId, "暂不支持该消息类型，请改用文本或文档/图片。")
  }
}

async function main(): Promise<void> {
  log.info(`PLM supervisor agent: ${config.opencode.agent}`)
  log.info(`OpenCode 工作目录: ${config.opencode.directory}`)
  log.info(`用户数据目录: ${config.store.userRoot}`)
  log.info(`支持文档：${SUPPORTED_DOC_EXTS.join(" ")}｜图片：${IMAGE_EXTS.join(" ")}`)

  await reportCapabilities()

  await startFeishuBot({
    onMessage: (message) => handleMessage(message),
  })
}

main().catch((error) => {
  log.error("启动失败", (error as Error).stack ?? error)
  process.exit(1)
})
