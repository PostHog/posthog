# Signals Skills

Two distinct skill families live in this directory:

1. **Official PostHog skills** — `signals/`, `inbox-exploration/`. First-party PostHog
   skills published via `products/posthog_ai/dist/skills/` and loaded by users through
   the PostHog MCP. They teach a caller how to query, browse, and reason about signals
   data. They are not part of the automated agent path — humans (and human-driven
   agents) reach for them on demand.
2. **Scout fleet** — `signals-scout-*/`. Canonical default skills that the headless
   Signals agent loads into its system prompt at runtime. These are also the first
   example of PostHog shipping templated skills _into a user's PostHog Skills Store_:
   `lazy_seed` mirrors them onto each agent-enabled team's `LLMSkill` rows on the first
   coordinator tick, where users can then edit or override them per-team. They are not
   designed to be invoked by humans directly; the prompt and tool affordances assume
   they are running inside the harness.

## Scout fleet convention (`signals-scout-*`)

The harness discovers scouts by globbing `signals-scout-*` over the team's `LLMSkill`
table. The canonical content on disk in this directory is mirrored to each
agent-enabled team's `LLMSkill` rows by `scout_harness/lazy_seed.py` — see
`../backend/scout_harness/AGENTS.md` for the sync mechanics, and the
`sync_signals_scout_skills` management command for the manual fan-out path.

### Generalist + specialists

- `signals-scout-general/` — cross-product generalist. Looks for cross-product
  correlations and surfaces no specialist covers, rather than deep-diving a single
  product. Carries two progressively-disclosed references: `references/emit.md` (the
  emit contract) and `references/conventions.md` (scratchpad key prefixes + the
  four-states dedupe classifier + cross-project noise patterns). This is the entry
  point if you want to understand how a scout decides what to investigate end-to-end.
- `signals-scout-llm-analytics/` — anomaly watcher for LLM analytics
  (cost / latency / error / token-share regressions).
- `signals-scout-logs/` — anomaly watcher for logs (rate / level / pattern shifts).
- `signals-scout-error-tracking/` — anomaly watcher for error tracking
  (issue spikes, regressions, suppression-rule churn).
- `signals-scout-revenue-analytics/` — anomaly watcher for revenue
  (MRR / churn / segment shifts).
- `signals-scout-surveys/` — anomaly watcher for surveys
  (response-rate drops, sentiment shifts, completion-funnel regressions).
- `signals-scout-observability-gaps/` — the odd one out. Watches for _structural
  gaps_ between events being captured and existing insight / dashboard / alert
  coverage, and emits P3 _recommendations_ rather than P0–P2 _anomalies_.
- `signals-scout-csp-violations/` — anomaly watcher for Content Security Policy
  violations (`$csp_violation` blocked-URL clusters, per-directive bursts,
  post-deploy page-scoped regressions, suspicious third-party domains).

### How the coordinator decides what runs

There is no sampling. Each scout has its own `SignalScoutConfig` row (one per
`(team, skill_name)`) carrying a `run_interval_minutes` schedule (default 1440 =
daily) and a `last_run_at` stamp. Every tick the coordinator:

1. Bounds candidates to the teams enrolled via the `signals-scout` feature flag's
   JSON payload allowlist (`guaranteed_team_ids` minus `skip_team_ids`,
   `_participating_teams` → `_enrolled_team_ids`). Editing the payload in the flag UI
   enrolls or drains a team next tick — no manual seed.
2. Auto-registers a config for any `signals-scout-*` skill missing one
   (`_register_missing_configs`) — on an enrolled team, authoring a skill is enough
   to get a scout.
3. Dispatches every enabled scout whose schedule is due (`last_run_at is None`, or
   `now - last_run_at >= run_interval_minutes`), most-overdue first, capped at
   `MAX_RUNS_PER_TICK` per tick. Each due scout becomes one `RunSignalsScoutWorkflow`
   child run; `last_run_at` is advanced for everything dispatched.

Pausing a scout is `enabled=False` on its config; slowing it is a larger
`run_interval_minutes`. Both are tunable via the `signals-scout-config-update` MCP
tool. See `scout_coordinator._collect_planned_runs` for the exact due-check.

### Authoring a new scout

Creating a new `signals-scout-foo/SKILL.md` directory and merging it is enough.
The next coordinator tick (or an explicit `sync_signals_scout_skills --all-enabled` run)
will:

- discover it via `lazy_seed.discover_canonical_skills()`,
- create matching `LLMSkill` rows on each agent-enabled team,
- auto-register an enabled, daily-schedule `SignalScoutConfig` for it so the next
  due tick dispatches it.

No coordinator-side code change is needed. Use `signals-scout-general` as the
template if your scout is broad; pick a specialist as the template if it is
domain-tight.

### What lives inside a scout SKILL.md

Each scout's body is an instruction set the harness loads verbatim into the system
prompt. References (siblings of `SKILL.md`) are progressively disclosed via
`Skill.read_file()` from inside the run. Keep the body lean — every line is a
recurring token cost on every run — and push detail into references that are only
read when needed.

The generalist (`signals-scout-general`) carries two references the rest of the
fleet also reasons in terms of:

- **`references/emit.md`** — the emit contract: required/recommended fields, the
  weight vs. confidence rubrics, severity mapping, dedupe keys, `finding_id`
  idempotency, and a worked example.
- **`references/conventions.md`** — the four-states dedupe classifier, scratchpad
  key-prefix vocabulary, and cross-project noise patterns.

The 7 specialists are each currently a single self-contained `SKILL.md` carrying
their own domain discriminator + investigation patterns. A simplification pass to
compress them and share the generalist's references is planned; until then, treat
the generalist as the reference shape.

## When editing skills in this directory

- **Official skills (`signals/`, `inbox-exploration/`).** Disk in this directory is
  the source of truth. Changes get published to `products/posthog_ai/dist/skills/`
  for distribution as part of the official PostHog skill set; they are not
  auto-synced onto teams' `LLMSkill` rows.
- **Scout skills (`signals-scout-*/`).** Disk in this directory is the source of
  truth, and `lazy_seed` mirrors changes onto each agent-enabled team's `LLMSkill`
  rows on the next coordinator tick (or immediately via
  `python manage.py sync_signals_scout_skills --all-enabled`). Teams that have
  manually edited a row are treated as "diverged" and left alone — the sync logs
  them so you can decide whether to nudge those teams to reset.
- **If you change the scout fleet shape (add a new specialist, rename, or change
  the SKILL.md schema), update this file.**

## Reference

- Harness layout and run lifecycle — `../backend/scout_harness/AGENTS.md`
- Coordinator + per-scout due-check rules — `../backend/temporal/agentic/scout_coordinator.py`
- Canonical sync mechanics + manual command —
  `../backend/management/AGENTS.md` (Canonical skill sync section)
