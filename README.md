# PLM Multi-Agent Supervisor (OpenCode)

A **supervisor** multi-agent structure for Product Lifecycle Management (PLM),
built on [OpenCode](https://opencode.ai/v2/docs/) and running on the
`myapi/deepseek-v4-free` model.

## Architecture

The supervisor pattern uses one primary agent that decomposes a request and
delegates to specialized subagents. It never does specialist work itself, which
keeps each concern focused and the synthesis honest.

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
| Specialist | `plm-launch` | subagent | Readiness, pricing, channels, rollout |
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

- `.opencode/skills/business-plan/SKILL.md` — the skill definition.
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
