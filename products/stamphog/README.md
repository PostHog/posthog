# Stamphog

Stamphog is an approve-first pull request reviewer.
It runs deterministic gates and a scoped LLM review over a PR and, when the policy allows it, posts a real GitHub approval instead of comments.
Repositories opt in one at a time, and nothing else is touched.

The review itself is done by the engine in [`packages/pr-approval-agent/`](packages/pr-approval-agent/).
This product decides which PRs are reviewed, runs the engine in a sandbox, and puts the verdict on GitHub.

## What a PR author sees

A repository either reviews every PR or waits for its trigger label, depending on its review mode.
The engine returns one of five verdicts, and `post_verdict` puts it on the PR.

| Verdict  | Where it lands                             | Trigger label in label mode |
| -------- | ------------------------------------------ | --------------------------- |
| APPROVED | A real GitHub review by `stamphog[bot]`    | Kept                        |
| REFUSED  | A GitHub comment review by `stamphog[bot]` | Removed                     |
| ESCALATE | A GitHub comment review by `stamphog[bot]` | Removed                     |
| WAIT     | A GitHub comment review by `stamphog[bot]` | Kept, retries               |
| ERROR    | A GitHub comment review by `stamphog[bot]` | Kept, retries               |
| Gated    | A GitHub comment review by `stamphog[bot]` | Removed                     |

Gated means a deterministic gate denied the PR before any review, such as the deny-list or the size ceiling.
The engine reports it as `REFUSED`; the product stores the run as gated with the verdict `WAIT`, and still removes the trigger label because a human has to take it from here.

The bot never posts request-changes.
Approvals are posted as real reviews so they count toward branch protection, once, as the Stamphog app (`stamphog[bot]`), carrying the review body.
Every other verdict is posted once per run as a comment review on the same surface, so approvals and non-approvals for one head never disagree across two lists.
A run that produced no verdict posts a short failure notice the same way, unless a newer run already holds the same head.
The engine reports `APPROVED` and `REFUSED`, and the API exposes them lowercase as `approved` and `refused`.

The trigger label only exists in label-triggered mode, and of the verdicts only a substantive non-approval removes it.
So the label can be re-applied once the feedback is addressed.
A verdict that says nothing about the PR keeps the label, and the next push retries.
A label can request at most one review per PR every 10 minutes.
A label added inside that window starts nothing, so stamphog removes it again and says in its status comment when a relabel will work.
`WAIT` means a reviewer bot still had a review in flight, or the `Migration risk` check had not reported yet.
`ERROR` means the run failed before it could judge the PR, because the LLM backend was unreachable or the reviewer hit a non-retryable analysis failure such as its turn limit.
A transient failure must not silently drop labels across every queued PR.

Each run is stored as a `ReviewRun` row with its evidence bundle.
Runs are listed in the Stamphog runs page in the PostHog app (`/stamphog/runs`), and the same data is available through the stamphog API and its MCP tools (review runs, repo configs, digest runs).
Retrieving one run also returns the reviewer's reasoning, the same text stamphog posts on GitHub.

A project member can also ask for a review directly, by creating a review run (`POST review_runs/`, or the `stamphog-review-runs-create` MCP tool), and then poll the run for its verdict.
The request replaces the trigger label, so it works in label mode.
Every other rule still applies: drafts, closed PRs, bot-authored PRs, PRs from outside the repository, and PRs whose author lacks write access are refused.

## Connect a repository

1. Install the Stamphog GitHub App on your GitHub organization.
2. Open Stamphog in the PostHog app and connect GitHub. The callback records the repositories you can reach with your own GitHub account. It adds none of them yet.
3. Add each repository you want reviewed from the **Add a repository** search (`POST repo_configs/add_repository`). Adding a repository turns its reviews on in label-triggered mode. The search lists the repositories you can add, from `GET repo_configs/available_repositories`.
4. Expand the repository's row to change the **review mode**: "Label-triggered" (the default) reviews only PRs carrying the trigger label, "All PRs" reviews every pull request. Set the trigger label name next to the mode.
5. Turn on **Include in the digest** if you want the daily Slack digest of merged PRs. The project needs a connected Slack integration first, or the digest run stops silently before posting.

