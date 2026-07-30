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
  retry) dismisses its own orphan (`_dismiss_orphaned_approval`).
- The sweep in [`logic/approvals.py`](backend/logic/approvals.py) keys off `posted_review_id`
  alone — filtering on a saved verdict would miss crashed runs' orphans.

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
