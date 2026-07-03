# Plan mode for the cloud inbox ("Projects") — Plan

> Status: **Draft** · Owner: Oliver Browne · Last updated: 2026-07-01

## Summary

Add a "plan mode" to the cloud inbox: a new **Plan** tab where a user creates a **project**
(internally a `SignalReport` of a new kind), then holds a planning conversation with an LLM agent
running in a cloud sandbox (reusing the existing task UI). The agent plans the feature _with_ the
user, pulls the relevant repositories for context, and — via the PostHog MCP — writes the plan back
into the report (title, summary, detailed artefact notes with code references), sets the report as
user-driven (P1, actionability + safety passed) with the creating user as suggested reviewer, emits
an `inbox`/`plan` signal bound to the report, and finally authors a monitoring **scout**. When done,
the user lands on the report detail view and an initial implementation task kicks off automatically.

This document scopes the **first end-to-end workflow** only (creation → planning conversation →
finalize → scout → redirect + implementation task). Later refinements (scout tuning UX, richer plan
detail view) are called out as follow-ups.

## Motivation / Problem

The inbox today surfaces _reactive_ work — signals grouped into reports that already happened. There
is no _proactive_ surface for planning a new feature and then carrying it through implementation and
post-ship monitoring in one place. Plan mode makes the inbox the home for a feature's whole life:
plan → implement → review feedback → ship → instrument → measure, with a scout keeping it moving.

## Goals

- A user can create a "project" (plan report) from a new **Plan** tab with a short initial description.
- A planning conversation with a sandbox agent starts immediately, rendered in the existing task UI.
- The agent has the report ID, the right MCP tools/scopes, and is instructed to gather repo context first.
- On completion the agent writes the finished plan into the report (title, summary, detailed notes
  with code references), P1 / actionability-passed / safety-passed, creating user as suggested reviewer.
- An `inbox`/`plan` signal carrying the title + summary is emitted and bound to that report.
- A monitoring scout is authored (interactively) to progress/feedback/instrument/measure the plan over time.
- The user is redirected to the report detail view and an initial implementation task auto-starts.

## Non-goals

- No new report **status** for "deployed" — deployment is _derived_ from the artefact activity log
  (task_run / commit artefacts) and the report's associated branch/PR state, not a stored enum.
- No Django migration for the new signal kind — it is a new **signal class** in the schema pipeline.
- Not rebuilding the task conversation UI — we embed the existing `ReadonlyRunSurface` transcript.
- Not building a general repo-management primitive — the agent simply `git clone`s the repos it needs
  inside its sandbox during the conversation.

## Terminology

- **Project / plan report** — a `SignalReport` created in plan mode. "Project" is the user-facing name
  for now; under the hood it is a `SignalReport` distinguished by its backing `inbox`/`plan` signal
  (and/or a marker note artefact).
- **Planning agent** — the sandbox LLM agent that runs the planning conversation.
- **Monitoring scout** — a `signals-scout-*` skill + `SignalScoutConfig` that periodically advances the plan.

## End-to-end flow (mapped to concrete mechanisms)

1. **User clicks "New plan"** in the Plan tab → a modal asks for a brief initial description.
2. **Report created in Postgres** with placeholder title + the user's initial description as summary,
   at status `READY` (born-ready, like scout-authored reports — bypasses the grouping pipeline).
   Created via a direct-write path modeled on `create_scout_report`
   (`scout_report/persistence.py:98`), inside `transaction.atomic()`.
3. **Planning task started** — a `Task` + `TaskRun` created via `tasks_facade.create_and_run_task(...)`
   with `mode="interactive"`, `posthog_mcp_scopes="full"`, `interaction_origin="signal_report"`,
   `ai_stage="planning"`, `signal_report_id=<report>`, and a `pending_user_message` /`description`
   carrying the planning instructions + report ID. Renders in the inbox via `ReadonlyRunSurface`
   (`interaction='live'`).
4. **Agent gathers repo context** — instructed to first ask the user which repositories the project
   affects, then `git clone` them into its sandbox (using the GitHub integration token) so it can
   read real code while planning.
5. **Agent plans with the user** — multi-turn; user replies flow back via the `send_followup_message`
   workflow signal.
