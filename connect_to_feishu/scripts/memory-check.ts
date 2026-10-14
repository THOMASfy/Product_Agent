import * as userStore from "../src/user-store.js"
import { maybeSummarize, readMemoryBlock } from "../src/memory.js"

const openId = "ou_memory_test"
const entries: userStore.HistoryEntry[] = []
for (let i = 1; i <= 50; i++) {
  entries.push({ ts: new Date().toISOString(), role: "user", content: `第${i}轮：我们在做路内智慧停车项目，主色 #0070C0，喜欢简洁汇报。` })
  entries.push({ ts: new Date().toISOString(), role: "assistant", content: `第${i}轮：已记录该偏好。` })
}
await userStore.appendHistory(openId, entries)
console.log("seeded entries:", (await userStore.readHistoryAll(openId)).length)

maybeSummarize(openId)

for (let i = 0; i < 90; i++) {
  await new Promise((r) => setTimeout(r, 1000))
  const m = await userStore.readMemory(openId)
  if (m.trim()) {
    console.log("=== memory.md ===")
    console.log(m.trim().slice(0, 800))
    break
  }
}
console.log("history after:", (await userStore.readHistoryAll(openId)).length)
const block = await readMemoryBlock(openId)
console.log("inject block chars:", block.length)
