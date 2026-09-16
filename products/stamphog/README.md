# Stamphog

Stamphog is an approve-first pull request reviewer.
It runs deterministic gates and a scoped LLM review over a PR and, when the policy allows it, posts a real GitHub approval instead of comments.
Repositories opt in one at a time, and nothing else is touched.

## What a PR author sees

A repository either reviews every PR or waits for its trigger label, depending on its review mode.
Stamphog then posts one of five verdicts.

| Verdict  | Where it lands                          | Trigger label |
| -------- | --------------------------------------- | ------------- |
| APPROVED | A real GitHub review by `stamphog[bot]` | Kept          |
| REFUSED  | The sticky comment                      | Removed       |
| ESCALATE | The sticky comment                      | Removed       |
| WAIT     | The sticky comment                      | Kept, retries |
| ERROR    | The sticky comment                      | Kept, retries |

The bot never posts request-changes.
Approvals are posted as real reviews so they count toward branch protection.
Every other verdict goes into one sticky comment that is updated in place on each run, so repeated refusals do not stack up on the PR.

Only a substantive non-approval removes the trigger label, so the label can be re-applied once the feedback is addressed.
A verdict that says nothing about the PR keeps the label, and the next push retries.
`WAIT` means an allowlisted reviewer bot still had a review in flight, or the `Migration risk` check had not reported yet.
`ERROR` means the run could not reach its LLM backend.

Runs are listed in the Stamphog runs page in the PostHog app (`/stamphog/runs`), with the evidence bundle for each run.
The same data is available through the stamphog API and its MCP tools (review runs, repo configs, digest runs).

## Connect a repository

1. Install the Stamphog GitHub App on your GitHub organization.
2. Open Stamphog in the PostHog app and select **Connect a repository**. The install callback syncs the repositories the installation can reach.
3. Turn on **Enabled** for each repository you want reviewed. A connected repository reviews nothing until you do.
4. Pick a **review mode**: "All PRs" reviews every pull request, "Label-triggered" reviews only PRs carrying the trigger label. Set the trigger label name next to the mode.
5. Turn on **Digest enabled** if you want the daily Slack digest of merged PRs.

Connecting a repository and the digest toggle need the `editor` level on the `stamphog` resource.
The gating fields, which are enabled, review mode and trigger label, need `manager`, because they decide whether a pull request is reviewed at all.

## Customize the review for your repository

Customization is optional.
A repository with no `.stamphog/` directory reviews under the hosted defaults in [`backend/logic/policy_defaults/`](backend/logic/policy_defaults/).

All four files are read from the repository's **default branch**, never from the PR head, so a PR cannot rewrite the policy that gates it.

| File                 | Required | Default when absent       | How it combines with the default                                                             |
| -------------------- | -------- | ------------------------- | -------------------------------------------------------------------------------------------- |
| `policy.yml`         | No       | The hosted default policy | Section overlay: each top-level section you declare replaces the default's section wholesale |
| `review-guidance.md` | No       | The hosted default norms  | Replaces the default prose wholesale                                                         |
| `steering.md`        | No       | Nothing is added          | Appended to the reviewer prompt under a marked section                                       |
| `AGENT_APPROVALS.md` | No       | No folder overrides       | Per-folder grants for the keys `policy.yml` delegates                                        |

A `policy.yml` that is present but unusable, such as malformed YAML or a non-mapping root, fails the run closed.
The repository declared something, so reviewing under pure defaults would be wrong.

Full reference, including the overlay example and the folder-override contract: [`.stamphog/README.md`](../../.stamphog/README.md).

## Daily digest

A repository with the digest turned on gets a daily Slack summary of its merged PRs (`backend/logic/digest_runs.py`, scheduled from `backend/tasks/digest.py`).
Only stamphog-approved merges are digested, so the digest needs reviews enabled for the repository.
A merge fans out to every audience it belongs to, and each audience resolves to a channel in this order:

- A `repo:` audience takes the channel that repository declared under `digest:` in `.stamphog/policy.yml`.
- A team slug takes the root `owners.yaml` registry of the repository the merge came from.
- A repository carrying no registry inherits the monorepo's.
- Otherwise the slug name-matches a Slack channel, and the app joins it.
- Channels shared outside the workspace are skipped, and `notifications: false` on a registry entry opts a team out.

Why the digest works this way: [`docs/digest.md`](docs/digest.md).

## How it runs

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`).
The workflow dismisses stale approvals first, waits out other in-flight reviewer bots, then reviews.

The review engine lives in [`packages/pr-approval-agent/`](packages/pr-approval-agent/).
Reviews run in an isolated Modal sandbox with per-run minted credentials: `review_local.py` consumes a pre-fetched context, with no GitHub token inside the sandbox.
`review_pr.py` in the same directory is the manual entrypoint for reviewing a PR from your own checkout, which fetches over the network instead.

**Stacked PRs.** A stacked PR targets its parent's branch and depends on parent code that has not merged yet.
The sandbox clones and checks out the PR head for every review, so the reviewer's Read, Grep and Glob already see the post-stack tree and parent symbols resolve.
The engine is told the checkout is the head (`head_checkout=True`), and the prompt flags the PR as stacked (`PRData.stacked`, keyed on the repository's actual default branch).
The diff stays scoped `base...head`.
When the parent merges and GitHub retargets the child onto the default branch, the diff changes without a push: the webhook path retracts the standing approval and queues a fresh run, and `post_verdict` rechecks the live base against the reviewed one before posting.
Engine details: [`packages/pr-approval-agent/README.md`](packages/pr-approval-agent/README.md#stacked-prs-graphite--git-stacks).

**Self-driving inbox PRs** are the one non-webhook entry.
When a self-driving Inbox implementation run opens its bot-authored draft PR, review_hog's inbox receiver calls the `queue_inbox_pr_review` facade, gated by the assigned reviewers' per-user `stamphog_review_inbox_prs` toggles, and the initial review runs while the PR is still a draft so the verdict is ready at Inbox triage time.
Later pushes re-review through the normal webhook path via a positively identified carve-out, and every other bot author stays refused at every layer.
See [AGENTS.md](AGENTS.md) for the carve-out's invariants.

## Security model

The sandbox runs an LLM over untrusted PR content, so it holds no long-lived secrets.
It gets a per-run `phe_` scoped token from the Go ai-gateway, pinned to `product=aio_stamphog`, capped at $5 and one hour, and revoked when the sandbox is destroyed.
Egress is fenced to an explicit domain allowlist.
Posted bodies are scrubbed and markdown-image-neutralized.
Approvals are governed by a strict supersession protocol, so no approval survives a push, a re-review or a repository being disabled.
Details and invariants: [AGENTS.md](AGENTS.md).

## Where to read more

- [AGENTS.md](AGENTS.md) - the invariants that keep approvals and the sandbox sound.
- [`packages/pr-approval-agent/README.md`](packages/pr-approval-agent/README.md) - the engine: gates, tiers, ownership, evidence bundle.
- [`.stamphog/README.md`](../../.stamphog/README.md) - the full repository configuration reference.
- [`docs/digest.md`](docs/digest.md) - the digest design note.
