# Stamphog

Approve-first PR review: an LLM reviewer that runs deterministic gates plus a scoped review over a pull request and, when the policy allows it, posts an actual GitHub **approval** — not just comments. Repos opt in per-repo; everything else stays untouched.

## Two runtimes, one engine

The review engine lives in [`tools/pr-approval-agent/`](../../tools/pr-approval-agent/) and runs in two places:

- **GitHub Action** — runs in the repo's own CI with the repo's own secrets (`review_pr.py`).
- **Hosted** (this product) — a GitHub App delivers webhooks here; reviews run in an isolated Modal sandbox with per-run minted credentials (`review_local.py` consumes a pre-fetched context, no GitHub token inside the sandbox).

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`). The workflow dismisses stale approvals _first_, waits out other in-flight reviewer bots, then reviews.

## Self-driving inbox PRs

Bot-authored PRs are refused everywhere, with one carve-out: a PR positively identified (task linkage through the tasks facade, never author-login matching) as a PostHog Code self-driving implementation PR is reviewed — while still draft, so the verdict is ready at Inbox triage time. The gate is the acting reviewer's per-user `stamphog_review_inbox_prs` toggle on ReviewHog's settings row (the Code review scene), plus a synced + enabled `StamphogRepoConfig` for the PR's repo; the per-repo review mode does not apply to these PRs. The initial review is queued by ReviewHog's inbox receiver through `facade/api.py::queue_self_driving_pr_review`; subsequent pushes flow through the webhook path, which re-checks the toggle before re-reviewing but always dismisses stale approvals regardless. Inside the engine the hosted context sets `self_driving_review: true`, which is the only thing that relaxes the bot-author refusal and the draft prerequisite — the Action never sets it.

## The digest

Independently of reviews, a repo can enable a daily Slack digest of its merged PRs (`backend/tasks/digest.py`): merges are stamped with an audience (author's GitHub team, or a channel the repo declares under `digest:` in `.stamphog/policy.yml`), summarized with a small model, and posted per channel. Review-enabled repos digest only stamphog-approved merges; digest-only repos (review off) digest every merge.

## Configuration

Per-repo settings live on `StamphogRepoConfig` (synced via the GitHub App install flow, managed in the Stamphog scene): review on/off, review mode (auto vs trigger label), digest on/off. Review policy (gates, deny-lists, tiers, ownership) is read from `.stamphog/policy.yml` on the repo's **default branch** — never from the PR head — layered over hosted defaults in [`backend/logic/policy_defaults/`](backend/logic/policy_defaults/).

## Security model, in one paragraph

The sandbox runs an LLM over untrusted PR content, so it holds no long-lived secrets: it gets a per-run OAuth token (scoped to `llm_gateway:read` + the server-mint marker) that only works against the gateway's stamphog route, egress is fenced to an explicit domain allowlist, posted bodies are scrubbed and markdown-image-neutralized, and approvals are governed by a strict supersession protocol so no approval survives events it shouldn't (pushes, re-reviews, repo disable). Details and invariants: [AGENTS.md](AGENTS.md).
