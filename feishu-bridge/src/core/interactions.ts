import type { CardActionEvent } from "@larksuiteoapi/node-sdk"
import type { OpencodeClient } from "../opencode/client.js"
import type { FormField, FormInfo, FormValue, PermissionRequest } from "../opencode/types.js"
import type { AuditLog, Logger } from "../util/logger.js"
import type { FeishuBot } from "../feishu/bot.js"
import type { SessionContext } from "./conversations.js"
import { formCard, permissionCard, statusCard, type CardValue } from "../feishu/cards.js"

interface PendingForm {
  form: FormInfo
  answers: Record<string, FormValue>
  messageId?: string
  context: SessionContext
}

export interface InteractionDeps {
  logger: Logger
  audit: AuditLog
  getClient: () => Promise<OpencodeClient>
  getBot: (name: string) => FeishuBot | undefined
  getContext: (sessionID: string) => SessionContext | undefined
  activeSessions: () => string[]
  pollIntervalMs?: number
}

/**
 * Bridges OpenCode permissions and forms (the AI asking a question) to Feishu
 * interactive cards, and routes card callbacks back to OpenCode.
 *
 * Detection combines the live event stream with polling of the pending lists,
 * so it works regardless of the exact event names a given OpenCode build uses.
 */
export class InteractionService {
  private readonly handledPermissions = new Set<string>()
  private readonly pendingForms = new Map<string, PendingForm>()
  private readonly sessionsWithPermission = new Set<string>()
  private timer?: NodeJS.Timeout
  private polling = false

  constructor(private readonly deps: InteractionDeps) {}

  /** True while a session is blocked on a permission prompt or a question form. */
  hasPending(sessionID: string): boolean {
    if (this.sessionsWithPermission.has(sessionID)) return true
    for (const pending of this.pendingForms.values()) {
      if (pending.form.sessionID === sessionID) return true
    }
    return false
  }