6. **Agent finalizes the plan** (all via PostHog MCP tools that already exist):
   - `inbox-reports-update` → set final `title` + `summary`.
   - `inbox-report-artefacts-create` → `note` artefacts (detailed plan notes), `code_reference`
     artefacts (file/line references), `priority_judgment` = **P1**, `actionability_judgment` =
     `immediately_actionable`, `safety_judgment` = `choice: true`, `suggested_reviewers` = creating user.
   - Emit an **`inbox`/`plan`** signal (title + summary) **bound to this report** by writing the
     backing row **directly to the embeddings Kafka topic** (not `emit_signal`, not the matcher — see
     Data model).
7. **Agent authors a monitoring scout** (interactive with the user) — creates a `signals-scout-plan-*`
   `LLMSkill` (`skill-create`) + `signals-scout-config-create`. The scout's instructions: on each run,
   read the plan report + its artefacts and either (a) progress outstanding implementation if the last
   changes merged, (b) incorporate user feedback notes, or (c) if deployed, instrument missing analytics
   or read usage data and update the report status note. Deployment state is derived from artefacts +
   branch, not a status enum.
8. **Redirect + implementation kickoff** — user is pushed to `urls.inboxReport('reports', reportId)`;
   an initial implementation task starts via `tasks_facade.create_and_run_task(..., ai_stage="implementation")`
   - `record_implementation_task(...)`, with suggested reviewer → assignee resolution as in `auto_start.py`.

## Architecture / components

### Data model

**Reuse `SignalReport`** (`models.py:185`) unchanged — no new columns.

- `title`, `summary` set at finalize via `inbox-reports-update`.
- Priority / actionability / safety / reviewers are **artefacts**, not columns
  (`SignalReportArtefact`, `models.py:720`; schemas in `artefact_schemas.py`).
- Distinguish plan reports from ordinary reports via their backing `inbox`/`plan` signal and/or a
  marker note artefact. (Decide: a dedicated marker vs. filtering on source product — see Open questions.)

**New signal class (no migration).** Add to `frontend/src/queries/schema/schema-signals.ts`:

- `InboxPlanSignalExtra extends SignalExtraBase` (carry `title`, `summary`, `report_id`, `plan_id`, …).
- `InboxPlanSignalInput extends SignalInputBase` with `source_product: 'inbox'`, `source_type: 'plan'`,
  `extra: InboxPlanSignalExtra`.
- Add `InboxPlanSignalInput` to the `SignalInput` union (line 478).
- Run `hogli build:schema` to regenerate `posthog/schema.py`. This gives us a typed shape for the
  row on the read side; note the `_SIGNAL_VARIANT_LOOKUP` validator (`facade/api.py:190-200`) only
  gates the `emit_signal` entrypoint, which we bypass (see below).
- **No** change to `SignalSourceConfig.SourceProduct` / `SourceType` TextChoices → **no Django migration**.
  `source_product`/`source_type` are plain `CharField`s; choices aren't DB-enforced.

