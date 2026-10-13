import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))

/** 仓库根目录（包含 opencode.json 与 data/ 的那一层）。 */
export const projectRoot = path.resolve(here, "..", "..")

// 载入 connect_to_feishu/.env（可选）。
try {
  process.loadEnvFile(path.resolve(here, "..", ".env"))
} catch {
  // 没有 .env 时使用环境变量与默认值。
}

function env(name: string, fallback = ""): string {
  const value = process.env[name]
  return value === undefined || value === "" ? fallback : value
}

function list(name: string): string[] {
  return env(name)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

export const config = {
  feishu: {
    appId: env("FEISHU_APP_ID", "cli_aa4f1f6694799bb4"),
    appSecret: env("FEISHU_APP_SECRET"),
  },
  opencode: {
    agent: env("PLM_AGENT", "plm-supervisor"),
    /** supervisor 会话的工作目录，决定它读到哪份 opencode 配置。 */
    directory: env("PLM_PROJECT_ROOT", projectRoot),
    /** 可选：直连已存在的 OpenCode server，跳过共享后台服务。 */
    baseUrl: env("OPENCODE_BASE_URL"),
    token: env("OPENCODE_TOKEN"),
    /**
     * 覆盖会话使用的模型。留空则沿用 agent 文件里的 model。
     * PLM_PROVIDER / PLM_MODEL 需成对提供。
     */
    provider: env("PLM_PROVIDER"),
    model: env("PLM_MODEL"),
    variant: env("PLM_VARIANT"),
    /** 等待 supervisor 单轮回复的超时（毫秒）。文件生成等重任务可调大。 */
    replyTimeoutMs: Number(env("REPLY_TIMEOUT_MS", "1200000")),
  },
  store: {
    /** 用户数据根目录：<repo>/data/user。 */
    userRoot: env("USER_DATA_DIR", path.join(projectRoot, "data", "user")),
  },
  policy: {
    /** 命中这些 open_id 的用户算管理员。 */
    adminOpenIds: list("ADMIN_OPEN_IDS"),
    /** 命中这些部门的用户算管理员。 */
    adminDepartments: list("ADMIN_DEPARTMENTS"),
    /** 群聊里是否仅在 @机器人 时响应。 */
    groupMentionOnly: env("GROUP_MENTION_ONLY", "true") !== "false",
  },
  llm: {
    /** OpenAI 兼容网关地址（与 opencode.jsonc 里的 provider 一致）。 */
    baseUrl: env("LLM_BASE_URL", "http://10.0.62.177:4000/v1"),
    apiKey: env("LLM_API_KEY"),
    /** 多模态/视觉模型（网关会把名字路由到具体后端）。 */
    visionModel: env("VISION_MODEL", "deepseek-v4"),
    /** 图像/扫描件 OCR 的固定提示词。 */
    visionPrompt: env(
      "VISION_PROMPT",
      "请准确提取图像/扫描件中的全部文字与表格，严格以结构良好的标准 Markdown 格式输出，保留原始数据的层级与行列关系。",
    ),
    /** 幻灯片渲染后的视觉解析提示词。 */
    slideVisionPrompt: env(
      "SLIDE_VISION_PROMPT",
      "这些是 PPT 各页渲染图。请逐页输出：标题、要点文字，以及版面与视觉风格（主色/辅助色、字体、排版结构、图形与图片元素、页眉页脚），用 Markdown 分页描述，便于他人据此复刻风格。",
    ),
    requestTimeoutMs: Number(env("LLM_TIMEOUT_MS", "180000")),
  },
  office: {
    /** LibreOffice soffice 路径；留空则自动探测常见安装位置与 PATH。 */
    sofficePath: env("SOFFICE_PATH"),
    /** 是否允许调用 LibreOffice 渲染（默认允许，未安装时自动跳过）。 */
    enabled: env("OFFICE_ENABLED", "true") !== "false",
    /** 单次渲染的等待上限。 */
    convertTimeoutMs: Number(env("OFFICE_TIMEOUT_MS", "120000")),
  },
  memory: {
    /** 是否启用长期记忆（异步摘要 + 每轮注入）。 */
    enabled: env("MEMORY_ENABLED", "true") !== "false",
    /** 每累计多少「轮」（1 轮 = 用户 1 条消息）触发一次摘要。 */
    turnsPerSummary: Number(env("MEMORY_SUMMARY_TURNS", "50")),
    /** 摘要使用的模型（网关会把名字路由到具体后端）。 */
    model: env("SUMMARY_MODEL", "deepseek-v4-free"),
    /** 注入提示词的长期记忆最大字符数。 */
    maxInjectChars: Number(env("MEMORY_MAX_INJECT_CHARS", "6000")),
  },
  files: {
    /** 允许回发到飞书的文件目录白名单；留空则用默认（仓库根、data、临时目录）。 */
    outboundRoots: list("OUTBOUND_FILE_ROOTS"),
  },
  limits: {
    /** 单个附件解析后送入 supervisor 的最大字符数，超出截断。 */
    maxAttachmentChars: Number(env("MAX_ATTACHMENT_CHARS", "60000")),
    /** 扫描版 PDF 最多渲染多少页交给 vision。 */
    maxVisionPdfPages: Number(env("MAX_VISION_PDF_PAGES", "8")),
    /** PDF 抽出的文本少于该字数时，视为扫描件，改走 vision。 */
    scannedPdfThreshold: Number(env("SCANNED_PDF_THRESHOLD", "80")),
    /** 单个附件最大字节数（飞书单文件上限 100MB）。 */
    maxAttachmentBytes: Number(env("MAX_ATTACHMENT_BYTES", String(100 * 1024 * 1024))),
  },
  logLevel: env("LOG_LEVEL", "info") as "debug" | "info" | "warn" | "error",
}

export type AppConfig = typeof config
