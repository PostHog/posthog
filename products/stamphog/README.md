# Stamphog

Approve-first PR review: an LLM reviewer that runs deterministic gates plus a scoped review over a pull request and, when the policy allows it, posts an actual GitHub **approval** — not just comments. Repos opt in per-repo; everything else stays untouched.

## Two runtimes, one engine

The review engine lives in [`tools/pr-approval-agent/`](../../tools/pr-approval-agent/) and runs in two places:

- **GitHub Action** — runs in the repo's own CI with the repo's own secrets (`review_pr.py`).
- **Hosted** (this product) — a GitHub App delivers webhooks here; reviews run in an isolated Modal sandbox with per-run minted credentials (`review_local.py` consumes a pre-fetched context, no GitHub token inside the sandbox).

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`). The workflow dismisses stale approvals _first_, waits out other in-flight reviewer bots, then reviews.

There is one non-webhook entry: **self-driving inbox PRs**. When a self-driving Inbox implementation run opens its (bot-authored, draft) PR, review_hog's inbox receiver calls the `queue_inbox_pr_review` facade — gated by the assigned reviewers' per-user `stamphog_review_inbox_prs` toggles on ReviewHog's settings (any opted-in reviewer is enough) — and the initial review runs while the PR is still a draft so the verdict is ready at Inbox triage time. Later pushes re-review through the normal webhook path via a positively identified carve-out (task linkage through the tasks facade, toggle re-checked through `facade/inbox_hooks.py`); every other bot author stays refused at every layer. See AGENTS.md § the self-driving carve-out.

## The digest

On top of reviews, a repo can enable a daily Slack digest of its merged PRs (`backend/tasks/digest.py`). Only stamphog-approved merges are digested, so the digest needs reviews enabled for the repo.

A merge fans out to every audience it belongs to (`backend/logic/audiences.py`): the author's GitHub team (or the channel the repo declares under `digest:` in `.stamphog/policy.yml`), plus every team owning a file it changed, read back from the ownership the review already resolved. So a team hears both what it shipped and what changed in its area, and a `PullRequestAudience` row per audience is what the daily run claims — one channel failing to post never strands the merge for another.

Each audience resolves to a Slack channel in three steps (`backend/logic/channel_resolution.py`): the repo's declared channel, then the team's entry in the repo's root `owners.yaml` registry (read through `posthog_owners`, which is what routes a team whose channel isn't named after its slug), then a plain name match. A resolved channel is enabled straight away and the app joins it on the first post, so a team's digest starts without anyone wiring it up — channels shared outside the workspace are skipped, and disabling one in the Stamphog scene is a permanent opt-out.

Summaries are written where the diff is. The reviewer emits a one-line `change_summary` alongside its verdict, which is stamped onto the merged PR; the daily run condenses those rather than guessing from PR titles, and for an owning team it also sees which of the changed files are theirs, so a repo-wide sweep that grazed two of them can be dropped as noise.

## Stacked PRs

A stacked PR targets its parent's branch, not the repo's default branch, and depends on parent code that hasn't merged yet.
The sandbox clones and checks out the PR head for every review, so the reviewer's Read/Grep/Glob already see the post-stack tree and parent symbols resolve.
The engine is told the checkout is the head (`head_checkout=True`) so it never builds the Action's separate head worktree, and the prompt flags the PR as stacked (`PRData.stacked`, keyed on the repo's actual default branch).
The diff stays scoped `base...head`.
When the parent merges and GitHub retargets the child onto the default branch, the diff changes without a push: the webhook path retracts the standing approval and queues a fresh run, and `post_verdict` rechecks the live base (ref and SHA) against the reviewed one before posting.
Engine details: [`tools/pr-approval-agent/README.md`](../../tools/pr-approval-agent/README.md#stacked-prs-graphite--git-stacks).

## Configuration

Per-repo settings live on `StamphogRepoConfig` (synced via the GitHub App install flow, managed in the Stamphog scene): review on/off, review mode (auto vs trigger label), digest on/off. Review policy (gates, deny-lists, tiers, ownership) is read from `.stamphog/policy.yml` on the repo's **default branch** — never from the PR head — layered over hosted defaults in [`backend/logic/policy_defaults/`](backend/logic/policy_defaults/).

## Security model, in one paragraph

The sandbox runs an LLM over untrusted PR content, so it holds no long-lived secrets: it gets a per-run OAuth token (scoped to `llm_gateway:read` + the server-mint marker) that only works against the gateway's stamphog route, egress is fenced to an explicit domain allowlist, posted bodies are scrubbed and markdown-image-neutralized, and approvals are governed by a strict supersession protocol so no approval survives events it shouldn't (pushes, re-reviews, repo disable). Details and invariants: [AGENTS.md](AGENTS.md).
