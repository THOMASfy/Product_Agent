import { config } from "./config.js"
import { createLogger } from "./logger.js"

const log = createLogger("vision")

export interface VisionImage {
  /** 例如 image/png、image/jpeg。 */
  mimeType: string
  /** base64（不含 data: 前缀）。 */
  base64: string
}

interface ChatCompletionResponse {
  choices?: Array<{ message?: { content?: string | null } }>
  error?: { message?: string }
}

/**
 * 调用 OpenAI 兼容网关的视觉模型，把一张或多张图片 OCR 成 Markdown。
 * 网关支持 image_url 形式的 data URL（已实测）。
 */
export async function extractWithVision(
  images: VisionImage[],
  prompt = config.llm.visionPrompt,
): Promise<string> {
  if (images.length === 0) return ""

  const content: any[] = [{ type: "text", text: prompt }]
  for (const image of images) {
    content.push({
      type: "image_url",
      image_url: { url: `data:${image.mimeType};base64,${image.base64}` },
    })
  }

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
        model: config.llm.visionModel,
        messages: [{ role: "user", content }],
        temperature: 0,
        max_tokens: 8192,
      }),
      signal: controller.signal,
    })

    const text = await response.text()
    if (!response.ok) {
      throw new Error(`vision HTTP ${response.status}: ${text.slice(0, 300)}`)
    }

    const data = JSON.parse(text) as ChatCompletionResponse
    if (data.error?.message) throw new Error(`vision 返回错误: ${data.error.message}`)
    const result = data.choices?.[0]?.message?.content ?? ""
    log.info(`vision 解析 ${images.length} 张图片，得到 ${result.length} 字`)
    return result
  } finally {
    clearTimeout(timer)
  }
}
