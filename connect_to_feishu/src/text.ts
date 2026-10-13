/** 飞书单条文本消息的字符上限（官方约 150KB，这里保守取 4000 便于阅读）。 */
const CHUNK_SIZE = 4000

/** 把过长的回复切成多条消息发送。 */
export function chunkText(text: string, size = CHUNK_SIZE): string[] {
  const normalized = text.replace(/\r\n/g, "\n").trim()
  if (normalized.length <= size) return [normalized]

  const chunks: string[] = []
  let rest = normalized
  while (rest.length > size) {
    // 优先在换行/句号处断开，读起来更自然。
    let cut = rest.lastIndexOf("\n", size)
    if (cut < size * 0.5) cut = rest.lastIndexOf("。", size)
    if (cut < size * 0.5) cut = size
    else cut += 1
    chunks.push(rest.slice(0, cut).trimEnd())
    rest = rest.slice(cut).trimStart()
  }
  if (rest) chunks.push(rest)
  return chunks.filter(Boolean)
}

/** 截断过长文本，并注明被截断。 */
export function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  return `${text.slice(0, max)}\n\n…（正文过长，已截断，共 ${text.length} 字）`
}

/** 从飞书消息文本里去掉 @机器人的占位符。 */
export function stripMentions(text: string, keys: string[]): string {
  let result = text
  for (const key of keys) {
    result = result.split(key).join(" ")
  }
  // 兜底：去掉形如 @_user_1 的残留占位符。
  result = result.replace(/@_user_\d+/g, " ")
  return result.replace(/[ \t]{2,}/g, " ").trim()
}