The repositories you can add are the ones a project member reached with their own GitHub account, not every repository the installation can reach.
Each member who connects adds the repositories they can reach, and connecting again refreshes the list.
Repositories removed from the installation on GitHub leave the list on their own.
A repository added to the installation later shows up after a member connects again, because only a member's own GitHub account can prove they can reach it.

Adding a repository, turning reviews back on, and the digest toggle need the `editor` level on the `stamphog` resource.
Turning reviews off, removing a repository, and changing the review mode or trigger label need `manager`.
So an editor can turn reviews back on for a repository a manager paused.
New repositories start in label-triggered mode, so an editor can turn reviews on without a manager, and widening them to every PR stays a manager decision.

When a repository is turned on in label-triggered mode, or its trigger label changes, Stamphog creates the label in the GitHub repository, because GitHub only offers existing labels on a PR.
This is best-effort: if the app may not write labels there, or the label already exists, nothing changes and nothing is reported.

## Customize the review for your repository

Customization is optional.
A repository with no `.stamphog/` directory reviews under the defaults the engine ships in [`packages/pr-approval-agent/defaults/`](packages/pr-approval-agent/defaults/).

The three `.stamphog/` files are read from the repository's **default branch**, never from the PR head, so a PR cannot rewrite the policy that gates it.
After the sandbox clones the PR head, the server overwrites the checkout's `.stamphog/` with the default-branch versions.
A file the repository does not carry is wiped from the checkout as well, so a planted PR-head copy cannot take its place.

`AGENT_APPROVALS.md` is the exception: it sits in arbitrary folders, so the engine reads it from the checkout, which is the PR head.
That is why its frontmatter is a bounded positive allow-list, and why the `stamphog_policy` deny routes every edit to one to a human reviewer.

| File                 | Required | Default when absent        | How it combines with the default                                                             |
| -------------------- | -------- | -------------------------- | -------------------------------------------------------------------------------------------- |
| `policy.yml`         | No       | The shipped default policy | Merged onto it: mappings merge key by key, a declared list replaces, `extend_<list>` appends |
| `review-guidance.md` | No       | The shipped default norms  | Replaces the default prose as a whole                                                        |
| `steering.md`        | No       | Nothing is added           | Appended to the guidance, because no default exists                                          |
| `AGENT_APPROVALS.md` | No       | No folder overrides        | Read from the PR's own tree, not merged                                                      |

