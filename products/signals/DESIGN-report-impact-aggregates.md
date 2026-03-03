# Design: Report-Level Impact Aggregates

## Problem

Priority estimation in `actionability_judge.py` relies on an LLM interpreting prose descriptions.
The quantitative impact data that _already exists_ in signal `extra` fields
is silently discarded by `render_signal_to_text()`,
which renders only `source_product`, `source_type`, `weight`, `timestamp`, and `content`.

The judge literally cannot see how many users are affected,
what percentage of the team's active users that represents,
how many external reports corroborate the problem,
or what severity external tools (Zendesk, Linear) assigned.
Priority is vibes, not measurement.

## Goal

Compute a single coherent **impact profile** for each report at summary time,
aggregating across heterogeneous signal types that measure impact in fundamentally different ways.
Feed this profile to both the summarizer and the actionability judge
so that priority reflects real, quantified impact.

---

## What each signal source provides today

### Session Replay (`session_replay` / `session_segment_cluster`)

The richest source. All metrics are pre-computed at emission time in `a4_emit_signals_from_clusters.py`.

| Dimension                  | Field                                  | Notes                                                                               |
| -------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------- |
| Users affected             | `extra.metrics.relevant_user_count`    | De-duped via `count_distinct_persons()` against `person_distinct_ids` in ClickHouse |
| Active users (denominator) | `extra.metrics.active_users_in_period` | All distinct persons across all distinct_ids in the clustering window               |
| Occurrence count           | `extra.metrics.occurrence_count`       | Number of video segments in the cluster                                             |
| Raw distinct_ids           | `extra.segments[].distinct_id`         | Available for cross-signal de-duplication                                           |
| Per-occurrence timestamps  | `extra.segments[].start_time`          | Absolute timestamps for recency/trend                                               |
| Blocking assessment        | `extra.actionable` + description       | LLM labeling categorizes "broken or blocked" workflows                              |

**Numerator:** Direct measurement.
Collect all `distinct_id` values from `extra.segments` across all session replay signals in the report,
then call `count_distinct_persons(team, all_distinct_ids)` for a de-duped report-level person count.

**Denominator:** `max(extra.metrics.active_users_in_period)` across session replay signals.
This is the team's total distinct persons in the clustering lookback window,
already computed by the session replay pipeline.

### LLM Analytics (`llm_analytics` / `evaluation`)

| Dimension       | Field                                           | Notes                                                       |
| --------------- | ----------------------------------------------- | ----------------------------------------------------------- |
| Events affected | Implicit: 1 per signal                          | Each signal = 1 evaluation on 1 LLM trace                   |
| Severity        | `weight` (= LLM-assessed significance, 0.0–1.0) | Filtered below 0.1 at emission                              |
| Trace/event IDs | `extra.target_event_id`, `extra.trace_id`       | Could join to events for user identity, but not wired today |

**Numerator:** No user count available today.
Each signal = 1 occurrence.
Signal count within the report = occurrence count.
To get user count, would need to join `trace_id` → events → `distinct_id` → `person_distinct_ids`.

**Denominator:** Not available.
Would need "total LLM traces for this team in period" — queryable but not wired.

**Practical approach for v1:** Count of eval signals = occurrence count, user impact = unknown.

### GitHub Issues (`github` / `issue`)

| Dimension        | Field                                  | Notes                                          |
| ---------------- | -------------------------------------- | ---------------------------------------------- |
| External reports | 1 per signal                           | Each signal = 1 issue filed by 1 person        |
| Labels           | `extra.labels`                         | May contain "bug", "critical", "blocker", "p0" |
| Recency          | `extra.created_at`, `extra.updated_at` |                                                |

**Numerator:** Each issue = minimum 1 affected user.
The count of distinct GitHub issue signals in a report is a **lower bound** on affected users.

**Denominator:** Not meaningful — GitHub issues don't map to "total users."

**Severity extraction:** Parse `extra.labels` for priority keywords.

### Zendesk Tickets (`zendesk` / `ticket`)

