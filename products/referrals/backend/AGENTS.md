# Referrals research

Two agentic flows that surface PostHog referral candidates from independent sources, so the
growth team can DM warm contacts and ask them to refer other companies.

Both flows are single-turn `MultiTurnSession` runs against the sandbox primitive from
`products/tasks/backend/services/`. They share nothing beyond that primitive: different data
sources, different sandbox tools, different identity systems, different cadences. They are
intentionally not combined into a single multi-step session — see _Design notes_ below.

## Layout

```text
products/referrals/backend/
├── apps.py                 # Django app config (label="referrals")
├── AGENTS.md               # this file
├── twitter/                # Twitter/X enthusiast flow
│   ├── research/
│   │   ├── prompts.py
│   │   └── research.py     # run_twitter_research(...)
│   └── x_dm.py             # send_referral_dms(...) — OAuth refresh, lookup, DM send
├── internal/research/      # PostHog power-user flow
│   ├── prompts.py
│   └── research.py         # run_internal_research(...)
├── temporal/               # production scheduling layer
│   ├── activities.py       # run_*_referral_research_activity + placeholder hooks
│   ├── workflows.py        # TwitterReferralResearchWorkflow, InternalReferralResearchWorkflow
│   ├── schedules.py        # create_*_referral_research_schedule
│   └── constants.py        # workflow names, schedule IDs, timeouts, retry policy
└── management/commands/
    ├── analyze_twitter_posts.py
    └── analyze_internal_users.py
```

## When to use which

|                     | Twitter flow                                                         | Internal flow                                                                |
| ------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **What it finds**   | Twitter users posting enthusiastic, personal endorsements of PostHog | Existing PostHog users whose behaviour looks like a referral target          |
| **Data source**     | twitterapi.io advanced_search                                        | PostHog ClickHouse via MCP `execute-sql`                                     |
| **Sandbox tool**    | `curl` (API key inlined into prompt)                                 | PostHog MCP (`execute-sql`) — context needs `posthog_mcp_scopes="read_only"` |
| **Output identity** | Twitter handle                                                       | PostHog email + org                                                          |
| **Time window**     | Last 1 hour (configurable)                                           | 30–180 days (per-signal, fixed in queries)                                   |
| **Cadence**         | Hourly Temporal schedule                                             | Hourly Temporal schedule (dedup deferred)                                    |
| **Side effect**     | DM each candidate via X v2 (`/2/dm_conversations/with/:id/messages`) | _Placeholder_: log only; will send a referral-ask email per candidate        |

## Twitter flow

`twitter/research/research.py` → `run_twitter_research(context, *, api_key, since_unix_ts, hours, ...)`.

The prompt embeds an exact `curl` command (with the API key inlined) for `twitterapi.io`. The
agent fetches all PostHog mentions in the window, applies six positive-signal categories
(superlative praise, firm preference, active recommendation, operational standardization,
specific positive experience, ecosystem alignment), and returns `TwitterReferralCandidates`
with `{id, user, reason}` per match.

### Local debug

```bash
# Default: last 1 hour
TWITTERAPI_IO_KEY=... python manage.py analyze_twitter_posts

# Wider window or verbose logs
python manage.py analyze_twitter_posts --hours 6
python manage.py analyze_twitter_posts --verbose
```

`TWITTERAPI_IO_KEY` must be in the shell environment of the command (it is injected into the
prompt at call time; the sandbox itself does not need env-var plumbing).

The DM side effect (in the activity, not this command) additionally needs `X_CLIENT_ID`,
`X_CLIENT_SECRET`, and `X_REFRESH_TOKEN` to be set on the worker. Use the helper at
`.scratch/x_oauth2_x/server.mjs` to do the one-time OAuth 2.0 dance and obtain the initial
refresh token; subsequent rotations are persisted to Django cache automatically.

## Internal flow

`internal/research/research.py` → `run_internal_research(context, ...)`.

The prompt embeds three validated HogQL queries the agent runs via PostHog MCP `execute-sql`:

1. **Signal query** — UNION-ALL of four behavioural CTEs (`login_streak`,
   `invited_colleagues`, `product_breadth`, `nps_promoter`), ordered by `signal_count DESC`,
   capped at `LIMIT 20`. Returns the candidate pool the agent reasons over.
2. **Person-detail lookup** — `argMax(person.properties.*, timestamp) … GROUP BY distinct_id`
   collapses each candidate to one row with the most recent email / name / org_id. With ≤20
   IDs this is a single query, no batching.
3. **Org-name lookup** — display names via `$groupidentify` events with `properties.$group_0`
   as the key (the `$group_set.organization_id` JSON field returns blank — known footgun).

