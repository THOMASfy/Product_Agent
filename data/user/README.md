# data/user/ — 用户档案与历史

记录"有哪些用户跟 agent 沟通过"，以及每个用户的 **profile（身份）** 与
**history（历史对话）**。

## 目录结构

```
data/user/
├── _index.json          # 所有已知用户的索引
├── _template/           # 新用户模板
│   ├── profile.json
│   └── history.jsonl
└── ou_xxxxxxxx/         # 一个用户 = 一个目录，目录名 = open_id
    ├── profile.json
    ├── history.jsonl    # 短期缓冲：未摘要的对话（累计到阈值后摘要并清空）
    ├── memory.md        # 长期记忆：单份滚动摘要（每轮注入提示词）
    ├── session.json     # 该用户绑定的 supervisor 会话（连接器维护）
    ├── pending.json     # 暂存待处理的附件（连接器维护）
    ├── attachments/     # 上传附件：临时暂存，处理完即删（不备份）
    └── output/          # 生成文件：临时产出，回发飞书后即清空
```

## profile.json — 用户身份

接入飞书后，以下字段都能自动从飞书获取。

```json
{
  "open_id": "ou_xxxxxxxxxxxxxxxx",
  "identity": "普通用户",
  "department": "产品部",
  "name": "张三",
  "created_at": "2026-10-12T10:00:00+08:00",
  "updated_at": "2026-10-12T10:00:00+08:00"
}
```

| 字段 | 说明 |
| --- | --- |
| `open_id` | 飞书用户唯一标识，与所在目录名一致 |
| `identity` | 身份，取值 `普通用户` 或 `管理员` |
| `department` | 所属部门（飞书部门名） |
| `name` | 显示名（可选） |
| `created_at` | 首次建立档案时间 |
| `updated_at` | 最近一次更新时间 |

## 记忆分两层

### 短期记忆 —— OpenCode 会话（`session.json`）
每个用户始终是**同一个长时间存活的 supervisor 会话**，多轮上下文由它承担。

### 长期记忆 —— `memory.md`（单份滚动摘要）
- 每累计 **50 轮**（1 轮 = 用户 1 条消息）后，**异步**把 `history.jsonl` 里的对话
  合并进 `memory.md` 并滚动重写；随后清空 `history.jsonl`，重新累计。
- `memory.md` 会在**每一轮**拼进提示词（`【长期记忆】` 块），
  这样即使会话被 OpenCode 的 compaction 压缩，关键事实仍在。
- 触发阈值/模型可用 `MEMORY_SUMMARY_TURNS` / `SUMMARY_MODEL` 调整。

### 缓冲日志 —— `history.jsonl`（未摘要的短期缓冲）
JSON Lines，一行一条消息，只追加；**被摘要后即清空，不保留原始归档**。

```jsonl
{"ts":"2026-10-12T10:00:00+08:00","role":"user","content":"帮我做一版新品的PRD"}
{"ts":"2026-10-12T10:00:05+08:00","role":"assistant","agent":"plm-supervisor","content":"..."}
```

| 字段 | 说明 |
| --- | --- |
| `ts` | 时间戳（ISO 8601，含时区） |
| `role` | `user` 或 `assistant` |
| `content` | 消息正文 |
| `agent` | 回复消息由哪个 agent 产生（可选，仅 assistant） |
| `specialists` | 本次编排调用的子智能体（可选，仅 assistant） |

## _index.json — 用户索引

快速回答"有哪些用户跟 agent 沟通过"。

```json
{
  "updated_at": "2026-10-12T10:00:00+08:00",
  "users": [
    {
      "open_id": "ou_xxxxxxxxxxxxxxxx",
      "identity": "普通用户",
      "department": "产品部",
      "name": "张三",
      "last_seen": "2026-10-12T10:00:05+08:00",
      "message_count": 2
    }
  ]
}
```

## 连接器维护的文件

- `session.json`：该用户绑定的 OpenCode supervisor 会话 id，用于多轮上下文（短期记忆）。
- `memory.md`：长期记忆，单份滚动摘要，由连接器异步维护。
- `history.jsonl`：未摘要的对话缓冲；摘要后清空，不保留归档。
- `pending.json`：暂存待处理的附件列表（用户先发文件、后发指令时，指令会消费它）。
- `attachments/`：上传附件**临时暂存**；本轮处理完成后即删除，不备份。
- `output/`：`docgen` skill 的**临时产出**；连接器回发飞书后即清空，不长期保留。
  （为兼容沙箱写入，仍使用该目录，但内容不会留存。）

## 新增一个用户

1. 复制 `_template/` 为 `data/user/<open_id>/`。
2. 填写 `profile.json`（接入飞书后由连接器自动完成）。
3. 首次对话后把该用户追加进 `_index.json`。
