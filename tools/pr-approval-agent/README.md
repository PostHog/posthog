# PR approval agent

AI-assisted PR approval for PostHog.
Runs deterministic safety gates, then calls Claude for evidence-bundle review and second-pass audit on eligible PRs.

## Quick start

```bash
# run from anywhere inside the posthog repo
uv run tools/pr-approval-agent/review_pr.py 46594

# dry run (gates only, no LLM calls)
uv run tools/pr-approval-agent/review_pr.py 46594 --dry-run

# save full evidence bundle as JSON
uv run tools/pr-approval-agent/review_pr.py 46594 --output-json /tmp/review.json

# different repo
uv run tools/pr-approval-agent/review_pr.py 123 --repo PostHog/other-repo
```

Requires `gh` CLI authenticated and `ANTHROPIC_API_KEY` in your environment.
The script uses PEP 723 inline metadata so `uv run` handles the `anthropic` dependency automatically — no venv setup needed.

## How it works

The agent evaluates PRs through a pipeline of deterministic gates followed by (optionally) two LLM passes.
Any gate failure stops the pipeline early and refuses approval.

```text
PR number
  │
  ▼
Prerequisites
  - Not draft, no merge conflicts
  - No outstanding "changes requested" reviews
  - All CI checks passing (no failures or pending)
  │
  ▼
Deny-list
  - Checks file paths + PR title against sensitive categories
  - Any match → REFUSE (see deny categories below)
  │
  ▼
Tier classification
  - T0-deterministic → AUTO-APPROVE (docs/tests/config only)
  - T1-agent → proceed to LLM review
  - T2-never → REFUSE (caught by deny-list, but belt-and-suspenders)
  │
  ▼
LLM Review (T1 only)
  - Claude produces a structured evidence bundle
  - Includes: change manifest, ownership assessment, review comments, tests, security
  - Ownership context from CODEOWNERS-soft is provided as input — the LLM decides
    whether the change warrants the owning team's attention
  - Verdict: APPROVE / REFUSE / ESCALATE
  │
  ▼
LLM Audit (second pass)
  - Independent model verifies the first reviewer's assessment
  - Checks deny-list compliance, intent↔diff alignment, missed review comments
  - Any disagreement → REFUSE
  │
  ▼
Final verdict
```

## Approval criteria

Based on analysis of 356 historically stamped PRs over ~90 days.
The criteria balance coverage (automating what humans fast-approved) with safety (never auto-approving high-blast-radius changes).

### Tier 0 — deterministic auto-approve

No LLM judgment needed. The PR touches only safe paths:

- Allow-listed extensions: `.md`, `.mdx`, `.txt`, `.rst`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.csv`, `.svg`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.webp`, `.snap`, `.lock`
- Allow-listed paths: `docs/`, `README`, `CHANGELOG`, `LICENSE`, `CONTRIBUTING`, `.github/CODEOWNERS`, `.gitignore`, `.editorconfig`, `generated/`, `__snapshots__/`
- Test-only PRs (all changed files are test files)

Coverage: ~4% of historically stamped PRs.

### Tier 1 — agent-verified approval

The LLM reviews the PR and must produce a verifiable evidence bundle before approving.
Sub-classified by risk:

| Sub-tier    | Lines       | Files | Breadth           | Description                       |
| ----------- | ----------- | ----- | ----------------- | --------------------------------- |
| T1a-trivial | ≤20         | ≤3    | single-area       | Minimal changes, single component |
| T1b-small   | ≤100        | ≤5    | not cross-cutting | Small focused changes             |
| T1c-medium  | ≤300        | ≤15   | not cross-cutting | Moderate changes, still focused   |
| T1d-complex | >300 or >15 | —     | any               | Large or diffuse changes          |

The LLM must produce:

- **Change manifest** — what changed, why, which components, risk class, supporting diff hunks
- **Review comment assessment** — whether existing review comments are addressed or unresolved
- **Test assessment** — tests present, coverage adequate, recommended test commands
- **Security assessment** — injection risk, auth impact, data risk

A second model independently audits the first reviewer's output for missed deny-list categories, intent↔diff misalignment, and overlooked review comments.

Coverage: ~69% of historically stamped PRs.

