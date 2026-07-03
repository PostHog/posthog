# Stage 6 implementation plan — Inbox trigger: auto-review self-driving implementations

> **Status: DESIGNED 2026-07-02, not built.** This is the self-contained implementation spec for
> [ARCHITECTURE.md → Stage 6](ARCHITECTURE.md). It front-loads every fact an implementing agent needs
> (verified against the branch on 2026-07-02) so implementation does not require re-researching the
> Signals/Tasks/ReviewHog integration surface. Where a decision was made, the rationale and the
> **rejected alternatives are binding** — do not re-litigate them silently.
>
> **Pre-flight (do this first).** The `signals/reviewhog` branch moves fast; before coding, reconcile
> this plan with the current tree: (1) migration numbers below are placeholders — take the next free
> number (`max_migration.txt`); (2) in-flight work you may find already landed: a ReviewHog reviews
> read API (`backend/api/reviews.py`), `ReviewReport.acting_user` (migration `0009_reviewreport_acting_user`),
> `ResolveActingUserInput.report_id`; (3) re-verify quoted line numbers with grep before editing —
> anchors are given as `path:line` for orientation, not as gospel.

## 0. What this feature is

When a **self-driving (Signals) implementation task run** finishes and produced code, ReviewHog
reviews what it produced, automatically. If the run opened a PR, the review publishes back as PR
comments (same as the Stage-5 label flow); if there is no PR (future branch-only implementations),
the identical review runs and its findings/verdicts/rendered body are **stored only** — usable for
shadow-fixing before anything is published, publishable on a later turn once a PR exists. Either
way the signal report's artefact log records the review, so a report reads as the full story:
signals → research → implementation `task_run` → `commit`s → **`code_review`** → merge/`RESOLVED`.

The consumer-facing switch already exists: `ReviewUserSettings.review_inbox_prs`
(`backend/models.py`, default **off**), surfaced in the Inbox "Code review" tab. It is stored but
consumed by nothing — this stage wires it up.

## 1. Context primer (verified facts — do not re-research)

### 1.1 How an Inbox implementation is born (Signals → Tasks)

- A promoted, immediately-actionable `SignalReport` auto-starts an implementation task:
  `products/signals/backend/auto_start.py:135` →
  `tasks_facade.create_and_run_task(team=…, title=…, description=…, origin_product=TaskOriginProduct.SIGNAL_REPORT,
user_id=<assignee>, repository=<owner/repo>, branch=<base>, signal_report_id=<report uuid>,
posthog_mcp_scopes="full", interaction_origin="signal_report", ai_stage="implementation")`.
  `interaction_origin="signal_report"` makes the agent auto-push and open a **draft PR** from an
  **origin branch** (never a fork) — structurally the only PR shape ReviewHog's sandbox checkout
  supports.
- `Task` model (`products/tasks/backend/models.py`): `created_by` FK (line ~81, `SET_NULL`,
  nullable — the auto-start assignee or the user who clicked "start task"), `origin_product`
  (~86), `repository` CharField (~110, **lowercased on save**, ~174), `signal_report` FK (~115,
  indexed `posthog_task_signal_report_idx`).
- `TaskRun` (`products/tasks/backend/models.py`): `status`, `branch`, `output` JSONField (holds
  `pr_url`; partial index `task_run_output_pr_url_idx` on `output__pr_url IS NOT NULL`), `task` FK,
  `team` FK.

### 1.2 How a run completes (the trigger moment)

> **⚠️ AMENDED AT BUILD TIME (2026-07-03, live-e2e discovery): this section's premise is wrong —
> successful runs NEVER complete, so the trigger moment is the `output`-recording save instead.**
> `mark_completed()` exists but has zero production callers (tests only);
> `execute_sandbox/workflow.py::_maybe_record_terminal_status` deliberately keeps a successful run
> `in_progress` ("the run is always followable"), the task-management orchestrator only ever writes
> `cancelled`/`failed`, and signals-origin tasks unconditionally opt into the PR follow-up loop
> (`get_task_processing_context.py`) which babysits the PR indefinitely. The `track_task_run_completion`
> precedent below predates that architecture. As built, the receiver fires on saves that (may) touch
> `output`: target = `output.pr_url` (PR leg) else `output.head_branch` (branch leg — synced by the
> agent server at end of any turn whose git branch changed, PR or no PR); creation saves,
> declared-fields saves without `output`, and failed/cancelled runs are skipped. See
> ARCHITECTURE.md → Stage 6 → "🔁 TRIGGER REDESIGNED 2026-07-03".

