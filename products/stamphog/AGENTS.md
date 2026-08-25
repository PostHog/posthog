# stamphog — invariants for agents

Read [README.md](README.md) for the product shape first. This file is the contract: the
invariants below were each earned through a real review finding — do not relax one without
understanding what it closes, and hold new code to all of them.

## The stale-approval invariant (the big one)

**No stamphog approval may remain standing over commits it didn't review.** GitHub never
auto-dismisses approvals, so every path that skips, supersedes, or abandons a review after a
head-changing event must retract standing approvals itself:

- The workflow runs `dismiss_stale_approvals` FIRST, and it voids EVERY standing approval —
  same-head included, since a re-review means fresh judgment is pending (fail-closed: if any
  later step crashes, the prior approval is already gone). The sweep's same-head exclusion is
  only for skip paths, where no new verdict is coming. A base retarget gets its own explicit
  all-heads retraction — it changes the diff without moving the head.
- Every Celery skip path that never reaches the workflow (trigger-label absent, author below
  write permission, untrusted association, disabled repo) retracts via
  `_retract_stale_approvals_on_skip`.
- `post_verdict` persists `posted_review_id` the moment GitHub accepts the review, and any path
  that abandons the run _after_ posting (lost terminal save, superseded/head-moved guards on
  retry) dismisses its own orphan (`_dismiss_orphaned_approval`). Before posting it also
  ADOPTS-then-persists: if this App already has an active APPROVE pinned to exactly `run.head_sha`
  on GitHub (a prior attempt that posted, then crashed before the immediate persist), it takes that
  review's id instead of stacking a second approval the DB-keyed sweep could never see.
- The sweep in [`logic/approvals.py`](backend/logic/approvals.py) keys off `posted_review_id`
  alone — filtering on a saved verdict would miss crashed runs' orphans.
