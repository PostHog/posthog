---
name: analyzing-experiment-session-replays
description: 'Analyze session replay patterns across experiment variants to understand user behavior differences. Use when the user wants to see how users interact with different experiment variants, identify usability issues, compare behavior patterns between control and test groups, or get qualitative insights to complement quantitative experiment results.'
---

# Analyzing experiment session replays

This skill guides you through analyzing session recordings for experiment variants to understand behavioral differences between control and test groups.

## When to use this skill

Use this skill when:

- The user asks to analyze session replays for an experiment
- The user wants to understand how users behave differently across experiment variants
- The user asks to compare user behavior between control and test variants
- The user wants qualitative insights to complement experiment metrics
- The user asks questions like "How are users behaving in my experiment?" or "Show me session replays for variant X"

## Prerequisites

Before analyzing session replays:

1. The experiment must be **launched** (not in draft state)
2. Session replay must be enabled for the project
3. Users must have been exposed to the experiment variants
4. The experiment must have a start date

## Workflow

### 1. Get experiment details and feature flag variants

First, retrieve the experiment information and the feature flag variants (source of truth).

**Step 1a: Get experiment metadata**

You can either:

- **Option A**: Use the `experiment_results_summary` tool if you already have the experiment ID from context
- **Option B**: Query the experiments table via HogQL:

```sql
SELECT
    id,
    name,
    feature_flag_key,
    start_date,
    end_date
FROM system.experiments
WHERE id = <experiment_id>
  AND team_id = <team_id>
```

From the experiment data, extract:

- `feature_flag_key`: The feature flag controlling the experiment
- `start_date` and `end_date`: The experiment's time range

**Step 1b: Get variants from the feature flag**

**IMPORTANT**: Always get variants from the feature flag, NOT from `experiment.parameters.feature_flag_variants`.
The parameters can be out of sync or deprecated. The feature flag is the source of truth.

Query the feature flag to get the current variants:

```sql
SELECT
    key,
    filters
FROM system.feature_flags
WHERE key = '<feature_flag_key>'
  AND team_id = <team_id>
```

Extract the variant keys from `filters.multivariate.variants` array.
Example structure: `[{"key": "control", "name": "Control", "rollout_percentage": 50}, {"key": "test", ...}]`

The variant `key` values (e.g., "control", "test", "variant_a") are what you'll use to filter session recordings.

### 2. Build session recording filters for each variant

For each variant in the experiment, construct recording filters that match users exposed to that variant.

**Filter structure for a variant:**

```json
{
  "date_from": "<experiment.start_date>",
  "date_to": "<experiment.end_date or current time>",
  "filter_test_accounts": true,
  "events": [
    {
      "id": "$feature_flag_called",
      "type": "events",
      "properties": [
        {
          "key": "$feature_flag",
          "value": ["<feature_flag_key>"],
          "operator": "exact",
          "type": "event"
        },
        {
          "key": "$feature/<feature_flag_key>",
          "value": ["<variant_key>"],
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ]
}
```

**Key points:**

- Filter by `$feature_flag_called` events where the flag matches the experiment's feature flag
- Use `$feature/<flag_key>` property to filter for the specific variant value
- Set the date range to the experiment's start and end dates
- Enable `filter_test_accounts: true` to exclude test users

### 3. Retrieve recordings for each variant

Use the `filter_session_recordings` tool with the filters constructed in step 2.

Call the tool once per variant to get recordings for each group:

- Variant "control" → recordings for control group
- Variant "test" → recordings for test variant
- Additional variants if the experiment has more than 2

The tool returns a list of recordings with metadata including:

- User/distinct_id
- Session duration
- Activity metrics (clicks, keypresses)
- Console errors
- First URL visited
- Start time

### 4. Compare and analyze

Compare the recordings between variants by looking for:

**Quantitative patterns:**

- Session duration differences
- Activity levels (clicks, keypresses)
- Console error rates
- Bounce rates

**Qualitative insights:**

- User confusion or frustration indicators
- Different navigation paths
- Feature discovery patterns
- Error recovery behavior

### 5. Present findings

Summarize the behavioral differences between variants, highlighting:

- Total recordings per variant
- Notable behavior patterns unique to each variant
- Usability issues or friction points observed
- Recommendations based on the qualitative data

## Example interaction

```text
User: "How are users behaving in my checkout experiment?"
Agent steps:
1. Query experiment details (ID: 123, feature_flag_key: "checkout-flow-test", date range: 2025-01-01 to 2025-01-31)
2. Query feature flag "checkout-flow-test" to get variants from filters.multivariate.variants
3. Extract variant keys: "control" and "new-checkout"
4. Build filters for control variant:
   - Events: $feature_flag_called with $feature_flag="checkout-flow-test" and $feature/checkout-flow-test="control"
   - Date range: 2025-01-01 to 2025-01-31
5. Call filter_session_recordings with control filters → 147 recordings found
6. Build filters for new-checkout variant and call filter_session_recordings → 152 recordings found
7. Compare patterns:
   - Control: Average 3m 45s session duration, 12% console errors
   - New-checkout: Average 2m 30s session duration, 5% console errors
8. Present findings:
   "I analyzed session replays for your checkout experiment. The new checkout flow shows:
   - 33% faster completion (2m 30s vs 3m 45s)
   - 58% fewer console errors (5% vs 12%)
   - Users in the new variant navigate directly to payment, while control users often backtrack to review cart
   - Recommendation: The new checkout flow reduces friction and errors"
```

## Important notes

**Do not make assumptions:**

- Always verify the experiment has recordings before analyzing
- Check that the experiment is launched (has a start_date)
- If no recordings are found, inform the user clearly

**Filter construction:**

- The `$feature/<flag_key>` property is how PostHog tracks which variant a user saw
- Always use `$feature_flag_called` as the event type
- Both `$feature_flag` and `$feature/<flag_key>` properties are required

**Error handling:**

- If the experiment is in draft state, tell the user it hasn't started yet
- If no recordings exist, suggest enabling session replay or waiting for user traffic
- If the variant count is unexpected, double-check the experiment configuration

## Related tools

- `filter_session_recordings`: Core tool for retrieving session recordings with filters
- `experiment_results_summary`: Get experiment metadata and statistical results
- `execute_sql`: Query experiments table for details via HogQL