What each file contains, and how per-folder overrides resolve: [the engine's "Policy files" section](packages/pr-approval-agent/README.md#policy-files).

The engine merges a repository's `policy.yml` onto its shipped default, so a repository declares only what it changes:

- A mapping merges key by key. A repository can add one deny category, or change one field of an inherited category, and everything it leaves out stays inherited, including future additions upstream.
- A list the repository declares replaces the default's list. That is how a repository drops an inherited pattern.
- An `extend_<name>` key appends to the inherited `<name>` list, for example `extend_paths` under a category's `match` or `extend_path_patterns` under `allow`. Declaring both `<name>` and `extend_<name>`, or extending a list the default does not have, fails the run closed.

A repository that only wants a bigger size gate and one more pattern in a deny category writes this:

```yaml
size_gate:
  max_lines: 1500
  max_files: 60
deny:
  infra_cicd:
    match:
      extend_paths:
        - '^deploy/'
```

A global limit may not exceed the matching ceiling under `overrides`, so a repository that wants to go past the shipped ceilings declares both.
The engine validates the merged document with its strict loader.
The `stamphog_policy` self-governance deny can gain patterns but never lose a shipped one: a merged policy without every shipped pattern fails the run closed.

A `policy.yml` that is present but unusable, such as malformed YAML or a non-mapping root, fails the run closed.
The repository declared something, so reviewing under pure defaults would be wrong.

### Deny exceptions

A repository can declare narrow exceptions without copying the hosted `deny` section:

```yaml
deny_exceptions:
  billing:
    - keyword: billing
      path_prefixes: [apps/, argocd/, shared/, state/, charts/]
      extensions: [.yaml, .yml]
  infra_cicd:
    - path_prefixes: [.github/]
```

The example permits agent review of billing-service deployment YAML and GitHub automation paths.
The billing exception skips only the `billing` pattern; `payment`, `stripe`, `invoice`, and `pricing` still match.
New billing patterns and other categories stay inherited because this file does not replace `deny`.

Every rule needs literal directory prefixes relative to the repository root, with a trailing slash.
The optional `extensions` list restricts the rule to those file suffixes.
The optional `keyword` must name an existing literal path-capable pattern in that category; omitting it exempts the category within the selected paths.
All selectors in a rule must match, and multiple rules provide alternative exceptions.
Path prefixes and extensions match without regard to case.

An exception that lifts a denial sends the PR to `T1-agent`, including YAML-only and test-only changes.
The reviewer still evaluates actual effects, independent assurance, and unresolved concerns; exceptions do not grant approval.
Title scrutiny, other categories, prerequisites, and size gates remain active.
Unknown categories or fields, malformed selectors, and any `stamphog_policy` exception fail the run closed.
Exception files use the same default-branch trust boundary as the rest of `policy.yml`, so editing them requires human review.

### The `digest:` key

`policy.yml` may also carry a `digest:` section.
It names a Slack channel that receives all of the repository's merged-PR digests, as one more audience next to the owning teams, so a merge can appear in the repository channel and in a team channel:

```yaml
digest:
  channel: '#my-team'
```

This key belongs to this product, not to the engine, which ignores it.
It is read from the default branch too, so a PR cannot redirect its own digest.

## Daily digest

A repository with the digest turned on gets a daily Slack summary of its merged PRs (`backend/logic/digest_runs.py`, scheduled from `backend/tasks/digest.py`).
Only stamphog-approved merges are digested, so the digest needs reviews enabled for the repository.
A merge fans out to every audience it belongs to, and each audience resolves to a channel in this order:

- A `repo:` audience takes the channel that repository declared under `digest:`.
- A team slug takes the root `owners.yaml` registry of the repository the merge came from.
- A repository carrying no registry inherits the first non-empty registry among the team's connected repositories, in repository name order.
- Otherwise the slug name-matches a Slack channel, and the app joins it.
- A registry-derived or name-matched channel that is shared outside the workspace is skipped. A channel the repository declared under `digest:` is posted to even when shared, because someone chose it on purpose. `notifications: false` on a registry entry opts a team out.

Why the digest works this way: [`docs/digest.md`](docs/digest.md).

## Reviewer routing

Reviewer routing requests reviews from the owners of the changed code (`backend/logic/routing/`, queued by its own webhook consumer).
Owners come from `owners.yaml` at the default branch, read with stamphog's installation token, so a PR cannot name its own reviewers.
When more than one owner is a candidate, one Claude Haiku call through the ai-gateway may cut owners whose part is trivial, with its own short-lived token capped far below the reviewer's.
Pinned owners (sensitive paths and owners of additions) are never cut, forks never reach the model, and any model failure requests everyone.
A comment names the cut owners and why.

`routing_mode` on the repo config decides when routing runs:

- `off` (the default): never.
- `always`: when a PR opens ready for review or is marked ready. It never reads or waits for a verdict, and it routes bot and fork PRs too.
- `fallback`: owners are requested only when stamphog does not approve. If stamphog will not review the head (reviews disabled, a draft, bot or untrusted author, or label mode without the trigger label), routing runs at once, like `always`. Otherwise the head waits for the verdict:
  - An approval requests only the pinned owners of that head that no earlier routing of the PR requested, and says so in the comment. When there are none, it requests nobody.
  - A WAIT keeps waiting, because stamphog reviews again later. A WAIT on a head that was not waiting starts waiting there.
  - Any other outcome (refused, escalate, gated, failed) routes in full.
  - A safety net fires 30 minutes after a head starts waiting. Unless the PR was already routed in full, or its current head was approved, it routes the current head in full, even when the head moved since.
  - Full routing happens at most once per PR, like `always`. After it, later verdicts and safety nets do nothing.
  - A PR that opened before `fallback` was on has no routing record, so its verdicts route nothing. Its reviewers came from elsewhere, and routing it would request again owners its author removed.
  - A verdict that lands before the opening event stores its record is dropped the same way, so the opening event checks for a finished review of the head first and routes by it.

`routing_fork_labels` maps a team slug to a label name. On a fork PR, a kept team with an entry gets that label instead of a review request, so an outside author cannot ping it.

`routing_mode` is set under "Reviewer requests" in the repository's row on the Stamphog page, or with `routing_mode` on the repo config API. Both directions take the `manager` level, like `review_mode`. A placeholder row resets it to `off` when it binds to an installation, like the other review policy fields.
The page offers the setting only when the default branch has a root `owners.yaml` (`GET repo_configs/{id}/owners_file/`, at most one GitHub call per repository every 10 minutes, at a priority the egress limiter can shed), and keeps it in view while it is on, so it can be turned off.
`routing_fork_labels` has no API yet. Set it with a manual DB write, for example `StamphogRepoConfig.objects.for_team(team_id).filter(repository="acme/widgets").update(routing_fork_labels={"team-alpha": "team/alpha"})`.

Routing only adds review requests, so a second assigner that requests every owner leaves the cut nothing to remove.
In PostHog/posthog, `.github/workflows/auto-assign-reviewers.yml` stops when the repository variable `AUTO_ASSIGN_REVIEWERS_PAUSED` is `true`.
Turn routing on first, then set the variable. To roll back, delete the variable first, then turn routing off.

The latest result is stored on `PullRequest.routing` with its mode, trigger (`opened`, `ready_for_review`, `verdict:<outcome>` or `safety_net`), scope (`full` or `pinned`) and status (`waiting`, `routing`, `requested` or `done`).
`full_routed_head`, `pinned_routed_head` (with their `_at` times) and `requested_owners` carry over to every later record, so the PR-level rules hold across pushes.
Routing never writes `payload_updated_at` or the descriptive fields of the row, so it cannot make the review path drop a delivery as stale.

Every routing run (event, verdict or safety net) takes the same steps:

1. A compare-and-swap claim sets `routing` with `claimed_by` (the Celery task id) and `claimed_at`.
2. The plan (kept and cut owners, the user, team and label requests, the comment body) is saved under the claim, with `planned_at`, before any GitHub write.
3. The labels and review requests go out, and the record becomes `requested`.
4. The comment is written or removed, and the record becomes `done`.

A retry of the same task keeps the task id: it reuses a saved plan without a second model call, and after `requested` it only finishes the comment.
While another task holds a claim on any head, the event and verdict tasks retry a minute later and the safety net returns.
A claim older than two hours counts as abandoned, so a task that died does not block the PR.
When GitHub lists fewer files than the PR's `changed_files`, the cut step is skipped (`files_truncated: true`, `llm_skipped: files_truncated`) and every owner found is requested.
`model` is set only when a request reached the gateway.

## How it runs

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`).
The workflow dismisses stale approvals first, waits out other in-flight reviewer bots, then reviews.
The sandbox starts right after the stale-approval sweep and fetches the PR head while the context loads. The checkout starts once the context is stored and runs beside the pre-check and the bot wait. Each step is its own activity, and the workflow does every wait between them. A pre-check verdict posts first, and the workflow then tears down the unused sandbox.
Before the wait, the worker runs the engine's gates alone on the fetched context (`review_local.py --pregate`).
The server also reads every `AGENT_APPROVALS.md` that governs a changed file at the PR head, so the pre-check budgets the size gate like the sandbox does.
When a gate refusal is certain to hold in the full review, stamphog posts it right away with a short LLM note on what the author can do, and skips the wait and the sandbox review.
A migration whose `Migration risk` check has not reported gets the same WAIT the full review would give, without the sandbox review.
Anything less certain, such as a PR with renamed files, a dependency manifest next to a pending migration, or folder files that could not be read, gets the full review.
A dismissed approval is also hidden on the PR timeline as outdated, so superseded reviews do not pile up. Hiding is best-effort and never blocks the dismissal.

Reviews run in an isolated Modal sandbox with per-run minted credentials.
The sandbox fetches the PR head and its merge base at depth 1, checks out the head, and runs `review_local.py` against a pre-fetched context, with no GitHub token inside the sandbox.

Every posted verdict emits a `stamphog_review_timings` event with one `stamphog_timing_<step>_ms` property per step: each context read, the bot wait, the pre-check or sandbox steps, the engine's own phases (uv launch, gates, familiarity, LLM, flush), and the verdict post.

**Stacked PRs.** A stacked PR targets its parent's branch and depends on parent code that has not merged yet.
The sandbox checkout is already the PR head, so the reviewer's Read, Grep and Glob see the post-stack tree and parent symbols resolve.
The server reads the merge base from GitHub's compare API, and the sandbox fetches that commit next to the head, so the diff stays scoped to the PR's own changes.
When the parent merges and GitHub retargets the child onto the default branch, the diff changes without a push, so no `synchronize` event fires and the normal push-dismiss path is skipped.
The webhook path therefore retracts the standing approval on a base retarget (`_retract_approvals_on_base_retarget`) and queues a fresh run, and `post_verdict` rechecks the live base ref and SHA against the reviewed ones before posting.
One limitation stays: a parent branch force-push or rebase without restacking the child emits no child PR event, so the child's approval is only revalidated once the child is restacked or pushed.
How the engine handles a stacked checkout: [`packages/pr-approval-agent/README.md`](packages/pr-approval-agent/README.md#stacked-prs-graphite--git-stacks).

**Self-driving inbox PRs** are the one non-webhook entry.
When a self-driving Inbox implementation run opens its bot-authored draft PR, review_hog's inbox receiver calls the `queue_inbox_pr_review` facade, gated by the assigned reviewers' per-user `stamphog_review_inbox_prs` toggles, and the initial review runs while the PR is still a draft so the verdict is ready at Inbox triage time.
Later pushes re-review through the normal webhook path via a positively identified carve-out, and every other bot author stays refused at every layer.
See [AGENTS.md](AGENTS.md) for the carve-out's invariants.

## Security model

The sandbox runs an LLM over untrusted PR content, so it holds no long-lived secrets.
It gets a per-run `phe_` scoped token from the Go ai-gateway, pinned to `product=aio_stamphog`, capped at $5 and one hour, and revoked when the sandbox is destroyed.
Egress is fenced to an explicit domain allowlist.
Posted bodies are scrubbed and markdown-image-neutralized.
Approvals are governed by a strict supersession protocol, so no approval survives a re-review or a push that changes the PR's diff.
A push that leaves the PR's own unified diff byte-identical, such as a base merge that touches none of its files, keeps the approval standing.
Disabling a repository stops new runs and retracts a standing approval on the next head change, not at the moment of disabling.
Details and invariants: [AGENTS.md](AGENTS.md).

## Where to read more

- [AGENTS.md](AGENTS.md) - the invariants that keep approvals and the sandbox sound.
- [`packages/pr-approval-agent/README.md`](packages/pr-approval-agent/README.md) - the engine: gates, tiers, policy file formats, evidence bundle.
- [`docs/digest.md`](docs/digest.md) - the digest design note.
- [`.stamphog/README.md`](../../.stamphog/README.md) - what the PostHog monorepo itself configures.
