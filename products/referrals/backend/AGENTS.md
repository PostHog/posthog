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
├── twitter/research/       # Twitter/X enthusiast flow
│   ├── prompts.py
│   └── research.py         # run_twitter_research(...)
├── internal/research/      # PostHog power-user flow
│   ├── prompts.py
│   └── research.py         # run_internal_research(...)
└── management/commands/
    ├── analyze_twitter_posts.py
    └── analyze_internal_users.py
```

## When to use which

|                      | Twitter flow                                                         | Internal flow                                                                |
| -------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **What it finds**    | Twitter users posting enthusiastic, personal endorsements of PostHog | Existing PostHog users whose behaviour looks like a referral target          |
| **Data source**      | twitterapi.io advanced_search                                        | PostHog ClickHouse via MCP `execute-sql`                                     |
| **Sandbox tool**     | `curl` (API key inlined into prompt)                                 | PostHog MCP (`execute-sql`) — context needs `posthog_mcp_scopes="read_only"` |
| **Output identity**  | Twitter handle                                                       | PostHog email + org                                                          |
| **Time window**      | Last 1 hour (configurable)                                           | 30–180 days (per-signal, fixed in queries)                                   |
| **Intended cadence** | Hourly Temporal cron (planned)                                       | Weekly/manual batch (signals do not move fast)                               |

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

`resolve_sandbox_context_for_local_dev` does not set scopes, so the management command layers
them on with `dataclasses.replace(context, posthog_mcp_scopes="read_only")`. Production
callers (future Temporal activities) should do the same.

### Local debug

```bash
python manage.py analyze_internal_users
python manage.py analyze_internal_users --verbose
```

Requires a GitHub integration on the first team in the local database — the resolver enforces
it, and `Task.create_and_run` needs it to bootstrap any sandbox, even with our dummy repo
`PostHog/.github`.

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

## When editing these flows

- Keep both modules **prompt-orchestration only**. Persistence (recording candidates, marking
  who has been DMed) belongs in the caller — today the management commands, later Temporal
  activities.
- Resist the urge to extract a shared abstraction between the two flows. They share only
  `MultiTurnSession.start → end`; the rest is genuinely independent.
- If you change the output shape of either pydantic model, update the prompt's schema fence
  in the same file so the agent's output still matches.
- If you broaden a flow (e.g. add a daily Twitter digest, or add billing enrichment to the
  internal flow), add it as a parameter to `run_*_research` rather than forking the
  orchestrator.
- If you bump the internal flow's `LIMIT 20` or change the argMax pattern, re-read the
  _Design notes_ on why those exist — adjust with the SSE timeout failure mode in mind.
- **If you change either command or either flow, update this file to match.**
