# ReviewHog decisions

Why ReviewHog is shaped the way [ARCHITECTURE.md](./ARCHITECTURE.md) describes it — the trade-offs made and the
alternatives rejected, so a future reader doesn't re-litigate a settled call or re-learn a gotcha the hard way.

**How to use this doc.** The reference (ARCHITECTURE.md) says *what* the code does today; this says *why*. When you
make a change that embodies a real trade-off, append a distilled entry here (the decision, the reason, the rejected
option, any gotcha) — not a worklog entry (no dates, "uncommitted", test counts, or e2e run logs; those belong in the
commit message and `eval/RUN_LOG.md`). Keep entries append-only and roughly grouped by area. If a decision is later
reversed, edit its entry to state the new call and why — don't leave two contradictory entries.

---

## Product placement & data model

**ReviewHog is a top-level peer product, not nested under Signals.** The repo has zero precedent for a product
nested inside another; the exact precedent for "an agentic product that feeds Signals" is `products/replay_vision/`, a
sibling that emits findings through Signals' facade. ReviewHog is the same shape.

**A PR review is not a `SignalReport` — separate parent entities, shared substrate only.** SignalReport's lifecycle
(ClickHouse embeddings → similarity grouping → `total_weight` accrual → promotion gate → autonomy auto-start) answers
"is this worth acting on, and which group does it join?" — a PR answers both by its identity `(repo, pr_number)`.
Modeling reviews as SignalReports would mean faking embeddings/weight, defeating the promotion gate, and polluting the
Status enum.

**Reuse path = "peer + reuse the leaf", not a shared abstract base.** Signals' `artefact_schemas.py` is
dependency-light (pydantic + one tasks-facade DTO), so ReviewHog imports the *content models* (`Commit`,
`CodeReference`, `TaskRunArtefact`, `NoteArtefact`, `ArtefactContentValidationError`, and `ArtefactAttribution` from a
new zero-dep leaf) cheaply and owns its own Django model (`ReviewReport` + `ReviewReportArtefact`). The Django artefact
*model* is the entangled part (funnel + a `tasks.Task` FK); hoisting it into core would invert the dependency
(core→product FK) and force re-parenting migrations. The repo rule is nest-then-promote — don't pre-build shared infra
before a second consumer proves it out. **Gotcha:** the registry *helpers* `artefact_type_for` / `parse_artefact_content`
are **not** reusable — they close over Signals' module-global registry and take no registry argument, so ReviewHog
defines its own ~6-line copies. Only the content models are imported.

**Postgres-first, no object storage.** Structured results (findings, verdicts, rendered report, per-turn diff
snapshots) are JSON/text in `TextField`s — Postgres TOAST compresses/out-of-lines large values and `.defer()` keeps
them off hot reads. Data is moderate (tens–hundreds of KB per turn) and reproducible. Object storage is reserved for a
blob that is both large *and* irreproducible, of which ReviewHog has none.

**The reviewed diff snapshot is persisted per turn, never re-fetched.** A review is a point-in-time judgment: a
finding's line numbers only make sense against the code as of the reviewed commit. Re-fetching later returns the
*current* code, and even re-fetching pinned at `head_sha` isn't durable — a force-push can orphan and GC that commit.
So each turn stores its own snapshot as an append-only `commit` artefact (reusing Signals' `Commit` with one optional,
Signals-neutral `diff` field), gated on the `head_sha` watermark so re-runs are idempotent.

---

## Pipeline shape

**Isolation over reuse: every LLM call is its own fresh sandbox session, specialists run in parallel with no shared
context.** The three perspectives run concurrently per chunk; overlap is absorbed by the downstream dedup, **not** by
chaining passes. The earlier sequential passes and their forward-context plumbing were removed. Higher sandbox count is
the accepted cost of clean isolation and no cross-talk.

**Skills as the customization surface — perspectives, validator, and blind-spots are all DB-synced LLMA skills the
agents pull over MCP.** The bar for "what to look for" and "what matters" is owned by the team, not baked into a prompt;
a team retunes by editing its `LLMSkill` row, no code change. The invariant that makes this safe: **the output schema is
fixed (code — `IssuesReview` / `IssueValidation` / `ChunksList`), only the skill body (logic) is editable**, so a skill
edit can never change the output format the downstream pipeline depends on. Skill *ownership and editing stay
team-level*; only *enablement* is per-user (below).

