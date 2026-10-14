# connect_to_feishu

把 OpenCode 的 **PLM supervisor** 接入飞书。用户只在飞书里跟机器人说话，
消息统一进入 `plm-supervisor`；是否调用 `plm-*` 子智能体、调用哪些，由
supervisor 自己判断。用户**不会**直接与子智能体通信。

```
飞书用户
   │  发消息（p2p 或 @机器人）
   ▼
飞书长连接（WSClient，无需公网回调地址）
   │  im.message.receive_v1
   ▼
本服务（connect_to_feishu）
   │  1. 解析消息、识别用户、写入 data/user
   │  2. 转发给 supervisor
   ▼
OpenCode  ──  plm-supervisor（primary agent）
                   │  按需 subagent 调度
                   ├── plm-requirements
                   ├── plm-design
                   ├── plm-sourcing
                   ├── plm-manufacturing
                   ├── plm-quality
                   ├── plm-launch
                   └── plm-sustainment
   │  流式收集回复（session.text.delta / session.idle）
   ▼
本服务 ── 回复飞书消息
```

## 目录

```
connect_to_feishu/
├── .env / .env.example    # 凭证与配置
├── scripts/smoke.ts       # 联通性自检
└── src/
    ├── index.ts           # 入口：装配并启动
    ├── config.ts          # 读取 .env / 环境变量
    ├── logger.ts
    ├── text.ts            # 文本分片、去 @
    ├── feishu.ts          # 飞书：长连接、发消息、抓用户信息
    ├── opencode.ts        # OpenCode：会话管理、prompt、收集回复
    └── user-store.ts      # data/user 读写（profile / history / index）
```

## 快速开始

```sh
cd connect_to_feishu
npm install
npm start          # 开发时可用 npm run dev
```

`.env` 已填好：

```
FEISHU_APP_ID=cli_aa4f1f6694799bb4
FEISHU_APP_SECRET=<你的飞书应用 App Secret>
GROUP_MENTION_ONLY=true
```

先跑一次自检，确认 OpenCode 能加载到 `plm-supervisor` 并正常回复：

```sh
npx tsx scripts/smoke.ts
# 期望输出 ... reply: "pong"
```

## 飞书开发者后台需要配置

1. **机器人能力**：开启「机器人」。
2. **事件订阅**：`事件与回调 → 订阅方式 → 使用长连接接收事件`，并订阅
   `接收消息 im.message.receive_v1`。
3. **权限**：至少开通
   - `im:message`（读消息）
   - `im:message:send_as_bot`（以机器人身份发消息）
   - `im:resource`（下载消息里的文件附件）
   - `contact:user.base:readonly`（读用户姓名等基础信息）
   - `contact:department.base:readonly`（读部门信息）
   没有通讯录权限时程序不会崩，只是姓名/部门留空、identity 退化为「普通用户」。
4. 把要使用的人加入应用「可用范围」。

> 想用公网回调（Webhook）而不是长连接时，SDK 也提供 `adaptExpress` / `adaptKoa`
> 适配器，可在此基础上改造 `src/feishu.ts`。

## 配置项（.env）

| 变量 | 说明 |
| --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书应用凭证 |
| `PLM_PROJECT_ROOT` | supervisor 工作目录，默认仓库根 `C:\Product_Agent` |
| `PLM_AGENT` | supervisor agent id，默认 `plm-supervisor` |
| `PLM_PROVIDER` / `PLM_MODEL` / `PLM_VARIANT` | 可选，临时覆盖会话模型；留空则用 agent 文件里的 model |
| `OPENCODE_BASE_URL` / `OPENCODE_TOKEN` | 直连已存在的 OpenCode server，跳过共享后台服务 |
| `ADMIN_OPEN_IDS` / `ADMIN_DEPARTMENTS` | 命中者记为「管理员」，逗号分隔 |
| `GROUP_MENTION_ONLY` | 群里是否仅在 @机器人 时响应，默认 `true` |
| `LOG_LEVEL` | `debug` / `info` / `warn` / `error` |

## 文档 / 文件消息（状态驱动的延迟解析）

因为飞书私聊无法同时发「文件 + 文本指令」，连接器采用**先存后解**的两段式：

```
路径 A：仅收到文件/图片 → 下载存到 attachments/ + 记入 pending.json
                         → 不调用 OpenCode、不解析、不摘要（静默）
路径 B：收到文本指令 → 读取 pending → 解析器路由 → 拼装联合上下文 → 交给 supervisor
```

