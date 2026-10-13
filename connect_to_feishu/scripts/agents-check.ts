import { OpenCode } from "@opencode/client"
import { Service } from "@opencode/client/service"

const endpoint = await Service.ensure()
const client = OpenCode.make({ baseUrl: endpoint.url, headers: Service.headers(endpoint) })

const agents: any = await client.agent.list({ location: { directory: "C:\\Product_Agent" } } as any)
const list = Array.isArray(agents) ? agents : agents?.data ?? []
for (const agent of list) {
  const name = agent?.name ?? agent?.id
  const mode = agent?.mode ?? "?"
  console.log(`${agent?.id ?? agent?.name}\t${mode}`)
}
const target = list.find((a: any) => a?.id === "plm-docs" || a?.name === "plm-docs")
console.log("\nplm-docs present:", Boolean(target))