| Dimension        | Field            | Notes                                                                                          |
| ---------------- | ---------------- | ---------------------------------------------------------------------------------------------- |
| External reports | 1 per signal     | Each signal = 1 support ticket = 1 customer                                                    |
| Priority         | `extra.priority` | Zendesk native: `"urgent"`, `"high"`, `"normal"`, `"low"` — set by support agents with context |
| Type             | `extra.type`     | `"incident"`, `"problem"`, `"question"`, `"task"`                                              |
| Tags             | `extra.tags`     | May contain severity/product tags                                                              |

**Numerator:** Each ticket = 1 affected customer.
Ticket count = customer report count.

**Denominator:** Not available.

**Severity extraction:** `extra.priority` is a direct, agent-assessed severity.
`extra.type == "incident"` is stronger evidence than `"question"`.

### Linear Issues (`linear` / `issue`)

| Dimension        | Field                      | Notes                                     |
| ---------------- | -------------------------- | ----------------------------------------- |
| External reports | 1 per signal               | Each signal = 1 engineering issue         |
| Priority         | `extra.priority` (int 0–4) | 0=none, 1=urgent, 2=high, 3=medium, 4=low |
| Priority label   | `extra.priority_label`     | Human-readable                            |
| Labels           | `extra.labels`             | Team-defined                              |
| Identifier       | `extra.identifier`         | e.g., "ENG-42"                            |

**Numerator:** Each issue = 1 report.

**Denominator:** Not available.

**Severity extraction:** `extra.priority` is a direct, engineer-assessed severity.

---

## Impact dimensions to compute

### 1. User breadth

The most important dimension.
How many real humans are affected, and what fraction of the team's user base is that?

**Computation strategy:**

```python
session_replay_distinct_ids = collect all extra.segments[].distinct_id
                              across all session_replay signals in report

if session_replay_distinct_ids:
    users_affected = count_distinct_persons(team, session_replay_distinct_ids)
    active_users   = max(s.extra.metrics.active_users_in_period
                         for s in signals
                         if s.source_product == "session_replay")
    user_impact_ratio = users_affected / active_users
else:
    users_affected     = None
    active_users       = None
    user_impact_ratio  = None
```

**Why re-query rather than sum per-signal counts:**
A single person can appear in multiple clusters.
If signal A reports 15 users and signal B reports 15 users,
the true count might be 20 (with 10 overlapping).
Collecting all distinct_ids and querying `count_distinct_persons` once
gives the de-duped report-level truth.

**Performance:**
`count_distinct_persons` runs `SELECT COUNT(DISTINCT person_id) FROM person_distinct_ids WHERE distinct_id IN (...)`.
The `person_distinct_ids` table is indexed on `(team_id, distinct_id)`.
For typical cluster sizes (hundreds to low thousands of distinct_ids), this is sub-second.

**When no session replay signals exist:**
Leave `users_affected` and `user_impact_ratio` as `None`.
The judge still has occurrence counts and external report counts.
A future enhancement could query `SELECT count(DISTINCT person_id) FROM events WHERE team_id = X AND timestamp > now() - INTERVAL 7 DAY`
to provide a denominator even for non-session-replay reports.

### 2. Occurrence frequency

How often is this happening?

```python
total_occurrences = 0
for signal in signals:
    if signal.source_product == "session_replay":
        total_occurrences += signal.extra.get("metrics", {}).get("occurrence_count", 1)
    else:
        # Each external/eval signal = 1 reported occurrence
        total_occurrences += 1
```

### 3. External report count

How many humans independently reported this problem through external channels?
Each GitHub issue, Zendesk ticket, or Linear issue represents someone
who cared enough to write a report.

```python
external_report_count = sum(
    1 for s in signals
    if s.source_product in ("github", "zendesk", "linear")
)
```

5 Zendesk tickets about the same problem is strong evidence
even without session replay data.

### 4. Source diversity

Are multiple independent observation systems seeing the same problem?
Cross-product corroboration (session replay + error tracking, or session replay + Zendesk)
is much stronger evidence than many signals from a single source.

```python
source_products = sorted(set(s.source_product for s in signals))
cross_product_corroboration = len(source_products) >= 2
```

### 5. Severity indicators from external sources