**The analyze stage was removed entirely.** The reviewer already self-investigates from the diff + the PR intent (its
mandated investigation step), and the chunker's `key_changes` already gives the body its per-chunk narrative — a
separate analysis pass was a redundant, lossy summary costing one sandbox turn per chunk plus tokens injected into every
`perspective × chunk` prompt. It was never needed at any chunk count.

**Blind-spot sweep is its own step (not a fourth perspective), always-on, one per chunk.** It *consumes* the wave's
findings ("what did every lens miss?"), so a perspective-prefix trick would still need an ordering layer while
contorting the multi-enable semantics. It runs on every review including single-chunk PRs, told per-chunk which lenses
already ran. A **separate child workflow for it was rejected as overengineering**: the round shares the review
activity / fan-out / persistence, is conditioned on the wave, and per-activity retries + DB skip-resume already give
child-workflow-grade recovery. The canonical blind-spot skill is deliberately **pure-generic** (no category checklist —
static content is fourth-perspective drift and breaks under per-user perspective customization); its unique power is
being conditioned on the run's actual output.

**Blind-spot findings run under a reserved pass number (`1000`), not `max(wave pass) + 1`.** `max+1` collides with the
persisted `(pass, chunk)` resume keys when the enabled-perspective set changes between executions at the same head — a
newly enabled perspective lands on the stale blind-spot row and is silently skipped, or the sweep lands on an occupied
wave pass and never runs. A fixed reserved pass can never collide with wave enumeration. (This surfaced in adversarial
review; the "obvious" `max+1` is a trap.)

**Perspective selection is a standalone step, fail-open, and may prune a chunk to zero perspectives.** A cheap one-shot
selector runs between loading perspectives and the fan-out so a tiny PR doesn't pay every specialist on every chunk. It
is **not** folded into the chunking LLM (the ≤400-addition deterministic path never reaches the chunker, and the
selection roster is per-user config while `chunk_set` is head-keyed). It **fails open everywhere** — selector error →
dense product with a warning, unknown skills drop, a missing chunk runs everything — because a run must never be failed
or thinned by its own optimizer. Zero perspectives on a chunk is allowed because the always-on blind-spot sweep
guarantees ≥1 pass per chunk (a coverage invariant deterministically ignores any selection that would leave a chunk with
zero units). **Scaling limit (by design):** the sweep runs one sandbox session on *every* chunk, so per-review sandbox
cost is bounded below by the chunk count — selection makes big runs safe and cheaper, not cheap.

**Chunking: a deterministic single-chunk gate + a semantic chunker; metric is additions only.** Below
`SINGLE_CHUNK_GATE_ADDITIONS` (400 reviewable added lines) the gate returns one all-files chunk with no chunking LLM
turn — a pure cost optimization for the common case that gives the same single chunk the LLM would. Above it, the
chunker targets `CHUNK_TARGET_ADDITIONS` (300) / `CHUNK_SOFT_MAX_ADDITIONS` (600) as *prompt guidance only* — there is
**no mechanical size cap** and no cap on chunk count (chunking exists to make a 10k PR as reviewable as a 1k one, not to
bound chunk size; a genuinely atomic concern stays whole even if it runs over). Deletions don't drive chunking (cheaper
to read). Generated files (API types/clients/schemas) are down-weighted by the prompt, not a deterministic filter — a
soft down-weight is inherently the LLM's job. **Reversed call:** the pinned-chunks eval instrument was removed — nothing
experimental ships, only the winners land; a future eval re-derives chunk structure from the archive (and must re-learn
that a pin has to be checked *before* the persisted-chunk-set resume, or a stale set silently voids it).

**Chunking and dedup run as one-shot direct-LLM-gateway calls within size gates.** Both are pure text tasks (their
prompts carry everything inline), so within `CHUNKING_ONESHOT_MAX_ADDITIONS` / `DEDUP_ONESHOT_MAX_FINDINGS` they skip
the sandbox — removing ~55s provisioning per stage on the serial critical path and killing the sandbox-provisioning and
chunking-schema failure classes structurally (via structured outputs). Above a gate the stage takes the sandbox path
with the *same* prompt, pinned to the *same* model, so the delivery path never changes which model judges the stage.
Dedup also feeds prior turns' findings + verdicts into its pre-filter, so a re-found dismissed/below-threshold problem
dies at dedup instead of burning another validation turn.

