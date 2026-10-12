# Product_Agent

Reusable agent skills and multi-agent setups, packaged for [OpenCode](https://opencode.ai).

## Skills

| Skill | Package | Description |
| ----- | ------- | ----------- |
| `marketing-offer-calendar` | [`marketing-offer-calendar.skills`](./marketing-offer-calendar.skills) | Sync marketing offers (Launch Notices) from a Feishu wiki space into a Feishu calendar and report upcoming expiries. |
| `artifact-template-productization-request-materials` | [`artifact-template-productization-request-materials.skills`](./artifact-template-productization-request-materials.skills) | Turn group cloud documents into a 产品化请示材料 document and deliver it as a Feishu cloud document, with a 待补充 questionnaire and in-place updates. |
| `business-plan` (商业计划书) | [`.opencode/skills/business-plan/`](./.opencode/skills/business-plan/SKILL.md) | Produce a formal Chinese business plan (BP / 融资计划书 / 项目计划书 / 市场分析报告) in a fixed five-chapter structure, exportable to Word/PDF. Scoped to the `plm-launch` agent. |

---

# PLM Multi-Agent Supervisor

A **supervisor** multi-agent structure for Product Lifecycle Management (PLM),
built on OpenCode and running on the `myapi/deepseek-v4-free` model.

## Architecture

One primary agent decomposes a request and delegates to specialized subagents.
It never does specialist work itself, which keeps each concern focused and the
synthesis honest.

```
                 ┌──────────────────────┐
   user ───────▶ │    plm-supervisor    │  primary agent
                 │  (route orchestrator)│
                 └──────────┬───────────┘
                            │ subagent tool
      ┌───────────┬─────────┼─────────┬───────────┬───────────┐
      ▼           ▼         ▼         ▼           ▼           ▼           ▼
 requirements  design   sourcing  manufacturing quality   launch   sustainment
      │           │         │         │           │           │           │
      └───────────┴─────────┴─────────┴───────────┴───────────┴───────────┘
                     structured findings back to supervisor
```

| Layer | Agent | Mode | Role |
| --- | --- | --- | --- |
| Supervisor | `plm-supervisor` | primary | Frames, routes, verifies, synthesizes |
| Specialist | `plm-requirements` | subagent | Voice of customer, PRD, requirements |
| Specialist | `plm-design` | subagent | Concept, specs, BOM, DFM/DFA |
| Specialist | `plm-sourcing` | subagent | Suppliers, make-vs-buy, cost, risk |
| Specialist | `plm-manufacturing` | subagent | Process, capacity, yield, ramp |
| Specialist | `plm-quality` | subagent | QA/QC, FMEA, compliance, release |
| Specialist | `plm-launch` | subagent | Readiness, pricing, channels, rollout — owns the `business-plan` skill |
| Specialist | `plm-sustainment` | subagent | Service, ECO, obsolescence, EOL |

## Files

```
opencode.jsonc                          # project config (default agent, model)
.opencode/agents/plm-supervisor.md      # primary orchestrator
.opencode/agents/plm-requirements.md    # specialists (subagents)
.opencode/agents/plm-design.md
.opencode/agents/plm-sourcing.md
.opencode/agents/plm-manufacturing.md
.opencode/agents/plm-quality.md
.opencode/agents/plm-launch.md
.opencode/agents/plm-sustainment.md
.opencode/commands/plm.md               # /plm entry point
.opencode/skills/business-plan/SKILL.md # business-plan skill (plm-launch only)
```

## Usage

Open OpenCode in this directory. `plm-supervisor` is the default agent, so a
normal prompt is already routed through the supervisor. Or use the command:

```text
/plm design and cost a rugged outdoor power bank for the EU market
```

The supervisor will:

1. **Frame** the request and pick the relevant stages.
2. **Delegate** to the `plm-*` specialists in parallel where independent.
3. **Verify** returns for conflicts (e.g. sourcing cost vs. launch price).
4. **Synthesize** one integrated recommendation with risks and next steps.

You can also drive a single stage directly, e.g.:

```text
Use the plm-quality subagent to list compliance requirements for a battery product in the EU.
```

## How routing and isolation work

- The supervisor may only launch agents matching `plm-*`
  (`subagent` permission rules in `opencode.jsonc` and the agent frontmatter).
- Specialists **cannot** launch further subagents, preventing recursion.
- Specialists are **read-only** (edit and shell denied) so analysis is safe.
  The supervisor alone may write final deliverables.
- Each specialist runs in a fresh child session with its own system prompt, so
  context stays clean and focused.

## Scoped skills

The `business-plan` skill (商业计划书) is **only** available to the `plm-launch`
subagent:

- `opencode.jsonc` globally denies the `skill` action for `business-plan`, so no
  other agent sees it.
- `plm-launch.md` re-allows `business-plan`, and its prompt tells it to load the
  skill for BP/funding/project-plan requests.

Last matching permission rule wins, and global rules apply before agent rules —
that is why the global deny plus the agent allow scopes the skill to one agent.
To expose it to another agent, add the same allow rule there; to expose it
everywhere, delete the global deny rule.

## Extending

- **Add a stage:** create `.opencode/agents/plm-<name>.md` with `mode: subagent`
  and add it to the routing table in `plm-supervisor.md`. It is auto-allowed by
  the `plm-*` rule.
- **Allow specialists to write:** remove the `edit` deny rule from a specialist.
- **Tune effort:** change the model variant (`#low`, `#medium`, `#high`) or
  `steps` in any agent's frontmatter.
- **Change the model:** update `model` in `opencode.jsonc` and the agent files.

---

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
