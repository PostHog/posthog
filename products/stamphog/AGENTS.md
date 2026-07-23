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

## Supersession and terminal states

A newer relevant delivery supersedes older non-terminal runs. Rules that keep this sound:

- Terminal states (`TERMINAL_STATUSES` in `facade/enums.py`) are never rewritten — `mark_review_failed`
  must not clobber a delivered outcome, and terminal saves are conditional
  (`.exclude(status=SUPERSEDED).update(...)`), never plain `save()`.
- `post_verdict` guards before ANY GitHub write: superseded status, current head vs run head, and
  a last fresh status read. Losing the final conditional update means dismiss-your-own-approval,
  not "log and return".
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
- The raw-Anthropic fallback is for the Action runtime only; hosted runs fail closed without a
  gateway. No `ANTHROPIC_API_KEY` may enter the sandbox environment.
- Egress is an explicit domain allowlist (`_sandbox_egress_allowlist`). Additions go through
  `STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS`, not code edits.
- Everything posted to GitHub goes through `_scrub_credentials` AND `_neutralize_active_markdown`
  (GitHub's camo proxy auto-fetches images — a markdown image URL is an exfiltration channel).

## Trust boundaries

- Review policy is read from the repo's **default branch**, never the PR head — a PR must not be
  able to rewrite the policy that gates it. Same for the `digest:` channel declaration.
- A manually-created repo config (blank `installation_id`) binds **disabled** when a sync adopts
  it: its flags were set by someone who never proved GitHub access. Reinstall rebinds keep
  settings — those were configured under a verified binding.
- Name-matched Slack digest channels provision **disabled** pending a human enable (a workspace
  member can squat a channel named like a team slug). Only repo-declared channels auto-enable.
- PR content — title, body, diff, comments, reactions — is untrusted input everywhere, including
  in reviewer prompts and error messages persisted to API-readable fields (`run.error` keeps only
  a truncated first line for exactly this reason).

## Engine parity (tools/pr-approval-agent)

`review_local.py` (hosted) must mirror `review_pr.py` (Action) semantics wherever both apply:
gate order, review filtering (bare COMMENTED reviews dropped, non-empty ones kept), in-flight
bot-reviewer WAIT behavior (`TRUSTED_REACTOR_BOTS` mirrored in `temporal/constants.py`), and
ownership summaries (individual owners count, not just teams). When you change one runtime,
check the other; divergence here has produced real approve-when-should-wait findings.

## Temporal specifics

- Registering a new activity requires adding it to `temporal/registry.py` — the
  registry-completeness test guards this, don't bypass it.
- Workflow bodies follow the repo-wide determinism rules (`workflow.patched()` for new commands).
- Activity payloads stay small; large context rides in `run.output`, not through the workflow.

## Tests

`hogli test products/stamphog/backend/tests/` (Django; `--reuse-db` after the first run) plus
`tools/pr-approval-agent/` tests for engine changes. The integration tests drive the full chain
through fakes (`tests/fakes.py`, `tests/conftest.py`) — extend the fakes rather than mocking
internals, and prefer adding a parameterized case to an existing test over a new function.