- `dismiss_stale_approvals` also runs a GitHub-side belt-and-braces sweep after the DB sweep: it
  lists this App's still-active APPROVED reviews and dismisses every one regardless of head, catching
  an orphan that has no `ReviewRun` row at all (the DB sweep is blind to it). Both write-adjacent
  paths (this sweep and `post_verdict`'s adopt) identify "ours" via the exact `<slug>[bot]` login and
  do NOTHING when `STAMPHOG_GITHUB_APP_SLUG` is unset — a fuzzy "any Bot" match must never dismiss or
  adopt another bot's review.
- A run that reaches a **non-approve terminal** (`post_verdict`'s gated/refused/escalate/wait branch,
  or `mark_review_failed`) re-runs the GitHub-side own-approvals sweep at its own end
  (`_sweep_orphan_approvals_at_terminal`). This closes the supersession race: an older run can clear
  `post_verdict`'s final guards, get superseded, then land its GitHub approval AFTER the newer run's
  STARTUP sweep — and if the newer run refuses (or fails), nothing lists our approvals again, so the
  orphan stands over a refusing verdict. The keep-set excludes every OTHER live run's persisted
  `posted_review_id` (writer-pinned read), so a slow run at terminal never dismisses a newer run's
  legit approval. UNLIKE the fail-closed startup sweep, the terminal sweep is fail-open: a GitHub error
  must not block the terminal save (the integrity gap on error is the pre-existing exposure, no worse).

The one deliberate exception is **approval retention**.
A head-changing delivery whose push left the PR's own diff byte-identical skips both the retraction and the review (`_standing_approval_retention` in the Celery task, deciding through [`logic/approval_retention.py`](backend/logic/approval_retention.py)).
It is content-based rather than commit-based: the PR's own unified diff at the approved head against the same at the current head.
So a merge of the base branch that touches none of the PR's files retains, and a merge that resolves a conflict inside one of them re-reviews.
Comparing the diff text rather than per-file blob shas is deliberate, because the text carries file modes and renames, and a blob sha covers contents only.
The one thing the text does not carry is binary content, which git renders as `Binary files ... differ` over an abbreviated blob id, so a diff mentioning one is refused rather than compared.

There is deliberately no "this file is harmless" rule, and adding one back needs a very good argument.
Successive review passes found every candidate wrong in this repository: lockfiles select the dependency code that gets installed, tests run in CI with CI's credentials, a file under a `generated/` directory can be hand-edited and still compiles into a service, `docs/onboarding` is aliased into the production frontend, MDX compiles to JavaScript, snapshot files are JavaScript modules the test runner executes, and even plain Markdown ships, because `services/mcp` imports `.md` templates and product `tools.yaml` files compile `.md` prompts into shipped tool definitions.

Both sides are read with `compare_diff`, from the base and head shas the run and the payload already fixed.
That is load-bearing rather than incidental: `get_pr_files` answers for whichever head is live when the request runs, so a contributor could push the approved content, let the comparison run, and push the unreviewed head back.
Retention must never consult that endpoint.

Everything ambiguous falls through to the normal path, which dismisses first: no standing approval, an approval already at this head, a run with no recorded base sha, an empty diff on either side, a diff describing a binary change, or any GitHub error, a diff too large for GitHub to render included.
Retention also re-checks GitHub that the stored approval is still active, because a maintainer dismissing it by hand updates nothing in the product DB, and skipping the review over a dismissed approval would leave the PR with neither.
A retained head is recorded on the approving run (`retained_head_shas`), because `_record_merged_pull_request` matches an approving run on `head_sha` alone and would otherwise treat every retained merge as unapproved and drop it from the digest for good.
Self-driving inbox runs are excluded so the carve-out's head pinning stays untouched.

## Supersession and terminal states

A newer relevant delivery supersedes older non-terminal runs. Rules that keep this sound:

- Terminal states (`TERMINAL_STATUSES` in `facade/enums.py`) are never rewritten — `mark_review_failed`
  must not clobber a delivered outcome, and terminal saves are conditional
  (`.exclude(status=SUPERSEDED).update(...)`), never plain `save()`.
- `post_verdict` guards before ANY GitHub write: superseded status, current head vs run head, current base (ref and SHA) vs the reviewed one (a retarget, or a parent branch moving under a stacked PR, rewrites the diff with the head unchanged, and the retarget delivery can trail the activity), and a last fresh status read.
  Losing the final conditional update means dismiss-your-own-approval, not "log and return".
- Out-of-order webhook deliveries are dropped by the `payload_updated_at` clock — checked before
  the transaction AND re-checked under the row lock, and the descriptive-field refresh is gated on
  the same clock inside the UPDATE's WHERE clause.

## Reader-lag: pin decision reads to the writer

The product DB has replicas. **Any read that gates a side effect (GitHub write, Slack post,
supersession, run creation) must be pinned via `.using(router.db_for_write(Model))`** — a lagged
reader silently skips retractions, resurrects disabled channels, or strands queued runs. If you
add a read-then-act path, pin it; this class of bug has been found on five separate paths.

## Sandbox credentials and egress

- The sandbox holds NO long-lived secret. `_mint_reviewer_gateway_token` mints a per-run OAuth
  token under the repo's connecting user with exactly `["llm_gateway:read", "internal_run:read"]`
  and `include_internal_scopes=False`. Never switch to `include_internal_scopes=True` — that
  drags `task:write` into a sandbox running an LLM over untrusted PR content. The
  `internal_run:read` marker is what satisfies the gateway route's `requires_server_credential`.
- The raw-Anthropic fallback exists for a local `review_pr.py` run only; hosted runs fail closed
  without a gateway. No `ANTHROPIC_API_KEY` may enter the sandbox environment.
- Egress is an explicit domain allowlist (`_sandbox_egress_allowlist`). Additions go through
  `STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS`, not code edits.
- Everything posted to GitHub goes through `_scrub_credentials` AND `_neutralize_active_markdown`
  (GitHub's camo proxy auto-fetches images — a markdown image URL is an exfiltration channel).
- The sandbox checkout is the PR head, so the engine's Agent SDK session runs with `setting_sources=[]` + `strict_mcp_config` (reviewer.py): a PR-shipped `.claude/settings.json` hook, `CLAUDE.md`, or `.mcp.json` is readable as untrusted content, never loaded as configuration.
  Don't reintroduce filesystem settings discovery there.

## The self-driving inbox carve-out (the one exception to the bot-author refusal)

Bot-authored PRs are refused at every layer — the webhook pre-filter (`_review_skip_reason`) and
the engine (`review_pr.py::_refuse_bot_author`, called by `review_local.py`) — with ONE deliberate
exception: a PR **positively linked** to a
self-driving Inbox implementation run (a signal-report-carrying TaskRun at
`ai_stage="implementation"`, matched through the tasks facade), one of whose assigned reviewers
opted in via ReviewHog's per-user `stamphog_review_inbox_prs` toggle. Rules that keep the exception
narrow:

- Identification is **server-attested task linkage plus server-attested PR identity** — both
  required, neither trusted alone. The task link is unforgeable by construction: signals'
  auto_start generates the head branch name (`posthog-self-driving/<slug>-<hex>`) before the
  agent runs and stamps it into PATCH-protected run state (`state.self_driving_head_branch`),
  and `find_signal_implementation_run` matches the PR's GitHub-attested head ref against that
  stamp — never against the API-writable `output.pr_url` / `output.head_branch`. The identity
  half, `_is_self_driving_pr`, requires two facts only GitHub attests — the PR is authored
  by this instance's PostHog GitHub App machine user (`<GITHUB_APP_SLUG>[bot]`) on a repo-native head
  (never a fork) — enforced on **both** the receiver leg (`process_inbox_pr_review`) and the
  webhook leg (`_inbox_rereview_carve_out`), failing closed when the App slug is unconfigured.
  The fork exclusion is load-bearing for the linkage too: a head ref is only GitHub's word when
  the head lives in the base repo. This is a positive App-identity match, not the general "any
  bot" rule: `github.py::is_bot_author` must not be weakened, and dependabot / renovate /
  posthog-bot / any foreign App fail it.
- **What a malicious teammate can still do, and what they can't.** Rewriting `output.pr_url`,
  `TaskRun.branch`, `Task.repository`, or `suggested_reviewers` no longer aims the carve-out at a
  different PR: matching reads none of them, and the stamped branch plus `ai_stage` and
  `signal_report_id` are not PATCHable. What remains team-internal and accepted: an opted-in
  assigned reviewer's existence is still the gate (see the reviewer-authorization discussion on
  PR #72680), and a teammate who can edit the _report_ before auto-start still influences what
  the implementation agent builds — that is the product working as designed, reviewed as any PR.
- The engine flag (`self_driving_review` in the hosted context JSON →
  `Pipeline(self_driving=...)`) defaults closed, so a local `review_pr.py` run never turns it on.
  It relaxes exactly two gates — the bot-author
  refusal and the draft prerequisite (the verdict must exist at Inbox triage time, while the
  PR is still a draft) — and swaps human-author trust context for a TRUSTED provenance block
  in the prompt. The hosted server sets the flag exclusively from the run's persisted inbox
  provenance (`ReviewRun.output["inbox_review"]`), which only the two linkage-verified
  trigger paths stamp.
- The initial review is the receiver leg (`process_inbox_pr_review`, entered via the
  `queue_inbox_pr_review` facade after review_hog checked the toggles); the webhook leg
  re-reviews only on synchronize / reopen / base retarget, re-checking them through the
  `facade/inbox_hooks.py` resolver (registered by review_hog at app-ready — a direct import
  of review_hog would be a dependency cycle). No registered resolver means fail-closed: no
  re-review. The gate is **any** assigned reviewer's opt-in, and both legs must resolve it
  identically: if one fired while the other saw "opted out", a push would retract a standing
  approval with somebody still opted in.
- Dismissal is never preference-gated. Every toggle switched off mid-PR stops new runs, but the
  skip paths' head-changing retraction still voids the standing approval (the stale-approval
  invariant above is untouched), and every carved-out run still enters the workflow through
  `dismiss_stale_approvals` first.
- These runs bypass the review-mode and author-write-permission gates: the reviewers' toggle is
  the gate, and the App's machine user is not a collaborator (the permission lookup would always
  deny). `review_mode` keeps governing human PRs only.
