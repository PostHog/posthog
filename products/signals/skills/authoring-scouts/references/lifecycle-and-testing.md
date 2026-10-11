# Lifecycle, distribution, and testing

How scouts get discovered, scheduled, and dispatched; the two distribution paths and their exact mechanics; and how to test a scout in each.

## How a scout runs

- **Discovery.** A scout is a skill that holds a `SignalScoutConfig`, and the coordinator dispatches from those config rows.
  The `signals-scout-` name prefix is optional; it controls only auto-registration, below.
- **Config.** Each scout has one `SignalScoutConfig` per `(project, skill_name)` carrying its schedule (`run_interval_minutes`, default 1440, or a project-local `run_cron_schedule` that takes precedence when set), `enabled`, `emit`, `network_access` (`trusted` default, `full` for scouts that read arbitrary external sites), the rest of the run posture (`output_destinations`, `structured_output_schema`, `write_scopes`, `mcp_gateway_server_ids`, `model`, `tags`, `auto_pause_exempt`, `display_name`), and a `last_run_at` stamp.
  A config is **auto-registered** the first time the coordinator sees a `signals-scout-*` skill without one, so authoring a prefixed skill is enough to get a scout.
  A skill named anything else needs its config created with it.
  Create a fresh per-team scout and its config together with `posthog:scout-create`; the nested `config` object sets its schedule, emit posture, and destinations before it can run, and `files` bundles reference files in the same call.
  The lower-level `posthog:scout-config-create` remains available when a skill already exists without a config.
  Config responses also carry the scout's `description`, read live from the skill's frontmatter (not a config field you set), plus `scout_origin` (`canonical` or `custom`) and `owners`.
- **Coordinator.** A periodic Temporal workflow ticks (~every 30 min).
  Each tick it bounds candidates to projects enrolled via the `signals-scout` feature-flag allowlist, then dispatches every **enabled** scout whose schedule is **due**, most-overdue first, capped per tick.
  On a rolling interval, due means `last_run_at is None` (a never-dispatched scout is maximally overdue; manual runs do not set the stamp) or `now - last_run_at ≥ run_interval_minutes`.
  On a cron schedule, due means the first slot after the latest of `last_run_at`, the last schedule edit, and the config's creation has passed, so a fresh or re-scheduled cron scout waits for its next slot instead of firing at once.
  There is no sampling — every due scout runs.
  `last_run_at` advances for everything dispatched.
- **Run.** Each dispatched scout becomes one sandboxed agent run with a hard budget of 15 minutes; a run still going at the wall is killed and its row marked failed.
  The body is the system prompt; the agent orients, explores, files reports or remembers, and writes a one-paragraph summary to the run row.
  A streak of consecutive **scheduled** failures longer than a twelve-hour outage could explain trips a breaker that pauses the scout (`pause_reason=repeated_failures`): the threshold is one more than the runs the schedule fits in twelve hours, clamped to 5–25 (five for a daily scout, thirteen for a rolling hourly interval, fifteen for an hourly cron, whose slots are counted over a window padded for daylight-saving shifts). Manual (`scout-run-now`) and workflow-triggered failures never count toward the streak, while a clean run from any trigger clears it. The coordinator then probes a paused scout once a day and resumes it on a clean run, unless the project is at its enabled-scout cap, in which case it stays paused until another scout is paused or deleted; enabling it by hand is refused at the cap too.

Pausing a scout = `enabled=false`.
That records `status=paused_by_user`, which automatic lifecycle sweeps never resume or re-pause; `enabled=true` resumes from any pause, including a system-applied one (`status=paused_by_system`, cause in the read-only `pause_reason`).
Config responses expose `status` and `pause_reason` read-only; writes flow through `enabled`.
Slowing it = a larger `run_interval_minutes` (or, on a cron scout, a sparser `run_cron_schedule`; the cron wins while it is set).
Dry-running it = `emit=false`.
Letting it reach sites outside the trusted-domain allowlist = `network_access="full"`.
All of these via `posthog:scout-config-update` (get the `id` from `-config-list`), or set at creation time in the nested `config` object passed to `posthog:scout-create`.

## Path A — per-team (skills store)

The common path for a user customizing scouts for their own project.
A scout is just an `LLMSkill` row named `signals-scout-*`; create or edit it with the skills-store tools, and the harness globs it in on the next tick.

