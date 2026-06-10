# Skill — auditing the fleet

The unattended nightly sweep. Once a day the `nightly-fleet-audit`
cron fires this session with no human attached: you look at **every**
agent in the team, find where each one tripped up, propose concrete
fixes as draft revisions, and leave a report behind. Nobody reads
your chat in real time — the memory report and the Slack digest are
the only outputs that survive.

This skill is the orchestration. It leans on two others:

- `debugging-sessions` — the per-session failure taxonomy + how to
  read an event log. Load it the first time you open a bad session.
- `editing-agents-safely` — the draft → validate mechanics. Load it
  before you branch your first proposal.

## What "unattended" changes

Read this before anything else — it inverts several defaults:

1. **No client tools.** `focus_*`, `toast`, `set_secret` all time
   out (no browser). Never call them. Narrate nothing for a UI that
   isn't there.
2. **No promotes, ever.** There is no `session_principal` to approve
   one, so `promote` / `archive` are unreachable by design — and they
   would be wrong here anyway. You **propose**; a human disposes. Your
   write surface this run is: `new-draft-create`, the bundle edit
   tools (`agent-md-update`, `skills-update`, `tools-update`,
   `partial-update`), and `validate-create`. Stop at validate. Do
   **not** `freeze` — a frozen revision reads as "ready to ship", and
   these are unreviewed.
3. **You act under the cron principal, scoped to this team.** Every
   agent you can `list` is in-scope; you can't reach another team's
   fleet, and you shouldn't try.
4. **Budget is finite.** `max_tool_calls` covers the whole fleet, not
   one agent. Triage breadth-first (below) so a 30-agent team doesn't
   spend the entire budget on agent #1.

## The sweep, step by step

### 1. Carry-over — read yesterday first

`memory-read` `reports/fleet-audit/latest.md` (and/or
`memory-search` for `fleet-audit`). You want yesterday's findings so
today's report can say **what changed** instead of re-listing the
same five issues. Hold the prior issue list in mind as you go; tag
each of today's findings new / recurring / resolved.

If there's no prior report, this is the first run — note that in the
report and audit everything fresh.

### 2. Enumerate the fleet

`agent-applications-list`. Drop archived agents. For each remaining
agent you have a slug + id + `live_revision`. That's your worklist.

### 3. Per-agent triage (breadth-first)

For **each** agent, cheapest signal first — only go deep when a
cheap signal is bad:

1. `agent-applications-sessions-list` for the agent, last ~24–48h.
   Bucket by `state`. The cheap red flags:
   - any `failed` / `errored` / `stuck` sessions
   - `completed` sessions pinned at the turn / tool-call cap (ran to
     the limit = probably looping or under-instructed)
   - a cost or turn-count outlier vs the agent's own norm
   - `waiting` sessions whose approval looks abandoned
2. If the buckets are clean, write one line ("healthy, N sessions,
   no failures") and move on. **Most agents should be one line.**
3. If a bucket is dirty, open the worst 1–3 sessions with
   `agent-applications-sessions-retrieve` + `agent-applications-session-logs`
   and run the `debugging-sessions` taxonomy. You're after the
   **root cause**, not a restatement of the symptom — "hit
   max_tool_calls because it re-ran the same `@posthog/query` 40×
   after an empty result, with no give-up path in agent.md" beats
   "limit_exceeded".

Cite session ids for every claim. A finding with no session id
behind it is a guess, and guesses are how this report loses trust.

For the population view — failure-rate, cost, and p95 latency rolled
up per agent, or "which sessions tripped up this week" in one query —
load `skills/querying-ai-observability` and HogQL the `$ai_*` events
the runner captured into this team's project. It's cheaper than
retrieving every session and surfaces systemic patterns (one root
cause across many sessions) the per-session view misses; use it to
pick _which_ sessions are worth a deep `sessions-retrieve`.

### 4. Turn a root cause into a proposal

Only when you can name a **specific, concrete** change. Vague
"could be more robust" notes go in the report as observations, not
as drafts. A good proposal is one a reviewer can read the diff of
and approve in a minute.

For each fix:

1. `new-draft-create` from the agent's `live_revision`
   (`source_revision_id`) — clones every file so your edit is
   surgical.
2. Apply the **smallest** change that addresses the root cause:
   - prompt/loop bug → `agent-md-update` or `skills-update`
   - missing/over-broad tool, wrong limit, wrong model/reasoning →
     `partial-update` on the spec
   - keep each draft to **one** root cause. Don't bundle unrelated
     fixes into one revision — a reviewer should be able to take or
     leave each independently.
3. `validate-create` on the draft. If it doesn't validate, your
   proposal is wrong — fix it or drop it; don't leave a broken draft
   lying around.
4. Record the draft revision id + a one-line "what this changes and
   why" in the report. **Stop here.** No freeze, no promote.

If a root cause has no safe surgical fix (needs a secret rotated, a
human decision, a Slack reconfig), write it as a **recommendation**
in the report instead of forcing a draft. Better an honest "this
needs you to decide X" than a draft that papers over it.

### 5. Write the report to memory

`memory-write` two paths:

- `reports/fleet-audit/{date}.md` — the dated archive.
- `reports/fleet-audit/latest.md` — same content, the stable handle
  tomorrow's carry-over reads.

Report shape:

```text
# Fleet audit — {date}

## TL;DR
- {1–4 bullets: the things a human should act on today, worst first}
- New since yesterday: {…}   Resolved: {…}   Still open: {…}

## Findings
### {agent-slug} — {healthy | degraded | failing}
- symptom (session ids: …)
- root cause
- proposal: draft {revision-id} — {one line}  |  recommendation: {…}
- vs yesterday: new | recurring | resolved

### {next agent} …

## Healthy ({count})
{agents with nothing to report, one line each}
```

Lead with the delta. A reviewer skimming at 8am wants "what's new or
worse" in the first five lines, not a re-read of last night.

### 6. Post the Slack digest

The condensed projection of the TL;DR + the agents that need
action. `slack-post-message` to the team's fleet-audit channel.

**Resolving the channel.** The channel id is operator config, not
something you invent:

1. Look for it in memory: `memory-read` `config/fleet-audit.md`
   (a `slack_channel: C0XXXXXXX` line). That's the source of truth.
2. If it's not set, **skip the Slack post silently** — do not guess a
   channel, do not fail the run. The memory report is complete on its
   own; note `slack: not configured` in the report so the operator
   knows to set `config/fleet-audit.md` if they want the digest.

Slack mrkdwn, not markdown: bold is `*text*`, links are
`<url|text>`, headers don't render. Keep it phone-readable — ~10–15
lines, worst-first, link nothing the reader can't act on. If
`slack-post-message` errors (`SLACK_BOT_TOKEN` missing / bad
channel), log it in the report (`slack: failed — <reason>`) and
finish — the report already landed, the run is not a failure.

## Scope guard — what this run must NOT do

- **No promotes / freezes / archives.** Proposals only. (Re-stating
  because it's the one rule that, broken, touches production.)
- **No edits to the live revision in place.** Always branch a draft.
- **No deletions** (`skills-destroy` / `tools-destroy`) — destructive
  and unreviewed is the worst combination.
- **No raw secrets.** If an agent's problem is a missing/expired
  credential, that's a recommendation for a human, never a value you
  set.
- **Don't audit yourself into the ground.** If you're burning budget
  and half the fleet is still untriaged, write what you have, mark
  the rest "not reached this run", and end. A partial report that
  ships beats a complete one that hits the wall mid-write.