The agent applies its own judgement (no hard signal-count threshold), weighting the strong
advocacy signals (`nps_promoter`, `invited_colleagues`) above engagement-only signals
(`login_streak`, `product_breadth`), and returns `InternalReferralCandidates` with
`{distinct_id, email, org_id, org_name, reason}` per match.

### MCP scopes wiring

The internal flow requires `context.posthog_mcp_scopes` to be set — the orchestrator raises a
`ValueError` if it is `None`. `"read_only"` is the right default; it expands to all read
scopes including `query:read`, which is what `execute-sql` needs.

`resolve_sandbox_context_for_local_dev` does not set scopes, so the management command and
the production activity both layer them on with
`dataclasses.replace(context, posthog_mcp_scopes="read_only")`.

### Local debug

```bash
python manage.py analyze_internal_users
python manage.py analyze_internal_users --verbose
```

Requires a GitHub integration on the first team in the local database — the resolver enforces
it, and `Task.create_and_run` needs it to bootstrap any sandbox, even with our dummy repo
`PostHog/.github`.

## Production scheduling

Both flows are scheduled by Temporal on the `TASKS_TASK_QUEUE` worker. The schedule layer is
intentionally thin — the scheduling glue does not know anything about Twitter or HogQL.

```text
ScheduleSpec(every=1h)           # in posthog/temporal/schedule.py
  → Workflow (run on TASKS_TASK_QUEUE)
    → Activity (Heartbeater + scoped_temporal)
      → resolve_sandbox_context_for_local_dev(...)
      → run_{twitter|internal}_research(...)        # spawns a Task → process-task workflow
      → _post_referral_dms | _send_referral_emails_placeholder
```

### Registered surface

| Layer       | Twitter                                  | Internal                                  |
| ----------- | ---------------------------------------- | ----------------------------------------- |
| Schedule ID | `referrals-twitter-research-schedule`    | `referrals-internal-research-schedule`    |
| Workflow    | `TwitterReferralResearchWorkflow`        | `InternalReferralResearchWorkflow`        |
| Workflow ID | `referrals-twitter-research`             | `referrals-internal-research`             |
| Activity    | `run_twitter_referral_research_activity` | `run_internal_referral_research_activity` |
| Side effect | `_post_referral_dms` (real DM send)      | `_send_referral_emails_placeholder`       |

### Worker / schedule registration

- Workflows + activities are added to `TASKS_TASK_QUEUE` in
  `posthog/management/commands/start_temporal_worker.py` (alongside `TASKS_WORKFLOWS`).
- The schedule creators (`create_twitter_referral_research_schedule`,
  `create_internal_referral_research_schedule`) are added to the global `schedules` list in
  `posthog/temporal/schedule.py`, run on startup by `a_init_general_queue_schedules`.
- `trigger_immediately=False` for both — they fire on the next hourly boundary.

### Cadence + dedup

- **Twitter** runs hourly with a 1h look-back. Adjacent windows are disjoint (modulo
  schedule jitter), so the same tweet should not surface twice on consecutive runs.
- **Internal** runs hourly with no look-back parameter (the queries' windows are fixed at
  30–180 days). It WILL re-surface the same users until we add an ignore-list / DM-sent
  table. The placeholder side-effect hook logs the duplicates rather than re-DMing.

### Side effects

`activities.py` wires the per-flow side effect inline:

- `_post_referral_dms(result: TwitterReferralCandidates)` — DMs each candidate via the
  X v2 API (`twitter/x_dm.py::send_referral_dms`). Credentials come from env vars
  (`X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_REFRESH_TOKEN`); the refresh token rotates on
  every refresh and the rotated value is cached in Django cache with the env var as the
  recovery fallback. **No idempotency yet** — a tweet that re-surfaces in a later window
  will trigger a duplicate DM. The `TODO(referrals)` in the hook is the wire-up point.
- `_send_referral_emails_placeholder(result: InternalReferralCandidates)` — still a
  placeholder; will send a referral-ask email (likely via the `messaging` product).