- A refused or escalated verdict hands the PR to ReviewHog (`post_verdict` adds the `reviewhog`
  label) **only** for these runs. A human author reads their own refusal and decides what comes next.
  A self-driving PR has no such author, and its refusal otherwise sits unread until Inbox triage.
  In ALL mode an unconditional handoff also fires a second bot review on every PR the repo opens.
  The condition is the derived `ReviewTrigger`, not the raw provenance flag, so it stays aligned with
  what the reviewer prompt was told about its own invocation.

## Trust boundaries

- Review policy is read from the repo's **default branch**, never the PR head — a PR must not be
  able to rewrite the policy that gates it. Same for the `digest:` channel declaration and the
  root `owners.yaml` team registry the digest routes through.
- A manually-created repo config (blank `installation_id`) binds **disabled** when a sync adopts
  it: its flags were set by someone who never proved GitHub access. Reinstall rebinds keep
  settings — those were configured under a verified binding.
- Digest routing is derived every run from the repositories and never stored, so nothing here can
  go stale silently — and nothing degrades either. A registry that cannot be read stops the whole
  team's run (`RoutingUnavailable`) rather than falling through to derived channel names: the
  unreadable repo could be the one every other repo inherits from. A repo that is permanently
  broken gets switched off, which drops it from the candidate list.