**Emit the backing signal directly to Kafka, bound to the report.** We do **not** use `emit_signal`
(`facade/api.py:228`) — it routes through async semantic grouping and cannot target a chosen report.
Instead follow the existing direct-write pattern in `create_scout_report`: `_emit_bound_signal`
(`scout_report/persistence.py:395`) calls `emit_embedding_request` (`posthog/api/embedding_worker.py`),
which writes the row straight to the embeddings Kafka topic → `document_embeddings`, with
`metadata.report_id` pre-set (and `match_metadata` omitted — "these rows never went through the
matcher"). For plan reports we reuse this path with `source_product="inbox"` / `source_type="plan"`
in `_signal_metadata` (defaults come from `scout_harness/tools/emit.py` `SOURCE_PRODUCT`/`SOURCE_TYPE`
today; we pass the inbox/plan values instead). No matcher, no `is_source_enabled` gate, no migration.

### Report creation (up front)

- New facade function in `products/signals/backend/facade/api.py` (product is isolated — see
  `.claude/rules/product-isolation.md`; external callers only touch the facade). Something like
  `create_plan_report(team, user_id, initial_description) -> report_id`.
- Implementation modeled on `create_scout_report` (`scout_report/persistence.py:98`): create the
  `SignalReport` at `READY` with placeholder `title` + `summary=initial_description`, append a
  provenance `note` artefact attributed to the user (`ArtefactAttribution.from_user`), inside
  `transaction.atomic()`. Defer signal emission / task kickoff to `transaction.on_commit`.

### Planning task / sandbox conversation

- Kick off via `tasks_facade.create_and_run_task(...)` (`products/tasks/backend/facade/api.py:647`).
  Key params: `origin_product=SIGNAL_REPORT`, `signal_report_id`, `mode="interactive"`,
  `posthog_mcp_scopes="full"`, `interaction_origin="signal_report"`, `ai_stage="planning"`,
  `pending_user_message=<planning kickoff message>`, `repository=None` — the sandbox boots repo-less
  and the agent `git clone`s whatever repos the user names, mid-conversation, in-sandbox.
- Agent gets the PostHog MCP auto-wired with `X-PostHog-Task-Id` for attribution
  (`start_agent_server.py` / `utils.py:414`). Writes are attributed to the task via
  `task_attribution.py` (`X-PostHog-Task-Id` → `ArtefactAttribution.from_task`).
- Record the run against the report with `append_task_run_artefact(...)`
  (`task_run_artefacts.py:49`), type `task_run`, so the detail view shows the planning conversation.

### Agent instructions (prompt)

The planning kickoff message / task `description` must tell the agent:

- It is the **planning agent** for report `<report_id>`; the human is planning a new feature.
- **First** ask the user which repositories the project affects, and obtain them for context.
- Discuss/plan the feature with the user.
- On completion: update title + summary (`inbox-reports-update`); write detailed `note` +
  `code_reference` artefacts (`inbox-report-artefacts-create`); set `priority_judgment=P1`,
  `actionability_judgment=immediately_actionable`, `safety_judgment.choice=true`,
  `suggested_reviewers=[<creating user's github_login>]`; emit the `inbox`/`plan` signal.
- Then author + register a monitoring scout (interactive), following the `authoring-scouts` skill.
- (Prompt authored as a reusable template under `products/signals/backend/` — consider a
  `custom_agent/` prompt module alongside existing agent prompts.)

### Finalization details

- **Priority P1 always**, **actionability passed**, **safety passed** — hardcoded expectations for
  user-driven plans (agent instructed to always set these; optionally enforce server-side when the
  finalize happens through a plan-specific action).
- **Suggested reviewer = creating user.** Resolve the user's GitHub login
  (`get_org_member_github_logins_by_user_uuid`) and write it as the single `SuggestedReviewers` entry.
- **`inbox`/`plan` signal** bound to the report (title + summary in `description`/`extra`) via the
  direct-write helper above.

### Monitoring scout (iterative authoring)

- Scout = an `LLMSkill` named `signals-scout-plan-<slug>` + a `SignalScoutConfig`
  (`models.py:1001`). No FK to the report; the scout stores the `report_id` in its `SignalScratchpad`
  (key like `report:plan:<plan-id>`) on first run and reads it thereafter.
- Created via MCP: `skill-create` (skills store) + `signals-scout-config-create`
  (`products/signals/mcp/tools.yaml:345`). Authoring is iterative per the `authoring-scouts` skill
  (dry-run `emit=false` → `signals-scout-run-now` → inspect → refine).
- Runs on the coordinator cron (`SignalsScoutCoordinatorWorkflow`, every 30 min, dispatches configs
  whose interval elapsed). Each run has full PostHog MCP read + `signals-scout-edit-report` /
  `inbox-report-artefacts-create` to advance the plan.
- Scout instructions branch on **derived** deployment state: inspect the report's artefact log
  (`task_run` / `commit` artefacts) and associated branch/PR to decide progress vs feedback vs
  instrument vs measure — no status enum lookup.

### Frontend

- **New Plan tab** — add `'plan'` to `InboxTabKey`, `INBOX_TAB_KEYS`, `INBOX_TAB_LABEL`
  (`frontend/src/scenes/inbox/types.ts:115`), a branch in `InboxScene.tsx` (`isReportListTab`
  - `ActiveTabBody`, lines 42-60), and a `PlanTab.tsx` under `components/tabs/`.
- **"New plan" button + description modal** — in `PlanTab.tsx`. New kea action (extend
  `inboxTaskKickoffLogic.ts` or a new `planKickoffLogic`) that: calls the create-plan API →
  gets `report_id` + planning `task_id` → renders the live conversation (`ReadonlyRunSurface`,
  `interaction='live'`) → on completion redirects to `urls.inboxReport('reports', reportId)`.
  - Guard the button against double-submission (`loading`/`disabledReason` while the request is in flight).
- **API** — reports have no `create` action today (`views.py`). Add a plan-specific create endpoint
  (viewset action or new route in `routes.py`) that calls the `create_plan_report` facade and starts
  the planning task. Annotate with `@extend_schema`/`@validated_request`; add a serializer with
  `help_text` so generated FE types + MCP schemas are populated (see `/improving-drf-endpoints`).
- **Conversation embed** — reuse `ReadonlyRunSurface` (`products/posthog_ai/frontend/components/`),
  as `ReportTasksSection.tsx` already does. Note: there is no existing in-inbox _composer_; user
  replies to a live run go through the `TaskRun` follow-up relay API.

## Rollout

- Feature-flag the Plan tab + create endpoint.
- Ship in phases (see Milestones) so the planning conversation works before scout auto-authoring
  and implementation auto-kickoff are wired.

## Risks & open questions

- **Repo access mid-conversation — DECIDED: agent `git clone`s in-sandbox.** Sandbox boots repo-less
  (`repository=None`); the agent asks which repos the project affects and clones them itself using the
  GitHub integration token. Remaining implementation detail: surfacing the integration credential/token
  into the sandbox for `git clone` (and handling multiple repos + private-repo auth). Verify the sandbox
  has the git credentials available; if not, thread the GitHub integration token into the sandbox env.
- **Distinguishing plan reports** in queries/UI — dedicated marker note artefact vs. filtering on the
  `inbox`/`plan` backing signal's source product. Affects the Plan tab's list query.
- **Enforcing P1 / actionability / safety** — rely on agent instructions, or enforce server-side in a
  plan-finalize action? Server-side is safer but adds an endpoint.
- **Single interactive sandbox for both plan + repo context** — keeping the sandbox alive
  (`mode="interactive"`) for a long planning conversation; watch inactivity/TTL settings on `TaskRun.state`.
- **Scout authoring interactivity** — authoring a scout is itself an interactive MCP loop; confirm the
  planning agent can drive `skill-create` + `signals-scout-config-create` end-to-end in one session.
- **Implementation kickoff timing** — kick off after finalize + scout creation; ensure idempotency via
  `record_implementation_task` (`task_run_artefacts.py:96`) so a retried workflow doesn't double-start.

## Implementation status (2026-07-02)

Built so far (see `products/signals/backend/plan_mode/`):

- **Plan tab + list** — CH-membership list (`inbox`/`plan` backing signals, latest-first) enriched from Postgres; `InboxPlanViewSet.list`.
- **Plan detail** — dedicated view with Status / Owner / Feed sub-tabs; click-to-edit title/summary; `question` artefact type (agent asks, user answers in place); reviewers surfaced as "Owners"; no Evidence section.
- **New plan flow** — modal (initial description) → `create` endpoint: draft report born READY + groundskeeping note + interactive repo-less planning task (`mode="interactive"`, `ai_stage="planning"`); draft view = live left column (5s poll) + embedded `TaskRunChat` conversation; **Finish plan** button gated on readiness (title, summary, repo_selection, suggested_reviewers, priority_judgment; hover lists missing).
- **Finish** — `finish` endpoint (idempotent): safety+actionability defaults written deterministically, **owner scout created/converged deterministically** (`signals-scout-plan-<id>` LLMSkill + `SignalScoutConfig`; plan-specific steering lives in the plan's "Owner scout playbook" note), first implementation pass auto-started. **No backing signal is emitted** — the `inbox`/`plan` signal was removed: Plan tab membership is the Postgres planning marker alone, and relatedness to other reports is the owner scout's sweep (`associated_report` artefacts), keeping plans entirely outside the grouping pipeline.
- Draft-ness is derived: a plan is a draft until its `safety_judgment` artefact exists (only `finish` writes one).

Implementation kickoff: the owner scout drives increments via the sandbox-only `signals-scout-start-implementation` tool (`signal_scout_report:write`, internal scope — never on the customer MCP surface): deterministic, one pass at a time (in-flight guard), repo/owner from the report's artefacts. Autostart was rejected for this (once-per-report gate + autonomy thresholds).

Finish plan also auto-starts the FIRST implementation pass (best-effort, same in-flight-guarded path as the scout tool; the owner scout drives subsequent increments).

## Milestones

- [ ] **M1 — Create + converse.** New signal class (`schema-signals.ts` + `hogli build:schema`);
      `create_plan_report` facade + create endpoint; Plan tab + "New plan" button + description modal;
      planning task kickoff (`create_and_run_task`, interactive, repo-less); live conversation embed.
      Verify GitHub integration token is available in-sandbox for the agent's `git clone`.
- [ ] **M2 — Finalize.** Agent prompt template; reuse the `_emit_bound_signal` / `emit_embedding_request`
      direct-to-Kafka path with `inbox`/`plan` metadata; finalize writes (title/summary + artefacts:
      P1 / actionability / safety / suggested reviewer); `inbox`/`plan` signal bound to report.
- [ ] **M3 — Scout.** Monitoring `signals-scout-plan-*` skill + config authored interactively;
      scratchpad-based report binding; run behavior (progress / feedback / instrument / measure) with
      derived deployment state.
- [ ] **M4 — Redirect + implementation.** Redirect to report detail; auto-start implementation task
      with suggested-reviewer → assignee resolution; idempotent kickoff.

## References

**Backend — signals**

- `products/signals/backend/models.py:185` — `SignalReport` (status lifecycle `246-367`).
- `products/signals/backend/models.py:720` — `SignalReportArtefact`; `1001` — `SignalScoutConfig`;
  `1089` — `SignalScoutRun`; `1237` — `SignalScratchpad`; `78` — `is_source_enabled`.
- `products/signals/backend/artefact_schemas.py` — artefact content schemas
  (`Priority` P0–P4 `:54`, `ActionabilityChoice` `:48`, `SafetyJudgment` `:161`, `SuggestedReviewers` `:182`).
- `products/signals/backend/facade/api.py:228` — `emit_signal` (NOT used); `190-200` — `_SIGNAL_VARIANT_LOOKUP`.
- `products/signals/backend/scout_report/persistence.py:98` — `create_scout_report`; `:395`
  `_emit_bound_signal` (direct-to-Kafka pattern to reuse); `:SOURCE_PRODUCT/SOURCE_TYPE` via
  `scout_harness/tools/emit.py`.
- `posthog/api/embedding_worker.py` — `emit_embedding_request` (writes the row to the embeddings Kafka topic).
- `products/signals/backend/task_run_artefacts.py:49,96` — `append_task_run_artefact`,
  `record_implementation_task`.
- `products/signals/backend/task_attribution.py:24,45` — `X-PostHog-Task-Id` attribution.
- `products/signals/backend/auto_start.py` — implementation autostart + assignee resolution.
- `products/signals/backend/views.py` / `routes.py` — report viewset (no create today).

**Signal schema**

- `frontend/src/queries/schema/schema-signals.ts:66` (`SignalInputBase`), `478` (`SignalInput` union).

**Tasks / sandbox**

- `products/tasks/backend/models.py:59` — `Task`; `772` — `TaskRun` (`state` config).
- `products/tasks/backend/facade/api.py:647` — `create_and_run_task`.
- `products/tasks/backend/temporal/process_task/workflow.py:151` — `ProcessTaskWorkflow` ("process-task").
- `products/tasks/backend/temporal/process_task/activities/start_agent_server.py` +
  `.../utils.py:414` — MCP wiring (`X-PostHog-Task-Id`, scopes).
- `products/tasks/backend/logic/repo_selection/agent.py` — LLM repo selection.

**MCP tools**

- `products/signals/mcp/tools.yaml` — `inbox-reports-update:232`, `inbox-report-artefacts-create:21`,
  `signals-scout-config-create:345`, `signals-scout-run-now:526`, `signals-scout-edit-report:428`.

**Frontend — inbox**

- `frontend/src/scenes/inbox/types.ts:115` — tab keys; `InboxScene.tsx:42-60`;
  `components/tabs/*`; `components/InboxReportList.tsx`; `components/detail/ReportDetail.tsx`;
  `components/detail/ReportTasksSection.tsx:85` — `ReadonlyRunSurface` embed;
  `inboxTaskKickoffLogic.ts`; `urls.ts:302` — `inboxReport(tab, reportId)`.

**Scout authoring**

- `products/signals/skills/authoring-scouts/SKILL.md` (+ `references/lifecycle-and-testing.md`).
- `products/signals/backend/scout_harness/runner.py:100` — `arun_signals_scout`.
- `products/signals/backend/temporal/agentic/scout_coordinator.py` — coordinator cron.
