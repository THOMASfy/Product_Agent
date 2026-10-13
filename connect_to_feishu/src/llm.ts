import { config } from "./config.js"
import { createLogger } from "./logger.js"

const log = createLogger("llm")

interface ChatCompletionResponse {
  choices?: Array<{ message?: { content?: string | null } }>
  error?: { message?: string }
}

/**
 * 调用 OpenAI 兼容网关，把「已有长期记忆 + 新增对话」滚动合并成一份更新后的长期记忆。
 * 返回 Markdown 文本；失败时抛出，由调用方决定是否保留旧记忆。
 */
export async function summarizeMemory(existing: string, transcript: string): Promise<string> {
  const system = [
    "你是用户长期记忆的维护者。请把『已有长期记忆』与『新增对话』合并、压缩重写成一份更新后的长期记忆。",
    "要求：",
    "1. 用 Markdown，条目化（可用小标题 + 短句/要点列表），中文。",
    "2. 只保留对后续协作有价值的信息：用户身份/偏好、关注的项目与产品、已确认的结论与决策、待办与未决问题。",
    "3. 删除寒暄、重复、一次性细节；不要编造或推断未出现的事实。",
    "4. 输出即最终的长期记忆全文（会覆盖旧文件），不要输出解释、前缀或代码块围栏。",
  ].join("\n")

  const user = [
    "## 已有长期记忆",
    existing.trim() || "（暂无）",
    "",
    "## 新增对话",
    transcript.trim(),
    "",
    "请输出更新后的长期记忆全文。",
  ].join("\n")

  const url = `${config.llm.baseUrl.replace(/\/+$/, "")}/chat/completions`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), config.llm.requestTimeoutMs)

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${config.llm.apiKey}`,
      },
      body: JSON.stringify({
        model: config.memory.model,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        temperature: 0,
        max_tokens: 4096,
      }),
      signal: controller.signal,
    })

    const text = await response.text()
    if (!response.ok) {
      throw new Error(`summary HTTP ${response.status}: ${text.slice(0, 300)}`)
    }
    const data = JSON.parse(text) as ChatCompletionResponse
    if (data.error?.message) throw new Error(`summary 返回错误: ${data.error.message}`)
    const result = (data.choices?.[0]?.message?.content ?? "").trim()
    if (!result) throw new Error("summary 返回空内容")
    log.info(`长期记忆摘要完成，${result.length} 字`)
    return result
  } finally {
    clearTimeout(timer)
  }
}