```text
# List existing scouts and other skills
posthog:skill-list {"search": "signals-scout"}

# Read a canonical scout to use as a template
posthog:skill-get {"skill_name": "signals-scout-error-tracking"}

# New idea to test: create the complete definition and config, paused.
posthog:scout-create {"name": "signals-scout-<scope>", "description": "...", "body": "...", "config": {"enabled": false, "run_interval_minutes": 120}}

# Adapt an existing per-team scout — use the SMALLEST primitive (find/replace, not full-body)
posthog:skill-get {"skill_name": "signals-scout-<scope>"}          # get current version first
posthog:skill-update {"skill_name": "signals-scout-<scope>", "base_version": N, "edits": [{"old": "...", "new": "..."}]}

# Duplicate a canonical scout into a new per-team scout you then edit (keeps the canonical intact)
posthog:skill-duplicate {"skill_name": "signals-scout-general", "new_name": "signals-scout-<scope>"}

# Bundle a reference file onto a per-team scout
posthog:skill-file-create {"skill_name": "signals-scout-<scope>", "path": "references/cookbook.md", "content": "...", "content_type": "text/markdown", "base_version": N}
```

Notes:

- Prefer `edits` (find/replace) over a full `body` rewrite for tweaks — a full rewrite forces you to reproduce the whole body and risks silently dropping unrelated content.
  Each `old` must match exactly once.
  Every write bumps an immutable `version`; chain further edits via `base_version`.
- **Divergence:** once you edit a canonical scout's row for your team, canonical sync treats it as **diverged** and stops force-updating it — you keep your edits but lose upstream improvements to that scout.
  To customize _without_ diverging, `duplicate` the canonical scout into a new `signals-scout-<your-scope>` row and edit that; leave the original alone.
- Writing reports needs the `signal_scout_report:write` scope, and the scratchpad needs `signal_scout_internal:write` (the sandbox has both).
  Authoring a scout doesn't require either — only the harness writes.

## Path B — canonical (in-repo, for PostHog contributors)

Improving a scout for **every** enrolled project.
Disk under `products/signals/skills/signals-scout-*/` is the source of truth; `lazy_seed` mirrors changes onto each enrolled team's `LLMSkill` rows on the next coordinator tick (or immediately via `python manage.py sync_signals_scout_skills --all-enabled`).
Teams that hand-edited a row are diverged and left alone.

```sh
hogli init:skill            # scaffold a new skill directory
hogli lint:skills           # validate frontmatter / syntax / binaries — fast, no Django
hogli build:skills          # render + package into dist/skills.zip
hogli sync:skill -- --name signals-scout-<scope>   # build + sync to .agents/skills/ for local agent testing
hogli unsync:skill -- --name signals-scout-<scope>
```

Authoring a new canonical scout is just creating `signals-scout-<scope>/SKILL.md` and merging — the next tick discovers it, seeds it onto enrolled teams, and auto-registers an enabled config on the default every-24-hours schedule.
**If you change the fleet shape (add/rename a scout, change the SKILL.md schema), update `products/signals/skills/AGENTS.md`.** On master, CI builds and publishes `dist/skills.zip` to the downstream distribution repos (the `ai-plugin` bundle and the standalone skills repo) automatically.

## Testing

**Dogfood the scout yourself first — before spending any real run.** The authoring agent has the same PostHog MCP tools a scout uses at runtime (`execute-sql`, `read-data-schema`, the per-product list tools, `scout-project-profile-get`), so the cheapest iteration is to walk the scout's own logic against the live project by hand: confirm the watched entity exists and has the assumed shape, run the **discriminator** to check it separates signal from noise on this project's data, and run each **explore pattern**'s queries.
Free and instant — refine the body, re-run the queries, repeat, until the logic holds on real data.

### Private trials with a saved rubric

Use `posthog:scout-trial-start` to run variants and automatically judge them against the same saved rubric.
Private trials and rubrics currently have a staff-only internal rollout; trial tools also require the `scout-trials` feature flag.
This keeps the source skill, shared memory, and live inbox reports unchanged, while still reading live project data.
Each run gets its own private report and memory changes from a shared starting context; live analytics queries can still return different data as time passes.
The tools and source scout must be eligible: `posthog:scout-trial-setup` returns `ready`, `blocked_reason`, the current `skill_body` / `skill_version`, and supported `models` with their `reasoning_efforts`.
Use those choices rather than guessing a model or effort.
If setup is blocked, resolve the stated cause or report it; do not silently replace the requested private trial with `scout-run-now`.

