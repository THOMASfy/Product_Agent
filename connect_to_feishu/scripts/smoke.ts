/**
 * 联通性自检：验证能连上 OpenCode、发现 plm-supervisor，并完整跑一轮 prompt。
 * 运行：npx tsx scripts/smoke.ts
 */
import { OpenCode } from "@opencode/client"
import { Service } from "@opencode/client/service"
import { config } from "../src/config.js"

const endpoint = config.opencode.baseUrl
  ? { url: config.opencode.baseUrl, auth: undefined }
  : await Service.ensure()

const client = OpenCode.make({
  baseUrl: endpoint.url,
  headers: config.opencode.baseUrl && config.opencode.token
    ? { authorization: `Bearer ${config.opencode.token}` }
    : ("auth" in endpoint ? Service.headers(endpoint) : undefined),
})

console.log("service:", endpoint.url)

const agents: any = await client.agent.list({ location: { directory: config.opencode.directory } } as any)
const ids = (agents?.data ?? agents ?? []).map?.((a: any) => a?.id ?? a?.name)
console.log("agents:", ids)
if (!ids?.includes(config.opencode.agent)) {
  console.error(`未找到 agent ${config.opencode.agent}，请检查 opencode.json / .opencode/agents`)
  process.exit(1)
}

const session: any = await client.session.create({
  agent: config.opencode.agent,
  location: { directory: config.opencode.directory },
  title: "smoke test",
  model:
    config.opencode.provider && config.opencode.model
      ? {
          providerID: config.opencode.provider,
          id: config.opencode.model,
          variant: config.opencode.variant || undefined,
        }
      : undefined,
} as any)
console.log("session:", session.id)

let text = ""
const done = new Promise<void>((resolve) => {
  void (async () => {
    for await (const event of client.event.subscribe()) {
      const e = event as any
      if (e?.data?.sessionID !== session.id) continue
      if (e.type === "session.text.delta") text += e.data.delta ?? ""
      if (["session.idle", "session.execution.succeeded", "session.execution.failed"].includes(e.type)) {
        console.log("event:", e.type, JSON.stringify(e.data))
        resolve()
      }
    }
  })()
})

await client.session.prompt({
  sessionID: session.id,
  text: "请只回复两个字：pong",
} as any)

const timeout = new Promise<void>((resolve) => setTimeout(resolve, 120_000))
await Promise.race([done, timeout])

console.log("reply:", JSON.stringify(text))
process.exit(0)