- `TaskRun.mark_completed()` (`products/tasks/backend/models.py:1141`):
  `self.status = COMPLETED; self.completed_at = now(); self.save(update_fields=["status", "completed_at"])`
  → **`post_save` fires**. Other completion writers (`temporal/process_task/activities/relay_sandbox_events.py:~180`,
  `logic/services/custom_prompt_internals.py:~306`) also go through instance saves.
- The **only** bulk `.update(status=…)` (which would NOT fire `post_save`) is a FAILED-cleanup at
  `products/tasks/backend/facade/api.py:~803` — irrelevant, failed runs never trigger a review.
- Precedent for a completion receiver **on this exact model**: `track_task_run_completion`
  (`products/tasks/backend/models.py:~1739`) — a `post_save` receiver gating on
  `not created and status == COMPLETED and …`.
- Timing note: `output.pr_url` is normally PATCHed by the agent **before** completion
  (`facade/api.py::update_task_run`, ~1323 — also fires `_post_slack_update_for_pr`). When agent-side
  detection misses, the GitHub webhook backfills it later via `_record_run_pr_url`
  (`products/tasks/backend/webhooks.py:146`) with `save(update_fields=["output", "updated_at"])` on
  the already-COMPLETED run — **that save re-fires `post_save`**, which is the natural recovery for
  the "completed before pr_url known" race (see §4 idempotency).

### 1.3 ReviewHog's existing entry points and workflow

- `ReviewPRWorkflowInputs` (`backend/temporal/types.py`): `team_id, user_id, pr_url, owner, repo,
pr_number, publish: bool = False, acting_user_id: int | None = None`. Deterministic id:
  `review_pr_workflow_id(...)` → `review-pr:{team_id}:{owner}/{repo}:{pr_number}`.
- `backend/temporal/client.py`: `start_review_pr_workflow(*, pr_url, team_id, user_id, publish,
acting_user_id=None) -> workflow_id` (non-blocking) and blocking `execute_review_pr_workflow`
  (CLI). Both share `_build_inputs` (parses the PR URL, `Team.objects.get(id=team_id)` fail-fast)
  and start `"review-pr"` on `settings.VIDEO_EXPORT_TASK_QUEUE` with
  `id_reuse_policy=ALLOW_DUPLICATE`, `id_conflict_policy=USE_EXISTING`,
  `RetryPolicy(maximum_attempts=2)`. **USE_EXISTING semantics:** re-trigger while a run is in
  flight joins the running execution (no error, no queue); after it closes, a new start begins a
  fresh turn.
- Workflow body (`backend/temporal/workflow.py`): fetch → early-exit if
  `meta.already_published` for this head (~322) → `resolve_acting_user_activity` (~331) → **the
  gate to extend** (~348–356):

  ```python
  # The label trigger's per-author opt-out. Only the cloud path (no explicit acting-user
  # override) is gated — an explicit CLI/eval invocation always runs. A second cloud trigger
  # (e.g. Inbox PRs) needs its own trigger-source input, not this gate.
  if inputs.acting_user_id is None and not acting.review_labeled_prs:
      ... skip ...
  ```

- `resolve_acting_user_activity` (`backend/temporal/activities.py:~414`): `override_user_id` set →
  used directly (no author-login mapping); loads `ReviewUserSettings.load(team_id, acting_user_id)`
  and snapshots `review_labeled_prs` + `urgency_threshold` into `ResolveActingUserResult` so
  mid-run settings edits can't flip gates. **The snapshot does not yet carry `review_inbox_prs`.**
- Fetch (`backend/temporal/activities.py::fetch_pr_data_activity`, `_fetch_and_persist` ~340–399):
  resolves the team's installation token, `PRFetcher(owner, repo, pr_number, token)`, rejects fork
  PRs non-retryably, `upsert_review_report(*, team_id, repository, pr_url, pr_metadata) -> report_id`
  (`backend/reviewer/persistence.py:54`), `persist_commit_snapshot` (head_sha-gated), persists the
  `pr_snapshot` artefact. Downstream stages reload inputs from the DB by `(report_id, head_sha)`.
