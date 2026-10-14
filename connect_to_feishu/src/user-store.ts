import fs from "node:fs/promises"
import path from "node:path"
import { config } from "./config.js"
import { createLogger } from "./logger.js"

const log = createLogger("store")

export type Identity = "普通用户" | "管理员"

export interface Profile {
  open_id: string
  identity: Identity
  department: string
  name: string
  created_at: string | null
  updated_at: string | null
}

export interface HistoryEntry {
  ts: string
  role: "user" | "assistant"
  content: string
  agent?: string
  specialists?: string[]
}

export interface IndexUser {
  open_id: string
  identity: Identity
  department: string
  name: string
  last_seen: string
  message_count: number
}

interface UserIndex {
  updated_at: string | null
  users: IndexUser[]
}

export interface UserSeed {
  open_id: string
  name: string
  department: string
  identity: Identity
}

function userDir(openId: string): string {
  return path.join(config.store.userRoot, sanitize(openId))
}

/** 该用户上传的附件存放目录（原始文件留档）。 */
export function attachmentsDir(openId: string): string {
  return path.join(userDir(openId), "attachments")
}

/** 该用户生成文件的临时目录（发送后即清理，不长期保留）。 */
export function outputDir(openId: string): string {
  return path.join(userDir(openId), "output")
}

/** 清空该用户的产出目录（文件已回发飞书，不再保留）。 */
export async function clearOutput(openId: string): Promise<void> {
  await fs.rm(outputDir(openId), { recursive: true, force: true })
}

/** 清空该用户的上传附件（处理完不再备份）。 */
export async function clearAttachments(openId: string): Promise<void> {
  await fs.rm(attachmentsDir(openId), { recursive: true, force: true })
}

export interface PendingAttachment {
  /** 飞书消息资源 key（file_key / image_key）。 */
  key: string
  /** 展示用文件名。 */
  name: string
  kind: "file" | "image"
  /** 相对 attachments/ 的文件名。 */
  path: string
  message_id: string
  ts: string
}

function pendingPath(openId: string): string {
  return path.join(userDir(openId), "pending.json")
}

/** 读取暂存（尚未被文本指令消费）的附件。 */
export async function readPending(openId: string): Promise<PendingAttachment[]> {
  const file = await readJson<{ attachments: PendingAttachment[] }>(pendingPath(openId))
  return file?.attachments ?? []
}

/** 追加一个暂存附件（路径 A：仅收到文件，先存不解析）。 */
export async function addPending(openId: string, item: PendingAttachment): Promise<void> {
  const dir = userDir(openId)
  await fs.mkdir(dir, { recursive: true })
  const current = await readPending(openId)
  current.push(item)
  const payload = { updated_at: nowIso(), attachments: current }
  await fs.writeFile(pendingPath(openId), JSON.stringify(payload, null, 2) + "\n", "utf8")
}

/** 清空暂存附件（路径 B：指令已消费）。 */
export async function clearPending(openId: string): Promise<void> {
  try {
    await fs.unlink(pendingPath(openId))
  } catch {
    // 不存在即视为已清空。
  }
}

/** open_id 一般形如 ou_xxx，这里再做一层防御，避免路径穿越。 */
function sanitize(openId: string): string {
  return openId.replace(/[^a-zA-Z0-9_-]/g, "_")
}

function nowIso(): string {
  return new Date().toISOString()
}

async function readJson<T>(file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(file, "utf8")) as T
  } catch {
    return null
  }
}

export async function readProfile(openId: string): Promise<Profile | null> {
  return readJson<Profile>(path.join(userDir(openId), "profile.json"))
}

/**
 * 读取用户档案；不存在则用飞书信息创建。
 * 返回档案以及“是否新建”。
 */
export async function ensureProfile(seed: UserSeed): Promise<{ profile: Profile; created: boolean }> {
  const existing = await readProfile(seed.open_id)
  const timestamp = nowIso()

  if (existing) {
    const updated: Profile = {
      ...existing,
      // 飞书侧信息以后端为准，能取到就刷新。
      name: seed.name || existing.name,
      department: seed.department || existing.department,
      identity: seed.identity,
      updated_at: timestamp,
    }
    if (
      updated.name !== existing.name ||
      updated.department !== existing.department ||
      updated.identity !== existing.identity
    ) {
      await writeProfile(updated)
    }
    return { profile: updated, created: false }
  }

  const profile: Profile = {
    open_id: seed.open_id,
    identity: seed.identity,
    department: seed.department,
    name: seed.name,
    created_at: timestamp,
    updated_at: timestamp,
  }
  await writeProfile(profile)
  log.info(`新建用户档案 ${seed.open_id}（${profile.identity}）`)
  return { profile, created: true }
}

