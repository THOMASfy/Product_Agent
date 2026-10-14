---
name: 文件生成 (Document Generation)
description: 依据用户需求/素材生成可交付的办公文件 —— PPT(.pptx)、Word(.docx)、Excel(.xlsx)、PDF(.pdf)，支持套用用户上传模板的版式与配色。涉及"做 PPT/演示文稿/汇报材料"、"生成 Word/文档/报告"、"做表格/Excel"、"导出 PDF"时使用。
---

# 文件生成 Skill

## 用途
把用户的需求（或由其他子智能体产出的结构化内容）转成**可交付的办公文件**：
PPT、Word、Excel、PDF。生成后由连接器回发到飞书。

## 何时必须使用
- 做 PPT / 演示文稿 / 幻灯片 / 汇报材料 / 套用模板 / 复刻版式
- 生成 Word / 文档 / 报告 / 方案 / 说明书
- 做表格 / Excel / 数据表 / 台账
- 导出 / 生成 PDF

## 执行方式（唯一，务必遵守）
生成/预览**只能**通过 Node 启动器调用（它内部自行定位 Python）：

```bat
node .opencode/skills/docgen/scripts/run.mjs build <spec.json>
node .opencode/skills/docgen/scripts/run.mjs render <file> <out_dir> [--png]
```

> ⚠️ 不要直接调用 `python` / `pip` / `build.py`：
> 本机可能存在 Windows 商店的“假 python”（空壳占位程序），且这类命令不在白名单内。
> 真的需要指定解释器时，用环境变量 `PYTHON_PATH`（启动器会优先使用）。
> 若 `run.mjs` 报错，把错误原样上报即可，**不要**换别的命令重试。
>
> ⚠️ shell 是**白名单**，只放行含 `run.mjs` 的命令。查看/浏览文件请用 `read`、`glob`
> 工具；**不要**用 shell 执行 `ls` / `dir` / `cat` / `echo` / `Copy-Item` / `python` 等
> ——它们会被拒绝并白白消耗步数。
>
> `render`（预览）是**可选**步骤：默认不做，仅在用户明确要求"看效果/预览"时才执行。

## 输入
1. **模板**（可选，主要用于 PPT/DOCX）：连接器会把用户上传文件的解析结果注入上下文
   （画布尺寸、主题配色、字体、媒体、逐页文本）。若上下文给出**原始文件路径**
   （形如 `data/user/<open_id>/attachments/xxx.pptx`），就填到规格的 `template` 字段，
   以便复用其母版/版式/配色。
2. **内容**：用户的文字需求，或由其他 plm-* 子智能体产出的结构化结论。

## 工作流
1. **确认**：先给出简短大纲/表结构/章节结构让用户确认；用户已给明确内容并要求直接生成时跳过。
2. **定型**：从模板解析结果取主色（如 `#0070C0`）、辅色与字体（如 `微软雅黑`），
   填入 `style`。中文字体优先 `微软雅黑`。
3. **写规格**：把结构写成 JSON 规格文件，存到
   `data/user/<open_id>/output/spec.json`（`<open_id>` 用当前用户，拿不到用 `local`）。
4. **生成**（相对仓库根执行）：
   ```bat
   node .opencode/skills/docgen/scripts/run.mjs build data/user/<open_id>/output/spec.json
   ```
   脚本会打印 `SAVED <绝对路径>`。
5. **（可选）自检**：需要看效果时渲染预览：
   ```bat
   node .opencode/skills/docgen/scripts/run.mjs render data/user/<open_id>/output/<文件> data/user/<open_id>/output/preview --png
   ```
6. **回发**：在最终回复里**单独一行**输出标记，连接器会自动把文件发到飞书：
   ```
   [[send-file: <绝对路径>]]
   ```

## 规格 JSON

### 公共字段
```json
{
  "type": "pptx | docx | xlsx | pdf",
  "output": "data/user/<open_id>/output/文件.pptx",
  "template": "data/user/<open_id>/attachments/模板.pptx",
  "style": {
    "primary": "0070C0", "secondary": "0445FE", "accent": "0FA4FE",
    "text": "333333",
    "title_font": "微软雅黑", "body_font": "微软雅黑",
    "title_size": 32, "body_size": 18
  }
}
```
- `template` 可选；仅 PPTX 会真正复用其母版/版式（DOCX 目前按 style 新建）。
- `style` 可省略，缺省即为上面的中国移动常用配色/字体。

### PPTX（`type: "pptx"`）
```json
{
  "type": "pptx",
  "output": "data/user/<open_id>/output/汇报.pptx",
  "slides": [
    { "layout": "title",   "title": "标题", "subtitle": "副标题 | 日期" },
    { "layout": "section", "title": "01 章节标题" },
    { "layout": "content", "title": "页标题", "bullets": ["要点1", "要点2"], "notes": "备注" }
  ]
}
```
`layout` 取值：`title`（封面）/ `section`（章节页）/ `content`（内容页）/ `blank`（自由页）。

### DOCX（`type: "docx"`）与 PDF（`type: "pdf"`）
两者结构相同（PDF 先建 DOCX 再转 PDF）。
```json
{
  "type": "docx",
  "output": "data/user/<open_id>/output/方案.docx",
  "title": "文档标题",
  "subtitle": "副标题/日期",
  "sections": [
    { "heading": "一、背景", "level": 1,
      "paragraphs": ["正文段落……"],
      "bullets": ["要点一", "要点二"] }
  ]
}
```
便捷写法：顶层也可直接用 `paragraphs: [...]` 与 `bullets: [...]`。

### XLSX（`type: "xlsx"`）
```json
{
  "type": "xlsx",
  "output": "data/user/<open_id>/output/台账.xlsx",
  "sheets": [
    { "name": "需求清单", "header": true,
      "rows": [ ["编号", "名称", "负责人"], ["1", "示例", "张三"] ] }
  ]
}
```
`header: true` 时首行加粗填色并冻结。顶层便捷写法：`rows: [...]`。

## 约束
- **只允许写 `data/user/<open_id>/output/` 目录**，不得改动仓库其他文件。
- 不编造数据、客户名、财务数字；缺失处标注 `【待确认】`。
- 模板里的示例文字按大纲替换，不原样保留。
- PPT 一页要点 ≤ 6 条、每条 ≤ 30 字；文档避免堆砌。
- 只说"已生成"，不要声称"已发送"；发送由连接器依据 `[[send-file: ...]]` 标记完成。