**Dedup is aggressive + uniform.** It collapses hard (fewer, useful findings is the goal) but privileges/excludes no
reviewer — the deterministic positional gate is author-blind, there is no hardcoded competing-bot handle and no
ours-vs-theirs branching. Every prior inline comment (bot, human, ReviewHog's own) is fed in uniformly; the LLM *uses*
the author only as a bot-vs-human signal (a code-review bot's comment is usually a formal finding, a human's may be a
nit/question). The anchor is **same concrete problem, not bare co-location** — a finding near an unrelated comment is
kept; genuine same-problem findings collapse to the single most comprehensive one.

**Validation is a warm multi-turn session per chunk (one verdict per turn), resume-aware.** Checkout/boot is paid once
per chunk instead of once per issue; each issue keeps its own independent judgment (not the old "neutered" all-issues-in-
one-output batch). `load_run_validations` splits done/pending so a retry re-researches only unjudged issues. **A failed
turn fails the activity so Temporal retries it** (cheap by design — skip-resume re-validates only the survivors on a
fresh session); only the *final* attempt degrades to skipping the wedged issue, so one persistently failing issue can't
sink the chunk. Session-OPEN failure raises on every attempt (the outage signal the failure floor counts).

**The validator can override a finding's priority (`adjusted_priority`, validator-wins), not just keep/drop.** It does
the deepest per-issue investigation, so it gets a middle gear between "keep at the reviewer's level" and "kill" — raise
when impact is worse than flagged, lower to `consider` to soft-suppress a real-but-minor finding rather than dismissing
it. Resolved at read time by `effective_priority(base, adjusted)`, used at *every* gate and every displayed priority so
gating and display never disagree. The keep/drop bar stays the team-owned criteria skill; this is just the I/O contract.

**Off-diff valid findings are surfaced in a review-body section, never silently dropped.** A valid `must/should-fix`
finding on a changed file but an *unchanged* line survives scope-cleaning but has no diff line to anchor an inline
comment. It goes into an "Other findings (outside the changed lines)" body section — **not** a nearest-changed-line
inline snap (mis-anchored comments are noise) and not a per-finding general comment. Publish posts the body whenever ≥1
valid publishable finding exists, even if zero inline comments resolve.

**Findings cross Temporal stage boundaries by reference (ids only), never by value.** The full post-review issue list
would otherwise cross five payload boundaries unbounded and hit Temporal's ~2 MiB cap (`PayloadSizeError`) on a large
PR, after all sandbox spend. Every activity reloads its inputs from the persisted `pr_snapshot` / finding rows by
`(report_id, head_sha)`; only `report_id` + `head_sha` + small key/JSON slices cross. Combine + scope-clean were folded
into the dedup activity (consecutive, both DB-local) to avoid a by-value return.

**Codex (`gpt-5.5` @ `xhigh`) runs the perspective review; Claude validates.** GPT-5.5 Codex is markedly stronger at
*finding* issues, so the finder runs on Codex while chunking, dedup, and the validator stay on Claude (its calibration is
the current keep/drop baseline). Scope is the perspective review *only* — the most important stage for surfacing issues.
**Gotcha — headless Codex needs `initial_permission_mode="full-access"`.** Codex's default `"auto"` mode auto-approves
only `read/search/fetch/think`, **not** `mcp_tool_call` — and the review pulls its perspective skills over MCP
(`skill-get`), so under `"auto"` every fresh sandbox parks on an approval prompt no headless run can answer, and the
workflow fails. Any future headless Codex stage must also pass `"full-access"`.

**`MAX_CONCURRENT_SANDBOXES` is a per-review, per-stage fan-out cap — not a global team throttle.** It's a fresh
`asyncio.Semaphore` constructed inside each child workflow's `run()`, so it bounds one review's per-stage fan-out per
execution; two concurrent reviews get their own. The true global ceiling is the tasks-queue worker's concurrency + Modal's
account limit, where the sandbox `ProcessTaskWorkflow`s actually run. The per-review cap is kept as a fairness /
blast-radius control (the tasks worker is shared with all other reviews and Tasks-product work) — size it right, don't
remove it.

---

## Skill customization (team vs user)

**Skill ownership and editing stay team-level; perspective *enablement* is per-user.** There is no per-user skill
ownership anywhere in the codebase (`LLMSkill` is `(team, name, version)`-scoped; `created_by` is audit-only), and
Signals' "custom scouts" are themselves team-scoped — per-user ownership would be net-new infrastructure with no
precedent. So a team edits the shared canonical-named row in place (the sync leaves a diverged row alone), and *which*
perspectives run on a PR is per-user via `ReviewSkillConfig` (mirroring Signals' `SignalScoutConfig`, minus the
scheduling fields — ReviewHog is PR-triggered, not scheduled).

**Perspectives are multi-enable (min-1 floor); the validator and blind-spots are single-active per user.** A review
runs many perspectives but exactly one validator (the bar for "does this matter") and one blind-spot sweep. Single-active
is an **app-code invariant, not a DB constraint** — a partial unique index was ruled overengineering for a borderline
single-user race; the loader raises loudly if the invariant is ever violated. All three kinds share one `ReviewSkillConfig`
table, discriminated by skill-name prefix (`review-hog-perspective-*` / `-validation-*` / `-blind-spots-*`) — so
shared-table queries must be prefix-scoped or a validator row gets loaded as a perspective (guarded by regression tests).

**A dangling enabled config (skill archived after being enabled) soft-skips; it does not fail the run.** This reverses an
earlier "enabled-but-missing-skill ⇒ raise" call: archiving a skill from the general Skills UI was a permanent,
non-self-healing outage (tombstone never recreated, loader raised, workflow died forever). Now perspectives warn-and-skip
dead names (raise only when *nothing* resolves), validator/blind-spots fall back to the canonical, and the sync
*resurrects* an all-dead canonical instead of tombstoning it. The config toggle is the one opt-out lever; skill deletion
is not a signal.

**Custom-skill menu visibility is per-user (canonical, or you authored it); the Skills page stays all-team.** A skill is
visible in the three Code-review config menus iff its name is canonical *or* its earliest live version's `created_by` is
you — so one teammate's custom no longer clutters everyone's menu. `partial_update` 404s on a non-visible skill exactly
like a missing one (a distinct error would leak that the name exists). This is a clutter fix, not confidentiality: bodies
stay team-readable on `/skills`, and teammates can still edit each other's customs (accepted). "Adopt a teammate's skill"
is now duplicate-under-a-new-name, not enable-by-name.

**Chunking stays one unified logic — never a per-user or editable skill.** Chunk ids are a structural invariant: chunking
runs once per PR, shared by every perspective and the validator, and the id is baked into finding identity
(`{pass}-{chunk}-{issue}`) and the persistence key. A divergent chunk set silently orphans findings and drops validations.
If team customization is ever truly needed, promote chunking to a *team-wide* versioned skill — never per-user.

**Stamp `source_perspective` at review time, not in `combine_issues`.** `review_chunk_activity` sets it from the skill
that actually ran (round-tripped through the `perspective_result`), so combine only re-stamps the `issue.id` and
`PerspectiveType` is demoted to the canonical-seed list. This is immune to a mid-run config change and needs no
`pass_number → skill_name` map threaded into combine. `pass_number` survives only as a compact per-run index inside the
hyphen-split `issue.id` (the long skill name can't live there).

---

## Triggers & publish

**Production trigger is "Action calls the app" (a thin GitHub Action → a PostHog endpoint → Temporal), not CI.**
ReviewHog is app-embedded (Temporal + Modal sandbox + Postgres + DB-synced skills), so it *cannot* run on a GitHub
Actions runner the way Stamphog does. The label Action carries one secret and does no GitHub I/O; the workflow fetches +
publishes server-side via the App installation token. **Rejected:** Path B (label → the existing webhook dispatcher → no
CI — diverges from the team's Stamphog model) and Path C (re-platform as a standalone CI script — discards the whole
Temporal pipeline).

**Trigger auth is a plain shared secret, not a project API key.** The endpoint compares the `Authorization` header to
`settings.REVIEWHOG_TRIGGER_TOKEN` — exactly how the GitHub webhook endpoint is gated. A PSAK + a new scope is
over-engineered for a single-team dogfood; graduate to PSAK only if this becomes a multi-caller service needing per-key
rotation / throttles / audit.

**GitHub identity is the existing App installation token — no dedicated ReviewHog GitHub App.** Validated that the
installation token can post reviews (`pull_requests: write`), resolved server-side via `first_for_team_repository(...)
.get_access_token()`, never a CI secret. The run `user_id` is resolved server-side too (the team integration's creator,
or `REVIEWHOG_RUN_USER_ID`) — the sandbox fan-out needs a real PostHog user; the CI caller never carries one.

**Publish control is a per-run `publish: bool` input, not a global flag.** It replaced the global
`PUBLISH_REVIEW_ENABLED` constant: the trigger sets `publish=true`, the eval CLI sets `false`. No team-wide flag, no
feature flag — "real run posts / eval run doesn't" is cleanly per-request, and the trigger endpoint is the durable
reusable interface (the label Action is just its first client).

**The UI trigger is a separate, session-authed endpoint from the shared-secret CI one.** The two callers have different
auth and scope rules, so they don't share an endpoint. The UI trigger always publishes (it's label-path parity for repos
the label can't reach), the **requester wins** (the acting user is the requesting PostHog user — their perspectives /
validator / threshold drive the run), and repo scope = **installation access** (`first_for_team_repository`), not a
hardcoded org list. Unlike the label endpoint's "no GitHub I/O" principle, the UI does a **synchronous** PR-meta fetch —
it has no upstream Action gates, so a silent async failure would leave the user staring at nothing.

**The inbox trigger is a `TaskRun` `post_save` receiver that fires on the output-recording save, not on completion.**
Successful implementation runs deliberately stay `in_progress` forever (they babysit CI + review threads), so "when the
run completes" is a lifecycle event that never happens — the receiver fires on the save that records `output.pr_url` (PR
leg, publishes) or `output.head_branch` (branch leg, stores only). A receiver (not a call from Tasks) keeps every edge in
the existing direction (review_hog → tasks/signals) with zero tasks changes and no webhook dependency. **Gotcha —
`TaskRun.branch` (the FIELD) is banned as a target**: it holds the *base* branch the agent started from, never the pushed
head; only `output.head_branch` (agent-server-synced) is trustworthy. Keep the receiver import-light (types + client
only, never workflow/activity imports) or it blows the Django startup-import budget.

