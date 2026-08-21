# PR approval agent

AI-assisted PR approval for PostHog.
Deterministic safety gates first, then Claude reviews for showstoppers.

> [!NOTE]
> This directory (together with `.stamphog/`) is vendored into other repos — e.g. [MLHog](https://github.com/PostHog/MLHog/tree/master/tools/pr-approval-agent) — each documenting its intentional local changes in its own copy of this README. Vendored copies live at `tools/pr-approval-agent/` with `tools/owners` beside them, which is also where this repo's review sandbox writes the engine; only the source of truth sits here. When you change the engine or policy format here, those copies stay stale until someone re-syncs them, so give the owning teams a heads-up (or re-sync yourself: diff, re-copy, re-apply their documented local changes).
> A policy that declares a `hogli-resolver` ownership source additionally needs the sibling `tools/owners` package vendored.
> The legacy `gh-codeowners` / `ph-product` ownership formats were removed together with the `CODEOWNERS-soft` migration, so a vendored copy whose policy still declares them must migrate to `hogli-resolver` (adopting `owners.yaml` + `tools/owners`) as part of the re-sync — or skip the re-sync and keep its previous engine until it's ready. The policy loader rejects unknown formats loudly at startup, so a missed migration fails closed rather than silently skipping the ownership source.

## Usage

Reviews run in the hosted stamphog product ([`products/stamphog/`](../../products/stamphog/)): a GitHub App delivers the PR webhook, and the engine runs in an isolated sandbox through `review_local.py`.
A repo either reviews every PR or waits for its trigger label, per its `review_mode`.
On approval a trigger label stays so it's visible which PRs were stamphog'd.
Only a substantive non-approval (`REFUSE`/`ESCALATE`) removes the label, so it
can be re-applied once the feedback is addressed; every other outcome —
including a crashed run that produced no verdict — keeps the label and retries
on the next push.
If the review agent can't reach its LLM backend (credentials, credit, or
outage) it returns `ERROR` and **keeps** the label — a transient infra failure
must not silently drop labels across every queued PR. The review retries on the
next push, or re-apply the label once the backend recovers.
`WAIT` also keeps the label. It means either that an allowlisted reviewer bot
still had a review in flight (👀 reaction) after the polling budget, or that the
`Migration risk` check had not reported yet — neither is a verdict on the PR, so
the next push retries automatically.

### Local review

```bash
# run from anywhere inside the posthog repo
uv run products/stamphog/packages/pr-approval-agent/review_pr.py 46594

# dry run (gates only, no LLM calls)
uv run products/stamphog/packages/pr-approval-agent/review_pr.py 46594 --dry-run

# save full result as JSON
uv run products/stamphog/packages/pr-approval-agent/review_pr.py 46594 --output-json /tmp/review.json

# verbose (show agent tool calls)
uv run products/stamphog/packages/pr-approval-agent/review_pr.py 46594 -v
```

`review_pr.py` is the manual entrypoint: it fetches everything over the network with `gh` and reviews a PR from your own checkout.
The hosted runtime never uses it, running `review_local.py` against a pre-fetched context instead, with no GitHub token inside the sandbox.
Requires `gh` CLI authenticated and `ANTHROPIC_API_KEY` in your environment.
Uses PEP 723 inline metadata so `uv run` handles dependencies automatically.

## How it works

