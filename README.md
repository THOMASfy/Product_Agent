# Product_Agent

Reusable agent skills, packaged for [OpenCode](https://opencode.ai).

## Skills

| Skill | Package | Description |
| ----- | ------- | ----------- |
| `marketing-offer-calendar` | [`marketing-offer-calendar.skills`](./marketing-offer-calendar.skills) | Sync marketing offers (Launch Notices) from a Feishu wiki space into a Feishu calendar and report upcoming expiries. |
| `artifact-template-productization-request-materials` | [`artifact-template-productization-request-materials.skills`](./artifact-template-productization-request-materials.skills) | Turn group cloud documents into a 产品化请示材料 document and deliver it as a Feishu cloud document, with a 待补充 questionnaire and in-place updates. |

## Install a `.skills` package

A `.skills` file is a ZIP archive of one skill directory. Extract it into a
skills directory so OpenCode can discover it:

- Project scope: `.opencode/skills/`
- Global scope: `~/.config/opencode/skills/`

```sh
# example: install into the current project
unzip marketing-offer-calendar.skills -d .opencode/skills/
```

Then restart OpenCode. Each skill is advertised to the model by its
`description`.

## marketing-offer-calendar

```
marketing-offer-calendar/
├── SKILL.md
├── references/
│   └── calendar-config.md
└── scripts/
    └── sync-offers.mjs
```

- Scope is always user-specified — it never defaults to scraping everything.
- Feishu: send `同步offer`, then reply with the product / keyword to scrape
  (or `全部` / `取消`).
- CLI: `node scripts/sync-offers.mjs sync --product "安全管家"`, `list`, `share`.
- A keyword with zero wiki matches returns immediately and does not change the
  calendar.

### Dependency

`scripts/sync-offers.mjs` is a thin CLI wrapper over
`feishu-bot/offer-calendar.mjs`. It locates that module automatically (via the
`OFFER_BOT_DIR` environment variable or a nearby `feishu-bot/` directory).
Extract the package next to the project's `feishu-bot/` folder, or set
`OFFER_BOT_DIR`.

### Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | success |
| 1 | extraction produced no JSON |
| 2 | no scope given and the configured scope is empty (refuses) |
| 3 | keyword matched 0 wiki documents (nothing changed) |

## artifact-template-productization-request-materials

```
artifact-template-productization-request-materials/
├── SKILL.md
├── artifact-template.json
├── agents/
│   └── openai.yaml
├── assets/
│   ├── preview.png
│   └── reference.docx
├── references/
│   └── end-to-end-flow.md
└── scripts/
    ├── clone_reference.py
    ├── dump_structure.py
    ├── export_pdf.ps1
    └── normalize_fonts.py
```

Generate a Chinese productization approval request (产品化请示材料) from source
documents. The end-to-end flow is orchestrated by an external Feishu bot; the
bot code is **not** part of this package:

```
@机器人 → 判断是否请示类任务 → 发选文档卡片 → 用户选群内云文档
      → 读取 → 分析整合 → 生成文档 → 建飞书云文档 → 链接回群
```

- **Deliverable:** a Feishu cloud document. No local DOCX/PDF by default — the
  DOCX is only the conversion source, and a PDF is exported only if explicitly
  requested.
- **Format (fixed):** 标题 仿宋 16pt；一级标题 仿宋 12pt；正文 / 列表 / 表格
  微软雅黑 10pt.
- **Template:** `assets/reference.docx` is cloned and never edited in place;
  `scripts/normalize_fonts.py` forces the font/size roles after filling.
- **Missing data:** every gap is marked `[待补充：具体问题]` and collected into
  one questionnaire; submitting the answers updates the **same** cloud document
  in place (link unchanged).
- **Sessions:** a new material starts a fresh session; a questionnaire supplement
  reuses that document's session.

### Install

```sh
unzip artifact-template-productization-request-materials.skills -d .opencode/skills/
```

Requires Python 3 with `python-docx`. Microsoft Word (COM) or LibreOffice is
optional, only for explicit PDF export.
