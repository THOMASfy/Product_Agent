---
name: 用户记忆 (User Memory)
description: 记录和读取与 agent 沟通过的用户档案与历史对话。当需要识别当前用户身份（普通用户/管理员）、区分权限、或回顾该用户的历史对话时使用。数据位于 data/user/。
---

# 用户记忆 Skill

## 用途
让 agent 能够**识别用户**并**延续上下文**。回答"有哪些用户跟 agent 沟通过"、
"这个用户是谁 / 是管理员吗"、"他上次问了什么"这类问题，以及需要按用户区分
权限或个性化时，必须使用本 skill。

## 数据位置
所有数据在仓库根目录的 `data/user/` 下：

```
data/user/
├── _index.json              # 用户索引：有哪些用户沟通过
├── _template/               # 新用户模板
└── <open_id>/               # 一个用户一个目录，目录名 = 飞书 open_id
    ├── profile.json         # 身份：identity / open_id / department ...
    └── history.jsonl        # 历史对话：一行一条消息
```

字段定义详见 `data/user/README.md`。

## 识别当前用户
- 接入飞书后，当前用户的 `open_id`、`identity`、`department` 会由连接器自动提供，
  目录名即 `open_id`。
- 若当前会话拿不到 `open_id`（如本地测试），可临时使用 `local_test_user`，
  或在回复中说明无法确定用户身份，不要编造 open_id。

## 读取（会话开始 / 需要上下文时）
1. 读 `data/user/<open_id>/profile.json` 获取身份，重点看 `identity`：
   - `管理员`：可执行管理类操作（查看他人记录、批量维护等）。
   - `普通用户`：只处理与其本人相关的数据。
2. 读 `data/user/<open_id>/history.jsonl` 回顾历史对话（必要时只取最近 N 条，
   不要把整份历史塞进上下文）。
3. 若目录不存在，说明是新用户，走"新建档案"流程。

## 写入（每轮对话后）
1. **profile**：新用户时，复制 `_template/` 到 `data/user/<open_id>/`，
   填写 `open_id` / `identity` / `department`，设置 `created_at`、`updated_at`；
   老用户只更新 `updated_at`（身份/部门有变化时同步更新）。
2. **history**：向 `data/user/<open_id>/history.jsonl` **追加**两行——
   用户消息一行、agent 回复一行，格式：
   ```jsonl
   {"ts":"2026-10-12T10:00:00+08:00","role":"user","content":"..."}
   {"ts":"2026-10-12T10:00:05+08:00","role":"assistant","agent":"plm-supervisor","specialists":["plm-requirements"],"content":"..."}
   ```
   只追加、不重写、不删行。
3. **索引**：在 `data/user/_index.json` 的 `users` 中新增或更新该用户的
   `open_id` / `identity` / `department` / `name` / `last_seen` / `message_count`，
   并刷新 `updated_at`。

## 约束
- 不编造 `open_id`、部门、身份等飞书字段；拿不到就留空并标注。
- 写文件需要 edit/write 权限；若当前 agent 被限制写文件，改为把结果返回给
  有权限的上游处理，不要伪造"已保存"。
- 用户数据含个人信息，只用于本系统，不对外泄露或写入其他位置。