  start(): void {
    if (this.timer) return
    const interval = this.deps.pollIntervalMs ?? 2_000
    this.timer = setInterval(() => void this.poll(), interval)
    this.timer.unref?.()
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer)
    this.timer = undefined
  }

  /** Watch a session for pending interactions (called when a turn starts). */
  async poll(): Promise<void> {
    if (this.polling) return
    this.polling = true
    try {
      const client = await this.deps.getClient()
      for (const sessionID of this.deps.activeSessions()) {
        await this.pollSession(client, sessionID)
      }
    } catch {
      // transient; retry next tick
    } finally {
      this.polling = false
    }
  }

  private async pollSession(client: OpencodeClient, sessionID: string): Promise<void> {
    const context = this.deps.getContext(sessionID)
    if (!context) return
    const bot = this.deps.getBot(context.botName)
    if (!bot) return

    try {
      const permissions = await client.pendingPermissions(sessionID)
      if (permissions.length > 0) this.sessionsWithPermission.add(sessionID)
      else this.sessionsWithPermission.delete(sessionID)
      const currentIds = new Set(permissions.map((p) => p.id))
      for (const id of [...this.handledPermissions]) {
        if (!currentIds.has(id)) this.handledPermissions.delete(id)
      }
      for (const request of permissions) {
        if (this.handledPermissions.has(request.id)) continue
        this.handledPermissions.add(request.id)
        await this.presentPermission(bot, context, request)
      }
    } catch (error) {
      this.deps.logger.debug("Permission poll failed", { sessionID, error: message(error) })
    }

    try {
      const forms = await client.pendingForms(sessionID)
      const currentIds = new Set(forms.map((f) => f.id))
      for (const [id, pending] of [...this.pendingForms]) {
        if (pending.form.sessionID === sessionID && !currentIds.has(id)) this.pendingForms.delete(id)
      }
      for (const form of forms) {
        if (this.pendingForms.has(form.id)) continue
        await this.presentForm(bot, context, form)
      }
    } catch (error) {
      this.deps.logger.debug("Form poll failed", { sessionID, error: message(error) })
    }
  }

  private async presentPermission(bot: FeishuBot, context: SessionContext, request: PermissionRequest): Promise<void> {
    this.deps.audit.record("permission.requested", {
      sessionID: request.sessionID,
      requestID: request.id,
      action: request.action,
      resources: request.resources,
    })
    try {
      await bot.sendCard(context.chatId, permissionCard(request), { replyTo: context.replyTo })
    } catch (error) {
      this.deps.logger.warn("Failed to send permission card", { error: message(error) })
    }
  }

  private async presentForm(bot: FeishuBot, context: SessionContext, form: FormInfo): Promise<void> {
    const pending: PendingForm = { form, answers: {}, context }
    this.pendingForms.set(form.id, pending)
    this.deps.audit.record("form.requested", { sessionID: form.sessionID, formID: form.id, title: form.title })
    try {
      const result = await bot.sendCard(context.chatId, formCard(form, {}), { replyTo: context.replyTo })
      pending.messageId = result.messageId
    } catch (error) {
      this.deps.logger.warn("Failed to send form card", { error: message(error) })
      // Fall back to a text prompt so the question is still answerable.
      await bot
        .sendMarkdown(context.chatId, renderFormAsText(form), { replyTo: context.replyTo })
        .catch((fallbackError) => {
          this.deps.logger.warn("Failed to send form text fallback", { error: message(fallbackError) })
        })
    }
  }

  // ---- card callbacks -----------------------------------------------------

  async handleCardAction(bot: FeishuBot, event: CardActionEvent): Promise<void> {
    const value = event.action.value as CardValue | undefined
    if (!value || typeof value !== "object" || !("k" in value)) return
    this.deps.audit.record("card.action", {
      bot: bot.name,
      chatId: event.chatId,
      operator: event.operator.openId,
      kind: value.k,
    })
    if (value.k === "perm" && value.s && value.r && value.d) {
      await this.resolvePermission(bot, event, value.s, value.r, value.d as "once" | "always" | "reject")
    } else if (value.k === "form" && value.s && value.f) {
      await this.resolveFormAction(bot, event, value)
    }
  }

  private async resolvePermission(
    bot: FeishuBot,
    event: CardActionEvent,
    sessionID: string,
    requestID: string,
    decision: "once" | "always" | "reject",
  ): Promise<void> {
    const client = await this.deps.getClient()
    await client.replyPermission(sessionID, requestID, decision)
    this.handledPermissions.add(requestID)
    const label = decision === "once" ? "仅本次允许" : decision === "always" ? "始终允许" : "已拒绝"
    this.deps.audit.record("permission.replied", { sessionID, requestID, decision })
    try {
      await bot.updateCard(event.messageId, statusCard("🔐 授权已处理", `决定：**${label}**`, decision === "reject" ? "red" : "green"))
    } catch {
      // card may be gone
    }
  }

  private async resolveFormAction(bot: FeishuBot, event: CardActionEvent, value: CardValue): Promise<void> {
    const pending = value.f ? this.pendingForms.get(value.f) : undefined
    if (!pending) {
      await bot.sendText(event.chatId, "该问题已结束或不存在。")
      return
    }
    if (value.key !== undefined) {
      const field = pending.form.fields.find((f) => f.key === value.key)
      if (field?.type === "multiselect") {
        // Toggle selection; submission happens via the explicit submit button.
        const current = Array.isArray(pending.answers[value.key]) ? (pending.answers[value.key] as string[]) : []
        const next = typeof value.v === "string" || typeof value.v === "number" ? String(value.v) : String(value.v)
        const index = current.indexOf(next)
        if (index >= 0) current.splice(index, 1)
        else current.push(next)
        pending.answers[value.key] = current
        await this.refreshFormCard(bot, pending)
        return
      }
      pending.answers[value.key] = normaliseAnswer(value.v)
    }
    const submitted = await this.maybeSubmit(bot, event.chatId, pending, value.key === undefined)
    if (!submitted) await this.refreshFormCard(bot, pending)
  }

  /** Handle `/answer <formId?> key=value ...` from a chat. */
  async answer(sessionID: string, args: string): Promise<string> {
    const pending = [...this.pendingForms.values()].find((p) => p.form.sessionID === sessionID)
    if (!pending) return "当前没有待回答的问题。"
    const tokens = args.trim().split(/\s+/).filter(Boolean)
    let target = pending
    const first = tokens[0]
    if (first && this.pendingForms.has(first)) {
      target = this.pendingForms.get(first) as PendingForm
      tokens.shift()
    }
    return this.applyAnswers(target, tokens)
  }

  private async applyAnswers(pending: PendingForm, tokens: string[]): Promise<string> {
    const applied: string[] = []
    for (const token of tokens) {
      const eq = token.indexOf("=")
      if (eq === -1) continue
      const key = token.slice(0, eq)
      const raw = token.slice(eq + 1)
      const field = pending.form.fields.find((f) => f.key === key)
      if (!field) continue
      pending.answers[key] = coerce(field, raw)
      applied.push(`${key}=${raw}`)
    }
    if (applied.length === 0) return "格式应为：/answer key=value（可多组，用空格分隔）"
    const bot = this.deps.getBot(pending.context.botName)
    if (!bot) return "找不到对应的机器人。"
    const submitted = await this.maybeSubmit(bot, pending.context.chatId, pending, true)
    if (!submitted) await this.refreshFormCard(bot, pending)
    return submitted ? `已提交回答：${applied.join(", ")}` : `已记录：${applied.join(", ")}`
  }

  /**
   * Attempt to submit. When `force` is false the form auto-submits only once
   * every field has an answer; when true it submits only if required fields are
   * satisfied.
   */
  private async maybeSubmit(bot: FeishuBot, chatId: string, pending: PendingForm, force: boolean): Promise<boolean> {
    const visible = pending.form.fields.filter((f) => !f.hidden && f.type !== "external")
    const answered = (f: FormField) => Object.prototype.hasOwnProperty.call(pending.answers, f.key)
    const allAnswered = visible.every(answered)
    const requiredOk = visible.filter((f) => f.required).every(answered)
    if (!force && !allAnswered) return false
    if (force && !requiredOk) {
      const missing = visible.filter((f) => f.required && !answered(f)).map((f) => f.key)
      await bot.sendText(chatId, `以下必填项尚未回答：${missing.join(", ")}`)
      return true
    }
    const client = await this.deps.getClient()
    await client.replyForm(pending.form.sessionID, pending.form.id, pending.answers)
    this.pendingForms.delete(pending.form.id)
    this.deps.audit.record("form.replied", { formID: pending.form.id, answers: pending.answers })
    if (pending.messageId) {
      const summary = Object.entries(pending.answers)
        .map(([k, v]) => `- **${k}**：${Array.isArray(v) ? v.join(", ") : v}`)
        .join("\n")
      try {
        await bot.updateCard(pending.messageId, statusCard("✅ 已提交回答", summary, "green"))
      } catch {
        // card may be gone
      }
    }
    return true
  }

  private async refreshFormCard(bot: FeishuBot, pending: PendingForm): Promise<void> {
    if (!pending.messageId) return
    try {
      await bot.updateCard(pending.messageId, formCard(pending.form, pending.answers))
    } catch (error) {
      this.deps.logger.debug("Failed to refresh form card", { error: message(error) })
    }
  }
}

