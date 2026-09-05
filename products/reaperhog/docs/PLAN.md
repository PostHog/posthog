# ReaperHog plan

ReaperHog finds dead code in this repository, proves it dead, deletes it, runs the tests and opens small draft PRs with the evidence.
It never merges. Humans do the burying.

The problem it targets is not unused imports.
It is features that shipped behind a flag and never got released, hackathon code nobody touched in two years, scenes nobody opens, endpoints nobody calls, and the losing variant of every concluded experiment still sitting in the tree next to the winner.
Static analysis cannot see those as dead because the code is reachable.
A flag is a runtime variable; the analyzer does not know whether it is on.
Production usage does.

## Thesis

Production data is context for code removal, the same way it is context for code generation.
PostHog already knows which flags evaluate true, which scenes get pageviews, which experiments concluded and who lost, which endpoints get requests.
ReaperHog joins that data to the source tree, so "is this feature used" becomes a query with a number in it, not a judgment call from reading the code.
The LLM's job is narrowed to tracing what a dead root drags with it and proving nothing else reaches it.

## Hard rules

- Never merges, never enqueues, never applies `stamphog`. Every PR is a draft with the `reaperhog` label.
- Never opens a mega PR. One root per PR, capped in size, capped in count.
- Never deletes on one signal. A deletion needs a scout hit plus a verifier verdict, and the verifier's rule is "on the fence means alive".
- Never touches migrations, `.github/`, CODEOWNERS, dependency manifests, generated files or public API contracts. These floors live in code, not in a skill.
- Flags get archived after merge, never deleted. Evaluation history stays queryable.

## Shape

Three stages that never share a run.
The durable object is the inventory, not the PR.

```text
scan     scope -> scouts -> hits -> clusters (inventory rows, idempotent by root)
verify   cluster -> warm sandbox session, one cluster per turn -> verdict (dead | alive | undecided)
harvest  dead clusters -> budget + size policy -> Tasks run deletes, checks, opens a draft PR
```

Scan is cheap and wide.
Verify is where the LLM spends.
Harvest is deterministic policy plus a coding-agent task.
Decoupling them is what stops the spam: a second scan of an unchanged repository produces zero new PRs.

## Scouts

Each scout emits hits, not deletions.
A hit is `(root, root_kind, evidence)`.
A root is the thing whose death drags a cluster with it: a flag key, a scene, a file, a directory.

| Scout         | Root kind    | Signal                                                                                                                                                                                                         |
| ------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `experiments` | flag         | Concluded experiments whose flag key still has code references. `cleanup_plan` in the experiments product already names the variant to keep; an ambiguous outcome is marked not confident and goes to a human. |
| `flags`       | flag         | Flag rows joined to the code's flag keys: deleted or archived rows with live references, flags disabled, uncalled, at 0% rollout or enabled for nobody who checked them, flags at 100% rollout.                |
| `archaeology` | directory    | Last non-sweep commit per directory (commits touching 200+ files are skipped), committer no longer in the org, hackathon or spike commit subjects.                                                             |
| `scenes`      | scene        | Product routes with zero `$pageview` traffic over 90 days on the configured project.                                                                                                                           |
| `static`      | file, symbol | knip, where a workspace ships a `knip.json` (`products/desktop` today).                                                                                                                                        |

Not built yet: `endpoints` (Prometheus request counts by view), `queries` (query log kinds vs `NodeKind`), `jobs` (Celery and Temporal names never executed).

## Convergence and ranking

Deterministic, no LLM.
Hits group by root into clusters.

- Two or more scouts on one root is a strong candidate, and so is a single decisive hit (a recorded experiment outcome).
- One non-decisive scout is weak and goes to the "needs a human" list, never to harvest.
- Oversize clusters (too many referencing files, or a directory over the line cap) are blocked and listed for a human.
- A cluster whose PR was closed unmerged stays `declined` until its file set changes.
- CODEOWNERS decides the owner shown in the summary and the PR body.

Ranking is the anti-spam.
The LLM never decides what gets a PR.

## Verification

One warm sandbox session per run, one cluster per turn, always repository-wide even when the scan scope was narrow.
The bar is the team-editable `reaperhog-verification-criteria` skill; the output schema is fixed in code.
Only `is_dead` with high confidence becomes `dead`; everything else is `alive` or `undecided`.

## Harvest

- One PR per cluster, `MAX_OPEN_REAPER_PRS` open at a time, size-capped by file count.
- The deletion runs as a Tasks coding-agent run with `create_pr=True`, the same path the experiments flag cleanup uses.
- The PR body is the evidence: scout numbers, the verifier's searches and argumentation, open questions, and an "archive the flag after merge" checklist.
- A sync step maps the task run and the PR into `reaped`, then `buried` (merged) or `declined` (closed).

## Build phases

- Phase 0: run the flags and experiments scan against the real project and read the list. This decides how much the rest is worth.
- Phase 1: inventory, scouts, convergence, `run_reaper` scan. Built.
- Phase 2: verification session and criteria skill. Built.
- Phase 3: harvest into draft PRs and PR-state sync. Built.
- Phase 4: scenes and static scouts, CODEOWNERS ownership, Temporal weekly schedule. Built. Remaining scouts and the "needs a human" surface are open.

## Decisions still open

- Which project's flag and pageview data is the truth for this repository, and how the worker reads it.
- Where the scan runs in the cloud: the worker needs a checkout with `rg`, so the repo-reading scouts either move into a sandbox turn or the worker gets a checkout.
- The staleness bars (flags one year, directories eighteen months, freshness thirty days). Start conservative, loosen with data.
- Whether `declined` clusters ever come back on their own, or only when a human clears them.
