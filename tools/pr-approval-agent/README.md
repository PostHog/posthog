# PR approval agent

AI-assisted PR approval for PostHog.
Deterministic safety gates first, then Claude reviews for showstoppers.

## Usage

Add the `stamphog` label to a non-draft PR.
The GitHub Action runs the agent and posts an approval or comment.
On approval the label stays so it's visible which PRs were stamphog'd.
Only a substantive non-approval (`REFUSE`/`ESCALATE`) removes the label, so it
can be re-applied once the feedback is addressed; every other outcome —
including a crashed run that produced no verdict — keeps the label and retries
on the next push.
If the review agent can't reach its LLM backend (credentials, credit, or
outage) it returns `ERROR` and **keeps** the label — a transient infra failure
must not silently drop labels across every queued PR. The review retries on the
next push, or re-apply the label once the backend recovers.
`WAIT` also keeps the label: it means an allowlisted reviewer bot still had a
review in flight (👀 reaction) after the polling budget — not a verdict on the
PR, so the next push retries automatically. When the whole
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
  - Checks file paths against sensitive categories
  - Any match → gates DENY
  - PR-title keywords never deny on their own — they surface as scrutiny
    flags the LLM must verify against the diff (REFUSE if the change
    behaviorally touches the flagged domain, judge normally if incidental)
  │
  ▼
Size ceiling (hard gate)
  - >500 substantive lines or >20 substantive files → too large for auto-review
  - Docs (.md/.txt/.rst anywhere; artifact-extension files under docs/),
    snapshots (.snap/.ambr, __snapshots__/), images,
    `.lock`-extension files (e.g. `yarn.lock`), and generated/ artifacts
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
  - For non-trivial changes, expects at least one independent reviewer (an
    agent reviewer like Codex/Greptile/Claude, or a teammate) to have passed
    over the current head; escalates otherwise. No independent review needed
    for trivial changes (docs, tests, config/lockfile, typo/comment fixes) or
    for small single-area changes (T1a/T1b) with tests by owning-team authors
    with no outstanding reviewer concerns — humans approve those unchanged
  - Gates are authoritative — LLM can tighten but never loosen
  │
  ▼
Final verdict → GitHub review (approve or comment)
```

The bot never posts request-changes — only approves or comments.

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
| **deps_toolchain** | package.json, requirements.txt, pyproject.toml, pnpm-lock, uv.lock, Cargo.toml, go.mod, etc.                                                  |

Notably absent, on purpose (calibrated against ~440 deny-listed PRs over 120 days):
`subscription` (means scheduled insight deliveries here, not payments),
`routing` (every match was app-level DRF routing, never infra), and the bare word `deploy`
(matches deploy-timing docs and unrelated code); narrow literals `bin/deploy`, `deploy.sh`,
and `.github/pr-deploy` cover real deployment artifacts instead.
Data warehouse connector sources (`products/warehouse_sources/.../sources/`)
are exempt from the **auth** and **billing** categories — connector code
legitimately does OAuth and talks to the Stripe API without touching
PostHog's auth system or its billing.

The **migrations** deny-list is bypassed when the `Migration risk` check on the head commit concludes `success` (all migrations classified Safe). The check is published by `analyze_migration_risk` in `ci-backend.yml` and is the same signal humans see in the PR's Checks tab. See `tools/pr-approval-agent/migration_risk.py` for how stamphog reads it.

If the check hasn't completed yet when stamphog runs, stamphog refuses with a message asking the user to wait for the `Migration risk` check and re-apply the `stamphog` label. The label-strip on non-approved verdicts breaks the auto-rerun loop, so the next labeling action is the one that triggers a fresh review against the now-classified head commit.

### Ownership

Uses `.github/CODEOWNERS-soft` as context for the LLM (not a hard gate).
Cross-team typo/test/comment fixes are fine, as are small well-tested behavioral
fixes (T1a/T1b) with no outstanding reviewer concerns; API contract, data model,
and larger behavioral changes get escalated.

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
