# PR approval agent

A Python package that reviews one pull request and returns a verdict.
It runs deterministic safety gates over the changed files, classifies the PR into a tier, then lets a Claude Agent SDK reviewer look for showstoppers.

The package reads its policy from the `.stamphog/` directory of the checked-out tree it runs in.
It writes nothing to GitHub.
The verdict is the output, and the caller decides what to do with it.

Two entrypoints:

- `review_pr.py` fetches the PR itself with the `gh` CLI and reviews it from the current checkout.
- `review_local.py` reviews from a pre-fetched context JSON, with a checkout that is already at the PR head (`head_checkout=True`).

The stamphog product in [`products/stamphog/`](../../../stamphog/) runs `review_local.py` in a sandbox.

## Verdicts

| Verdict  | Meaning                                                 |
| -------- | ------------------------------------------------------- |
| APPROVE  | No showstoppers found                                   |
| REFUSE   | A concrete issue was found                              |
| ESCALATE | Only a human can rule out a showstopper                 |
| WAIT     | No verdict yet: a reviewer bot or a CI check is pending |
| ERROR    | The run could not produce a verdict                     |

`WAIT` means either that an allowlisted reviewer bot still had a review in flight (👀 reaction) after the polling budget, or that the `Migration risk` check had not reported yet.
Neither is a verdict on the PR, so the caller can retry unchanged.
`ERROR` means the run failed before it could judge the PR: the LLM backend was unreachable through credentials, credit or an outage, the reviewer hit a non-retryable analysis failure such as its turn limit, or `review_pr.py` could not create the worktree for a stacked PR.
It is never a judgment on the PR.

