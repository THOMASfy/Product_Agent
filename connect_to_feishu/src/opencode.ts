import { OpenCode } from "@opencode/client"
import { Service } from "@opencode/client/service"
import { config } from "./config.js"
import { createLogger } from "./logger.js"
import * as userStore from "./user-store.js"

const log = createLogger("opencode")

type OcClient = ReturnType<typeof OpenCode.make>

/** 单次等待 supervisor 回复的超时时间（可配，默认见 config）。 */
const REPLY_TIMEOUT_MS = config.opencode.replyTimeoutMs

let clientPromise: Promise<OcClient> | null = null

/** 获取 OpenCode 客户端：默认复用后台共享服务，也可直连已存在的 server。 */
async function getClient(): Promise<OcClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      if (config.opencode.baseUrl) {
        const headers = config.opencode.token
          ? { authorization: `Bearer ${config.opencode.token}` }
          : undefined
        log.info(`连接 OpenCode server：${config.opencode.baseUrl}`)
        return OpenCode.make({ baseUrl: config.opencode.baseUrl, headers })
      }
      const endpoint = await Service.ensure()
      log.info(`已就绪 OpenCode 后台服务：${endpoint.url}`)
      return OpenCode.make({ baseUrl: endpoint.url, headers: Service.headers(endpoint) })
    })()
  }
  return clientPromise
}

/* ------------------------------------------------------------------ *
 * 事件订阅：把每个会话的流式文本汇总到对应等待者
 * ------------------------------------------------------------------ */

interface Waiter {
  /**
   * 按出现顺序保存的文本片段。
   * key = assistantMessageID#ordinal：同一次执行可能有多个 assistant 消息
   * （例如“开始调度”的说明 + 最终结论），每个消息也可能有多个文本片段，
   * 只用 ordinal 会互相覆盖，必须带上消息 id。
   */
  segments: Map<string, string>
  settled: boolean
  resolve: (text: string) => void
  reject: (error: Error) => void
}

const waiters = new Map<string, Waiter>()
let subscribed = false

function segmentKey(data: any): string {
  return `${data?.assistantMessageID ?? ""}#${data?.ordinal ?? 0}`
}

function assemble(waiter: Waiter): string {
  // Map 保持插入顺序：先出现的片段在前，最终结论在后。
  return [...waiter.segments.values()].join("")
}

function settle(sessionID: string, ok: boolean, error?: unknown): void {
  const waiter = waiters.get(sessionID)
  if (!waiter || waiter.settled) return
  waiter.settled = true
  waiters.delete(sessionID)
  if (ok) waiter.resolve(assemble(waiter))
  else waiter.reject(new Error(typeof error === "string" ? error : "session execution failed"))
}