External tools often carry severity assessments from humans with context.
Normalize the heterogeneous priority fields to a common scale:

```python
SEVERITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}

def extract_severity(signal: SignalData) -> str | None:
    extra = signal.extra
    match signal.source_product:
        case "zendesk":
            prio = extra.get("priority")
            return {"urgent": "urgent", "high": "high",
                    "normal": "medium", "low": "low"}.get(prio)
        case "linear":
            prio = extra.get("priority")
            return {1: "urgent", 2: "high", 3: "medium", 4: "low"}.get(prio)
        case "github":
            labels = [l.lower() if isinstance(l, str) else "" for l in extra.get("labels", [])]
            for label in labels:
                if any(kw in label for kw in ("critical", "blocker", "p0", "urgent")):
                    return "urgent"
                if any(kw in label for kw in ("high", "p1", "important")):
                    return "high"
            return None
        case _:
            return None
```

Take the strongest severity across all signals.
Also build a `severity_details` list for the judge:
`["2 Zendesk tickets marked 'urgent'", "Linear ENG-42 priority 'High'"]`

### 6. Recency and trend

Is this an active incident or a chronic background issue?

```python
timestamps = sorted(datetime.fromisoformat(s.timestamp) for s in signals)
most_recent = timestamps[-1]
earliest    = timestamps[0]
span_days   = max((most_recent - earliest).total_seconds() / 86400, 0.042)  # floor at 1h
signals_per_day = len(signals) / span_days
```

`signals_per_day > 10` → burst / active incident.
`signals_per_day < 0.5` → slow accumulation / chronic.

---

## Data structure

```python
@dataclass
class ReportImpactAssessment:
    # --- User breadth ---
    users_affected: int | None          # De-duped persons from session replay
    active_users_in_period: int | None  # Team's total active users in period
    user_impact_ratio: float | None     # users_affected / active_users (0.0–1.0)

    # --- Occurrence frequency ---
    total_occurrences: int              # Sum across all sources
    external_report_count: int          # Distinct external reports (GitHub + Zendesk + Linear)

    # --- Source diversity ---
    source_products: list[str]          # Distinct source_product values
    cross_product_corroboration: bool   # True when 2+ different source_products

    # --- Severity ---
    strongest_external_severity: str | None   # "urgent" | "high" | "medium" | "low"
    severity_details: list[str]               # Human-readable per-source details

    # --- Recency & trend ---
    most_recent_signal: str             # ISO timestamp
    earliest_signal: str                # ISO timestamp
    signals_per_day: float              # Trend indicator
```

---

## Pipeline integration

### Current flow (summary.py)

```text
1. fetch_signals_for_report_activity     → signals
2. mark_report_in_progress_activity
3. summarize_signals_activity            → title, summary
4. safety_judge + actionability_judge    (parallel)
5. mark ready / pending / failed
```

### Proposed flow

```text
1. fetch_signals_for_report_activity     → signals
2. mark_report_in_progress_activity
3. compute_impact_assessment_activity    → ReportImpactAssessment   ← NEW
4. summarize_signals_activity            → title, summary
        (receives impact assessment)
5. safety_judge + actionability_judge    (parallel)
        (both receive impact assessment)
6. store_impact_artefact_activity        ← NEW (optional, for observability)
7. mark ready / pending / failed
```

Step 3 is a new Temporal activity that:

- Takes `team_id` + `list[SignalData]`
- Collects all `distinct_id` values from session replay signals' `extra.segments`
- Calls `count_distinct_persons(team, all_distinct_ids)` for de-duped user count
- Extracts denominators, severities, occurrence counts from `extra` fields
- Computes trend from timestamps
- Returns `ReportImpactAssessment`

Step 6 stores the assessment as a `SignalReportArtefact` with type `impact_assessment`
for future calibration and observability. This is optional — the primary value is in steps 4–5.

---

## Feeding impact to the judge

### Change 1: Update `render_signal_to_text()` (types.py)

Add source-specific impact lines extracted from `extra`:

