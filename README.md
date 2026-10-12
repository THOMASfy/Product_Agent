# 飞书定时群发机器人

基于飞书开放平台**企业自建应用**（非自定义机器人 Webhook）实现的定时群消息发送工具。

## 功能

- 获取 `tenant_access_token` 并完成 API 鉴权
- 向指定群（`chat_id`）发送 **text** 类型消息
- 支持 `@用户` / `@所有人`（文档语法）
- 通过 YAML 配置 cron 定时任务，支持多群群发
- **查询并解析**接收消息 content（text / post / image / file 等）

## 前置条件（飞书开放平台）

1. 登录 [飞书开放平台](https://open.feishu.cn/)，创建**企业自建应用**
2. 在「凭证与基础信息」复制 **App ID**、**App Secret**
3. 在「权限管理」开通：
   - `im:message`（获取与发送单聊、群组消息）
   - `im:message:send_as_bot`（以应用身份发消息）
   - `im:message:readonly` 或 `im:message.history:readonly`（读取历史消息，查询 content 时需要）
4. 在「版本管理与发布」创建并发布应用版本
5. 将机器人**添加到目标群**，并确保机器人在群内可发言/可读消息
6. 获取群 `chat_id`（形如 `oc_xxx`），可通过 API 调试台或消息事件中的 `chat_id` 字段获得

## 快速开始

### 1. 安装依赖

```bash
cd feishu-robot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置凭证

```bash
copy .env.example .env
```

编辑 `.env`，填入 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。

### 3. 测试鉴权

```bash
python main.py test-token
```

### 4. 发送测试消息

```bash
python main.py send --chat-id oc_你的群ID --text "Hello from bot"
```

@ 用户示例：

```bash
python main.py send --chat-id oc_xxx --text "请查收" --mention-user-id ou_xxx --mention-name Tom
```

### 5. 配置定时任务

编辑 `config/schedules.yaml`：

```yaml
schedules:
  - name: weekly-reminder
    enabled: true
    cron: "0 9 * * *"   # 每天 9:00
    chat_ids:
      - oc_xxxxxxxxxxxxxxxxxx
    message:
      type: text
      text: "早上好，定时提醒。"
```

cron 格式：`分 时 日 月 周`（与 Linux crontab 类似）

### 6. 启动定时服务

```bash
python main.py run
```

手动触发某条任务（不等待 cron）：

```bash
python main.py run-once --name weekly-reminder
```

### 7. 查询并解析消息 content

获取指定消息（按文档解析 `body.content` 和 `mentions`）：

```bash
python main.py get --message-id om_xxxxxxxx
```

获取群聊历史消息：

```bash
python main.py list --chat-id oc_xxxxxxxx --page-size 10
```

## 接收消息 content 说明

查询接口返回的 `body.content` 是 **JSON 字符串**，与发送时的结构不同：

| msg_type | 接收 content 示例 |
|----------|------------------|
| text | `{"text":"@_user_1 test content"}` |
| post | `{"title":"...", "content":[[{"tag":"text",...}]]}` |
| image | `{"image_key":"img_xxx"}` |

文本消息中的 `@` 会被替换为 `@_user_1` 占位符，真实用户信息在 `mentions` 字段中。
项目中的 `src/message_parser.py` 会自动解析并还原为可读文本。

## 消息 content 说明（发送）

发送接口要求 `content` 为 **JSON 字符串**。本项目按官方文档构造：

```json
{"text": "test content"}
```

@ 用户时在 text 中嵌入：

```
<at user_id="ou_xxxx">Tom</at> 消息正文
```

@ 所有人：

```
<at user_id="all"></at> 消息正文
```

## 项目结构

```
feishu-robot/
├── main.py                 # CLI 入口
├── config/schedules.yaml   # 定时任务配置
├── src/
│   ├── feishu_client.py    # 鉴权 + 发送/查询消息 API
│   ├── message_builder.py  # 构造发送 content
│   ├── message_parser.py   # 解析接收 content
│   └── scheduler_service.py
├── .env.example
└── requirements.txt
```

## 参考文档

- [发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)
- [发送消息内容结构](https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json)
- [接收消息内容结构](https://open.feishu.cn/document/server-docs/im-v1/message-content-description/message_content)
- [获取指定消息的内容](https://open.feishu.cn/document/server-docs/im/v1/message/get)
- [获取会话历史消息](https://open.feishu.cn/document/server-docs/im-v1/message/list)
