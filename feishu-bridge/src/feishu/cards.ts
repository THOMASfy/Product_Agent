import type { FormField, FormInfo, PermissionRequest } from "../opencode/types.js"

/** A stable marker used to route card callbacks back to the bridge. */
export interface CardValue {
  k: "perm" | "form" | "menu" | "cancel"
  s?: string
  r?: string
  d?: string
  f?: string
  key?: string
  v?: unknown
}

export interface CardAction {
  tag: string
  text: { tag: "plain_text"; content: string }
  type?: string
  value: CardValue
}

function callbackButton(text: string, value: CardValue, type = "default"): object {
  return {
    tag: "button",
    text: { tag: "plain_text", content: text },
    type,
    behaviors: [{ type: "callback", value }],
  }
}

function buttonRow(buttons: object[]): object {
  return {
    tag: "column_set",
    flex_mode: "flow",
    horizontal_spacing: "8px",
    columns: buttons.map((b) => ({ tag: "column", width: "auto", elements: [b] })),
  }
}

export function escapeMarkdown(text: string): string {
  return text.replace(/([\\`*_{}[\]()#+\-.!|>])/g, "\\$1")
}

function baseCard(title: string, template: string, elements: object[]): object {
  return {
    schema: "2.0",
    config: { update_multi: true, streaming_mode: false },
    header: {
      title: { tag: "plain_text", content: title },
      template,
    },
    body: { elements },
  }
}

export function markdownCard(title: string, markdown: string, template = "blue"): object {
  return baseCard(title, template, [{ tag: "markdown", content: markdown }])
}

export function statusCard(title: string, markdown: string, template = "turquoise"): object {
  return baseCard(title, template, [{ tag: "markdown", content: markdown }])
}

export function permissionCard(request: PermissionRequest): object {
  const lines = [
    `**操作：** \`${escapeMarkdown(request.action)}\``,
    request.resources?.length ? `**资源：**\n${request.resources.map((r) => `- \`${escapeMarkdown(r)}\``).join("\n")}` : "",
    request.message ? `\n${escapeMarkdown(request.message)}` : "",
  ].filter(Boolean)
  return baseCard("🔐 需要授权", "orange", [
    { tag: "markdown", content: lines.join("\n") },
    buttonRow([
      callbackButton("仅本次允许", { k: "perm", s: request.sessionID, r: request.id, d: "once" }, "primary"),
      callbackButton("始终允许", { k: "perm", s: request.sessionID, r: request.id, d: "always" }, "default"),
      callbackButton("拒绝", { k: "perm", s: request.sessionID, r: request.id, d: "reject" }, "danger"),
    ]),
  ])
}

function fieldHeader(field: FormField, index: number): string {
  const title = field.title ?? field.key
  const required = field.required ? " *必填*" : ""
  const description = field.description ? `\n${escapeMarkdown(field.description)}` : ""
  return `**${index + 1}. ${escapeMarkdown(title)}${required}**${description}`
}

function optionsOf(field: FormField): { value: string; label: string }[] {
  const options = Array.isArray(field.options) ? field.options : []
  return options
    .filter((o): o is { value: string; label?: string } => typeof (o as { value?: unknown }).value === "string")
    .map((o) => ({ value: o.value, label: o.label ?? o.value }))
}

/**
 * Render an OpenCode form (the AI asking a question) as an interactive card.
 * Choice fields become buttons; free-form fields instruct a text fallback.
 */
export function formCard(form: FormInfo, answers: Record<string, unknown>): object {
  const elements: object[] = []
  if (form.metadata && typeof form.metadata === "object" && "description" in form.metadata) {
    elements.push({ tag: "markdown", content: escapeMarkdown(String((form.metadata as { description: unknown }).description)) })
  }
  form.fields.forEach((field, index) => {
    if (field.hidden) return
    const answered = Object.prototype.hasOwnProperty.call(answers, field.key)
    const header = fieldHeader(field, index)
    if (field.type === "multiselect" && optionsOf(field).length > 0) {
      const current = Array.isArray(answers[field.key]) ? (answers[field.key] as unknown[]).map(String) : []
      const summary = current.length > 0 ? `\n已选：**${escapeMarkdown(current.join("、"))}**` : ""
      elements.push({ tag: "markdown", content: `${header}${summary}` })
      elements.push(
        buttonRow(
          optionsOf(field).map((option) => {
            const selected = current.includes(option.value)
            return callbackButton(
              selected ? `✅ ${option.label}` : option.label,
              { k: "form", s: form.sessionID, f: form.id, key: field.key, v: option.value },
              selected ? "primary" : "default",
            )
          }),
        ),
      )
      return
    }
    if (answered) {
      elements.push({ tag: "markdown", content: `${header}\n已选择：**${escapeMarkdown(String(answers[field.key]))}**` })
      return
    }
    elements.push({ tag: "markdown", content: header })
    if (field.type === "boolean") {
      elements.push(
        buttonRow([
          callbackButton("是", { k: "form", s: form.sessionID, f: form.id, key: field.key, v: true }, "primary"),
          callbackButton("否", { k: "form", s: form.sessionID, f: form.id, key: field.key, v: false }, "default"),
        ]),
      )
      return
    }
    const options = optionsOf(field)
    if (options.length > 0) {
      elements.push(
        buttonRow(
          options.map((o) =>
            callbackButton(o.label, { k: "form", s: form.sessionID, f: form.id, key: field.key, v: o.value }),
          ),
        ),
      )
      return
    }
    elements.push({
      tag: "markdown",
      content: `请回复：\`/answer ${form.id} ${field.key}=你的回答\``,
    })
  })
  elements.push({ tag: "hr" })
  elements.push({
    tag: "markdown",
    content: `<font color='grey'>表单 ${form.id} · 完成后将自动提交给 AI</font>`,
    text_size: "notation",
  })
  elements.push(
    buttonRow([callbackButton("✅ 提交", { k: "form", s: form.sessionID, f: form.id }, "primary")]),
  )
  return baseCard("❓ AI 提问", "wathet", elements)
}

export function helpCard(): object {
  const commands = [
    "/new — 开启一个全新会话",
    "/reset — 重置并新建会话",
    "/sessions — 列出当前会话",
    "/agent <name> — 切换 Agent",
    "/model <provider/model> — 切换模型",
    "/stop — 中断当前执行",
    "/export — 导出当前会话（迁移用）",
    "/import <json> — 导入会话（迁移用）",
    "/answer <formId> key=value — 回答 AI 提问",
    "/cron list | add … — 管理定时任务",
    "/whoami — 显示当前绑定信息",
    "/help — 显示本帮助",
  ]
  return baseCard("🤖 OpenCode 机器人", "blue", [
    { tag: "markdown", content: "我可以把你的消息转发给 OpenCode，并实时流式回复。\n\n**支持：**\n- 文本、图片、文件（图片/文本会作为上下文附件）\n- 交互式卡片授权与提问\n- 每个会话独立目录，上下文互不干扰\n- 定时任务、会话迁移" },
    { tag: "hr" },
    { tag: "markdown", content: commands.map((c) => `- \`${c}\``).join("\n") },
  ])
}