```text
Signal 1:
- Source: session_replay / session_segment_cluster
- Weight: 0.73
- Timestamp: 2024-03-10T14:22:00Z
- Description: Users are failing to complete checkout...
- Impact: 47 users affected (of 5,000 active), 312 occurrences

Signal 2:
- Source: zendesk / ticket
- Weight: 1.0
- Timestamp: 2024-03-10T16:05:00Z
- Description: Customer reports checkout is broken...
- Severity: urgent (Zendesk priority)
```

### Change 2: Add report-level impact block to actionability judge prompt

Update `_build_actionability_judge_prompt()` to include:

```text
REPORT IMPACT ASSESSMENT:
- Users affected: 47 of 5,000 active users (0.94%)
- Total occurrences: 312 across 5 signals
- External reports: 3 (2 Zendesk tickets, 1 GitHub issue)
- Source diversity: session_replay, zendesk, github (cross-product corroboration)
- Strongest external severity: urgent (2 Zendesk tickets marked 'urgent')
- Trend: 8.5 signals/day over 3 days (active incident pattern)
```

### Change 3: Add priority anchors to judge system prompt

Update priority level descriptions to reference concrete thresholds.
These are not hard rules — the judge uses extended thinking
and can weigh context — but they prevent defaulting to "P2 for everything":

```text
- P0: Critical, needs immediate attention.
  Guideline: user_impact_ratio > 20%, OR cross-product corroboration
  with external severity "urgent", OR signals_per_day > 10.

- P1: High, should be addressed soon.
  Guideline: user_impact_ratio > 5%, OR external severity "urgent"/"high"
  with 3+ external reports, OR signals_per_day > 3.

- P2: Medium, normal course of work.
  Guideline: user_impact_ratio > 1%, OR 2+ external reports,
  OR moderate external severity.

- P3: Low, address when convenient.
  Guideline: user_impact_ratio < 1% with few occurrences,
  OR single external report with no corroboration.

- P4: Minimal, nice-to-have.
  Guideline: minimal measurable impact, no external severity indicators.
```

### Change 4: Feed impact to summarizer

Add the assessment to `_build_summarize_prompt()` so the summarizer can write
"47 users (0.94% of active users) are hitting checkout failures"
instead of the vague "several users are experiencing issues" it generates from prose today.

---

## New file: `impact.py`

All impact computation logic lives in a single new file
`products/signals/backend/temporal/impact.py`:

- `compute_impact_assessment(team_id, signals) -> ReportImpactAssessment`
- `extract_severity(signal) -> str | None`
- `render_impact_assessment_to_text(assessment) -> str`

The Temporal activity wrapper lives in `summary.py` alongside the other summary activities.

---

## What this does NOT do

- **Revenue data:** Not available in signal sources today.
  Could be added later by enriching signals with billing metadata at emission time.
- **Customer tier:** Would need billing integration.
  Worth doing eventually, not needed for v1.
- **Dynamic re-evaluation:** This computes impact at summary time.
  Re-computing as new signals arrive is a natural extension, separate change.
- **Feedback loop / calibration:** This produces the raw data
  that would enable calibration, but doesn't implement the loop itself.
- **LLM eval user count enrichment:** Would need `trace_id` → events → person join.
  Low priority — eval signals rarely carry user impact data.

---

## Changes by file

| File                              | Change                                                                                                                        |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **New: `temporal/impact.py`**     | `ReportImpactAssessment` dataclass, `compute_impact_assessment()`, `extract_severity()`, `render_impact_assessment_to_text()` |
| `temporal/types.py`               | Update `render_signal_to_text()` to include key `extra` fields per source type                                                |
| `temporal/summary.py`             | Add `compute_impact_assessment_activity` between fetch and summarize; pass assessment to summarizer and both judges           |
| `temporal/actionability_judge.py` | Update `_build_actionability_judge_prompt()` to include impact block; update priority descriptions with concrete anchors      |
| `temporal/summarize_signals.py`   | Update `_build_summarize_prompt()` to include impact data                                                                     |
| `temporal/__init__.py`            | Register new activity                                                                                                         |
| `models.py`                       | Add `IMPACT_ASSESSMENT` to `ArtefactType` enum (optional)                                                                     |