- Publish: DB-driven, `head_sha`-pinned COMMENT review; idempotent via
  `ReviewReport.published_head_sha`; gated per run by `inputs.publish`.
- Skills: `load_perspectives_for_run(team_id, acting_user_id)` etc.
  (`backend/reviewer/skill_loader.py`) — canonical skills **auto-seed per team on first resolve**
  (`lazy_seed.sync_canonical_*`), so a cold team works with zero setup.
- Findings/verdicts persistence is publish-independent: `issue_finding` + `validation_verdict`
  rows and `ReviewReport.report_markdown` are written in stages 7–9 regardless of `publish` —
  "store-only" already exists; only the last stage is conditional.

### 1.4 Multi-team / multi-repo audit (verified — the design is generic)

- The `posthog/posthog` restriction lives **only** in the label-path HTTP endpoint
  (`backend/api/trigger.py:19` `ALLOWED_REPOS`, plus `settings.REVIEWHOG_TEAM_ID` /
  `REVIEWHOG_RUN_USER_ID` reads at ~121–125). The inbox trigger calls
  `start_review_pr_workflow(...)` directly and never touches that endpoint or those settings.
- Token resolution is generic: `GitHubIntegration.first_for_team_repository(team_id, repository)`
  (`posthog/models/integration.py:2619`) validates the repo path shape (SSRF guard), iterates the
  team's `kind="github"` integrations ordered by id, and returns the first whose **installation can
  access the repository** — multi-org teams and any customer repo work.
- DB level: all four ReviewHog models are team-scoped (`TeamScopedRootMixin`, fail-closed managers,
  writes via `for_team`); `ReviewReport.repository` is a plain CharField; uniqueness and the
  workflow id both include `team_id`, so two teams reviewing the same GitHub PR get independent
  rows/executions.
- Publish permission: the review posts with the same App installation token the tasks agent already
  used to push the branch and open the PR — wherever self-driving implementations work, publish
  permission is already proven.
- Sandbox: `CustomPromptSandboxContext(team_id, user_id, repository)` → Tasks' `get_sandbox_for_repository`
  clones the base repo and checks out the head branch by name — the same infra that ran the
  implementation on that repo minutes earlier.

### 1.5 The Signals artefact write surface (for the `code_review` artefact)

- `SignalReportArtefact` (`products/signals/backend/models.py:~683`): `ArtefactType` TextChoices
  (`video_segment, safety_judgment, actionability_judgment, priority_judgment, signal_finding,
repo_selection, suggested_reviewers, dismissal, code_reference, commit, task_run, note,
title_change, summary_change`), `LOG_ARTEFACT_TYPES` frozenset (~719), write funnel `_create` +
  `add_log(*, team_id, report_id, content, attribution)` (~857) which derives the row's type from
  the content model class (`artefact_type_for`).
- Content schemas (`products/signals/backend/artefact_schemas.py`): one pydantic model per type,
  registered in `ARTEFACT_CONTENT_SCHEMAS` (~458, plain-string keys, Django-free);
  `_ARTEFACT_TYPE_BY_MODEL` derives the reverse map; **a test asserts the registry's key set equals
  the model enum exactly** — adding a type means touching both, and the test tells you if you
  missed one. `LogArtefactContent` union (~453) must include new log models.
- `NON_WRITABLE_ARTEFACT_TYPES` (~485): system-generated types (`video_segment, title_change,
summary_change`) that the generic artefact API must reject for create/update while staying
  readable. **`code_review` belongs in this set** — its only writer is the ReviewHog workflow.
- Attribution: every write requires `ArtefactAttribution` — use `ArtefactAttribution.system()`
  (`products/signals/backend/artefact_attribution.py`; ReviewHog already imports this module, so
  the `review_hog → signals` edge exists).
- The Inbox UI renders a report's artefacts from `GET signals/reports/{id}/artefacts/?limit=1000`
  (`frontend/src/scenes/inbox/components/detail/ArtefactLogList.tsx`). Rendering the new type is
  the maintainer's side (UI is being iterated separately) — but confirm the list degrades
  gracefully for an unknown type before shipping the backend write.

### 1.6 Dependency directions (why the trigger lives in review_hog)

