import { config } from "./config.js"
import { summarizeMemory } from "./llm.js"
import { createLogger } from "./logger.js"
import { truncate } from "./text.js"
import * as userStore from "./user-store.js"

const log = createLogger("memory")

/** 正在摘要的用户，避免同一用户并发摘要。 */
const running = new Set<string>()

function formatTranscript(entries: userStore.HistoryEntry[]): string {
  return entries
    .map((entry) => `${entry.role === "user" ? "用户" : "助手"}: ${entry.content}`)
    .join("\n")
}

/**
 * 若短期缓冲累计达到阈值（默认 50 轮），**异步**触发一次长期记忆摘要。
 * 不阻塞调用方（用户回复已经发出）；同一用户不会并发摘要。
 *
 * 1 轮 = 用户 1 条消息；摘要成功后清掉已摘要的缓冲，新对话继续累计。
 */
export function maybeSummarize(openId: string): void {
  if (!config.memory.enabled) return
  if (running.has(openId)) return
  running.add(openId)
  summarize(openId)
    .catch((error) => log.error(`长期记忆摘要失败 ${openId}`, (error as Error).stack ?? error))
    .finally(() => running.delete(openId))
}

async function summarize(openId: string): Promise<void> {
  const entries = await userStore.readHistoryAll(openId)
  const turns = entries.filter((entry) => entry.role === "user").length
  if (turns < config.memory.turnsPerSummary) return

  const snapshotCount = entries.length
  const transcript = formatTranscript(entries).slice(0, 60000)
  const existing = await userStore.readMemory(openId)

  const updated = await summarizeMemory(existing, transcript)

  await userStore.writeMemory(openId, updated)
  // 只移除本次已摘要的部分；期间新到的对话（追加在尾部）保留下来继续累计。
  await userStore.trimHistoryHead(openId, snapshotCount)
  log.info(`用户 ${openId} 长期记忆已更新，清空 ${snapshotCount} 条缓冲（约 ${turns} 轮）`)
}

/** 读取用于注入提示词的长期记忆块（超长截断）。 */
export async function readMemoryBlock(openId: string): Promise<string> {
  if (!config.memory.enabled) return ""
  const memory = await userStore.readMemory(openId)
  if (!memory.trim()) return ""
  return truncate(memory.trim(), config.memory.maxInjectChars)
}
