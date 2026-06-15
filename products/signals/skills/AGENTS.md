# Signals Skills

Two distinct skill families live in this directory:

1. **Official PostHog skills** — `signals/`, `inbox-exploration/`,
   `authoring-signals-scouts/`, `exploring-signals-scouts/`. First-party PostHog skills
   published via `products/posthog_ai/dist/skills/` and loaded by users through the PostHog
   MCP. They teach a caller how to query, browse, and reason about signals data. Two are
   meta skills about the scout fleet itself: `authoring-signals-scouts/` teaches a user's
   agent how to write, edit, and adapt scouts (per-team via the skills store, or canonically
   in this directory), and `exploring-signals-scouts/` is its read-only counterpart —
   teaching a caller how to observe and make sense of what a project's scouts are doing and
   how they're performing (the `signals-scout-config-list` / `-runs-list` / `-runs-retrieve`
   / `-scratchpad-search` / `-project-profile-get` tools, run anatomy, and health
   assessment). They are not part of the automated agent path — humans (and human-driven
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
- `signals-scout-ai-observability/` — anomaly watcher for AI observability
  (cost / latency / error / token-share regressions).
- `signals-scout-logs/` — anomaly watcher for logs (rate / level / pattern shifts).
- `signals-scout-error-tracking/` — anomaly watcher for error tracking
  (issue spikes, regressions, suppression-rule churn).
- `signals-scout-feature-flags/` — state-vs-traffic watcher for feature flags. Audits
  the wiring between the flag UI and the code: evaluation cliffs on healthy flags,
  ghost flags (code calling deleted keys), response-distribution shifts with no
  matching flag edit, plus a bundled flag-debt hygiene pass (stale / dead-check
  flags). Its discriminator is the flag's configured state against the
  `$feature_flag_called` stream; experiment-linked flags are the experiments
  scout's territory.
- `signals-scout-data-pipelines/` — delivery watcher for data pipelines: CDP
  destinations and transformations (hog functions), batch exports, and hog flows.
  Watches for platform interventions (the hog watcher degrading or auto-disabling
  an enabled function), delivery failure shares stepping above a pipeline's own
  baseline, batch export runs failing or stalling (a growing data gap), filter
  starvation, and active flows failing for the people they trigger on. Its
  discriminator is configured-to-deliver vs actually-delivering — drafts, paused
  exports, and deliberately disabled functions are operator choices, not signal;
  data warehouse / external-data syncs are the health-checks scout's territory.
- `signals-scout-revenue-analytics/` — anomaly watcher for revenue
  (MRR / churn / segment shifts).
- `signals-scout-session-replay/` — capture-integrity + friction watcher for session
  replay. Watches recording volume against site traffic for capture cliffs (SDK
  breakage, config drift — recordings are not retroactive), and the friction stream
  (`$rageclick`, dead clicks, errors-after-click via `session_replay_features`) for
  clusters concentrating on one URL or element above that surface's own baseline.
  Also the judgment layer over replay vision: scanner watch-gaps (failing scanners,
  exhausted quota) and cross-session aggregation of `$recording_observed` scanner
  output. Its discriminator is concentration-vs-diffusion — friction that piles up
  in one place is signal, friction that tracks traffic is baseline; exceptions per
  se are the error-tracking scout's territory.
- `signals-scout-replay-vision/` — agentic pull watcher over Replay Vision scanners
  (the standing LLM probes that write `$recording_observed` events). Replay Vision is
  the newer evolution of session replay, so this scout and `signals-scout-session-replay`
  intentionally coexist for now. Watches two promises: that enabled scanners are
  actually observing (throughput / success-rate cliffs, exhausted quota — a silent
  watch gap), and that what the scanners see in aggregate gets surfaced (a monitor's
  `yes`-rate or a scorer's mean stepping away from its own baseline, a classifier tag
  or recurring summarizer theme concentrating across many sessions). It is the
  complement to the per-session push path: scanners with `emits_signals: true` already
  emit one signal per session (source `replay_vision`, type `scanner_finding`) into the
  same inbox, so this scout never repeats them — it adds the cross-session shape the
  per-session probe can't see. Its discriminators are
  aggregate-shift-vs-per-session-baseline and
  configured-to-observe-vs-actually-observing; raw friction / capture is the
  session-replay scout's territory and exceptions are the error-tracking scout's.
- `signals-scout-surveys/` — anomaly watcher for surveys
  (response-rate drops, sentiment shifts, completion-funnel regressions).
- `signals-scout-web-analytics/` — acquisition + site-health watcher for web traffic.
  Reads the `sessions` table for per-channel volume diverging from
  seasonality-aligned baselines (same 24h window 7/14 days back), attribution
  breakage (paid traffic reclassifying into Direct/Unknown when UTM tagging breaks),
  entry-path bounce steps and traffic cliffs, 404 spikes (via the project's own
  not-found event, discovered by name), and per-path web vitals p75 regressions. Its
  discriminator is segment-vs-aggregate divergence — one channel/path/referrer
  stepping away from its own baseline while totals hold is signal; the whole site
  moving together is baseline. Whole-site metric anomalies on watched dashboards are
  the anomaly-detection scout's territory.
- `signals-scout-experiments/` — validity watcher for A/B experiments. Audits the
  measurement machinery rather than the results: sample ratio mismatch, `$multiple`
  contamination, exposure stalls, mid-run flag mutations, plus lifecycle drift
  (zombies, ended-but-contaminating flags). Its discriminator is config-vs-data
  contradiction — the configured split / status / flag state against what the
  exposure stream actually shows.
- `signals-scout-observability-gaps/` — the odd one out. Watches for _structural
  gaps_ between events being captured and existing insight / dashboard / alert
  coverage, and emits P3 _recommendations_ rather than P0–P2 _anomalies_.
- `signals-scout-csp-violations/` — anomaly watcher for Content Security Policy
  violations (`$csp_violation` blocked-URL clusters, per-directive bursts,
  post-deploy page-scoped regressions, suspicious third-party domains).
- `signals-scout-anomaly-detection/` — anomaly watcher for the dashboards and
  insights a team actually views. Discovers high-traffic insights (view counts +
  dashboard access), curates a durable scratchpad watchlist, and balances
  re-checking known items (exploit) against discovering new ones (explore) across
  runs; scores the latest complete bucket by robust (MAD) deviation from each
  insight's own seasonality-matched baseline. Bundles its own references
  (`anomaly-methods.md`, `watchlist-and-memory.md`, `emit-contract.md`).
- `signals-scout-health-checks/` — the judgment layer over PostHog's own health
  checks. Reads the project's active health issues (`health-issues-summary` /
  `-list` / `-get`) rather than re-running detection, and decides which are worth
  surfacing: bundles same-kind clusters into one finding, weights by real blast
  radius (cross-referenced against event volume / reach / SDK-version share), and
  prioritizes issues an agent can resolve via the MCP over credential-gated ones.
  Its discriminator is kind-concentration × severity × agent-fixability ×
  persistence, not raw firing count.