Existing edges: `review_hog → tasks` (facade `products.tasks.backend.facade.agents` for
`MultiTurnSession`), `review_hog → signals` (`artefact_attribution`), `tasks → signals`
(webhooks). Therefore:

- **tasks must not import review_hog** (cycle with `review_hog → tasks`). No trigger code in
  `ProcessTaskWorkflow`, the tasks webhook handler, or the tasks facade.
- **signals must not import review_hog** (cycle with `review_hog → signals`).
- The receiver lives in **review_hog**, connecting to `tasks.TaskRun` via
  `apps.get_model("tasks", "TaskRun")` in `AppConfig.ready()` — every edge stays in the existing
  direction, zero changes to tasks.
- Run `tach check --dependencies --interfaces` after wiring; if the `review_hog → tasks/signals`
  edges aren't yet declared for the new modules, extend the existing facade usage — do not add
  reverse edges.

## 2. Locked decisions (maintainer, 2026-07-02) — with rationale

1. **Two triggers only:** the Stage-5 `reviewhog` label (unchanged) and "self-driving
   implementation task finished" (new, internal). **No GitHub webhook for the inbox path** — the
   implementation runs in our own worker; completion is our own DB state change. (Webhook trigger
   was designed and rejected: PR-centric, dies when implementations stop opening PRs.)
2. **Scope:** tasks with `Task.signal_report_id` set. Nothing else (Slack / MaxAI / user-created
   origins excluded for now).
3. **The review target is the implementation output** (branch/diff). The PR is a publish
   destination, not the identity: PR resolvable → publish comments; no PR → store-only. **No
   shadow-mode flag** — the target's shape decides.
4. **Failed run, or a run that pushed nothing → do nothing.** (Failed = receiver ignores
   non-COMPLETED; pushed-nothing = fetch-time empty-diff self-skip, see §3 step 4.)
5. **Repeat turns allowed from day one.** Re-review relies on previous findings (watermark
   early-exit, working-state resume, covered-set). Maintainer: assume the loop works; dogfood is
   its first real exercise. Do **not** add a "first turn only" restriction.
6. **Acting user = `task.created_by`** — the GitHub PR author is a bot, so author-login mapping
   can't apply. Their perspectives / blind-spots / validator / urgency threshold drive the run.
   The **single existing urgency threshold** applies; no separate inbox knob.
   > **AMENDED at build time (maintainer, 2026-07-02): acting user = the report's assigned
   > reviewer, NOT `task.created_by`.** Signals tasks are created in the background (research /
   > repo-selection / custom-agent tasks literally as the GitHub-integration creator via
   > `resolve_user_id_for_team`), so `created_by` carries no assignment meaning. Assignment = the
   > Inbox "For you" semantics: the report's **latest `suggested_reviewers` artefact**, logins
   > resolved to org members exactly like `_apply_signal_report_suggested_reviewer_filter`
   > (signals `views.py`) and the Slack inbox notifications. The acting reviewer is the task's own
   > user (`created_by` — whoever clicked "Create PR", or the auto-start assignee) **when they are
   > among the resolved reviewers** (someone who asked for the implementation gets their own rules
   > applied to its review — maintainer, 2026-07-03); otherwise the **first login that resolves to
   > an org member is canonical**. The acting reviewer's `review_inbox_prs` gates the review and
   > their ReviewHog options drive it — a non-acting reviewer's opt-in never hijacks whose options
   > apply. Acting reviewer missing or opted out → skip. The receiver also skips `task.internal`
   > tasks — research/repo-selection/custom-agent tasks carry `signal_report_id` too, and only
   > implementation tasks (auto-start or "Create PR") are non-internal.
7. **Gate = `review_inbox_prs`** (default off — the budget gate for 100%-coverage cost). Checked
   cheaply at the trigger **and** snapshotted at resolve time. Gates become trigger-aware:
   `label → review_labeled_prs`, `inbox → review_inbox_prs`, `manual` (CLI/eval) → ungated.
8. **Signals-side record = one pointer-first `code_review` artefact per turn** (counts + links +
   `review_report_id`; **no digest/summary duplication** — an agent reads details itself via
   `execute_sql` over the review_hog tables; `ReviewReport.report_markdown` has the full body even
   for stored-only turns). Appended on completion **or failure**, never on gate-skips (nothing was
   done). No dedicated read API in this stage.