The placeholder still logs a `WARNING` ("hook not implemented — N candidate(s) would
receive an email") plus per-candidate `INFO` lines so the schedule output stays
observable. Grep for `TODO(referrals)` to find the remaining wire-up points.

### CI worker trigger

The `Tasks Agent Temporal worker` CI deployment is gated on changes under
`products/tasks/backend` _and_ `products/referrals/backend`
(see `.github/workflows/container-images-cd.yml`). Any change here that affects the worker
should be picked up automatically.

## Design notes

Things that are not obvious from reading the code and would have to be re-discovered:

- **Two separate agents, not one multi-step session.** The flows share only the high-level
  goal. Different data sources and different identity systems (Twitter handle vs PostHog
  email) mean step 2 cannot use anything from step 1, so a combined session pays multi-step
  overhead for zero context reuse — plus exposes itself to cascading failures and agent
  off-script risk. Keep them separate.
- **Both flows are single-turn for simplicity.** Multi-turn is the natural escape hatch if a
  flow becomes unreliable. Important asymmetry: `MultiTurnSession.start` does **not** retry
  on empty-end-turn, but `send_followup` does. A single-turn flow that stalls mid-reasoning
  is fatal; a multi-turn flow recovers automatically on the next turn. If you see repeated
  SSE timeouts or `relay_sandbox_events_cancelled` in worker logs, that is the trigger to
  promote a flow to multi-turn.
- **Internal flow's `LIMIT 20` and argMax dedup are not arbitrary.** An earlier version
  capped step 1 at 100 candidates and grouped step 2 by all property columns, so the same
  distinct_id was emitted many times — once per geoip/org combination. The agent juggled ~50
  fragmented rows in a single turn and stalled in a thinking block for ~6.5 min, hitting the
  Claude SDK's streaming idle timeout. The smaller cap plus argMax keep the reasoning load
  bounded. If 20 is too tight on a real run, bump cautiously; promoting to multi-turn is the
  safer upgrade than raising the cap.
- **PII-free prompt text.** The static prompt strings must not name real Twitter handles,
  emails, or company names — the prompt is logged and stored every run. Worked examples use
  generic pattern shapes (`@another_user`, `[my tool]`). The agent _output_ names real users
  by design; the _prompt_ does not.
- **`PostHog/.github` is intentional.** Neither flow needs the PostHog source tree. We clone
  the smallest available repo to keep sandbox bootstrap fast. `Task.create_and_run` still
  requires a GitHub integration to do the clone, even when we never read the contents.
- **Twitter API key is inlined into the prompt.** Acceptable risk for internal use; the
  alternative (sandbox env-var plumbing) is more work for no real safety win. If this ever
  goes external, revisit.
- **Production identity resolution uses `resolve_sandbox_context_for_local_dev`.** The name
  is misleading — the function picks the first team / first org-member in the DB and is the
  same path the management commands use. The schedules deliberately reuse it so production
  and dev runs are identical. This works because internal-flow research operates on
  PostHog's own product data, where "first team" is the right team. If we ever extend this
  to multi-tenant referral research, replace the resolver with an explicit team_id input
  (settings-driven) rather than fanning out — the queries are PostHog-specific.
- **Activities live on `TASKS_TASK_QUEUE`, not a referrals-specific queue.** The activities
  spawn `process-task` workflows on `TASKS_TASK_QUEUE` and then poll their S3 logs for the
  agent turn, so co-locating them on the same worker avoids a cross-queue hop and means we
  do not need a separate deployment for one workflow per hour.
- **Side-effect hooks are inside the activity, not the workflow.** If the workflow restarts
  mid-run (worker crash, etc.) Temporal will replay the activity from scratch — running the
  research again is expensive but tolerable. The Twitter DM hook is NOT yet idempotent: a
  worker crash mid-dispatch will re-DM whichever subset already received a message. The
  hourly cadence + 1h disjoint windows make this acceptable for the hackathon, but the
  `TODO(referrals)` in `_post_referral_dms` is the wire-up point — pick a key
  (`tweet_id` or `twitter_user_id`), persist sent DMs, and skip-on-conflict before
  widening the look-back window.
- **`non_retryable_error_types=["ValueError", "TypeError"]`.** Config errors
  (missing `TWITTERAPI_IO_KEY`, missing X OAuth creds, missing `posthog_mcp_scopes`) raise
  `ValueError` so they fail loudly on the first attempt instead of burning 2× cost on a
  re-run that cannot possibly succeed. Transient infra issues bubble up as
  `RuntimeError`/network errors and retry once.

## When editing these flows

- Keep the research modules **prompt-orchestration only**. Persistence (recording
  candidates, marking who has been DMed) belongs in the activity or downstream of the
  side-effect hook, never in `run_*_research`.
- Resist the urge to extract a shared abstraction between the two flows. They share only
  `MultiTurnSession.start → end`; the rest is genuinely independent.
- If you change the output shape of either pydantic model, update the prompt's schema fence
  in the same file so the agent's output still matches.
- If you broaden a flow (e.g. add a daily Twitter digest, or add billing enrichment to the
  internal flow), add it as a parameter to `run_*_research` and the matching
  `*ActivityInput` rather than forking the orchestrator.
- If you bump the internal flow's `LIMIT 20` or change the argMax pattern, re-read the
  _Design notes_ on why those exist — adjust with the SSE timeout failure mode in mind.
- When promoting a placeholder side-effect hook to a real implementation, make the call
  idempotent (per-candidate keyed). Until then, treat duplicate logs as expected output of
  the hourly schedule.
- **If you change either command, either flow, or anything under `temporal/`, update this
  file to match.**