**The Signals-side record of a review is pointer-first.** The `code_review` artefact carries
`{review_report_id, repository, head_sha, pr_url?, review_url?, outcome, counts}` — enough for an agent to SQL-join and
go look, no digest/summary duplication. **Rejected merging the two artefact tables:** different parents/identity (label
reviews have no SignalReport), ReviewHog's working-state rows are MB-scale resume substrate (not activity-log content),
and Signals artefacts are user-mutable while ReviewHog's are resume-correctness substrate that must not be.

**Pushes no longer re-trigger a review (`synchronize` dropped, ADR 0002); re-review = re-add the label.** And a stale
re-trigger at an already-published head is a no-op: the early-exit gate keys on `published_head_sha == head_sha` — a
deliberately precise key that can't skip an incomplete review, a not-yet-published turn, or a moved head. New comments at
an unchanged head currently do **nothing** (logged only) — the right scope while ReviewHog only *reviews*; it flips once
the action plane lands (a human reply should advance a turn to respond/fix), which is why the gate already surfaces
`new_comment_count`.

**The `head_sha` checkout pin is deferred (conditional).** Pinning the sandbox checkout to the reviewed commit (instead
of the moving branch tip) makes "reviewed == recorded" exact, but it crosses the isolated `products/tasks` facade (model
+ migration) and has no user-facing effect while publish is gated per-run and the injected change-set is the
authoritative record. It lands as its own tasks-owned change only if resume-correctness, the loop, or re-enabling publish
actually needs it. Until then branch-tip drift stays the same rare edge case as before.