9. **Rejected: merging the two artefact tables.** Different parents/identity (label reviews have
   no `SignalReport`); ReviewHog working-state rows (`pr_snapshot` holds whole diffs) are MB-scale
   resume substrate, not activity-log content (the Inbox fetches artefacts at `limit=1000`);
   signals artefacts are user-mutable (PATCH/DELETE) while ReviewHog's rows are resume-correctness
   substrate that must not be. The `SignalReportArtefact` mirroring stays pattern-level.
10. **Provenance lives on `ReviewReport`** (`signal_report_id`, `trigger_source`) because signals
    artefacts are API-deletable — the review row is the durable link.

## 3. Implementation steps

Ship in this order; each step is independently landable and testable.

### Step 1 — workflow inputs, trigger-aware gate, provenance

**Files:** `backend/temporal/types.py`, `backend/temporal/client.py`,
`backend/temporal/activities.py`, `backend/temporal/workflow.py`, `backend/models.py`,
`backend/reviewer/persistence.py`, `backend/api/trigger.py`, new migration.

- `ReviewPRWorkflowInputs` += `trigger_source: str = "manual"` (module constants
  `TRIGGER_LABEL = "label"` / `TRIGGER_INBOX = "inbox"` / `TRIGGER_MANUAL = "manual"` — plain
  strings, dataclass defaults keep in-flight Temporal payloads deserializing) and
  `signal_report_id: str | None = None`.
- Thread both through `_build_inputs` / `start_review_pr_workflow` / `execute_review_pr_workflow`
  (keyword-only, defaulted). The label endpoint (`api/trigger.py`) passes
  `trigger_source=TRIGGER_LABEL`; `run_review` stays `manual`.
- `ResolveActingUserResult` += `review_inbox_prs: bool = False`; `_resolve_acting_user` populates
  it from the same `ReviewUserSettings.load(...)` snapshot.
- Replace the workflow gate (~`workflow.py:348`) with a trigger-source map, preserving current
  semantics exactly for label and manual:

  ```python
  if inputs.trigger_source == TRIGGER_LABEL and inputs.acting_user_id is None and not acting.review_labeled_prs:
      skip("labeled-PR reviews turned off")
  if inputs.trigger_source == TRIGGER_INBOX and not acting.review_inbox_prs:
      skip("inbox reviews turned off")   # re-check even though the receiver gated — snapshot-at-resolve consistency
  ```

  (Manual stays ungated. Keep the existing "author is not a PostHog user → skip" check above it —
  the inbox path always sets `acting_user_id`, so it never hits that skip.)

- `ReviewReport` += `signal_report_id = models.UUIDField(null=True, blank=True)` (plain UUID, not
  an FK — the link must survive report deletion/reingestion on the signals side; index it) and
  `trigger_source = models.CharField(max_length=20, default="manual")`. Migration (next free
  number; FKs to hot tables are not involved, plain additive columns are safe).
- `upsert_review_report` gains optional `signal_report_id` / `trigger_source` kwargs: stamp on
  create; on update only fill when currently NULL (a label re-trigger of an inbox PR must not
  erase provenance, and vice versa).

**Tests** (extend `backend/tests/test_temporal_workflow.py` gate cases, parameterized): gate matrix
(trigger_source × review_labeled_prs × review_inbox_prs × acting override), provenance stamped on
create and preserved on re-upsert, old-shape payload deserializes (defaults).

### Step 2 — the signals `code_review` artefact

**Files:** `products/signals/backend/models.py`, `products/signals/backend/artefact_schemas.py`,
signals migration, new review_hog activity + workflow wiring.

- Signals `ArtefactType` += `CODE_REVIEW = "code_review"`; add to `LOG_ARTEFACT_TYPES`.
  Migration = choices-only `AlterField` (no DB change, safe).
- `artefact_schemas.py`:

  ```python
  class CodeReviewCounts(BaseModel):
      must_fix: int = 0
      should_fix: int = 0
      consider: int = 0

  class CodeReview(BaseModel):
      review_report_id: str          # ReviewReport UUID — the drill-down handle (SQL join key)
      repository: str                # owner/repo
      head_sha: str
      head_branch: str
      base_branch: str
      pr_number: int | None = None   # absent for branch-only targets
      pr_url: str | None = None
      review_url: str | None = None  # GitHub review permalink, when published
      outcome: Literal["published", "stored", "failed"]
      counts: CodeReviewCounts = CodeReviewCounts()   # is_valid=True findings by priority (threshold-independent)
  ```

  Register `"code_review": CodeReview` in `ARTEFACT_CONTENT_SCHEMAS`, add to `LogArtefactContent`,
  and add `"code_review"` to `NON_WRITABLE_ARTEFACT_TYPES` (system-generated: readable via the
  API/log, not creatable/editable through it). The registry-coverage test forces enum/registry
  agreement — update both sides together.

