# PR approval agent

AI-assisted PR approval for PostHog.
Deterministic safety gates first, then Claude reviews for showstoppers.

## Usage

Add the `stamphog` label to a non-draft PR.
The GitHub Action runs the agent and posts an approval or comment.
On approval the label stays so it's visible which PRs were stamphog'd.
On a substantive non-approval (`REFUSE`/`ESCALATE`) the label is removed so it
can be re-applied once the feedback is addressed.
If the review agent can't reach its LLM backend (credentials, credit, or
outage) it returns `ERROR` and **keeps** the label — a transient infra failure
must not silently drop labels across every queued PR. The review retries on the
next push, or re-apply the label once the backend recovers. When the whole
fleet of stamphog reviews suddenly returns `ERROR`, suspect the
`STAMPHOG_ANTHROPIC_API_KEY` org secret first (stamphog uses its own dedicated
Anthropic key, separate from the shared `ANTHROPIC_API_KEY`).

### Local testing

```bash
# run from anywhere inside the posthog repo
uv run tools/pr-approval-agent/review_pr.py 46594

# dry run (gates only, no LLM calls)
uv run tools/pr-approval-agent/review_pr.py 46594 --dry-run

# save full result as JSON
uv run tools/pr-approval-agent/review_pr.py 46594 --output-json /tmp/review.json

# verbose (show agent tool calls)
uv run tools/pr-approval-agent/review_pr.py 46594 -v
```

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
  - Checks file paths + PR title against sensitive categories
  - Any match → gates DENY
  │
  ▼
Size ceiling (hard gate)
  - >500 lines or >20 files → too large for auto-review
  │
  ▼
Tier classification
  - T0-deterministic: docs/tests/config only
  - T1-agent: eligible for review (sub-classified by risk)
  - T2-never: caught by deny-list
  │
  ▼
LLM Review
  - Claude Agent SDK with Read/Grep/Glob tools
  - Explores the repo via git diff, reads source files if needed
  - Looks for showstoppers: production breakage, security, missed deps
  - Gates are authoritative — LLM can tighten but never loosen
  │
  ▼
Final verdict → GitHub review (approve or comment)
```

The bot never posts request-changes — only approves or comments.

## Stacked PRs (Graphite / git stacks)

A stacked PR targets its parent branch, not master, and depends on code the
parent introduces but hasn't merged yet. Two parts make stamphog correct on
these:

- **Exploration sees the post-stack tree.** The workflow checks out master
  (hardcoded, so a PR can't swap the review script), but the LLM reviewer's
  `Read`/`Grep`/`Glob` run in a detached **worktree at the PR head** instead.
  The head tree already contains the parent PRs' code, so symbols from a
  not-yet-merged parent resolve and aren't flagged as broken imports. The diff
  itself is still computed `base_sha...head_sha`, so the review is scoped to
  exactly this PR's changes. Worktree creation falls back to reviewing from
  master if it fails.
  - **Security:** the worktree is PR-authored content. The reviewer runs the
    Agent SDK with `setting_sources=[]` (isolation mode), so it does **not**
    load `.claude/settings.json` hooks (command execution) or `CLAUDE.md`
    (injected instructions) from the head tree. Those files are still readable
    as untrusted _content_ under the anti-injection notice — never as
    configuration.

- **Base retarget dismisses the stale approval.** When a stack's parent merges,
  the child PR is retargeted from the parent branch onto master, changing its
  effective diff **without a push** — so no `synchronize` fires and the normal
  push-dismiss path is skipped. Under the master ruleset
  (`dismiss_stale_reviews_on_push=false`), a prior bot approval would silently
  carry onto the new base. The workflow listens for the `edited` event and, when
  the base changed, dismisses the bot approval and re-reviews against the new
  base (if the label is still present).

The base commit of a stacked PR is its parent branch tip, which the master
checkout doesn't fetch by default — `github.ensure_commits` and the
`decide-delta` job both fetch the base branch so `git diff base_sha...head_sha`
and the dismiss-time merge classification resolve it.

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

| Category           | Patterns                                                                                     |
| ------------------ | -------------------------------------------------------------------------------------------- |
| **auth**           | auth, login, signup, session, token, oauth, saml, sso, permission, oidc, credential, etc.    |
| **crypto_secrets** | crypto, encrypt, decrypt, secret, key, cert, signing, .env, vault                            |
| **migrations**     | migrations/, migrate, backfill, schema_change                                                |
| **infra_cicd**     | terraform, k8s, helm, dockerfile, .github/workflows, deploy, iam, cloudflare, etc.           |
| **billing**        | billing, payment, stripe, invoice, subscription, pricing                                     |
| **public_api**     | openapi, api_schema, swagger, public_api                                                     |
| **deps_toolchain** | package.json, requirements.txt, pyproject.toml, pnpm-lock, uv.lock, Cargo.toml, go.mod, etc. |

The **migrations** deny-list is bypassed when the `Migration risk` check on the head commit concludes `success` (all migrations classified Safe). The check is published by `analyze_migration_risk` in `ci-backend.yml` and is the same signal humans see in the PR's Checks tab. See `tools/pr-approval-agent/migration_risk.py` for how stamphog reads it.

If the check hasn't completed yet when stamphog runs, stamphog refuses with a message asking the user to wait for the `Migration risk` check and re-apply the `stamphog` label. The label-strip on non-approved verdicts breaks the auto-rerun loop, so the next labeling action is the one that triggers a fresh review against the now-classified head commit.

### Ownership

Uses `.github/CODEOWNERS-soft` as context for the LLM (not a hard gate).
Cross-team typo/test/comment fixes are fine; behavioral changes to business logic get escalated.

## Evidence bundle

Every run produces a JSON evidence bundle (`--output-json` locally, uploaded as artifact in CI) containing:

- PR metadata (number, author, title)
- Classification (tier, sub-tier, breadth, commit type, deny categories, ownership)
- Gate results (each gate's pass/fail status and message)
- Reviewer output (verdict, reasoning, risk, issues)
- Final verdict

The GitHub Action uploads this as a build artifact with 30-day retention.

## Architecture

- `review_pr.py` — pipeline orchestrator (fetch → classify → gates → LLM)
- `gates.py` — deterministic classification and deny-list logic
- `github.py` — GitHub data fetching via `gh` CLI
- `reviewer.py` — Claude Agent SDK reviewer (showstoppers prompt)
- `.github/workflows/pr-approval-agent.yml` — GitHub Action (label trigger)

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
