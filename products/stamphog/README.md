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

The bot never posts request-changes.
Approvals are posted as real reviews so they count toward branch protection, once, as the Stamphog app (`stamphog[bot]`), carrying the review body.
Every other verdict is posted once per run as a comment review on the same surface, so approvals and non-approvals for one head never disagree across two lists.
A run that produced no verdict posts a short failure notice the same way, unless a newer run already holds the same head.
The engine reports `APPROVED` and `REFUSED`, and the API exposes them lowercase as `approved` and `refused`.

The trigger label only exists in label-triggered mode, and only a substantive non-approval removes it.
So the label can be re-applied once the feedback is addressed.
A verdict that says nothing about the PR keeps the label, and the next push retries.
`WAIT` means a reviewer bot still had a review in flight, or the `Migration risk` check had not reported yet.
`ERROR` means the run failed before it could judge the PR, because the LLM backend was unreachable or the reviewer hit a non-retryable analysis failure such as its turn limit.
A transient failure must not silently drop labels across every queued PR.

Each run is stored as a `ReviewRun` row with its evidence bundle.
Runs are listed in the Stamphog runs page in the PostHog app (`/stamphog/runs`), and the same data is available through the stamphog API and its MCP tools (review runs, repo configs, digest runs).

## Connect a repository

1. Install the Stamphog GitHub App on your GitHub organization.
2. Open Stamphog in the PostHog app and select **Connect a repository**. The install callback syncs the repositories the installation can reach.
3. Turn on **Enabled** for each repository you want reviewed. A connected repository reviews nothing until you do.
4. Pick a **review mode**: "All PRs" reviews every pull request, "Label-triggered" reviews only PRs carrying the trigger label. Set the trigger label name next to the mode.
5. Turn on **Digest enabled** if you want the daily Slack digest of merged PRs. The project needs a connected Slack integration first, or the digest run stops silently before posting.

Connecting a repository and the digest toggle need the `editor` level on the `stamphog` resource.
The gating fields, which are enabled, review mode and trigger label, need `manager`, because they decide whether a pull request is reviewed at all.

## Customize the review for your repository

Customization is optional.
A repository with no `.stamphog/` directory reviews under the hosted defaults in [`backend/logic/policy_defaults/`](backend/logic/policy_defaults/).

The three `.stamphog/` files are read from the repository's **default branch**, never from the PR head, so a PR cannot rewrite the policy that gates it.
After the sandbox clones the PR head, the server overwrites the checkout's `.stamphog/` with the default-branch versions.
A file the repository does not carry is wiped from the checkout as well, so a planted PR-head copy cannot take its place.

`AGENT_APPROVALS.md` is the exception: it sits in arbitrary folders, so the engine reads it from the checkout, which is the PR head.
That is why its frontmatter is a bounded positive allow-list, and why the `stamphog_policy` deny routes every edit to one to a human reviewer.

| File                 | Required | Default when absent       | How it combines with the default                                                             |
| -------------------- | -------- | ------------------------- | -------------------------------------------------------------------------------------------- |
| `policy.yml`         | No       | The hosted default policy | Section overlay: each top-level section you declare replaces the default's section wholesale |
| `review-guidance.md` | No       | The hosted default norms  | Replaces the default prose wholesale                                                         |
| `steering.md`        | No       | Nothing is added          | Passed through as-is, because no default exists                                              |
| `AGENT_APPROVALS.md` | No       | No folder overrides       | Read from the PR's own tree, not overlaid                                                    |

What each file contains, and how per-folder overrides resolve: [the engine's "Policy files" section](packages/pr-approval-agent/README.md#policy-files).

The overlay means a repository can declare only the sections it wants to change.
A repository that only wants a bigger size gate writes five lines:

```yaml
version: 1
size_gate:
  max_lines: 1000
  max_files: 40
```

Everything else, including every deny category, still comes from the hosted default.
A global limit may not exceed the matching ceiling under `overrides`, so a repository that wants to go past the shipped ceilings declares both sections.
The merged document is validated by the engine's strict loader inside the sandbox, so required sections and the `stamphog_policy` self-governance deny cannot be dropped by omission.

A `policy.yml` that is present but unusable, such as malformed YAML or a non-mapping root, fails the run closed.
The repository declared something, so reviewing under pure defaults would be wrong.

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

## How it runs

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`).
The workflow dismisses stale approvals first, waits out other in-flight reviewer bots, then reviews.

Reviews run in an isolated Modal sandbox with per-run minted credentials.
The sandbox clones the repository, checks out the PR head, and runs `review_local.py` against a pre-fetched context, with no GitHub token inside the sandbox.

**Stacked PRs.** A stacked PR targets its parent's branch and depends on parent code that has not merged yet.
The sandbox checkout is already the PR head, so the reviewer's Read, Grep and Glob see the post-stack tree and parent symbols resolve.
The sandbox fetches the base SHA explicitly during the clone, and the diff stays scoped `base...head`.
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