- New review_hog activity `append_code_review_artefact_activity` (in
  `backend/temporal/activities.py`): inputs `(team_id, signal_report_id, review_report_id,
outcome)` — it loads repository/branches/head_sha/pr fields off the `ReviewReport` row and counts
  off the valid-verdict rows (reuse `load_valid_findings` / the verdict loaders in
  `reviewer/persistence.py`), then
  `SignalReportArtefact.add_log(team_id=…, report_id=signal_report_id, content=CodeReview(...),
attribution=ArtefactAttribution.system())`. Import direction `review_hog → signals` already
  exists. Tolerant: if the signal report row is gone (deleted/reingested), log and return — never
  fail the review over its own receipt.
- Workflow wiring (only when `inputs.signal_report_id` is set):
  - after a publish that posted → `outcome="published"` (+ `review_url` captured from the publish
    activity's return — extend its result with the review's `html_url`);
  - after finalize when publish was skipped/not applicable → `outcome="stored"`;
  - wrap the body so an unhandled failure appends `outcome="failed"` before re-raising (activity
    call from the except path; guard so artefact-append failure never masks the original error);
  - the early-exit paths (`already_published`, gate-skips, no-acting-user) append **nothing**.

**Tests:** signals — registry coverage (auto-enforced), funnel accepts `CodeReview` via `add_log`,
API rejects `code_review` create/PATCH (non-writable), parses on read. review_hog — workflow
appends on published/stored/failed and not on skips (parameterized); counts computed from
verdicts; missing signal report tolerated.

### Step 3 — the trigger (TaskRun completion receiver)

**Files:** new `backend/receivers.py`, `backend/apps.py`, tests.

- `backend/apps.py` gains `def ready(self)` that imports `products.review_hog.backend.receivers`
  and calls its `connect()` which does
  `post_save.connect(handle_task_run_saved, sender=django_apps.get_model("tasks", "TaskRun"),
dispatch_uid="review_hog_task_run_completed")`. Keep the module import-light
  (django-startup-time budget): it may import `ReviewUserSettings`, the temporal **client** module
  (deliberately heavy-dependency-free per its docstring), and nothing from
  `workflow.py`/`activities.py`.
- Receiver logic, cheapest checks first (this fires on **every** TaskRun save — a hot model):

  ```python
  def handle_task_run_saved(sender, instance, created, **kwargs):
      try:
          if created or instance.status != COMPLETED:
              return
          task = instance.task                      # first DB hit
          if task.signal_report_id is None or task.created_by_id is None:
              return
          settings = ReviewUserSettings.load(task.team_id, task.created_by_id)
          if not settings.review_inbox_prs:
              return
          pr_url = (instance.output or {}).get("pr_url") if isinstance(instance.output, dict) else None
          if not pr_url:
              return  # pre-Step-4: PR required; log. Step 4 replaces this with the branch target.
          transaction.on_commit(lambda: _start(pr_url, task))
      except Exception:
          logger.exception("review_hog_inbox_trigger_failed")   # NEVER raise — this is inside tasks' save path
  ```

  `_start` calls `start_review_pr_workflow(pr_url=pr_url, team_id=task.team_id,
user_id=task.created_by_id, publish=True, acting_user_id=task.created_by_id,
trigger_source=TRIGGER_INBOX, signal_report_id=str(task.signal_report_id))`, catching and
  logging all exceptions (Temporal down must not surface into the request/activity that saved the
  run).

- Idempotency / races (all already handled by existing machinery — do not add bookkeeping):
  - repeat saves of a COMPLETED run (output PATCHes, webhook `_record_run_pr_url` backfill) re-fire
    the receiver → `USE_EXISTING` joins an in-flight run; a closed one starts a fresh turn whose
    fetch hits the `already_published` same-head early-exit. Cost: one workflow + one fetch
    activity, no sandbox spend.
  - run completed **before** `pr_url` was recorded → receiver skips; the webhook backfill save
    re-fires it with `pr_url` present — the race self-heals.
  - `user_id` doubles as the sandbox run user; `task.created_by` is a real PostHog user by
    construction (auto-start resolves an org member; manual start is the requesting user).
