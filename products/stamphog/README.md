# Stamphog

Approve-first PR review: an LLM reviewer that runs deterministic gates plus a scoped review over a pull request and, when the policy allows it, posts an actual GitHub **approval** — not just comments. Repos opt in per-repo; everything else stays untouched.

## Two runtimes, one engine

The review engine lives in [`tools/pr-approval-agent/`](../../tools/pr-approval-agent/) and runs in two places:

- **GitHub Action** — runs in the repo's own CI with the repo's own secrets (`review_pr.py`).
- **Hosted** (this product) — a GitHub App delivers webhooks here; reviews run in an isolated Modal sandbox with per-run minted credentials (`review_local.py` consumes a pre-fetched context, no GitHub token inside the sandbox).

Hosted flow: webhook → Celery (`backend/tasks/tasks.py`) → Temporal (`backend/temporal/workflow.py`) → sandboxed engine → verdict posted back (`post_verdict`). The workflow dismisses stale approvals _first_, waits out other in-flight reviewer bots, then reviews.

## The digest

Independently of reviews, a repo can enable a daily Slack digest of its merged PRs (`backend/tasks/digest.py`): merges are stamped with an audience (author's GitHub team, or a channel the repo declares under `digest:` in `.stamphog/policy.yml`), summarized with a small model, and posted per channel. Review-enabled repos digest only stamphog-approved merges; digest-only repos (review off) digest every merge.

## Configuration

Per-repo settings live on `StamphogRepoConfig` (synced via the GitHub App install flow, managed in the Stamphog scene): review on/off, review mode (auto vs trigger label), digest on/off. Review policy (gates, deny-lists, tiers, ownership) is read from `.stamphog/policy.yml` on the repo's **default branch** — never from the PR head — layered over hosted defaults in [`backend/logic/policy_defaults/`](backend/logic/policy_defaults/).

## Security model, in one paragraph

The sandbox runs an LLM over untrusted PR content, so it holds no long-lived secrets: it gets a per-run OAuth token (scoped to `llm_gateway:read` + the server-mint marker) that only works against the gateway's stamphog route, egress is fenced to an explicit domain allowlist, posted bodies are scrubbed and markdown-image-neutralized, and approvals are governed by a strict supersession protocol so no approval survives events it shouldn't (pushes, re-reviews, repo disable). Details and invariants: [AGENTS.md](AGENTS.md).
