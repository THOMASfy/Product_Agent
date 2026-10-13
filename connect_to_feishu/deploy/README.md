# 部署与运行环境

## 结论：用户端零安装

文件生成（PPT / Word / Excel / PDF）**全部在服务器上完成**，用户只用飞书：

```
用户(飞书)  ──发文件/指令──►  连接器(服务器)  ──►  OpenCode 服务(同机)
     ▲                                                        │
     └──────────── 生成的 .pptx/.docx/.xlsx/.pdf ◄──  plm-docs + Python + LibreOffice(同机)
```

- `connect_to_feishu` 是**一个集中进程**，用飞书长连接同时服务所有用户。
- 它在**同一台机器**上通过 `@opencode/cli` 拉起 OpenCode 后台服务。
- 真正被 shell 执行的是 `python .opencode/skills/docgen/scripts/build.py` 与 LibreOffice，
  只发生在**这台服务器/容器**里。
- 所以：**只要部署这套服务的那台服务器具备依赖即可，用户电脑不需要装 Python / LibreOffice。**

> 启动时连接器会打印一行「文件生成能力（本机/服务器）」，用来自检服务器依赖是否齐全。

## 安装服务器依赖

任选其一：

```bash
# Linux 服务器 / 容器
sudo bash connect_to_feishu/deploy/setup-linux.sh
```

```powershell
# Windows 服务器（管理员 PowerShell）
powershell -ExecutionPolicy Bypass -File connect_to_feishu\deploy\setup-windows.ps1
```

```bash
# 用容器
docker build -f connect_to_feishu/deploy/Dockerfile -t plm-feishu .
docker run --rm -v "$PWD/data:/app/data" --env-file connect_to_feishu/.env plm-feishu
```

依赖清单：

| 组件 | 用途 | 缺失时的降级 |
| --- | --- | --- |
| Python + `python-pptx` `python-docx` `openpyxl` `Pillow` | 生成 PPT/Word/Excel | 无法生成文件 |
| LibreOffice (`soffice`) | 导出 PDF、预览渲染 | PPT/Word/Excel 仍可生成；PDF 不可用 |
| `poppler-utils` / poppler bin | `pdf2image` 把 PDF 转 PNG（预览） | 预览不可用，不影响生成 |
| 中文字体（如 `fonts-noto-cjk`） | PDF 中文正常显示 | PDF 中文可能缺字 |

## 关键环境变量

配置见 `connect_to_feishu/.env.example`。部署时最少需要：

- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`：飞书应用。
- `OPENCODE_BASE_URL`（可选）：直连已有 OpenCode 服务；留空则由连接器本机拉起。
- `SOFFICE_PATH`（可选）：LibreOffice 路径，留空自动探测。
- `USER_DATA_DIR`（可选）：用户数据目录，默认 `<repo>/data/user`（**务必挂卷持久化**）。

## 用户产出物

- 生成的文件落在 `data/user/<open_id>/output/`（按用户隔离）。
- 由 `plm-docs` 子 agent 输出 `[[send-file: <绝对路径>]]`，连接器负责上传回飞书。
- 连接器仅回发白名单目录（默认仓库根、`data/user`、临时目录）内的文件。
