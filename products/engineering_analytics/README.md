# Engineering analytics

Answers about your PR and CI lifecycle, served as MCP tools to whatever agent you already use (Claude Code, Cursor, PostHog AI) and to PostHog Code itself.

## What you can ask

- "Of the PRs I opened recently, which ones merged, which got reverted, which are still stuck and why?"
- "Which CI workflows have been slowest this week, and which product areas do they belong to?"
- "Is `products/X` getting slower or faster to land PRs against?"
- "The deploy that just went out bumped error rate. Which PRs were in that deploy?"
- "Did the PR I just merged actually fix the issue I was trying to fix?"

## How you use it

The primary surface is MCP tools, callable two ways:

- An engineer driving an agent (Claude Code, Cursor, PostHog AI in Slack) asking about their own monorepo.
- PostHog Code itself, autonomously, calling the same tools on its own PRs — to diagnose why a PR is stuck, decide whether to retry, and eventually see how a merged change behaved in production.

A read-only UI on the PostHog design system renders a subset of the same data for show-and-tell.

## Why this product exists

PostHog already tracks code at both ends of the agent-to-prod loop.
Upstream: PostHog Code generates code and opens PRs.
Downstream: PostHog product analytics observes the running app (events, errors, flag exposures, surveys, replays).

The middle — CI, review, merge, deploy — is invisible to both ends today.
Engineering analytics is the middle.

## Concepts that shape the metrics

**PR** — an open GitHub pull request, draft or ready-for-review. The atomic unit of value.

**Draft phase** — experimentation. Low-friction expectations.

**Ready-for-review phase** — high stakes. The north star is to shorten ready-for-review-to-merge without removing useful friction.

**Bots and drafts** — excluded by default in cohort metrics like throughput and cycle time. First-class in bot-impact analysis so they're never silently stripped everywhere.

## Where to next

- [PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md) — motivations, persona, locked decisions, full glossary.
- [SPEC.md](./SPEC.md) — engineering contract: architecture, canonical types, file layout.
