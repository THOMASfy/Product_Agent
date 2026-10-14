import { Client, EventDispatcher, WSClient } from "@larksuiteoapi/node-sdk"
import fs from "node:fs/promises"
import path from "node:path"
import { config } from "./config.js"
import { createLogger } from "./logger.js"
import { stripMentions } from "./text.js"

const log = createLogger("feishu")

const client = new Client({
  appId: config.feishu.appId,
  appSecret: config.feishu.appSecret,
})

/* ------------------------------------------------------------------ *
 * 兼容不同版本的 SDK 路径：优先 im.v1.message，退回 im.message。
 * ------------------------------------------------------------------ */
function imMessageApi(): any {
  const anyClient = client as any
  return anyClient?.im?.v1?.message ?? anyClient?.im?.message
}

function imMessageResourceApi(): any {
  const anyClient = client as any
  return anyClient?.im?.v1?.messageResource ?? anyClient?.im?.messageResource
}

function contactUserApi(): any {
  const anyClient = client as any
  return anyClient?.contact?.v3?.user ?? anyClient?.contact?.user
}

function contactDepartmentApi(): any {
  const anyClient = client as any
  return anyClient?.contact?.v3?.department ?? anyClient?.contact?.department
}

/* ------------------------------------------------------------------ *
 * 接收消息
 * ------------------------------------------------------------------ */

export type MessageKind = "text" | "post" | "file" | "image" | "other"

export interface IncomingMessage {
  openId: string
  chatId: string
  chatType: string
  messageId: string
  kind: MessageKind
  text: string
  mentioned: boolean
  file?: { key: string; name: string; size: number }
  imageKey?: string
}

function safeJson(raw: string | undefined): any {
  try {
    return JSON.parse(raw ?? "{}")
  } catch {
    return {}
  }
}

/** 把飞书富文本(post)消息拍平成纯文本。 */
function flattenPost(content: any): string {
  const lines: string[] = []
  if (content?.title) lines.push(String(content.title))
  const body = Array.isArray(content?.content) ? content.content : []
  for (const line of body) {
    if (!Array.isArray(line)) continue
    const text = line
      .map((node: any) => {
        if (!node) return ""
        if (node.tag === "at") return ` @${node.user_name ?? node.user_id ?? ""}`
        return node.text ?? ""
      })
      .join("")
    if (text.trim()) lines.push(text)
  }
  return lines.join("\n").trim()
}

/** 解析 im.message.receive_v1 事件；无法识别时返回 null。 */
export function parseIncoming(data: any): IncomingMessage | null {
  const message = data?.message
  const sender = data?.sender
  const openId = sender?.sender_id?.open_id
  if (!message || !openId) return null
  // 忽略机器人/应用发出的消息，避免自循环。
  if (sender?.sender_type && sender.sender_type !== "user") return null

  const type: string = message.message_type
  const mentions: any[] = message.mentions ?? []
  const keys = mentions.map((mention) => mention?.key).filter(Boolean)
  const content = safeJson(message.content)

  const base = {
    openId,
    chatId: message.chat_id,
    chatType: message.chat_type,
    messageId: message.message_id,
    mentioned: mentions.length > 0,
  }

  if (type === "text") {
    return { ...base, kind: "text", text: stripMentions(content.text ?? "", keys) }
  }
  if (type === "post") {
    return { ...base, kind: "post", text: flattenPost(content) }
  }
  if (type === "file") {
    return {
      ...base,
      kind: "file",
      text: "",
      file: {
        key: content.file_key ?? "",
        name: content.file_name ?? "file",
        size: Number(content.file_size ?? 0),
      },
    }
  }
  if (type === "image") {
    return { ...base, kind: "image", text: "", imageKey: content.image_key }
  }
  return { ...base, kind: "other", text: "" }
}