```text
"stamphog" label added to PR
  │
  ▼
Prerequisites (hard gate)
  - Not draft, no merge conflicts
  - No outstanding "changes requested" reviews
  │
  ▼
Deny-list (hard gate)
  - Checks file paths against sensitive categories
  - Any match → gates DENY
  - PR-title keywords never deny on their own — they surface as scrutiny
    flags the LLM must verify against the diff (REFUSE if the change
    behaviorally touches the flagged domain, judge normally if incidental)
  │
  ▼
Size ceiling (hard gate)
  - >800 substantive lines or >30 substantive files → too large for auto-review
    (limits derived from 90 days of denial outcomes: the friction cluster of
    denied-yet-merged-unchanged PRs sits at 500-750 substantive lines, and past
    ~800 the merged-unchanged rate collapses, so escalation is genuinely right)
  - Docs (.md/.txt/.rst anywhere; artifact-extension files under docs/),
    snapshots (.snap/.ambr, __snapshots__/), images,
    `.lock`-extension files (e.g. `yarn.lock`), tests (test dirs and
    .test/.spec/_test files), and generated/ artifacts
    (regenerated-artifact extensions only: .ts/.tsx/.js/.jsx/.json/.md/.snap/.pyi/.txt)
    don't count toward the ceiling — they inflate diffs without adding review
    surface. Note: `pnpm-lock.yaml` and `package-lock.json` are not `.lock`-extension
    files and do count toward the ceiling. All files still count toward tier
    classification and still appear in the diff the LLM reads.
  │
  ▼
Tier classification
  - T0-deterministic: docs/tests/config only
  - T1-agent: eligible for review (sub-classified by risk)
  - T2-never: caught by deny-list
  │
  ▼
Wait for in-flight bot reviews (skipped when gates already denied)
  - Reviewer bots (greptile, hex-security, codex) put 👀 on the PR while
    reviewing and swap it for a verdict reaction minutes later; stamphog is
    triggered at the same moment, so an 👀 at fetch time is a race, not a
    lasting state
  - Polls until allowlisted-bot 👀 reactions clear (up to 5 min); if one
    remains, verdict is WAIT — label kept, next push retries
  - Bot 👀 older than ~45 min is a crashed reviewer, not an in-flight one —
    ignored, so a wedged bot can't stall every review (reactions never
    expire and humans can't remove another app's reaction)
  - Human 👀 reactions are not waited on — the LLM refuses over them instead
  - If the wait refetched the PR, classification and gates re-run on the
    fresh data before the LLM sees it
  │
  ▼
LLM Review
  - Claude Agent SDK with Read/Grep/Glob tools
  - Explores the repo via git diff, reads source files if needed
  - Looks for showstoppers: production breakage, security, missed deps
  - Receives the PR description (untrusted) and verifies the diff matches the
    author's stated intent — undisclosed sensitive behavior gets extra scrutiny
  - Reads the discussion-comment timeline (untrusted, newest first, capped)
    alongside inline comments; an un-withdrawn maintainer hold blocks approval
  - Gets a trusted one-line `Assurance:` digest (current-head approvals,
    unresolved inline comments, discussion count) so review state is at a glance
  - Reads other reviewers' signals as context (not a gate): top-level review
    states (annotated current-head vs older-commit), inline comments (tagged
    resolved/outdated), and reactions (👍/👎/👀) on the PR and comments —
    filtered to org members and an allowlist of reviewer bots (installed
    apps like inkeep react for non-review reasons), never the PR author
  - An 👀 reaction signals an in-flight review — the LLM refuses rather than
    approving over someone who is mid-review (bot 👀 races are waited out
    before the LLM runs; see above)
  - Stamphog's own prior reviews (stamphog[bot] refusals, github-actions[bot]
    approvals) and its own inline comments are excluded from the prompt — they
    describe an earlier snapshot of the PR and are never independent review
    signal. Quoted stamphog verdicts in other reviewers' comments are treated
    as history, not tampering
  - For changes entering risky territory (migrations, billing, auth, and
    similar; the full list lives in `.stamphog/review-guidance.md`), expects
    independent assurance over the risky part on the current head: a
    substantive reviewer pass, or an owning-team / STRONG-familiarity author;
    escalates otherwise. Outside risky territory no independent review is
    required, regardless of size tier. We move fast and fix forward, and the
    LLM's own reading suffices for contained, reversible changes
  - Gates are authoritative — LLM can tighten but never loosen
  │
  ▼
Final verdict → GitHub review (approve) or sticky comment (everything else)
```

The bot never posts request-changes.
Approvals are posted as real PR reviews (they must count toward branch protection).
An approval is posted once, as the Stamphog app (`stamphog[bot]`), carrying the review body.
This identity was confirmed to satisfy branch protection, so the earlier bodyless `github-actions[bot]` fallback approval has been dropped and every stamphog action now runs under the app token.
Every other verdict (REFUSED, ESCALATE, WAIT, ERROR) goes into a single sticky comment that is updated in place on each run, with a counter of how many verdicts the comment has carried (failure notes append without bumping it) — repeated refusals don't stack up as separate review comments on the PR.

## Stacked PRs (Graphite / git stacks)

A stacked PR targets its parent branch, not the repo's default branch, and depends on code the parent introduces but hasn't merged yet.
`PRData.stacked` (`base_ref != default_branch`, so repos whose trunk is `main` work too) drives the handling; the reviewer prompt tells the agent it is looking at a stacked PR.
Two parts make stamphog correct on these:

