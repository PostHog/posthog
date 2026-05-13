# Referrals research

Agentic flows that surface PostHog referral candidates from two distinct sources, so the growth
team can DM warm contacts and ask them to refer other companies that would benefit from PostHog.

Both flows are built on the same sandbox primitive (`MultiTurnSession`) from
`products/tasks/backend/services/`, but they are otherwise independent: different data sources,
different sandbox tools, different cadences. They run as separate single-turn agents and produce
separate outputs.

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

The prompt embeds an exact `curl` command (with the API key inlined) for `twitterapi.io`. The agent
fetches all PostHog mentions in the window, applies enthusiasm criteria (six positive-signal
categories — superlative praise, firm preference, active recommendation, operational
standardization, specific positive experience, ecosystem alignment), and returns
`TwitterReferralCandidates` with `{id, user, reason}` per match.

### Local debug

```bash
# Default: last 1 hour
TWITTERAPI_IO_KEY=... python manage.py analyze_twitter_posts

# Wider window
python manage.py analyze_twitter_posts --hours 6

# Stream raw sandbox logs
python manage.py analyze_twitter_posts --verbose
```

Requires `TWITTERAPI_IO_KEY` in the shell environment of the management command (the value is
injected into the prompt at call time; the sandbox itself does not need env-var plumbing).

## Internal flow

`internal/research/research.py` → `run_internal_research(context, ...)`.

The prompt embeds three validated HogQL queries that the agent runs via PostHog MCP `execute-sql`:

1. **Signal query** — UNION-ALL of four behavioural CTEs (`login_streak`, `invited_colleagues`,
   `product_breadth`, `nps_promoter`), returning every distinct_id that matched at least one
   signal plus the list of matched signals.
2. **Person-detail lookup** — emails, names, and `organization_id`s for the candidates the agent
   wants to keep.
3. **Org-name lookup** — display names via `$groupidentify` events.

The agent applies its own judgement (no hard threshold) when picking who to include, weighing
the stronger advocacy signals (`nps_promoter`, `invited_colleagues`) above engagement-only
signals (`login_streak`, `product_breadth`), dedups by email, and returns
`InternalReferralCandidates` with `{distinct_id, email, org_id, org_name, reason}` per match.

### MCP scopes

The internal flow requires `context.posthog_mcp_scopes` to be set — the orchestrator raises a
`ValueError` if it is `None`. `"read_only"` is the right default; it expands to all read scopes
including `query:read`, which is what `execute-sql` needs. The default
`resolve_sandbox_context_for_local_dev` resolver does not set scopes — layer them on with
`dataclasses.replace(context, posthog_mcp_scopes="read_only")`, as the management command does.

### Local debug

```bash
python manage.py analyze_internal_users
python manage.py analyze_internal_users --verbose
```

Requires a GitHub integration on the first team in the local database (the resolver enforces
this; `Task.create_and_run` needs it to bootstrap any sandbox, even with our dummy repo
`PostHog/.github`).

## When editing these flows

- Keep both modules **prompt-orchestration only**. Persistence (recording candidates, marking who
  has been DMed) belongs in the caller — today the management commands, later Temporal
  activities.
- The two flows do not share criteria, prompts, or pydantic models. Resist the urge to create a
  shared abstraction; the only thing they have in common is `MultiTurnSession.start → end`.
- If you change the output shape of either pydantic model, update the prompt's schema fence in
  the same file so the agent's output still matches.
- If you broaden a flow (e.g. add a daily Twitter digest, or add billing enrichment to the
  internal flow), add it as a parameter to `run_*_research` rather than forking the orchestrator.
- **If you change either command or either flow, update this file to match.**