How a verdict reaches GitHub, and what happens to a trigger label, is the caller's concern.
For the hosted product see [`products/stamphog/README.md`](../../README.md#what-a-pr-author-sees).

## Local review

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

`review_pr.py` requires the `gh` CLI authenticated and `ANTHROPIC_API_KEY` in your environment.
It uses PEP 723 inline metadata, so `uv run` handles dependencies automatically.

## How it works

```text
review requested
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
  - PR-title keywords never deny on their own. They surface as scrutiny
    flags the LLM must verify against the diff (REFUSE if the change
    behaviorally touches the flagged domain, judge normally if incidental)
  │
  ▼
Size ceiling (hard gate)
  - >800 substantive lines or >30 substantive files → too large for auto-review
    (limits derived from 90 days of denial outcomes: the friction cluster of
    denied-yet-merged-unchanged PRs sits at 500-750 substantive lines, and past
    ~800 the merged-unchanged rate collapses, so escalation is genuinely right)
  - A folder's AGENT_APPROVALS.md can raise either ceiling for its own files,
    within the `overrides` contract in policy.yml (see "Policy files" below)
  - The whole PR still has to fit the most generous ceiling in play, so
    per-scope budgets never sum. With no folder grant that roof is the global
    ceiling above, so the gate keeps measuring the PR size these limits were
    derived from
  - Docs (.md/.txt/.rst anywhere; artifact-extension files under docs/),
    snapshots (.snap/.ambr, __snapshots__/), images,
    `.lock`-extension files (e.g. `yarn.lock`), tests (test dirs and
    .test/.spec/_test files), and generated/ artifacts
    (regenerated-artifact extensions only: .ts/.tsx/.js/.jsx/.json/.md/.snap/.pyi/.txt)
    don't count toward the ceiling, because they inflate diffs without adding review
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
    reviewing and swap it for a verdict reaction minutes later; the review is
    triggered at the same moment, so an 👀 at fetch time is a race, not a
    lasting state
  - Polls until allowlisted-bot 👀 reactions clear (up to 5 min); if one
    remains, the verdict is WAIT
  - Bot 👀 older than ~45 min is a crashed reviewer, not an in-flight one:
    ignored, so a wedged bot can't stall every review (reactions never
    expire and humans can't remove another app's reaction)
  - Human 👀 reactions are not waited on; the LLM refuses over them instead
  - If the wait refetched the PR, classification and gates re-run on the
    fresh data before the LLM sees it
  │
  ▼
LLM Review
  - Claude Agent SDK with Read/Grep/Glob tools
  - Explores the repo via git diff, reads source files if needed
  - Looks for showstoppers: production breakage, security, missed deps
  - Receives the PR description (untrusted) and verifies the diff matches the
    author's stated intent. Undisclosed sensitive behavior gets extra scrutiny
  - Reads the discussion-comment timeline (untrusted, newest first, capped)
    alongside inline comments; an un-withdrawn maintainer hold blocks approval
  - Gets a trusted one-line `Assurance:` digest (current-head approvals,
    unresolved inline comments, discussion count) so review state is at a glance
  - Reads other reviewers' signals as context (not a gate): top-level review
    states (annotated current-head vs older-commit), inline comments (tagged
    resolved/outdated), and reactions (👍/👎/👀) on the PR and comments,
    filtered to org members and an allowlist of reviewer bots (installed
    apps like inkeep react for non-review reasons), never the PR author
  - An 👀 reaction signals an in-flight review, so the LLM refuses rather than
    approving over someone who is mid-review (bot 👀 races are waited out
    before the LLM runs; see above)
  - Stamphog's own prior reviews and its own inline comments are excluded from
    the prompt, because they describe an earlier snapshot of the PR and are never
    independent review signal. Quoted stamphog verdicts in other reviewers'
    comments are treated as history, not tampering
  - For changes entering risky territory (migrations, billing, auth, and
    similar; the full list lives in the review guidance file), expects
    independent assurance over the risky part on the current head: a
    substantive reviewer pass, or an owning-team / STRONG-familiarity author;
    escalates otherwise. Outside risky territory no independent review is
    required, regardless of size tier. We move fast and fix forward, and the
    LLM's own reading suffices for contained, reversible changes
  - Gates are authoritative: the LLM can tighten but never loosen
  │
  ▼
Final verdict returned to the caller
```

## Policy files

The engine reads four files from the checked-out tree.
The repo root is resolved from the package's own location, never from the working directory, so the policy always comes from the same tree the engine reviews.

### `policy.yml`

Required, at `.stamphog/policy.yml`.
The machine policy, loaded and validated by a strict loader: a malformed or incomplete file hard-fails at load rather than reviewing under a half-loaded policy.

Top-level sections:

| Section       | What it declares                                                     |
| ------------- | -------------------------------------------------------------------- |
| `version`     | The policy schema version                                            |
| `deny`        | The T2 categories and the title/path patterns that match them        |
| `allow`       | The path patterns and extensions that make a PR eligible for T0      |
| `size_gate`   | The global `max_lines` and `max_files` ceilings                      |
| `tiers`       | The T1 sub-class thresholds                                          |
| `overrides`   | The keys a folder file may override, and each key's ceiling          |
| `familiarity` | The author-familiarity bands, a judgment input and never a gate      |
| `ownership`   | The ownership sources that feed the reviewer's advisory team context |

A rule may carry a `rationale`.
It records why the rule became what it is, which false positives drove an exclusion and when.
Treat it as historical justification like a commit message, not as a claim about the present.

The `deny` section must keep a `stamphog_policy` category matching the policy files and the engine itself.
The loader hard-fails without it, so the gate can never be configured to approve edits to its own policy or engine.

The loader rejects unknown top-level keys.
The two exceptions are `digest` and `dismiss`, which a hosting server may declare and parse itself; the engine allows them and never reads them.

### `review-guidance.md`

The trusted review-norms prose, injected into the reviewer's system prompt.
Ordinary markdown.
Editing it changes the reviewer's behavior directly, so update it deliberately.

### `steering.md`

Optional, and there is no default.
When present, it is appended to the review guidance under a "Repository-specific steering" section, so a repository can add its own advisory norms without replacing the whole guidance file.
An absent file leaves the prompt unchanged.

### `AGENT_APPROVALS.md`

A folder anywhere in the tree may carry an `AGENT_APPROVALS.md` with a `stamphog:` frontmatter block plus advisory prose.

Resolution:

- Every `AGENT_APPROVALS.md` at or above a changed file governs it.
  Guidance accumulates outermost first, and a child file adds to its ancestors rather than replacing them.
- For a delegated key, the nearest file on the chain with a valid grant wins for its files, within the contract ceiling.
  Each key resolves on its own.
  A folder that grants only one key leaves its files to the nearest ancestor grant of the other key, or to the global pool when no ancestor grants it.
  Files whose chain grants nothing belong to the global pool.
- The frontmatter is a positive allow-list.
  Only keys named in the `overrides` contract in `policy.yml` are read, within their ceilings.
  Anything else invalidates the whole file, frontmatter and prose: an unknown key, an out-of-bounds value, or unparseable frontmatter.
  An invalid file contributes nothing itself, but it does not cancel its ancestors.
  Files under it still ride an ancestor's grant, or fall to the global pool if the chain grants nothing.
  Treating invalid as absent grants no extra power, because an author who can write an invalid file could equally delete it.
- The prose is untrusted advisory guidance.
  It is sanitized, length-capped, and injected inside the reviewer prompt's untrusted region.
  It can never override the deny rules or the refusal criteria.

#### Mixed PRs get mixed leniency

Each scope's files are counted against that scope's own ceiling.
A grant covers exactly the files that resolve to it, which is the nearest valid grant of that key on their chain, and nothing else.

Example: with a folder ceiling of 50 files and a global ceiling of 20, a PR changing 30 files under that folder plus 19 files elsewhere passes, because each budget fits.
Add a 21st global file and the PR is denied for the global budget, however much headroom the folder still has.

Files whose chain grants nothing count against the global budget, so splitting files across pseudo-scopes can never inflate the allowance.
That covers a missing folder file, a prose-only file, and a file with only invalid grants.
Lines follow the same rule: a scope's substantive lines count against that scope's own line ceiling, and the global pool's lines against the global line ceiling.
The two ceilings are budgeted separately.
A folder that raises only the line ceiling still counts its files against the one global file budget, which keeps a one-key grant from opening a second budget for the key it never asked for.

#### The roof bounds the whole PR

Per-scope budgets alone would let a PR's total grow with the number of scopes it touches.
A folder granting 1000 lines next to an 800-line global pool would allow 1800, and every further granting folder would add its own budget on top.
So each ceiling also carries a roof over the whole PR: the most generous ceiling in play for that key.
A PR touching a folder that grants 1000 lines gets a 1000-line roof, whatever else it touches.

The roof needs no separate number in `policy.yml`.
Every grant is validated at or under the contract ceiling, and the global pool is always a scope, so the roof stays between the global default and the contract ceiling.
With no grant in play it equals the global default.

The roof takes no headroom away from a scope.
The per-scope budgets still hold, so the extra lines a folder's grant unlocks are only spendable inside that folder.

#### Delegation contract

The `overrides` section of `policy.yml` names the delegable keys and each key's ceiling.
Today the engine delegates `size_gate.max_files` and `size_gate.max_lines`.

A ceiling bounds two things: the largest value a folder may grant, and the highest a PR's roof can ever go for that key.
It is not the limit every PR gets.
A PR whose files reach no grant keeps the lower global roof.
The loader rejects a ceiling under its own global default, which would otherwise bound nothing.

`deny`, `allow`, `dismiss` and `tiers` are non-delegable by construction.
They are absent from the contract and cannot be granted from a folder file.

## Stacked PRs (Graphite / git stacks)

A stacked PR targets its parent branch, not the repo's default branch, and depends on code the parent introduces but hasn't merged yet.
`PRData.stacked` (`base_ref != default_branch`, so repos whose trunk is `main` work too) drives the handling; the reviewer prompt tells the agent it is looking at a stacked PR.

**Exploration sees the post-stack tree.**
The LLM reviewer's `Read`/`Grep`/`Glob` must run over a tree that already contains the parent PRs' code, so symbols from a not-yet-merged parent resolve and aren't flagged as broken imports.
The diff itself is still computed `base_sha...head_sha`, so the review is scoped to exactly this PR's changes.
How the head tree is materialized differs per entrypoint:

- `review_local.py` runs the pipeline with `head_checkout=True`, because the checkout is already at the PR head. No worktree is created.
- `review_pr.py` reviews from the current checkout, which is not the PR head, so it creates a detached **worktree at the PR head** for stacked PRs.
  If the worktree cannot be created, the verdict is `ERROR` rather than a review against the wrong source tree.
  Symbolic links the PR adds or repoints fail closed, so a PR path cannot resolve outside the worktree.

**The explored tree is PR-authored content.**
The reviewer runs the Agent SDK with `setting_sources=[]` (isolation mode) plus `strict_mcp_config`, so it does **not** load `.claude/settings.json` hooks (command execution), `CLAUDE.md` (injected instructions), or `.mcp.json` from the tree.
Those files are still readable as untrusted _content_ under the anti-injection notice, never as configuration.
The diff scratch file is created with `mkstemp` under an unpredictable name, so a tracked symlink in the tree cannot redirect the write.

The base commit of a stacked PR is its parent branch tip, which the checkout does not necessarily carry.
`github.ensure_commits` fetches it for `review_pr.py`, and `review_local.py` expects the caller to have fetched it during the clone.

## Tiers

### T0 - deterministic

Lowest risk. The LLM still reviews but with a lighter bar. The PR touches only safe paths: allow-listed extensions, allow-listed paths, or test files only.
The extension and path lists live under `allow:` in `policy.yml`.

### T1 - agent-reviewed

Sub-classified by risk to calibrate scrutiny, from `tiers:` in `policy.yml`:

| Sub-tier    | Lines       | Files | Breadth           |
| ----------- | ----------- | ----- | ----------------- |
| T1a-trivial | ≤20         | ≤3    | single-area       |
| T1b-small   | ≤100        | ≤5    | not cross-cutting |
| T1c-medium  | ≤300        | ≤15   | not cross-cutting |
| T1d-complex | >300 or >15 | -     | any               |

### T2 - never AI-approved

Deny-listed categories where even a small diff can have high blast radius.
The patterns for each category, and the `rationale` behind them, live under `deny:` in `policy.yml`.
The categories the shipped policy defines:

| Category            | What it covers                                       |
| ------------------- | ---------------------------------------------------- |
| **auth**            | Authentication and authorization surfaces            |
| **crypto_secrets**  | Cryptography, secrets, and key material              |
| **migrations**      | Database and schema migrations                       |
| **infra_cicd**      | Infrastructure, CI, and deployment artifacts         |
| **billing**         | Payments and billing                                 |
| **public_api**      | Public API contracts and schemas                     |
| **deps_toolchain**  | Dependency lockfiles and toolchain/build files       |
| **stamphog_policy** | Stamphog's own policy files, engine, and gate inputs |

Some words are absent on purpose, calibrated against deny-listed PRs over 120 days.
`subscription` means scheduled insight deliveries in the PostHog monorepo, not payments.
`routing` only ever matched app-level DRF routing, never infrastructure.
The bare word `deploy` matches deploy-timing docs and unrelated code, so narrow literals like `bin/deploy` and `deploy.sh` cover real deployment artifacts instead.

Dependency _manifests_ (package.json, pyproject.toml, tsconfig, Cargo.toml, go.mod) don't hard-deny either: without a lockfile change they can't pull in third-party code, because CI installs are frozen-lockfile.
Three guards cover the residual risk that manifest scripts or hooks execute in CI.
A deterministic scan of the manifest's diff hard-denies edits to known scripts, lifecycle and build keys (see `manifest_risk.py`, which fails closed if the diff can't be read).
Manifest PRs are kept out of the T0 fast path.
And the reviewer prompt must REFUSE on execution-bearing changes the scan can't name.