---

## The loop (designed, not built)

A single review turn is the current pipeline. The **loop** wraps it so a PR review becomes a living, multi-turn process
(re-check on new commits/comments, converge, and eventually implement fixes). The living `ReviewReport` (unique per PR,
with `run_count` / watermarks / head-scoped resume) is already the loop's memory; the design below is settled but unbuilt.

**Topology = event-driven re-trigger (Variant B) first, per-PR singleton (Variant A) later.** B keeps the workflow
short-lived: each trigger `start_workflow`s the deterministic per-PR id (`ALLOW_DUPLICATE`), the durable `ReviewReport` is
the only long-lived state, and each "wait" is a webhook gap (more restart-robust than a live wait). It reuses today's
idempotent, resumable workflow as-is with none of the `continue_as_new` traps. Promote to A (a long-lived
`while True` singleton with `@workflow.query` / `@workflow.signal`) only when live control — talk-to-it, pause,
inject-context mid-turn — is genuinely the ask; A is a clean copy of Signals' `buffer.py` / `grouping_v2.py` when we get
there. This is the doc's own nest-then-promote rule.

**Cross-turn finding identity is NOT a "stable key" problem.** The feared duplicate (a prior turn's finding re-posted)
was a publish-accumulation bug, already fixed by a `run_index`-prefixed `issue_key` + turn-scoped
`load_valid_findings`. That key is a unique *occurrence* id, and need not be a cross-turn problem identity. The only thing
needing cross-turn matching is resolve/update of our own comment — and that is the **dedup LLM's existing "same concrete
problem?" judgment**, persisted alongside the GitHub comment id. A normalized title/body signature or content hash is the
*wrong* tool — brittle to re-phrasing and line drift.

**Router = copy-and-own Stamphog's pure gate logic, inverted.** Re-vendor `gates.py`'s deterministic detection into
`products/review_hog/` (the repo's no-cross-import-from-`tools/` norm says copy, not import) and **invert its semantics**:
where Stamphog *denies* a risk category to force human review, ReviewHog *enables* the matching specialist perspective.
Reuse the detection, drop the deny→skip routing. Thresholds were calibrated for "safe to rubber-stamp", so expect
re-tuning for "how much review".

**Action plane = suggestion blocks (C) first, delegate to the Tasks engine (A) next, skip a ReviewHog write sandbox
(B).** C (a one-click GitHub suggestion inside the comment ReviewHog already posts) is inert until a human clicks, so it's
prod-usable the moment publish flips and it forces the cross-turn lifecycle prerequisite to land. A (build an implement
prompt → create a Tasks `Task` with `create_pr=True` → companion PR) reuses Tasks' *verified* edit→commit→push→open-PR
engine and its installation-token authorship mode, never force-pushing the author's branch. B (a ReviewHog-owned write
sandbox) re-derives all of that at large effort — skip unless cross-product coupling to Tasks proves unacceptable.

---

## Reversed calls & things tried and dropped

Kept so they're not re-proposed:

**Warm per-perspective review session — built, evaluated, not adopted.** Running one warm session per perspective
(walking chunks as turns) mechanically works and cuts sandbox count, but anchoring replicated in both eval runs — later
chunk-turns went near-silent (2–3 valid vs 4–6 for isolated sandboxes at equal tokens). Intentionally not adopted;
revisit only with an explicit anti-anchoring device and a re-eval against the archived yardstick.

**`sync_review_hog_skills` management command — deleted as redundant.** The run-path cold-start sync (`prune=True`) is the
one sync moment; a standalone command duplicated it.

**A schema migration to persist a build-time publish threshold — reverted as disproportionate** for a manual, local-only
ops tool. The standalone `publish_review` command instead always publishes at `DEFAULT_URGENCY_THRESHOLD` — deterministic,
no per-run tracking, small residual accepted (a run built at a non-default threshold and republished manually gates on the
default). The production workflow path has no such gap (it snapshots one threshold to both build + publish).

**Serializer lost-update guards (`update_fields` override, `select_for_update`) — reverted as overengineering** for
3-field, self-scoped config rows with a borderline single-user race. The loader/viewset app-level checks are the backstop;
a wrong review fails loudly rather than being produced.

**The full-detail `ARCHITECTURE_DIAGRAM.mmd` was deleted deliberately** — every attempt to keep it readable and current
failed. The one compact flowchart in ARCHITECTURE.md is the only diagram; don't recreate the big one.

---

## Verification lessons

**Verify against the product's `backend:test` script, not a hand-picked path.** `products/review_hog` has tests in
*both* `backend/tests/` and `backend/reviewer/tests/`; running only the former looks green while silently skipping the
latter — this let a real regression (unupdated call sites after a required-param change) through until an adversarial
reviewer ran the real script.

**Point the review-quality eval at a frozen PR.** Findings are a judgment over one specific commit, so quality is only
comparable across runs that reviewed the **same** `head_sha`; if the PR moves between runs the comparison is confounded
(it happened). The `head_sha` checkout pin would make any PR reproducible, but until then a stale branch is the stopgap.
`eval/RUN_LOG.md` is the agent-maintained per-run log.