async function writeProfile(profile: Profile): Promise<void> {
  const dir = userDir(profile.open_id)
  await fs.mkdir(dir, { recursive: true })
  await fs.writeFile(path.join(dir, "profile.json"), JSON.stringify(profile, null, 2) + "\n", "utf8")
}

/** 追加历史对话（一行一条，永不重写）。 */
export async function appendHistory(openId: string, entries: HistoryEntry[]): Promise<void> {
  if (entries.length === 0) return
  const dir = userDir(openId)
  await fs.mkdir(dir, { recursive: true })
  const lines = entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n"
  await fs.appendFile(path.join(dir, "history.jsonl"), lines, "utf8")
}

function historyPath(openId: string): string {
  return path.join(userDir(openId), "history.jsonl")
}

/** 读取全部历史（时间正序）。history.jsonl 是「未摘要的短期缓冲」。 */
export async function readHistoryAll(openId: string): Promise<HistoryEntry[]> {
  try {
    const raw = await fs.readFile(historyPath(openId), "utf8")
    return raw
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as HistoryEntry)
  } catch {
    return []
  }
}

/** 读取历史对话，默认取最近 limit 条（时间正序返回）。limit<=0 表示全部。 */
export async function readHistory(openId: string, limit = 20): Promise<HistoryEntry[]> {
  const all = await readHistoryAll(openId)
  return limit > 0 ? all.slice(-limit) : all
}

/** 移除缓冲最前面的 removeCount 条（已摘要部分），其余保留（不丢新对话）。 */
export async function trimHistoryHead(openId: string, removeCount: number): Promise<void> {
  if (removeCount <= 0) return
  const kept = (await readHistoryAll(openId)).slice(removeCount)
  const dir = userDir(openId)
  await fs.mkdir(dir, { recursive: true })
  const body = kept.map((entry) => JSON.stringify(entry)).join("\n") + (kept.length ? "\n" : "")
  await fs.writeFile(historyPath(openId), body, "utf8")
}

/** 长期记忆：单份滚动摘要文件 memory.md。 */
function memoryPath(openId: string): string {
  return path.join(userDir(openId), "memory.md")
}

export async function readMemory(openId: string): Promise<string> {
  try {
    return await fs.readFile(memoryPath(openId), "utf8")
  } catch {
    return ""
  }
}

/** 原子写入长期记忆，避免被读到半截内容。 */
export async function writeMemory(openId: string, text: string): Promise<void> {
  const dir = userDir(openId)
  await fs.mkdir(dir, { recursive: true })
  const target = memoryPath(openId)
  const tmp = `${target}.tmp`
  await fs.writeFile(tmp, text.endsWith("\n") ? text : `${text}\n`, "utf8")
  await fs.rename(tmp, target)
}

async function readIndex(): Promise<UserIndex> {
  const index = await readJson<UserIndex>(path.join(config.store.userRoot, "_index.json"))
  return index ?? { updated_at: null, users: [] }
}

/** 更新 _index.json：记录“有哪些用户跟 agent 沟通过”。 */
export async function updateIndex(profile: Profile, messageCountDelta = 1): Promise<void> {
  const index = await readIndex()
  const timestamp = nowIso()
  const current = index.users.find((user) => user.open_id === profile.open_id)

  if (current) {
    current.identity = profile.identity
    current.department = profile.department
    current.name = profile.name
    current.last_seen = timestamp
    current.message_count += messageCountDelta
  } else {
    index.users.push({
      open_id: profile.open_id,
      identity: profile.identity,
      department: profile.department,
      name: profile.name,
      last_seen: timestamp,
      message_count: messageCountDelta,
    })
  }
  index.updated_at = timestamp

  await fs.mkdir(config.store.userRoot, { recursive: true })
  await fs.writeFile(
    path.join(config.store.userRoot, "_index.json"),
    JSON.stringify(index, null, 2) + "\n",
    "utf8",
  )
}

interface SessionFile {
  session_id: string
  updated_at: string
}

/** 读取该用户绑定的 OpenCode supervisor 会话 id。 */
export async function getSessionId(openId: string): Promise<string | null> {
  const file = await readJson<SessionFile>(path.join(userDir(openId), "session.json"))
  return file?.session_id ?? null
}

export async function setSessionId(openId: string, sessionId: string): Promise<void> {
  const dir = userDir(openId)
  await fs.mkdir(dir, { recursive: true })
  const payload: SessionFile = { session_id: sessionId, updated_at: nowIso() }
  await fs.writeFile(path.join(dir, "session.json"), JSON.stringify(payload, null, 2) + "\n", "utf8")
}