function normaliseAnswer(value: unknown): FormValue {
  if (Array.isArray(value)) return value.map((v) => String(v))
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "string") return value
  return String(value)
}

function coerce(field: FormField, raw: string): FormValue {
  if (field.type === "number" || field.type === "integer") {
    const n = Number(raw)
    return Number.isNaN(n) ? raw : field.type === "integer" ? Math.trunc(n) : n
  }
  if (field.type === "boolean") return raw === "true" || raw === "是" || raw === "1"
  if (field.type === "multiselect") return raw.split(",").map((v) => v.trim()).filter(Boolean)
  return raw
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Plain-markdown rendering of a form so it stays answerable when the card fails. */
function renderFormAsText(form: FormInfo): string {
  const lines = [`❓ **AI 提问：${form.title}**`]
  if (form.metadata && typeof form.metadata === "object" && "description" in form.metadata) {
    lines.push(String((form.metadata as { description: unknown }).description))
  }
  const fields = form.fields.filter((field) => !field.hidden)
  fields.forEach((field, index) => {
    const title = field.title ?? field.key
    const required = field.required ? "（必填）" : ""
    lines.push(`${index + 1}. **${title}**${required}${field.description ? `：${field.description}` : ""}`)
    if (field.options?.length) {
      lines.push(`   选项：${field.options.map((option) => option.value).join(" / ")}`)
    }
  })
  const sample = fields[0]
  const hint = !sample
    ? "key=value"
    : sample.type === "multiselect"
      ? `${sample.key}=选项1,选项2`
      : sample.type === "boolean"
        ? `${sample.key}=true`
        : `${sample.key}=你的回答`
  lines.push(`\n请回复：\`/answer ${hint}\`（多个字段用空格分隔）`)
  return lines.join("\n")
}
