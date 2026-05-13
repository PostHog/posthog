from __future__ import annotations

import json

from pydantic import BaseModel, Field


class InternalCandidate(BaseModel):
    distinct_id: str = Field(
        description="PostHog `distinct_id` of the candidate user, exactly as returned by the signal query.",
    )
    email: str | None = Field(
        default=None,
        description="Candidate's email from `person.properties.email`. Null when the lookup did not return one.",
    )
    org_id: str | None = Field(
        default=None,
        description="The PostHog organization id the user belongs to, from `person.properties.organization_id`.",
    )
    org_name: str | None = Field(
        default=None,
        description="The organization's display name, from the `$groupidentify` lookup. Null when the lookup did not return one.",
    )
    reason: str = Field(
        description=(
            "One short sentence explaining which behavioural signals fired for this user and why they look like "
            "a promising referral candidate. Format: '[signals fired]: [why this makes them a referral target].' "
            "Example: 'NPS promoter (10) + invited 3 teammates + multi-product use: active advocate already "
            "spreading PostHog inside their org.'"
        ),
    )


class InternalReferralCandidates(BaseModel):
    candidates: list[InternalCandidate] = Field(
        description=(
            "PostHog users who look like promising referral targets. "
            "Empty list is valid when the data did not surface anyone worth flagging."
        ),
    )


_INTERNAL_RESEARCH_PREAMBLE = """You are a growth research agent for PostHog. Your job is to find existing PostHog users whose behaviour suggests they would happily refer other companies to PostHog if asked. The growth team will DM each candidate personally.

The bar is **"would this person plausibly engage with a friendly referral ask?"** — you are not gated on a hard signal count. Use your judgement after looking at the data. A user with one strong advocacy signal (e.g. NPS promoter who invited teammates) can be a better candidate than a quiet 30-day-login-streak user with no other engagement."""


_INTERNAL_TOOLS_BLOCK = """## Tool: PostHog MCP

You have access to the PostHog MCP tool `execute-sql`. Run the HogQL queries below in sequence:

1. The **signal query** to find users who match one or more behavioural signals.
2. A **person-detail lookup** for the distinct_ids you want to keep.
3. An **org-name lookup** for the org_ids surfaced by the person lookup.

Process the results in your own head — apply your judgement when deciding who to include. Do not invent or modify the queries beyond changing the IN-list values; the queries below are pre-validated against the live schema."""


# Validated against the live schema in PostHog's MCP execute-sql tool.
# Sourced from the PostHog Referral Candidate Identifier skill doc.
_INTERNAL_QUERIES = """## Step 1 — Signal query

```sql
WITH
streak_users AS (
    SELECT distinct_id, 'login_streak' as signal
    FROM events
    WHERE event = '$pageview'
      AND timestamp >= now() - INTERVAL 60 DAY
      AND toDayOfWeek(timestamp) NOT IN (6, 7)
    GROUP BY distinct_id
    HAVING COUNT(DISTINCT toDate(timestamp)) >= 30
),
invite_users AS (
    SELECT distinct_id, 'invited_colleagues' as signal
    FROM events
    WHERE event IN ('user invited', 'team member invited', 'bulk invite executed')
      AND timestamp >= now() - INTERVAL 90 DAY
    GROUP BY distinct_id
    HAVING COUNT(*) >= 1
),
breadth_users AS (
    SELECT distinct_id, 'product_breadth' as signal
    FROM events
    WHERE event = '$pageview'
      AND timestamp >= now() - INTERVAL 30 DAY
    GROUP BY distinct_id
    HAVING COUNT(DISTINCT multiIf(
        properties.$pathname LIKE '%/insights%' OR properties.$pathname LIKE '%/dashboard%', 'analytics',
        properties.$pathname LIKE '%/replay%' OR properties.$pathname LIKE '%/recordings%', 'session_replay',
        properties.$pathname LIKE '%/feature_flags%', 'feature_flags',
        properties.$pathname LIKE '%/surveys%', 'surveys',
        properties.$pathname LIKE '%/experiments%', 'experiments',
        properties.$pathname LIKE '%/data-warehouse%', 'data_warehouse',
        NULL
    )) >= 3
),
nps_users AS (
    SELECT distinct_id, 'nps_promoter' as signal
    FROM events
    WHERE event = 'survey sent'
      AND toInt(properties.$survey_response) >= 9
      AND toInt(properties.$survey_response) <= 10
      AND timestamp >= now() - INTERVAL 180 DAY
    GROUP BY distinct_id
),
all_signals AS (
    SELECT * FROM streak_users
    UNION ALL SELECT * FROM invite_users
    UNION ALL SELECT * FROM breadth_users
    UNION ALL SELECT * FROM nps_users
)
SELECT
    distinct_id,
    COUNT(DISTINCT signal) as signal_count,
    groupArray(signal) as signals_matched
FROM all_signals
GROUP BY distinct_id
ORDER BY signal_count DESC
LIMIT 20
```

Returns rows like: `('abc-123', 3, ['login_streak', 'invited_colleagues', 'nps_promoter'])`. The `LIMIT 20` cap keeps the candidate pool small — focus on these top-ranked rows for the rest of the flow.

## Step 2 — Person-detail lookup

For the distinct_ids you want to keep, run this **once** (the cap above guarantees ≤20 IDs, well under memory limits). The `argMax(..., timestamp)` pattern collapses each distinct_id to a single row holding the most recent email, name, and org_id — no agent-side dedup needed.

```sql
SELECT
    distinct_id,
    argMax(person.properties.email, timestamp) as email,
    argMax(person.properties.name, timestamp) as name,
    argMax(person.properties.organization_id, timestamp) as org_id
FROM events
WHERE distinct_id IN ('id1', 'id2', ...)
GROUP BY distinct_id
```

## Step 3 — Org-name lookup

For the org_ids returned in step 2:

```sql
SELECT
    properties.$group_0 as org_id,
    argMax(JSONExtractString(properties.$group_set, 'name'), timestamp) as org_name
FROM events
WHERE event = '$groupidentify'
  AND properties.$group_type = 'organization'
  AND properties.$group_0 IN ('org_id_1', 'org_id_2', ...)
GROUP BY org_id
LIMIT 50
```

> Use `properties.$group_0` (not `JSONExtractString(properties.$group_set, 'organization_id')`) — the latter returns blank."""


