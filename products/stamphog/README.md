# Stamphog

Approve-first PR review: an LLM reviewer that runs deterministic gates plus a scoped review over a pull request and, when the policy allows it, posts an actual GitHub **approval** — not just comments. Repos opt in per-repo; everything else stays untouched.

## The engine

The review engine lives in [`packages/pr-approval-agent/`](packages/pr-approval-agent/).
A GitHub App delivers webhooks here, and reviews run in an isolated Modal sandbox with per-run minted credentials: `review_local.py` consumes a pre-fetched context, with no GitHub token inside the sandbox.
`review_pr.py` in the same directory is the manual entrypoint for reviewing a PR from your own checkout, which fetches over the network instead.

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`). The workflow dismisses stale approvals _first_, waits out other in-flight reviewer bots, then reviews.

There is one non-webhook entry: **self-driving inbox PRs**. When a self-driving Inbox implementation run opens its (bot-authored, draft) PR, review_hog's inbox receiver calls the `queue_inbox_pr_review` facade — gated by the assigned reviewers' per-user `stamphog_review_inbox_prs` toggles on ReviewHog's settings (any opted-in reviewer is enough) — and the initial review runs while the PR is still a draft so the verdict is ready at Inbox triage time. Later pushes re-review through the normal webhook path via a positively identified carve-out (task linkage through the tasks facade, toggle re-checked through `facade/inbox_hooks.py`); every other bot author stays refused at every layer. See AGENTS.md § the self-driving carve-out.

## The digest

On top of reviews, a repo can enable a daily Slack digest of its merged PRs (`backend/logic/digest_runs.py`, scheduled from `backend/tasks/digest.py`). Only stamphog-approved merges are digested, so the digest needs reviews enabled for the repo.

A merge fans out to every audience it belongs to (`backend/logic/audiences.py`): every team owning a file it changed, read back from the ownership the review already resolved, plus a per-repo audience when a repo declares its own channel under `digest:` in `.stamphog/policy.yml`. A team hears about code it owns, not about everywhere its members touched, so a merge nobody owns in a repo that declares nothing reaches nobody — that is an ownership gap, and `hogli owners:unowned` is where it gets fixed. A `PullRequestAudience` row per audience is what the daily run claims, so one channel failing to post never strands the merge for another.

Routing is config, and it lives in the repositories rather than in this database (`backend/logic/channel_resolution.py`). Nothing is stored: a run resolves, posts, and records where it went, so changing a declaration moves the next morning's digest. The order is proximity. A `repo:` audience takes the channel that repo declared. A team slug takes the root `owners.yaml` registry of the repo the merge came from, and a repo that carries a registry answers for its own merges completely, including by omission — a registry lists the teams whose derived name is wrong, so a missing slug means the derived name is right. A repo carrying no registry inherits one, which is what lets `charts` route `logs` to `#team-apm` because the monorepo says so. Otherwise the slug name-matches a Slack channel, and the app joins one it was never invited to, so a team's digest starts without anyone wiring it up. Channels shared outside the workspace are skipped, and `notifications: false` on a registry entry is how a team opts out. The registry is asked where _automation_ posts (`notifications`), which falls back to the team's own `slack` channel, so a team that wants bots somewhere quieter says so once and every producer follows.

Two repos declaring one team is a scope, not a conflict. Each answers for the merges that came from it, so one audience can resolve to two channels in a run and the digest partitions between them. No merge is posted twice and no declaration is discarded.

Summaries are written where the diff is. The reviewer emits a one-line `change_summary` alongside its verdict, which is stamped onto the merged PR; the daily run condenses those rather than guessing from PR titles, and for an owning team it also sees which of the changed files are theirs, so a repo-wide sweep that grazed two of them can be dropped as noise.

A digest posts as two messages (`backend/logic/slack_digest.py`). The channel gets one lead: the model's headline when it judged something worth a channel-level sentence, and the scope line ("3 of 11 stamphog-approved merges") when it did not. The per-change lines go in a thread under that lead, so a team spends one line of its channel and opens the rest by choice. The footer marks the digest as beta and asks for a reaction or a reply, which is where feedback on the digest itself lands. A failed thread reply never fails the run — the lead is already posted and the run's PRs are consumed on that basis, so treating it as a failure would post the same lead again the next day.

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