For an **existing scout**, find its config with `posthog:scout-config-list`, read the skill and relevant bundled files, then call setup with that config `id`.
For a **new idea**, use `posthog:scout-create` with the full body and files and `config.enabled=false`, then use the returned `config.id` for the same path.
Pausing prevents scheduled runs during development; it does not prevent private trials.
The scout can keep its intended emit setting because trial outputs stay private.

#### Generate, select, and save criteria

1. Read `posthog:scout-rubric-get {"id": "<config_id>", "fields": ["revision", "criteria", "reference_generation_id", "generation.id", "generation.status"]}`.
   Omit `fields` for the full document, including the adopted `reference_context` and latest `generation`.
   Revision `0` means the defaults have not been saved yet.
   Reuse a suitable saved rubric and source; generate when the user requests fresh suggestions or the rubric lacks a usable reference.
2. Call `posthog:scout-rubric-generate {"id": "<config_id>", "context": "<optional priorities>"}`.
   `context` is at most 2,000 characters and supplements the scout's full job; it is not a replacement prompt.
   Generation is paid and asynchronous. Poll `posthog:scout-rubric-get` with `fields: ["revision", "generation.id", "generation.status", "generation.error"]` until generation is `completed` or `failed`, rather than starting another generation while one is running.
3. Review `generation.suggestions`, `generation.summary`, and `generation.reference_context`.
   Request these with `fields`, together or separately; the reference's `instructions`, `report_disposition_instructions`, and `reference_texts` can also be selected separately.
   The reference contains the captured instructions, report-disposition rules, bundled reference texts, source version, and omission/truncation indicators.
   Check that it represents the intended job and that each selected criterion has an observable pass condition and sensible applicability.
   Required checks should still apply when a candidate skips the required work; otherwise skipping can make the comparison inconclusive instead of failing the check.
   Do not resolve contradictory source requirements by quietly choosing one, or turn optional work into a mandatory criterion.
   A missing or truncated saved reference cannot support a trial; address the source size/completeness issue and generate again.
4. Save with `posthog:scout-rubric-save`, passing `id`, the latest `revision`, the **complete** desired `criteria` array, and `adopt_generation_id: generation.id` to adopt that completed generation's reference for the whole rubric.
   Merge selected suggestions into the existing criteria by ID, preserve all six default IDs and their `source`, and disable a default with `enabled=false` instead of deleting it.
   Custom IDs must start with `custom-`; the full list has at most 30 criteria.
   Generation does not save suggestions or adopt their source automatically. Omitting `adopt_generation_id` preserves the already adopted source.
   On a stale-revision `409`, reread the rubric and reconcile with the latest edits before saving again.
5. Check the saved response's new revision, selected criteria, and adopted reference.
   Starting a trial freezes that saved rubric for all variants; later saves do not rewrite an existing trial's judgments.

Poor generated criteria can be corrected through the same `posthog:scout-rubric-save` call without generating again:

- **Enable or disable** any criterion with `enabled=true` or `false`; **edit** its `title`, `description`, `pass_condition`, or `applicability` while retaining its ID and source.
- **Add** a check with a unique `custom-` ID, `source="custom"`, the four text fields above, and an explicit `enabled` value.
- **Delete** a custom check, including a selected generated suggestion, by omitting it from the complete saved array. Suggestions that were never selected need not be added.
- Keep `default-evidence`, `default-clarity`, `default-actionability`, `default-priority`, `default-instructions`, and `default-memory` with `source="default"`; disable unwanted defaults instead of removing them.

Read the latest `revision` first and send every criterion you intend to retain, up to 30 in total; this replaces the saved set rather than patching one check.
Omit `adopt_generation_id` when only editing criteria so the adopted reference stays fixed. Regenerate and adopt a new reference only when that source needs refreshing.

#### Compare prompts, models, or efforts