- **Exploration sees the post-stack tree.**
  The LLM reviewer's `Read`/`Grep`/`Glob` must run over a tree that already contains the parent PRs' code, so symbols from a not-yet-merged parent resolve and aren't flagged as broken imports.
  The diff itself is still computed `base_sha...head_sha`, so the review is scoped to exactly this PR's changes.
  How the head tree is materialized differs per runtime:
  - **Action:** the workflow checks out master (hardcoded, so a PR can't swap the review script), so the reviewer explores a detached **worktree at the PR head** created just for stacked PRs.
    If the worktree cannot be created, stamphog returns `ERROR` and retains the label rather than reviewing against the wrong source tree.
    Symbolic links the PR adds or repoints (relative to the default branch's tree, which already carries trusted ones like `CLAUDE.md`) fail closed, so a PR path cannot resolve outside the worktree.
  - **Hosted:** the sandbox clones and checks out the PR head for every review, so nothing extra is needed — `review_local.py` runs the pipeline with `head_checkout=True` and no worktree is created.
  - **Security (both runtimes):** the explored tree is PR-authored content.
    The reviewer runs the Agent SDK with `setting_sources=[]` (isolation mode) plus `strict_mcp_config`, so it does **not** load `.claude/settings.json` hooks (command execution), `CLAUDE.md` (injected instructions), or `.mcp.json` from the tree.
    Those files are still readable as untrusted _content_ under the anti-injection notice — never as configuration.
    The diff scratch file is created with `mkstemp` under an unpredictable name, so a tracked symlink in the tree cannot redirect the write.

- **Base retarget dismisses the stale approval.**
  When a stack's parent merges, the child PR is retargeted from the parent branch onto master, changing its effective diff **without a push** — so no `synchronize` fires and the normal push-dismiss path is skipped.
  Under the master ruleset (`dismiss_stale_reviews_on_push=false`), a prior bot approval would silently carry onto the new base.
  The Action listens for the `edited` event and, when the base changed, dismisses the bot approval and re-reviews against the new base (if the label is still present); the approval step also rechecks the live base and head SHAs right before posting.
  The hosted runtime does the same from the webhook (`_retract_approvals_on_base_retarget`, then a fresh run) and `post_verdict` rechecks the live base ref and SHA against the reviewed ones.

The base commit of a stacked PR is its parent branch tip, which the Action's master checkout doesn't fetch by default — `github.ensure_commits` and the `decide-delta` job both fetch the base branch so `git diff base_sha...head_sha` and the dismiss-time merge classification resolve it.
The hosted sandbox fetches the base SHA explicitly during the clone.

Known limitation (both runtimes): a parent branch force-push or rebase without restacking the child emits no child PR event, so the child's approval is only revalidated once the child is restacked or pushed.

## Tiers

### T0 — deterministic

Lowest risk. LLM still reviews but with a lighter bar. PR touches only safe paths:

- Allow-listed extensions: `.md`, `.mdx`, `.txt`, `.rst`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.csv`, `.svg`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.webp`, `.snap`, `.lock`
- Allow-listed paths: `docs/`, `README`, `CHANGELOG`, `LICENSE`, `CONTRIBUTING`, `.github/CODEOWNERS`, `.gitignore`, `.editorconfig`, `generated/`, `__snapshots__/`
- Test-only PRs (all changed files are test files)

### T1 — agent-reviewed

Sub-classified by risk to calibrate scrutiny:

| Sub-tier    | Lines       | Files | Breadth           |
| ----------- | ----------- | ----- | ----------------- |
| T1a-trivial | ≤20         | ≤3    | single-area       |
| T1b-small   | ≤100        | ≤5    | not cross-cutting |
| T1c-medium  | ≤300        | ≤15   | not cross-cutting |
| T1d-complex | >300 or >15 | —     | any               |

### T2 — never AI-approved

Deny-listed categories where even a small diff can have high blast radius:

| Category           | Patterns                                                                                                                                      |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **auth**           | auth, authentication, authenticate, authenticated, authorize, authorization, authorized, login, signup, oauth, saml, sso, oidc, credential, … |
| **crypto_secrets** | crypto, encrypt, decrypt, secret, key, cert, signing, .env, vault                                                                             |
| **migrations**     | migrations/, migrate, backfill, schema_change                                                                                                 |
| **infra_cicd**     | terraform, k8s, helm, dockerfile, .github/workflows, .github/pr-deploy, bin/deploy, deploy.sh, iam, cloudflare, etc.                          |
| **billing**        | billing, payment, stripe, invoice, pricing                                                                                                    |
| **public_api**     | openapi, api_schema, swagger, public_api                                                                                                      |
| **deps_toolchain** | lockfiles (pnpm-lock, uv.lock, Cargo.lock, go.sum, …), requirements.txt, Makefile, Dockerfile, .nvmrc                                         |

Notably absent, on purpose (calibrated against ~440 deny-listed PRs over 120 days):
`subscription` (means scheduled insight deliveries here, not payments),
`routing` (every match was app-level DRF routing, never infra), and the bare word `deploy`
(matches deploy-timing docs and unrelated code); narrow literals `bin/deploy`, `deploy.sh`,
and `.github/pr-deploy` cover real deployment artifacts instead.
Dependency _manifests_ (package.json, pyproject.toml, tsconfig, Cargo.toml,
go.mod) don't hard-deny either: without a lockfile change they can't pull in
third-party code (CI installs are frozen-lockfile). Three guards cover the
residual risk that manifest scripts/hooks execute in CI: a deterministic scan
of the manifest's diff hard-denies edits to known scripts/lifecycle/build
keys (see `manifest_risk.py` — fails closed if the diff can't be read),
manifest PRs are kept out of the T0 fast path, and the reviewer prompt must
REFUSE on execution-bearing changes the scan can't name.
Manifest/lockfile pairing is per-ecosystem, from the `DEPENDENCY_ECOSYSTEMS`
table in `gates.py` (the single source the deny patterns and helpers derive
from): a Cargo.lock bump hard-denies on its own but doesn't silence the
scripts guard on an unrelated package.json edit in the same PR.
Data warehouse connector sources (`products/warehouse_sources/.../sources/`)
are exempt from the **auth** and **billing** categories — connector code
legitimately does OAuth and talks to the Stripe API without touching
PostHog's auth system or its billing.

The **migrations** deny-list is bypassed when the `Migration risk` check on the head commit concludes `success` (all migrations classified Safe). The check is published by `analyze_migration_risk` in `ci-backend.yml` and is the same signal humans see in the PR's Checks tab. See `migration_risk.py` for how stamphog reads it.

If the check hasn't reported yet when stamphog runs, the hosted runtime returns `WAIT` rather than a verdict: the deny-list only matched because the engine could not tell a safe migration from a risky one, and a refusal would cost a trigger-label strip, and a ReviewHog handoff on a self-driving PR, over a race with CI. The label is kept and the next push reviews against the now-classified head commit.

### Ownership

Ownership context for the LLM (not a hard gate). The sources are declared in
`.stamphog/policy.yml` under `ownership:` and read from the master checkout: a
`hogli-resolver` source that resolves ownership through the shared hogli
resolver over the distributed `owners.yaml` / `product.yaml` files. A file's
owning teams are the union across all sources, so stamphog sees the same merged
view the reviewer auto-assigner builds. Cross-team typo/test/comment fixes are
fine, as are small well-tested behavioral fixes (T1a/T1b) with no outstanding
reviewer concerns; API contract, data model, and larger behavioral changes get
escalated.

## Versioning

`version.py` holds `STAMPHOG_VERSION` (semver, pre-releases like `2.0.0b1`).
It is stamped onto the `stamphog_review_completed` event (alongside the
checkout commit sha), the LLM trace properties, the evidence bundle, and the
verdict comment's mechanics table — so verdict quality and reviewer behavior
can be segmented by version in LLM analytics. Bump it in the same PR as any
behavior-affecting change to the engine, the prompt scaffold, or the review
guidance. Policy data edits don't need a bump; they're tracked by the policy
sha shown next to the version.

## Evidence bundle

Every run produces a JSON evidence bundle (`--output-json` locally, uploaded as artifact in CI) containing:

- Stamphog version and PR metadata (number, author, title)
- Classification (tier, sub-tier, breadth, commit type, deny categories, ownership)
- Gate results (each gate's pass/fail status and message)
- Reviewer output (verdict, reasoning, risk, issues)
- Final verdict

The hosted runtime persists it on the `ReviewRun` row, readable through the stamphog API.

## Architecture

- `review_pr.py` — pipeline orchestrator (fetch → classify → gates → LLM)
- `gates.py` — deterministic classification and deny-list logic
- `github.py` — GitHub data fetching via `gh` CLI
- `reviewer.py` — Claude Agent SDK reviewer (showstoppers prompt)
- `review_local.py` — offline entrypoint the hosted sandbox runs, consuming a pre-fetched context

## Empirical basis

Tier thresholds and deny categories calibrated against 356 PRs that received quick human approval (stamp) in the PostHog repo over ~90 days:

- 126 tiny (1-10 lines), 102 small (11-50 lines) — most quick approvals are small
- 284/356 single-area — narrow scope dominates
- Top profiles: frontend-only (122), python-only (57), python+test (28), config-only (21), test-only (16)
- 184 `fix`, 101 `chore` — fixes and chores are the modal commit types
- Frontend-only cluster: median 9 lines/1 file, 0% has tests
- Python+test cluster: median 73 lines/2.5 files, 100% has tests
- Python-only cluster: median 13 lines/1 file, 3% has tests

Key insight: size alone is not a safe proxy. Small PRs touching CI workflows, auth, or SAML should never be auto-approved regardless of size. The deny-list exists precisely for this.