/** 下载消息里的资源文件（附件/图片/音视频），返回 SDK 的文件流对象。 */
export async function downloadMessageResource(
  messageId: string,
  fileKey: string,
  type = "file",
): Promise<{
  writeFile: (filePath: string) => Promise<unknown>
  headers?: Record<string, unknown>
}> {
  const api = imMessageResourceApi()
  return api.get({ path: { message_id: messageId, file_key: fileKey }, params: { type } })
}

/* ------------------------------------------------------------------ *
 * 发送消息
 * ------------------------------------------------------------------ */

/** 回复某条消息（用于“收到，处理中…”这类即时反馈）。 */
export async function replyText(messageId: string, text: string): Promise<string | null> {
  const api = imMessageApi()
  const res = await api.reply({
    path: { message_id: messageId },
    data: { msg_type: "text", content: JSON.stringify({ text }) },
  })
  if (res?.code && res.code !== 0) log.warn("reply 失败", res.code, res.msg)
  return res?.data?.message_id ?? null
}

/** 主动给用户发消息（open_id 维度）。 */
export async function sendText(openId: string, text: string): Promise<string | null> {
  const api = imMessageApi()
  const res = await api.create({
    params: { receive_id_type: "open_id" },
    data: { receive_id: openId, msg_type: "text", content: JSON.stringify({ text }) },
  })
  if (res?.code && res.code !== 0) log.warn("create 失败", res.code, res.msg)
  return res?.data?.message_id ?? null
}

/* ------------------------------------------------------------------ *
 * 出站：上传并发送文件 / 图片
 * ------------------------------------------------------------------ */

function imFileApi(): any {
  const anyClient = client as any
  return anyClient?.im?.v1?.file ?? anyClient?.im?.file
}

function imImageApi(): any {
  const anyClient = client as any
  return anyClient?.im?.v1?.image ?? anyClient?.im?.image
}

/** 飞书 file 消息的 file_type 枚举映射。 */
function fileTypeOf(fileName: string): "opus" | "mp4" | "pdf" | "doc" | "xls" | "ppt" | "stream" {
  switch (path.extname(fileName).toLowerCase()) {
    case ".pdf":
      return "pdf"
    case ".doc":
    case ".docx":
      return "doc"
    case ".xls":
    case ".xlsx":
      return "xls"
    case ".ppt":
    case ".pptx":
      return "ppt"
    case ".mp4":
      return "mp4"
    case ".opus":
      return "opus"
    default:
      return "stream"
  }
}

/** 上传文件到飞书，返回 file_key。 */
export async function uploadFile(filePath: string): Promise<string | null> {
  const buffer = await fs.readFile(filePath)
  const api = imFileApi()
  const res = await api.create({
    data: { file_type: fileTypeOf(filePath), file_name: path.basename(filePath), file: buffer },
  })
  return res?.file_key ?? null
}

/** 把本地文件发送给用户（单聊/群）。 */
export async function sendFile(openId: string, filePath: string): Promise<boolean> {
  const fileKey = await uploadFile(filePath)
  if (!fileKey) {
    log.warn("上传文件失败", filePath)
    return false
  }
  const api = imMessageApi()
  const res = await api.create({
    params: { receive_id_type: "open_id" },
    data: {
      receive_id: openId,
      msg_type: "file",
      content: JSON.stringify({ file_key: fileKey }),
    },
  })
  return !(res?.code && res.code !== 0)
}

/** 把本地图片作为图片消息发送给用户。 */
export async function sendImage(openId: string, filePath: string): Promise<boolean> {
  const buffer = await fs.readFile(filePath)
  const imageApi = imImageApi()
  const res = await imageApi.create({ data: { image_type: "message", image: buffer } })
  const imageKey = res?.image_key
  if (!imageKey) {
    log.warn("上传图片失败", filePath)
    return false
  }
  const api = imMessageApi()
  const sent = await api.create({
    params: { receive_id_type: "open_id" },
    data: {
      receive_id: openId,
      msg_type: "image",
      content: JSON.stringify({ image_key: imageKey }),
    },
  })
  return !(sent?.code && sent.code !== 0)
}