- Analytics (optional, mirrors signals conventions): capture `review_hog_inbox_review_triggered` /
  `_skipped` with `team_id`, `signal_report_id`, `task_id`, `run_id`, skip reason.

**Tests** (`backend/tests/test_inbox_trigger.py`, parameterized; use
`django_capture_on_commit_callbacks`): full gate matrix (created / non-COMPLETED / no
signal_report / no created_by / settings off / no pr_url / happy path), workflow client called
with exact kwargs, client exception swallowed, repeat-save does not duplicate beyond the
workflow-id collapse (mock returns same id).

### Step 4 — branch targets (PR-less reviews)

**Files:** `backend/temporal/types.py`, `backend/temporal/client.py`,
`backend/temporal/activities.py`, `backend/reviewer/tools/github_meta.py`,
`backend/reviewer/persistence.py`, `backend/models.py` + migration, `backend/receivers.py`.

- `ReviewReport.pr_number` → nullable; replace the single unique constraint with two partial ones:
  `Unique(team, repository, pr_number) WHERE pr_number IS NOT NULL` and
  `Unique(team, repository, head_branch) WHERE pr_number IS NULL`. Migration is on an unmerged
  product — plain swap is fine.
- Inputs grow a branch target: `pr_url/owner-repo/pr_number` become optional alongside
  `head_branch: str | None` (exactly one target shape required — validate in `_build_inputs`).
  Workflow id for branch targets: `review-branch:{team_id}:{owner}/{repo}:{head_branch}`.
- Receiver: prefer `output.pr_url` when present; else fall back to
  `(task.repository, instance.branch)` as the branch target (drop the Step-3 "no pr_url → skip").
  > **AMENDED at build time (adversarial review, 2026-07-03): the receiver fallback is DISABLED —
  > the Step-3 "no pr_url → skip" behavior stands.** `TaskRun.branch` holds the _base_ branch the
  > agent started from (auto_start passes the autostart base; the agent-server receives it as
  > `--baseBranch`), never the pushed head — so this fallback can only compare the wrong ref.
  > Branch targets stay fully supported at the client/workflow layer for callers that know a real
  > head branch; the receiver rejoins once tasks records the pushed head branch on the run.