Manifest and lockfile pairing is per-ecosystem, from the `DEPENDENCY_ECOSYSTEMS` table in `gates.py`, which is the single source the deny patterns and helpers derive from.
So a Cargo.lock bump hard-denies on its own but doesn't silence the scripts guard on an unrelated package.json edit in the same PR.

A deny category may carry `exempt_path_prefixes`, for code that legitimately looks like a sensitive domain without touching one.

The **migrations** deny-list is bypassed when the `Migration risk` check on the head commit concludes `success` (all migrations classified Safe).
The check is the same signal humans see in the PR's Checks tab.
See `migration_risk.py` for how the engine reads it.

If the check hasn't reported yet, `review_local.py` returns `WAIT` rather than a verdict, because its caller can retry on the next push.
`review_pr.py` has no such caller and returns `REFUSED` instead.
The deny-list only matched because the engine could not tell a safe migration from a risky one, so a refusal would be a verdict on a race with CI rather than on the PR.
A retry against the now-classified head commit reviews it properly.

### Ownership

Ownership context for the LLM, not a hard gate.
The sources are declared in `policy.yml` under `ownership:` and read from the checked-out tree: a `hogli-resolver` source that resolves ownership through the shared hogli resolver over the distributed `owners.yaml` / `product.yaml` files.
A file's owning teams are the union across all sources.
Cross-team typo, test and comment fixes are fine, as are small well-tested behavioral fixes (T1a/T1b) with no outstanding reviewer concerns.
API contract, data model, and larger behavioral changes get escalated.

