# Skill — reading an agent

How to inspect an existing agent and produce a useful summary,
without dumping JSON at the user.

## The standard inspection flow

For "what does X do?" / "show me X" / "is X healthy?", in this
order — DO NOT skip steps because you already have a partial
mental model from earlier in the session.

1. **Locate the application.** Call `posthog__agent-applications-list` if
   you only have a description, or `posthog__agent-applications-retrieve`
   directly if you have a slug. Capture `id`, `slug`,
   `live_revision_id`, `description`.

2. **Open the live revision.** Call
   `posthog__agent-applications-revisions-retrieve` for
   `live_revision_id`. Capture `spec` (the full JSON) and
   `bundle_sha256`.

3. **Pre-focus in PostHog Code.** If you have `focus_revision`,
   fire `focus_revision({ slug, revisionId: <live_revision_id> })`
   now so the user sees the same screen you do.

4. **Read the system prompt.** Call
   `posthog__agent-applications-revisions-system-prompt` — returns the
   fully-rendered prompt (framework preamble + `agent.md` + skills
   index). This is what the model sees on every turn, so it's the
   most informative single artifact.

5. **List recent sessions.** Call
   `posthog__agent-applications-sessions-list` with the last 50. Look at:
   - `state` distribution (how many `completed` vs `failed` vs
     `closed`)
   - `started_at` recency — when did this agent last run?
   - trigger source mix
   - `usage_total` for cost / token signal

6. **If anything stood out in step 5,** retrieve one or two of the
   outliers (`posthog__agent-applications-sessions-retrieve` + `posthog__agent-applications-session-logs`) for a concrete
   example. Do not list every session — list the patterns.

## The summary shape

Once you have steps 1-5, produce a structured summary in this
shape. The user can ask you to drill into any section.

```text
**weekly-digest** — Sends a weekly product-usage digest to a
designated Slack channel every Monday.

Trigger surface: cron (every Monday 09:00 UTC). No chat / webhook /
mcp / slack entry points.

Models: auto (level medium), reasoning: medium.

Tools (5): @posthog/query, @posthog/slack-post-message,
@posthog/load-skill, @posthog/meta-end-turn, @posthog/meta-end-session.

Skills (3): query-recipes, slack-formatting, digest-template.

Live revision r_xyz789 (frozen 2026-05-12, promoted 2026-05-13).
Bundle sha: ab12cd34…

Recent activity (last 14 days, 2 fires):
- ✅ s_aaa111 (2026-05-26) — completed in 4 turns, $0.04, posted
  to #weekly-digest
- ✅ s_bbb222 (2026-05-19) — completed in 5 turns, $0.05

No failed or closed sessions. No pending approvals.

Want me to: read the system prompt? show the latest digest's
output? pull cost over the last 90 days?
```

## What to mention vs what to suppress

**Mention reflexively:**

- Trigger surface — most users have forgotten what triggers an
  agent
- Model + reasoning level — these drive cost
- Tool surface, including class (native vs custom vs MCP)
- Revision age — agents that haven't been touched in months are
  red flags worth surfacing
- Any session in `failed` state in the last 7 days
- Any pending approvals surfaced by the session you're inspecting
  (the Agent Builder has no approvals-read tool — note them when they
  show up in session logs, don't promise to fetch them)

**Suppress unless asked:**

- The full system prompt (offer to read it; don't paste it)
- The full bundle manifest (offer to list files; don't dump them)
- Token-by-token cost (the average + last 7d total is enough)
- Every session id (the patterns + a couple of outlier ids suffice)

## When the user asks about something specific

Drill in narrowly. Don't repeat the whole summary.

| User asks                      | Right next call                                                                                                                                                |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "show me its prompt"           | `posthog__agent-applications-revisions-system-prompt` for live revision                                                                                        |
| "what skills does it have?"    | Already in `spec.skills[]` — render the table                                                                                                                  |
| "read me skill X"              | `posthog__agent-applications-revisions-bundle-retrieve` — the skill body is in the returned `skills[]`                                                         |
| "what was the latest session?" | `posthog__agent-applications-sessions-list` with `limit: 1`, then `posthog__agent-applications-sessions-retrieve` + `posthog__agent-applications-session-logs` |
| "how much is it costing?"      | Load the `cost-and-quota-analysis` playbook and run the standard query                                                                                         |
| "show me the bundle"           | `posthog__agent-applications-revisions-manifest-retrieve` — file tree only                                                                                     |
| "what's its history?"          | `posthog__agent-applications-revisions-list` — chronological revision states                                                                                   |

## The 'this agent doesn't exist' case

If `posthog__agent-applications-list` doesn't have a slug the user named,
**don't suggest it exists somewhere else and proceed**. Tell them:

> No agent with slug `<x>` in this project. The closest match by name
> is `<y>`. Did you mean that one, or are you in the wrong project /
> wanting to create `<x>` fresh?

Offer to switch context. Don't invent.

## When inspecting multiple agents

Common: "show me everything in this team". Call
`posthog__agent-applications-list` once and produce a table — slug, name,
last-session timestamp, live-revision age, archived flag. Don't
load each one individually; that's a separate request the user can
make after they see the list.

For "audit this team's agents" — load
the `cost-and-quota-analysis` playbook for the cost lens, list the
applications, and combine into one health view. That's its own
mode; the bare inspect flow is per-agent.