async function ensureSubscribed(): Promise<void> {
  if (subscribed) return
  subscribed = true
  const client = await getClient()

  void (async () => {
    // 订阅是 live-only 的，断开后需要重连。
    for (;;) {
      try {
        for await (const event of client.event.subscribe()) {
          const anyEvent = event as any
          const sessionID: string | undefined = anyEvent?.data?.sessionID
          if (!sessionID) continue
          const waiter = waiters.get(sessionID)
          if (!waiter || waiter.settled) continue

          switch (anyEvent.type) {
            case "session.text.delta": {
              // delta 是「增量」文本，必须累加；直接覆盖会丢掉除最后一段外的全部内容。
              const key = segmentKey(anyEvent.data)
              waiter.segments.set(
                key,
                (waiter.segments.get(key) ?? "") + (anyEvent.data.delta ?? ""),
              )
              break
            }
            case "session.text.ended": {
              // ended 携带该片段的完整文本，作为权威值，纠正可能漏收的增量。
              const key = segmentKey(anyEvent.data)
              if (typeof anyEvent.data.text === "string") {
                waiter.segments.set(key, anyEvent.data.text)
              }
              break
            }
            case "session.idle":
            case "session.execution.succeeded":
              settle(sessionID, true)
              break
            case "session.execution.failed":
              settle(sessionID, false, anyEvent.data?.error?.message)
              break
          }
        }
      } catch (error) {
        log.warn("事件订阅中断，1s 后重连", (error as Error).message)
      }
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  })()
}

/* ------------------------------------------------------------------ *
 * 会话管理：一个飞书用户 <-> 一个 supervisor 会话
 * ------------------------------------------------------------------ */

async function getOrCreateSession(openId: string): Promise<string> {
  const client = await getClient()
  const cached = await userStore.getSessionId(openId)

  if (cached) {
    try {
      await client.session.get({ sessionID: cached } as any)
      return cached
    } catch {
      log.warn(`历史会话 ${cached} 已失效，重建。`)
    }
  }

  const session = (await client.session.create({
    agent: config.opencode.agent,
    location: { directory: config.opencode.directory },
    title: `飞书用户 ${openId}`,
    model:
      config.opencode.provider && config.opencode.model
        ? {
            providerID: config.opencode.provider,
            id: config.opencode.model,
            variant: config.opencode.variant || undefined,
          }
        : undefined,
  } as any)) as { id: string }

  await userStore.setSessionId(openId, session.id)
  log.info(`为用户 ${openId} 创建 supervisor 会话 ${session.id}`)
  return session.id
}

/** 兜底：从会话消息里取最后一条 assistant 文本。 */
async function fetchLatestAssistantText(sessionID: string, since = 0): Promise<string> {
  try {
    const client = await getClient()
    const res: any = await client.message.list({ sessionID, order: "desc", limit: 10 } as any)
    const items: any[] = res?.data ?? []
    for (const message of items) {
      if (message?.type !== "assistant") continue
      // 只认本轮（prompt 之后）产生的消息，避免失败时把上一轮的旧回复当成本轮结果。
      const created = message?.time?.created ?? 0
      if (since && created && created < since) continue
      const text = (message.content ?? [])
        .filter((part: any) => part?.type === "text")
        .map((part: any) => part.text)
        .join("")
      if (text.trim()) return text
    }
  } catch (error) {
    log.debug("兜底读取消息失败", (error as Error).message)
  }
  return ""
}

/* ------------------------------------------------------------------ *
 * 对外：把用户消息交给 supervisor 并等回复
 * ------------------------------------------------------------------ */

// 同一用户的消息串行处理，避免并发 prompt 打到同一个会话。
const queues = new Map<string, Promise<unknown>>()

function enqueue<T>(key: string, task: () => Promise<T>): Promise<T> {
  const previous = queues.get(key) ?? Promise.resolve()
  const next = previous.then(task, task)
  queues.set(
    key,
    next.catch(() => undefined),
  )
  return next
}

/**
 * 用户消息 -> supervisor -> （由 supervisor 自行调度 plm-* 子智能体）-> 回复文本。
 * 用户不会直接与子智能体通信。
 */
export function askSupervisor(openId: string, text: string): Promise<string> {
  return enqueue(openId, async () => {
    const client = await getClient()
    const sessionID = await getOrCreateSession(openId)
    await ensureSubscribed()

    const answer = new Promise<string>((resolve, reject) => {
      waiters.set(sessionID, { segments: new Map(), settled: false, resolve, reject })
    })

    const startedAt = Date.now()
    await client.session.prompt({ sessionID, text } as any)

    const timeout = new Promise<string>((_, reject) =>
      setTimeout(() => {
        settle(sessionID, false, `等待 supervisor 回复超时（${REPLY_TIMEOUT_MS / 60000} 分钟）`)
      }, REPLY_TIMEOUT_MS),
    )

    let streamed = ""
    let failure = ""
    try {
      streamed = await Promise.race([answer, timeout])
    } catch (error) {
      failure = (error as Error).message
      log.warn("等待回复失败", failure)
    }

    // 以服务端会话里的「本轮最后一条 assistant 消息」为准：它是 supervisor 的最终结论，
    // 不受订阅建立时机与增量丢包影响。流式文本仅作兜底。
    if (!failure) {
      const authoritative = await fetchLatestAssistantText(sessionID, startedAt)
      if (authoritative.trim()) return authoritative.trim()
    }
    if (streamed.trim()) return streamed.trim()
    return failure ? `处理失败：${failure}` : "（supervisor 未返回有效内容，请稍后重试）"
  })
}
