## Workflow: act on an actionable report

When the user wants to _do_ something about a report — "fix this inbox item", "turn this into a
PR", "implement this" — not just read it. A `ready` report with
`actionability: immediately_actionable` is the usual candidate. The discipline that matters here:
**a report is a diagnosis, not ground truth — verify it against the actual code before you
implement.** Reports from `signals_scout` (and any LLM-research source) are especially worth
double-checking; their `summary` often reads as a confident root-cause with file and function
names, but it can be stale or wrong.

### Step 1 — Retrieve, check existing work, and claim it

```json
inbox-reports-retrieve
{ "id": "<report_uuid>" }
```

Before doing any work, look at:

- `already_addressed` — if `true`, the fix may already be in flight or merged; confirm with the
  user before duplicating it.
- `pull_requests` — inspect existing PRs before opening another; a report can have a stack or PRs across repositories.
- `work_state` and `assignee` — show whether someone else has already picked it up. A takeover is
  allowed, but make it deliberate rather than overlooking active work.
- `status` — only `ready` reports carry a finished judgment. A `candidate` / `pending_input`
  report hasn't been researched yet; don't implement off a half-formed summary.

Before starting research or implementation, claim the report:

```json
posthog:inbox-reports-claim
{ "report_id": "<report_uuid>" }
```

Save the returned `assignee.claim_id` and pass it on subsequent work updates and artefact writes.
Taking over another actor requires `takeover=true`; stale claim IDs are rejected.
The claim is attributed to the current internal task or external MCP client. Claims do not expire, so
release the report whenever you walk away without landing a fix.
Dismissing a report releases its claim for you.
A resolved, closed, or Monitoring report keeps its claim, because a late open pull request moves it back to ready.
Release clears ownership only; an attached pull request stays on the report.
An MCP client that acts for a person can release that person's own claim.

### Step 2 — Verify the diagnosis against the code (do not skip)

Start by reading the report's work log — its evidence and the judgments behind it:

```json
inbox-report-artefacts-list
{ "report_id": "<report_uuid>" }
```

This surfaces the `signal_finding` evidence, the status/priority/actionability judgments, and any
`commit` / `task_run` history — exactly the "why it exists and what's already been done" you need
before touching code. Then the report's `summary` will name files, functions, and sometimes line
numbers. **Open them and confirm the claim holds** — that the cited code exists, still looks the
way the report describes, and actually produces the described failure. As a deeper fallback, pull
the raw underlying signals via the `signals` skill (`metadata.report_id`) if you need the signal
text behind the curated findings. If the diagnosis doesn't hold up, say so and stop — a wrong
report is itself a useful finding (and a candidate for _dismiss_ below), not a license to write a
speculative fix. Release the claim you took in Step 1 before you stop, so the report returns to the
unclaimed view instead of reading as active work nobody is doing:

```json
posthog:inbox-reports-claim
{ "report_id": "<report_uuid>", "claim_id": "<claim_uuid>", "release": true }
```

### Step 3 — Scope the fix to the right layer

- If `source_products` includes `signals_scout` and the root cause is in a **scout's own
  behavior** (the prompt it runs, a threshold it uses), the better fix is often the scout's
  `SKILL.md`, not the harness. Note that per-team custom scouts live in the user's Skills Store,
  not this repo, so the fix site may be out of reach of a repo PR — flag that to the user.
- Otherwise treat it like any normal change: follow the repo's conventions (`CLAUDE.md`,
  area-specific skills), make the change minimal, and add a regression test that would have caught
  the reported failure.

### Step 4 — Open the PR and attach it

Open the PR following the repo's PR conventions, then attach it to the report:

```json
posthog:inbox-reports-claim
{
  "report_id": "<report_uuid>",
  "claim_id": "<claim_uuid>",
  "pull_requests": ["https://github.com/example/repository/pull/123"]
}
```

PR links are additive and retries do not duplicate them. Send every known PR together so completion
considers the entire stack. The same PR may be attached to multiple reports. Connected repositories receive immediate state
validation and webhook updates. PRs from unconnected repositories are accepted with unknown state,
so resolve those reports manually after the work lands. Also reference the report's `_posthogUrl`
in the PR description so the loop is traceable from either side.

**Don't resolve a report because you opened a PR.** A report resolves when all linked PRs are closed
or merged and at least one merged.
Where the organization has Monitoring on and the report has open follow-up checks, it enters `monitoring` instead (see [Monitoring](report-state.md#monitoring)).
If all closed without merging, it is suppressed. Any open, draft,
or unknown PR prevents automatic completion. Resolving by hand at PR-open
time asserts work that hasn't landed, and a reviewer looking at the inbox can't tell the difference.
Manual resolve is for fixes a PR merge will never cover — a skill-body change, a config change, a
`NO_REPO` report — see the [report state workflow](report-state.md).
