# Product_Agent

Reusable agent skills, packaged for [OpenCode](https://opencode.ai).

## Skills

| Skill | Package | Description |
| ----- | ------- | ----------- |
| `marketing-offer-calendar` | [`marketing-offer-calendar.skills`](./marketing-offer-calendar.skills) | Sync marketing offers (Launch Notices) from a Feishu wiki space into a Feishu calendar and report upcoming expiries. |

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