### Tier 2 — never AI-approved

Deny-listed categories where even a small diff can have high blast radius.
Always requires human review.

| Category           | Patterns                                                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **auth**           | auth, login, signup, session, token, oauth, saml, sso, permission, oidc, credential, password, 2fa, mfa                                                                 |
| **crypto_secrets** | crypto, encrypt, decrypt, secret, key, cert, signing, .env, vault                                                                                                       |
| **migrations**     | migrations/, migrate, backfill, schema_change                                                                                                                           |
| **infra_cicd**     | terraform, k8s, kubernetes, helm, dockerfile, docker-compose, .github/workflows, deploy, iam, cloudflare, cdn, waf, routing                                             |
| **billing**        | billing, payment, stripe, invoice, subscription, pricing                                                                                                                |
| **public_api**     | openapi, api_schema, swagger, public_api                                                                                                                                |
| **deps_toolchain** | package.json, requirements.txt, pyproject.toml, pnpm-lock, package-lock, yarn.lock, uv.lock, Cargo.toml, go.mod, Makefile, Dockerfile, tsconfig, .tool-versions, .nvmrc |

Coverage: ~27% of historically stamped PRs.

### Ownership (LLM context, not a hard gate)

Uses `.github/CODEOWNERS-soft` to determine team ownership of changed files.
This is provided as context to the LLM reviewer, not as a blocking gate — matching how CODEOWNERS-soft works in practice (alerts, doesn't block).

The LLM is instructed to:

- **Approve** cross-team changes that are clearly safe: typo fixes, log strings, test fixes, comment updates, mechanical refactors
- **Escalate** cross-team changes with behavioral impact: business logic, API contracts, data models — anything the owning team would reasonably want to review
- **Default to escalate** when ownership intent is ambiguous

## Empirical basis

The tier thresholds and deny categories were calibrated against 356 PRs that received quick human approval (stamp) in the PostHog repo over ~90 days:

- 126 tiny (1-10 lines), 102 small (11-50 lines) — most quick approvals are small
- 284/356 single-area — narrow scope dominates
- Top profiles: frontend-only (122), python-only (57), python+test (28), config-only (21), test-only (16)
- 184 `fix`, 101 `chore` — fixes and chores are the modal commit types
- Frontend-only cluster: median 9 lines/1 file, 0% has tests
- Python+test cluster: median 73 lines/2.5 files, 100% has tests
- Python-only cluster: median 13 lines/1 file, 3% has tests

Key insight: size alone is not a safe proxy. Small PRs touching CI workflows, auth, or SAML should never be auto-approved regardless of size. The deny-list exists precisely for this.

## Example output

```text
Reviewing PR #46594 (PostHog/posthog)

  fix(workflows): use proper autocorrect in HogQL expressions
  by @havenbarnes | closed | 1 files | 0 comments

Gates
  ✓ prerequisites: all clear
  ✓ deny-list: no deny categories matched
  ✓ tier: T1-agent / T1a-trivial (7L, 1F, single-area, fix)
    ownership: no owned paths (CODEOWNERS-soft has no match)

LLM Review
  Verdict: APPROVE
  Risk: low
  Reasoning: Straightforward configuration fix...

LLM Audit
  Verdict: AGREE

  ✓ APPROVED — both reviewer and auditor agree
```

## Tested PRs

| PR     | Type                            | Result                                   |
| ------ | ------------------------------- | ---------------------------------------- |
| #43716 | CI workflow permissions         | REFUSED at deny-list (auth, infra_cicd)  |
| #46594 | Tiny HogQL config fix (7L, 1F)  | APPROVED — reviewer + auditor agree      |
| #49610 | Cross-team HogQL fix            | LLM decides — ownership context provided |
| #45314 | Error tracking reload (32L, 3F) | ESCALATED — no tests for new state logic |

## Next steps

- Wire into a GitHub Action (trigger on `priority-review` label or `workflow_dispatch`)
- Add batch mode to evaluate multiple PRs
- Tune deny-list patterns (current keyword matching is broad, e.g. "key" matches too much)
- Add AST-level checks for python-only changes without tests (prove no control-flow changes)
- Track approval accuracy over time against human reviewer decisions
