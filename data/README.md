# data/ — 数据目录

本目录存放 Agent 运行时产生的业务数据，与 `.opencode/` 里的智能体配置分开。

```
data/
└── user/                # 用户档案与历史对话
    ├── _index.json      # 已知用户索引（有哪些用户跟 agent 沟通过）
    ├── _template/       # 新用户模板（不要直接改，复制它来建新用户）
    │   ├── profile.json
    │   └── history.jsonl
    └── <open_id>/       # 每个用户一个文件夹，文件夹名 = 飞书 open_id
        ├── profile.json
        ├── history.jsonl
        ├── session.json     # supervisor 会话绑定（连接器维护）
        └── attachments/     # 上传的原始文件留档（连接器维护）
```

## 约定

- **一个用户一个目录**，目录名使用飞书 `open_id`（例如 `ou_xxxxxxxx`）。
  未接入飞书前如需测试，可用临时 id（如 `local_test_user`）。
- `profile.json`：用户身份信息，接入飞书后由连接器自动写入。
- `history.jsonl`：用户历史对话，一行一条消息，便于追加写入。
- 以 `_` 开头的条目（`_index.json`、`_template`）为系统保留，不对应具体用户。

详细字段说明见 [`user/README.md`](user/README.md)。