_INTERNAL_SIGNAL_GUIDE = """## What the signals mean

- **`login_streak`** — Logged in on ≥30 distinct weekdays in the last 60 days. Indicates an embedded power user, but not by itself an advocate.
- **`invited_colleagues`** — Invited at least one teammate to PostHog in the last 90 days. **Strong advocacy signal** — they are already recommending PostHog inside their org.
- **`product_breadth`** — Touched ≥3 different PostHog product areas (analytics, replay, flags, surveys, experiments, warehouse) in the last 30 days. Indicates they understand PostHog holistically and can speak to its breadth.
- **`nps_promoter`** — Submitted an NPS score of 9 or 10 in the last 180 days. **Self-declared advocate** — they have explicitly said they would recommend PostHog.

## Selection criteria

Pick candidates whose signals collectively suggest they would refer PostHog to other companies. There is no fixed minimum signal count — use your judgement.

Weighting cues (not rules):
- `nps_promoter` and `invited_colleagues` are the two **strongest** referral signals. A user with either of these is usually worth including.
- `login_streak` and `product_breadth` alone signal engagement but not advocacy — include them when combined with another signal, or when they are exceptionally strong (e.g. a very long login streak with broad product use).
- Two strong signals are usually better than three weak ones.

Bias: when in doubt, include and explain in the `reason`. The growth team can filter before DMing.

## Deduplication and identity

The step-2 query already collapses each distinct_id to a single row via `argMax`, so within one distinct_id you do not need to dedup. The rare remaining case is the **same email surfacing under two different distinct_ids** (identity merges that did not converge); when that happens, keep the distinct_id with the higher signal count and drop the others — one row per email in the final output.

If `email` is empty or null after the lookup, skip that distinct_id — without an email the growth team cannot reach the user."""


_HOGQL_SYNTAX_GUARDRAILS = """## HogQL syntax guardrails

The queries above are validated. If you need to adapt them (e.g. shrink the IN-list), keep these in mind — these are common HogQL pitfalls.

| Do not use | Use instead |
|---|---|
| `CASE WHEN … THEN … END` | `multiIf(cond, val, cond2, val2, default)` |
| `properties['$pathname']` | `properties.$pathname` |
| `toInt32OrNull()`, `toInt64()` | `toInt()` |
| `JOIN persons p ON p.id = e.person_id` | `person.properties.*` directly on the events table |
| `group_properties('organization', …)` | `$groupidentify` event + `properties.$group_0` |

`toDayOfWeek(timestamp)` returns 1–7 with 6=Saturday and 7=Sunday in ClickHouse.

If a query errors with a memory limit, shrink the IN-list to ≤20 values and re-run."""


def build_internal_research_prompt() -> str:
    """Build the single-turn prompt that finds PostHog power users worth a referral DM."""
    schema = json.dumps(InternalReferralCandidates.model_json_schema(), indent=2)
    return f"""{_INTERNAL_RESEARCH_PREAMBLE}

---

{_INTERNAL_TOOLS_BLOCK}

---

{_INTERNAL_QUERIES}

---

{_INTERNAL_SIGNAL_GUIDE}

---

{_HOGQL_SYNTAX_GUARDRAILS}

---

## Output format

After running all three steps and applying your judgement, respond with a single JSON object matching this schema. Use the `distinct_id` exactly as returned by the queries. Emit one candidate per unique user (dedup by email):

<jsonschema>
{schema}
</jsonschema>

If the data does not surface anyone worth flagging, return `{{"candidates": []}}`. Otherwise, include every user who plausibly fits — err on the side of inclusion when at least one strong signal fired."""