## Versioning

`version.py` holds `STAMPHOG_VERSION` (semver, pre-releases like `2.0.0b1`).
It is stamped onto the `stamphog_review_completed` event (alongside the checkout commit sha), the LLM trace properties, the evidence bundle, and the verdict comment's mechanics table, so verdict quality and reviewer behavior can be segmented by version in LLM analytics.
Bump it in the same PR as any behavior-affecting change to the engine, the prompt scaffold, or the review guidance.
Policy data edits don't need a bump; they're tracked by the policy sha shown next to the version.

## Evidence bundle

Every run produces a JSON evidence bundle (`--output-json` on `review_pr.py`) containing:

- Stamphog version and PR metadata (number, author, title)
- Classification (tier, sub-tier, breadth, commit type, deny categories, ownership)
- Gate results (each gate's pass/fail status and message)
- Reviewer output (verdict, reasoning, risk, issues)
- Final verdict

## Architecture

- `review_pr.py` - pipeline orchestrator (fetch → classify → gates → LLM), and the `gh`-fetching entrypoint
- `review_local.py` - the entrypoint that reviews from a pre-fetched context JSON
- `policy.py` - policy loader, resolver, and the untrusted-text sanitizer
- `gates.py` - deterministic classification and deny-list logic
- `github.py` - GitHub data fetching via `gh` CLI
- `reviewer.py` - Claude Agent SDK reviewer (showstoppers prompt)

## Empirical basis

Tier thresholds and deny categories calibrated against 356 PRs that received quick human approval (stamp) in the PostHog repo over ~90 days:

- 126 tiny (1-10 lines), 102 small (11-50 lines) - most quick approvals are small
- 284/356 single-area - narrow scope dominates
- Top profiles: frontend-only (122), python-only (57), python+test (28), config-only (21), test-only (16)
- 184 `fix`, 101 `chore` - fixes and chores are the modal commit types
- Frontend-only cluster: median 9 lines/1 file, 0% has tests
- Python+test cluster: median 73 lines/2.5 files, 100% has tests
- Python-only cluster: median 13 lines/1 file, 3% has tests

Key insight: size alone is not a safe proxy.
Small PRs touching CI workflows, auth, or SAML should never be auto-approved regardless of size.
The deny-list exists precisely for this.