**路径 A（File Received Only）**
- 立即把文件**临时暂存**到 `data/user/<open_id>/attachments/`，写入 `pending.json`。
- **绝不触发任何 Session / 推理 / 摘要**，无回复（仅后台存好）。
- 文件不长期留档：等路径 B 处理完本轮后即删除。

**路径 B（Instruction Received）**
- Step 1 读取 `pending.json` 里的暂存附件；
- Step 2 解析器路由：
  - 图片 / 扫描件 PDF / 截图 / 拍照单据 → **vision 模型**（网关多模态，
    固定提示词：准确提取图像/扫描件中的全部文字与表格，输出标准 Markdown）；
  - 电子结构化文档 → **代码解析器**（docx→mammoth、doc→word-extractor、pdf→unpdf 文本层、纯文本直读）；
- Step 3 按模板拼装联合上下文，一次性交给 supervisor：

  ```markdown
  ### 待处理上下文数据
  【关联文件】: {file_name}
  【原始文件路径】: {file_abs_path}   # 可选，供 docgen 复用模板
  【文档/表格解析内容】:
  {parsed_markdown_content}

  ---
  ### 用户执行指令
  {user_text_instruction}
  ```

- 消费后清空 `pending.json`；本轮处理完成后再删除暂存的附件文件（**不备份**）。

要点：
- 支持：`.docx` `.doc` `.pdf` `.pptx` `.ppt` `.txt` `.md` `.csv` `.json` `.log` `.xml` `.html` `.htm`
  以及图片 `.png` `.jpg` `.jpeg` `.webp` `.gif` `.bmp` `.tif` `.tiff`。
- **PPTX**：纯 JS 解析出画布尺寸、主题配色/字体、媒体清单、逐页文本与配色/字体/图片引用
  （不再出现 zip 乱码）。**若本机装了 LibreOffice**，会再把每页渲染成图片交给 vision 描述
  视觉风格，实现"复刻版式"；未安装则自动跳过、只给结构信息。
- 扫描件判定：PDF 文本层少于 `SCANNED_PDF_THRESHOLD`（默认 80 字）即按扫描件走 vision，
  最多渲染 `MAX_VISION_PDF_PAGES`（默认 8）页。
- 解析正文送入 supervisor，超过 `MAX_ATTACHMENT_CHARS`（默认 60000 字）会截断。
- **不依赖文档权限**：机器人因为收到了这条消息，就有权用 `im:resource` 下载其中的资源。
- 多模态走 OpenAI 兼容网关（`LLM_BASE_URL`/`LLM_API_KEY`/`VISION_MODEL`），
  网关会把模型名路由到具体后端（实测 `deepseek-v4` → MiniMax-M3、`DeepSeek-V4-Pro` → Kimi-K2.5）。

> 如果用户只能给一个**飞书云文档链接**（不是发文件），用飞书官方 MCP 读取：
> 已配置在 `opencode.jsonc` 的 `mcp.servers.lark`，以**用户身份**读取
> （能读「机器人无权限、但你有权限」的文档）。首次需登录一次：
>
> ```cmd
> npx -y @larksuiteoapi/lark-mcp login -a <你的飞书应用 App ID> -s <你的飞书应用 App Secret>
> ```
>
> 之后 `opencode mcp list` 应显示 `✓ lark connected`。注意 lark-mcp 目前
> **不支持文件上传/下载**，只支持云文档（docx/wiki/bitable 等）的在线读取。

## 生成文件回发到飞书

连接器支持把服务器上的文件/图片**发回给用户**。约定：当 supervisor 的回复里包含标记时，
连接器会自动上传并发送，然后从文本中删除标记：

```
[[send-file: C:\Product_Agent\data\user\<open_id>\output\汇报.pptx]]
[[send-image: C:\Product_Agent\data\user\<open_id>\output\封面.png]]
```

- 文件走 `im.v1.file.create`（≤30MB），图片走 `im.v1.image.create`（≤10MB）。
- 只允许发送白名单目录内的路径（默认：仓库根、`data/user`、系统临时目录；
  可用 `OUTBOUND_FILE_ROOTS` 覆盖），防止误发敏感文件。
- 生成文件临时写到 `data/user/<open_id>/output/`，**回发飞书后即清空**（不长期保留）。