- `signals-scout-inbox-validation/` — follow-up watcher for the inbox itself.
  Watches reports that recently transitioned to `resolved` (implementation PR
  merged), waits out a deployment soak window, then re-probes the entities the
  report's underlying signals named (pre-fix baselines captured at enqueue time)
  to check the fix actually held — plus a strictly-gated escalation check on
  recently dismissed reports. Its discriminator is resolution-vs-reality — the
  resolved status's promise against the post-deploy data stream. Emits only
  failed validations; confirmations are scratchpad memory. It never detects new
  problems — that's the rest of the fleet's territory.

### How the coordinator decides what runs

There is no sampling. Each scout has its own `SignalScoutConfig` row (one per
`(team, skill_name)`) carrying a `run_interval_minutes` schedule (default 60 =
hourly) and a `last_run_at` stamp. Every tick the coordinator:

1. Bounds candidates to the teams enrolled via the `signals-scout` feature flag's
   JSON payload allowlist (`guaranteed_team_ids` minus `skip_team_ids`,
   `_participating_teams` → `_enrolled_team_ids`). Editing the payload in the flag UI
   enrolls or drains a team next tick — no manual seed.
2. Auto-registers a config for any `signals-scout-*` skill missing one
   (`scout_harness/config_registry.register_missing_configs`) — on an enrolled team,
   authoring a skill is enough to get a scout. To register (and tune) one immediately
   instead, use the `signals-scout-config-create` endpoint.
3. Dispatches every enabled scout whose schedule is due (`last_run_at is None`, or
   `now - last_run_at >= run_interval_minutes`), most-overdue first, capped at
   `MAX_RUNS_PER_TICK` per tick. Each due scout becomes one `RunSignalsScoutWorkflow`
   child run; `last_run_at` is advanced for everything dispatched.

Pausing a scout is `enabled=False` on its config; slowing it is a larger
`run_interval_minutes`. Both are tunable via the `signals-scout-config-update` MCP
tool, and settable at creation time via `signals-scout-config-create` (an upsert that
registers the config immediately instead of waiting for the tick). See
`scout_coordinator._collect_planned_runs` for the exact due-check.

### Authoring a new scout

Creating a new `signals-scout-foo/SKILL.md` directory and merging it is enough.
The next coordinator tick (or an explicit `sync_signals_scout_skills --all-enabled` run)
will:

- discover it via `lazy_seed.discover_canonical_skills()`,
- create matching `LLMSkill` rows on each agent-enabled team,
- auto-register an enabled, hourly-schedule `SignalScoutConfig` for it so the next
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
  confidence rubric, severity mapping, dedupe keys, `finding_id`
  idempotency, and a worked example.
- **`references/conventions.md`** — the four-states dedupe classifier, scratchpad
  key-prefix vocabulary, and cross-project noise patterns.

The specialists each carry their own domain discriminator + investigation patterns.
Most are a single self-contained `SKILL.md`; a few bundle surface-specific references
read on demand — `signals-scout-anomaly-detection` (`anomaly-methods.md`,
`watchlist-and-memory.md`, `emit-contract.md`), `signals-scout-ai-observability`
(`lenses.md`), and `signals-scout-surveys` (`response-querying.md`). Treat the
generalist as the reference shape. Note that a scout can only read its own bundled
files at runtime (each team's `LLMSkill` row carries just that skill's files), so a
specialist that needs the emit/dedupe conventions in depth bundles its own copy
rather than pointing at the generalist's.

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