- A name match binds an audience to a Slack channel nobody chose for it, so the shared-channel
  guard stays on for it and for registry entries alike — that is the only path where a digest
  leaves the workspace. Only the repo's own `digest:` channel skips the guard, because the
  `owners.yaml` registry can name a channel for a team the declaring repo does not own.
- The app is not a member of a channel it only matched by name, so `post_digest` joins on
  `not_in_channel` and retries the post once. The join is attempted, never gated on the scope:
  `conversations.join` needs `channels:join`, and whether an install granted it is invisible to the
  person who set the digest up, so asking Slack is the only way to find out. A refused join fails
  the run with an error naming the invite, which is a signal in the digests scene and self-heals the
  moment somebody adds the app.
- A declared channel that does not resolve is a dead end, never a retry with the audience slug —
  the slug is the wrong name the declaration exists to correct.
- PR content — title, body, diff, comments, reactions — is untrusted input everywhere, including
  in reviewer prompts and error messages persisted to API-readable fields (`run.error` keeps only
  a truncated first line for exactly this reason).

## Engine parity (packages/pr-approval-agent)

`review_local.py` is the entrypoint the sandbox runs. It drives `review_pr.Pipeline`'s own steps, so
gate order, review filtering (bare COMMENTED reviews dropped, non-empty ones kept), in-flight
bot-reviewer WAIT behavior (`TRUSTED_REACTOR_BOTS` mirrored in `temporal/constants.py`), and
ownership summaries (individual owners count, not just teams) all come from shared code. `review_pr.py`
remains as the manual entrypoint for reviewing a PR from a local checkout; changing a `Pipeline` method
changes both, and divergence here has produced real approve-when-should-wait findings.

Inputs `review_pr.py` fetches over the network reach the sandbox through the context JSON instead, and
dropping one is a silent behavior change rather than a missing section. `author_team_slugs` feeds
`author_on_owning_team`, which the reviewer prompt reads with a default of `True`, so an unset key
tells the reviewer that every author owns the code they touched. `pr_provenance` needs no token and
is computed in the sandbox from the checkout.

A pending `Migration risk` check returns WAIT rather than falling through to a refusal, because a
refusal costs a trigger-label strip, and a ReviewHog handoff on a self-driving PR, over what is a
race with CI. It can't reuse `Pipeline._only_pending_migration_check`: that method disqualifies on
any failing gate other than the deny-list, and a migrations deny always drags the tier gate to
T2-never with it, so it answers False for every PR it exists to catch.

## Temporal specifics

- Registering a new activity requires adding it to `temporal/registry.py` — the
  registry-completeness test guards this, don't bypass it.
- Workflow bodies follow the repo-wide determinism rules (`workflow.patched()` for new commands).
- Activity payloads stay small; large context rides in `run.output`, not through the workflow.

## Tests

`hogli test products/stamphog/backend/tests/` (Django; `--reuse-db` after the first run) plus
`packages/pr-approval-agent/` tests for engine changes. The integration tests drive the full chain
through fakes (`tests/fakes.py`, `tests/conftest.py`) — extend the fakes rather than mocking
internals, and prefer adding a parameterized case to an existing test over a new function.