### 文件生成（PPT / Word / Excel / PDF）

`plm-supervisor` 自身 **deny edit / deny shell**，不直接写文件；它会把「做文件」类需求
路由给专门的文件 subagent **`plm-docs`**：

- 只对 `plm-docs` 放行 `docgen` skill（全局对其余 agent 隐藏）。
- `plm-docs` 只允许写 `data/user/*/output/*`，只允许执行 skill 自带的 Node 启动器
  `run.mjs`（其内部自行定位 Python），其余 edit/shell 一律拒绝。
- skill 用 Python（python-pptx / python-docx / openpyxl）+ LibreOffice 生成
  `.pptx` / `.docx` / `.xlsx` / `.pdf`，生成后由 `plm-docs` 输出
  `[[send-file: ...]]` 标记，连接器负责回发。

环境依赖（已在本机安装）：`python-pptx python-docx openpyxl pdf2image Pillow`
与 LibreOffice（用于 PDF 导出与预览渲染；`SOFFICE_PATH` 可覆盖路径）。

## 记忆：短期 = 会话，长期 = memory.md

- **短期记忆**：每个用户始终是**同一个长时间存活的 supervisor 会话**（`session.json`），
  多轮上下文由 OpenCode 会话承担。
- **长期记忆**：`data/user/<open_id>/memory.md`，**单份滚动摘要**。
  - 每累计 `MEMORY_SUMMARY_TURNS`（默认 50）**轮**（1 轮 = 用户 1 条消息），
    **异步**把 `history.jsonl` 的对话合并进 `memory.md`，然后清空缓冲、重新累计；
  - **每一轮**都会把当前 `memory.md` 作为「长期记忆」块拼进提示词，
    即使会话被 compaction 压缩，关键事实仍在；
  - 摘要调用网关模型 `SUMMARY_MODEL`（默认 `deepseek-v4-free`），失败不影响本轮回复。
- **缓冲日志**：`history.jsonl` 只保留**未摘要**的对话；摘要后清空，**不保留原始归档**。

## 与 data/user 的衔接

`<repo>/data/user` 下按用户隔离（结构见 `data/user/README.md`）：

- `data/user/<open_id>/profile.json`：`open_id` / `identity` / `department` / `name`。
  `open_id` 来自消息事件；`department`、姓名来自通讯录接口；
  `identity` 由 `ADMIN_OPEN_IDS` / `ADMIN_DEPARTMENTS` 判定。
- `data/user/<open_id>/session.json`：该用户绑定的 supervisor 会话 id（短期记忆）。
- `data/user/<open_id>/memory.md`：长期记忆，异步滚动摘要。
- `data/user/<open_id>/history.jsonl`：未摘要对话缓冲，摘要后清空。
- `data/user/<open_id>/pending.json`：暂存待处理的附件（被文本指令消费后清空）。
- `data/user/<open_id>/attachments/`：上传附件**临时暂存，处理完即删**。
- `data/user/<open_id>/output/`：生成文件**临时产出，回发后即清空**。
- `data/user/_index.json`：所有沟通过的用户汇总。

> 「有哪些用户跟 agent 沟通过」「这个用户是不是管理员」可直接从 `data/user` 得到；
> 但原始历史不长期保留，只有 `memory.md` 的要点摘要会沉淀。

## 说明

- 每个飞书用户对应一个长期 supervisor 会话，多轮对话有上下文；同一用户的消息
  串行处理，避免并发 prompt 打乱会话。
- 处理可能耗时（supervisor 要调度子智能体），因此会先回「收到，处理中…」，
  再回最终结论；超长回复自动分片。
- 用户身份以 `【当前飞书用户】...` 形式注入提示词，便于 supervisor 区分权限。

### ⚠️ 模型配置注意

`.opencode/agents/*.md` 里写的是 `myapi/deepseek-v4-free`。实测在未配置
`myapi` provider 的环境下，上游会报 `Model exo-free has been deprecated`。
本连接器**默认沿用 agent 文件里的 model**，不做覆盖；只要你在 OpenCode 里把
`myapi` provider 配好（指向可用模型），整条链路即可工作。

如果某次需要临时改用别的 provider，可在 `.env` 里打开可选覆盖：

```
PLM_PROVIDER=company-internal
PLM_MODEL=deepseek-v4-free
```

（`company-internal` 是 `opencode.json` 里已配置的 provider，仅作示例。）