Choose a baseline and label each candidate by the change it tests.
For 5–10 prompts, use one comparison with the requested number of variants, including a baseline; each variant needs an `id`, `label`, explicit supported `model` and `reasoning_effort`, and one or more `launch_ids`.
Omit the baseline's `skill_body` to use the saved instructions, and send each candidate's complete replacement body in `skill_body`.
This overrides only the trial body; it does not edit the saved skill or its bundled files.
Keep model and effort fixed for a prompt comparison, or keep the body fixed to compare runtimes.

`posthog:scout-trial-start` takes the config `id`, a fresh `comparison_id`, `baseline_variant_id`, the `variants` array, and preferably `expected_skill_version` from setup.
An optional `note` applies to every run in the comparison.
Use unique UUIDs for each comparison, variant, and launch; retain the exact request so a transport retry can reuse those IDs without launching duplicate work.
Changing a prompt, rubric, runtime, or variant selection calls for a new comparison.
The API supports up to 20 variants and 20 runs per variant; these are limits, not a suggested spend.
Start with the requested count and enough repeats to answer the question, using the same repeat count for every variant; unequal counts make the comparison inconclusive.
Generation, scout execution, and judging all spend usage, so account for all three within the user's budget.

#### Read, resume, and apply

Poll `posthog:scout-trial-report {"id": "<config_id>", "comparison_id": "<comparison_id>", "fields": ["status", "error", "evaluation.status", "evaluation.error"]}` through startup, scout execution, and judging.
Once complete, the saved comparison is available under `evaluation.report`.
Read `evaluation.report.summary`, `evaluation.report.outcome`, `evaluation.report.variants`, and `evaluation.report.limitations` first via `fields`, then fetch `evaluation.report.runs` for verdicts and `evaluation.report.evidence` for their sources.
Review criterion verdicts and cited evidence, rubric coverage, run failures, and costs alongside the winner/tie/provisional/inconclusive summary.
`unknown` means the criterion could not be assessed; `not_applicable` means it did not apply.
Both are excluded from pass rates, while `unknown` reduces rubric coverage; neither is a pass.
An execution failure is distinct from a valid run that failed quality criteria, and missing cost is unknown rather than zero.
Small comparisons are descriptive, so report what the observed runs support and what remains uncertain.

Both read tools return the full response when `fields` is omitted; selection reduces output but does not guarantee a size limit.
If the host clips even one selected reference or report section, capture the full JSON through an already configured PostHog CLI (`posthog-cli api call --json <tool> '<input>' > result.json`) or programmatic MCP client and inspect the saved file.
Host clipping does not mean the stored source is truncated, and does not require another paid generation.

Use `posthog:scout-trial-list` to rediscover saved comparisons, following its cursor for more results.
Use `posthog:scout-trial-resume` with the same `comparison_id` when the saved error permits resuming; a stale judge version requires a new comparison.
`posthog:scout-trial-archive` with `archived=true` hides a finished comparison from default history; `archived=false` restores it without rerunning anything.
The lower-level `posthog:scout-trial-create` / `posthog:scout-trial-get` tools expose a single private run without automatic rubric judging, so prefer `scout-trial-start` / `scout-trial-report` for scored comparisons.

When the user asked to apply a successful candidate, reread the saved skill and use `posthog:skill-update` with its current `base_version` to apply the intended change.
Use `posthog:scout-config-update` for the desired model, schedule, and `enabled` state, including enabling the scout when that is part of the requested work.
Testing alone does not apply a winner or change the scout's schedule.

### Ordinary runs

`posthog:scout-run-now {"id": "<config_id>"}` dispatches one execution of the saved scout immediately, including while paused, without changing its schedule or `last_run_at`.
An optional `note` steers that run alone and needs `llm_skill:write` plus skill-editor access.
This is an ordinary run: it writes shared scratchpad memory and, with `emit=true`, live inbox reports and configured deliveries.
Poll `posthog:scout-runs-list` / `posthog:scout-runs-retrieve`, then inspect `posthog:inbox-reports-list` and `posthog:scout-scratchpad-search`.
It obeys the scheduled path's access, quota, concurrency, and daily run-budget guards; `emit=false` still spends a run.
Use it for an intended ordinary execution rather than a loop of prompt comparisons.

To inspect an ordinary run without publishing inbox reports, set `emit=false` through `posthog:scout-config-update` and use `posthog:scout-run-now`.
Inspect the logs and restore the intended emit setting when applying the final run posture.

Repo contributors additionally get `hogli sync:skill` to run the scout against the local harness for a tighter loop before merging.