/* ------------------------------------------------------------------ *
 * 用户身份（接飞书后自动获取 open_id / 姓名 / 部门 / 管理员）
 * ------------------------------------------------------------------ */

export interface FeishuUser {
  openId: string
  name: string
  department: string
  isAdmin: boolean
}

async function fetchDepartmentName(departmentId: string): Promise<string> {
  const api = contactDepartmentApi()
  if (!api?.get) return departmentId
  try {
    const res = await api.get({
      path: { department_id: departmentId },
      params: { department_id_type: "open_department_id" },
    })
    return res?.data?.department?.name ?? departmentId
  } catch (error) {
    log.debug("获取部门信息失败", departmentId, (error as Error).message)
    return departmentId
  }
}

/**
 * 通过通讯录接口补全用户信息。
 * 缺少通讯录权限时会优雅降级，仅保留 open_id。
 */
export async function resolveUser(openId: string): Promise<FeishuUser> {
  let name = ""
  let department = ""

  const api = contactUserApi()
  if (api?.get) {
    try {
      const res = await api.get({
        path: { user_id: openId },
        params: { user_id_type: "open_id", department_id_type: "open_department_id" },
      })
      const user = res?.data?.user
      name = user?.name ?? ""
      const departmentId = user?.department_ids?.[0]
      if (departmentId) department = await fetchDepartmentName(departmentId)
    } catch (error) {
      log.warn("获取用户信息失败（请确认已开通通讯录权限）", openId, (error as Error).message)
    }
  }

  const isAdmin =
    config.policy.adminOpenIds.includes(openId) ||
    (department !== "" && config.policy.adminDepartments.includes(department))

  return { openId, name, department, isAdmin }
}

/* ------------------------------------------------------------------ *
 * 启动长连接
 * ------------------------------------------------------------------ */

export interface BotHandlers {
  onMessage: (message: IncomingMessage, data: any) => void | Promise<void>
}

/* ------------------------------------------------------------------ *
 * 事件去重：飞书在未及时收到 ACK 时会重发同一条消息
 * ------------------------------------------------------------------ */

const seenMessages = new Map<string, number>()
const DEDUPE_TTL_MS = 10 * 60 * 1000

function isDuplicate(messageId: string): boolean {
  if (!messageId) return false
  const now = Date.now()
  for (const [id, ts] of seenMessages) {
    if (now - ts > DEDUPE_TTL_MS) seenMessages.delete(id)
  }
  if (seenMessages.has(messageId)) return true
  seenMessages.set(messageId, now)
  return false
}

/**
 * 用 WebSocket 长连接订阅飞书事件，无需公网回调地址。
 * 用户消息只会进入 onMessage，由上层交给 supervisor。
 */
export async function startFeishuBot(handlers: BotHandlers): Promise<void> {
  const dispatcher = new EventDispatcher({}).register({
    "im.message.receive_v1": (data: any) => {
      const message = parseIncoming(data)
      if (!message) return
      if (isDuplicate(message.messageId)) {
        log.warn(`忽略重复投递的消息 ${message.messageId}`)
        return
      }
      // 关键：不要 await 处理逻辑。SDK 是在事件回调返回后才回 ACK 的，
      // 而 supervisor 调度子智能体可能耗时数分钟，会让飞书判定超时并重发事件，
      // 导致同一条用户消息被重复处理（重复读取用户输入 / 重复回复）。
      // 这里后台执行，让回调立刻返回，ACK 得以即时送达。
      void Promise.resolve(handlers.onMessage(message, data)).catch((error) => {
        log.error("处理消息异常", (error as Error).stack ?? error)
      })
    },
  })

  const wsClient = new WSClient({
    appId: config.feishu.appId,
    appSecret: config.feishu.appSecret,
  })

  await wsClient.start({ eventDispatcher: dispatcher })
  log.info("飞书长连接已启动，等待用户消息…")
}