- Fetch activity, branch-target path:
  1. resolve an open PR for the head branch first — one API call,
     `repo.get_pulls(state="open", head=f"{owner}:{branch}")` (precedent:
     `products/tasks/backend/temporal/code_workstreams/activities/poll_pull_requests.py::discover_branch_prs`).
     Found → continue exactly as the PR path (comments feed dedup; publish possible; backfill
     `pr_number`/`pr_url` onto a previously branch-keyed report row).
  2. not found → compare fetch `repo.compare(base, head)` (precedent for branch-vs-default diffs:
     `GitHubIntegration.get_diff`, used by Signals' commit-artefact `diff` action) → synthesize the
     `PRMetadata`-shape (author `""`, `is_fork=False`, head/base branches, `head_sha` = compare
     head), `pr_comments=[]`, build `PRFile`s from the compare payload, same filtering.
  3. **empty diff → self-skip the turn** before any sandbox spend (this is the "pushed nothing →
     do nothing" rule, enforced at the authoritative place, like fork rejection).
- Publish stage: skip when the turn has no PR (`outcome="stored"`); everything else identical.
- A stored review publishes on the next turn once a PR exists: fetch finds the PR, resume reuses
  the persisted rows for the unchanged head, `published_head_sha` still gates double-posting.

**Tests:** target validation in `_build_inputs`; branch workflow id; constraint pair; compare-path
fetch (mocked PyGithub) incl. empty-diff self-skip; branch→PR upgrade turn publishes and backfills
`pr_number`; receiver fallback.

### Step 5 — dogfood e2e (manual, before non-staff rollout)

> **✅ RUN 2026-07-03 (local, synthetic report + real click-through + real PR).** Full chain
> verified live: seeded report (For-you assignee = the clicking user) → "Create PR" in the Inbox →
> implementation agent → PR #68141 → the `output.pr_url` save fired the redesigned receiver
> (see the §1.2 amendment — the run itself never completes) → inbox workflow
> (`trigger_source="inbox"`, `signal_report_id` stamped at row creation) → single-chunk pipeline
> (size gate; 3 perspectives + blind-spots) → **zero findings on the clean 4-word typo PR** →
> publish self-skipped (no noise comment posted) → `code_review` receipt on the report with
> `outcome="stored"`, counts 0/0/0. The e2e also caught the trigger-premise bug itself (first
> click-through stalled forever on the completion gate) and exercised the same-head
> already-published early-exit + provenance backfill on a prior run against PR #68108. Still
> unobserved live: a receipt with `outcome="published"` (needs a findings-bearing PR; the publish
> machinery itself is proven by the Stage-5/manual leg on #68108) and the repeat-turn re-review
> (item 3 below).

1. On a dev/staging team with a GitHub integration: flip `review_inbox_prs` on for a user, run a
   self-driving implementation end-to-end (or `Task.create_and_run` with
   `interaction_origin="signal_report"` + a real `signal_report_id`).
2. Verify: receiver fired (logs) → workflow ran → comments on the draft PR → `code_review`
   artefact on the report (`GET signals/reports/{id}/artefacts/`) with `outcome="published"` and
   correct counts → `ReviewReport.signal_report_id`/`trigger_source` stamped.
3. Repeat-turn: run a follow-up implementation on the same branch — verify the second turn resumes
   (reuses working state for unchanged head or reviews the new head), publishes only deltas, and
   appends a second `code_review` artefact. **This is the first real exercise of re-review** — log
   the outcome in ARCHITECTURE.md Stage 6.
4. Update ARCHITECTURE.md (Stage 6 → BUILT notes) — the doc's keep-in-sync rule applies.

## 4. Invariants & edge-case checklist (assert during review)

- Receiver never raises into the tasks save path; workflow-start failures are logged, not raised.
- No artefact on gate-skips; exactly one `code_review` artefact per executed turn (completion or
  failure).
- Same-head re-trigger costs ≤ one fetch activity (early-exit), zero sandbox spend.
- `USE_EXISTING` join: no error and no duplicate turn when a trigger fires mid-review.
- Label re-trigger of an inbox PR (dogfood overlap) lands on the same `ReviewReport`; provenance
  is not overwritten.
- Draft PRs are reviewed (agent PRs open as drafts — no draft gate anywhere server-side).
- Fork PRs remain impossible on the inbox path (origin-branch by construction) and rejected on the
  label path (fetch activity).
- Two teams, same repo/PR → independent reports and workflow ids (team id in both).
- `Task.repository` is lowercased on save — use it verbatim; don't re-case.
- Deleting/reingesting the signal report must not break reviews (plain UUID provenance, tolerant
  artefact append).
- CLI/eval runs (`trigger_source="manual"`) stay ungated and never publish unless `--publish`.

## 5. Verification commands

- `pytest products/review_hog/backend` — **run the product's real `backend:test` scope: BOTH
  `backend/tests` and `backend/reviewer/tests`** (a prior regression shipped because only
  `backend/tests` was run — see the 2026-07-02 adversarial-review note in ARCHITECTURE.md).
- `pytest products/signals/backend/test` (artefact registry coverage + API non-writable cases).
- `ruff check products/review_hog products/signals --fix && ruff format products/review_hog products/signals`
- `tach check --dependencies --interfaces`
- `python manage.py makemigrations --check`
- `hogli build:openapi` — the signals artefact serializers surface generated types; expect zero
  unexplained drift beyond the new artefact type.

## 6. Out of scope (this stage)

GitHub webhooks for the inbox path; a shadow-mode flag; a dedicated findings read API/MCP tool
(agents use `execute_sql` + `review_report_id`); non-`signal_report` task origins; Inbox UI
rendering of the `code_review` artefact (maintainer's parallel work — coordinate, don't build);
promo-comment copy + fleet cost controls before non-staff rollout (the per-user default-off switch
is the budget gate; consider a feature flag for fleet-level alpha control); orchestrated
shadow-fix loop (implement → review → fix → publish) — future Temporal-composition work that this
trigger's thin-adapter shape deliberately leaves room for.
