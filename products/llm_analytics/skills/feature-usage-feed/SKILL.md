---
name: feature-usage-feed
description: >
  Set up an LLM-judge evaluation that extracts canonical use cases for a
  PostHog feature at scale and streams the results to a Slack channel as a
  live feed. Use when someone wants to understand how users are actually
  using a specific AI/LLM-powered feature in production — what they're
  investigating, what questions they're trying to answer, and what
  patterns surface — without manually reading hundreds of traces. Assumes
  the feature emits `$ai_generation` and `$ai_evaluation` events with
  `$session_id` linkage to the trigger user's recording (the standard
  setup post the session-summary linkage PRs).
---

# Building a feature usage feed via LLM evals

Some PostHog features (group session summaries, single session summaries, replay AI search, error tracking AI debug, etc.) generate hundreds or thousands of LLM traces per week. Reading them by hand is not feasible. This skill covers the end-to-end pattern for turning that trace volume into a live Slack feed of canonical use cases — what users are actually doing with the feature.

The workflow is **mixed**: eval creation, prompt iteration, and trace inspection are MCP-driven. The Slack alert setup is UI-driven (no create tool exists for subscriptions or hog functions). Plan accordingly — you can do steps 1-5 from chat, then hand the templates from this skill into the UI for step 6.

## When to use

- "How are people actually using [feature X] in production?"
- "Can we identify the canonical use cases for [feature X] so we can write better docs / prioritize improvements?"
- "I want a Slack feed of representative usage examples without manually skimming traces."
- "Set up a feed of use cases for [feature X] in #team-[area]-usage."

If the user just wants to debug a single trace or tune an existing eval, redirect to `exploring-llm-traces` or `exploring-llm-evaluations` instead.

## Prerequisites

| Requirement | How to verify |
| --- | --- |
| Feature emits `$ai_generation` events with a stable `$ai_trace_id` pattern | `posthog:execute-sql` for distinct `$ai_trace_id` prefixes |
| `$session_id` is attached to the `$ai_generation` events (links trace to trigger session) | `posthog:execute-sql` for `count() / countIf($session_id is not null)` |
| `$session_id` is also attached to the `$ai_evaluation` events (lets the Slack alert link to the session) | Same query but on `$ai_evaluation` events after the eval has run once |
| User has organisation-level AI data processing approval | Required for `llm_judge` evaluations and the eval summary tool |

If `$session_id` is missing on either event type, file a backend fix before continuing — there is no UI workaround. The session-summary feature has a worked example of the threading pattern in PR #54952.

## Tools

| Tool | Purpose |
| --- | --- |
| `posthog:query-llm-traces-list` | Find sample traces matching the feature's `$ai_trace_id` pattern |
| `posthog:query-llm-trace` | Inspect a specific trace's contents end-to-end |
| `posthog:execute-sql` | Verify trace volume, session_id coverage, eval result distributions |
| `posthog:evaluation-create` | Create the LLM-judge eval (disabled at first) |
| `posthog:evaluation-run` | Dry-run the eval against specific generations during prompt iteration |
| `posthog:evaluation-update` | Tweak the prompt / enable when ready |
| `posthog:llm-analytics-evaluation-summary-create` | After the feed is running, get an AI summary of pass/N/A patterns to validate signal quality |

## Workflow

### Step 1 — Identify the feature's trace_id pattern

Most PostHog AI features use a structured `$ai_trace_id` like `session-summary:group:<user>-<team>:<span>:<uuid>` or `replay-search:...`. Find the prefix:

```sql
SELECT
    splitByChar(':', properties.$ai_trace_id)[1] AS root,
    splitByChar(':', properties.$ai_trace_id)[2] AS subtype,
    count() AS events
FROM events
WHERE timestamp > now() - INTERVAL 3 DAY
    AND event = '$ai_generation'
    AND properties.$ai_trace_id IS NOT NULL
GROUP BY root, subtype
ORDER BY events DESC
LIMIT 25
```

Note the prefix that maps to the feature you care about. You'll use it as the eval's filter.

### Step 2 — Pull a handful of sample traces

Use these for prompt iteration in step 4:

```json
posthog:query-llm-traces-list
{
  "properties": [
    {
      "type": "event",
      "key": "$ai_trace_id",
      "operator": "icontains",
      "value": "<your-prefix-here>"
    }
  ],
  "limit": 10,
  "dateRange": { "date_from": "-2d" },
  "randomOrder": true
}
```

`randomOrder: true` matters — recency bias produces a non-representative sample. Pick 5-10 traces to test against.

### Step 3 — Draft the LLM-judge prompt

The prompt has two responsibilities: (a) classify the trace as relevant or not, (b) produce reasoning text that is **directly postable to Slack** (no preamble, no meta-description). The reasoning field becomes the Slack message body.

Template:

```
You are analyzing a PostHog [FEATURE NAME] trace to extract its real use case.
Your reasoning text will be posted directly to a Slack channel as a notification.
Write it as a short, ready-to-post message — no preamble, no meta-description.

Step 1 — Classification:
- PASS = this trace is the [feature kind] you care about
- FAIL = a different LLM call or a false match
- N/A = ambiguous from the trace alone

Step 2 — Reasoning (only matters if PASS). Write 2-3 sentences in this exact format:

"A user ran [feature name] on [what they targeted/filtered for]. They were
trying to [understand X / debug Y / find Z]. The result surfaced [key pattern
or finding]."

Your output MUST start with the exact phrase "A user ran". No other opening is allowed.

Rules:
- No "This is a [feature]..." or "The input contains..." preamble
- No JSON, field names, system-prompt references, or meta-description
- Concrete > generic. "users hitting error tracking for the first time" beats "user behavior"
- If you cannot infer one of the three pieces from the trace, write "(unclear from trace)" in that slot — do not guess
```

The forced opening (`"A user ran"`) and the negative example list are both load-bearing — without them, models drift into describing the input structure instead of extracting use case content. Do not remove them.

### Step 4 — Create the eval (disabled), test, iterate

Create with `enabled: false` so it doesn't immediately fan out to all traces:

```json
posthog:evaluation-create
{
  "name": "[feature] use case feed",
  "description": "Extracts canonical use cases for [feature] for the #team-[area]-usage Slack feed",
  "evaluation_type": "llm_judge",
  "evaluation_config": {
    "prompt": "<full prompt from step 3>"
  },
  "output_type": "boolean",
  "output_config": { "allows_na": true },
  "model_configuration": {
    "provider": "openai",
    "model": "gpt-5-mini"
  },
  "enabled": false,
  "conditions": {
    "filters": [
      { "key": "$ai_trace_id", "operator": "icontains", "value": "<your-prefix>" }
    ]
  }
}
```

Then dry-run against your sample traces:

```json
posthog:evaluation-run
{
  "evaluationId": "<uuid from create>",
  "target_event_id": "<a $ai_generation event id from step 2>",
  "timestamp": "<ISO timestamp of that event>"
}
```

Look at the returned `$ai_evaluation_reasoning`. If it preambles, drifts, or describes the input, fix the prompt via `evaluation-update` and re-run. Iterate on 3-5 traces before enabling.

Common failure modes during iteration:

| Symptom | Fix |
| --- | --- |
| Reasoning starts with "This is a..." | Strengthen the forced opener instruction; add a counter-example |
| Reasoning is generic ("user behavior", "various patterns") | Add positive examples of concrete phrasing in the prompt |
| Model classifies everything as PASS | Tighten the FAIL definition; add an example of what a non-match looks like |
| Reasoning is too long for Slack | Add a hard sentence cap ("MAX 3 sentences, hard limit") |

### Step 5 — Enable the eval

Once 3-5 sample runs produce clean Slack-ready output:

```json
posthog:evaluation-update
{
  "evaluationId": "<uuid>",
  "enabled": true
}
```

The eval will now run on every new matching `$ai_generation` event.

### Step 6 — Set up the Slack alert (UI only)

This part is not MCP-accessible. Walk the user through:

1. Go to the Slack alert / subscription / hog function UI in PostHog (depends on which surface their org uses for event-driven Slack notifications)
2. Set the trigger filter:

```sql
event = '$ai_evaluation'
AND properties.$ai_evaluation_name = '<your eval name from step 4>'
AND properties.$ai_evaluation_result = 'PASS'
```

3. Set the message template (Slack block kit JSON):

```json
[
  {
    "text": {
      "text": "📊 *{event.properties.$ai_evaluation_name}* triggered by *{person.name}*",
      "type": "mrkdwn"
    },
    "type": "section"
  },
  {
    "text": {
      "text": "{event.properties.$ai_evaluation_reasoning}",
      "type": "mrkdwn"
    },
    "type": "section"
  },
  {
    "type": "actions",
    "elements": [
      {
        "url": "https://us.posthog.com/project/{project_id}/llm-analytics/traces/{event.properties.$ai_trace_id}?event={event.properties.$ai_target_event_id}",
        "text": { "text": "View Trace", "type": "plain_text" },
        "type": "button"
      },
      {
        "url": "https://us.posthog.com/project/{project_id}/replay/{event.properties.$session_id}",
        "text": { "text": "View Trigger Session", "type": "plain_text" },
        "type": "button"
      },
      {
        "url": "{person.url}",
        "text": { "text": "View Person", "type": "plain_text" },
        "type": "button"
      }
    ]
  }
]
```

Replace `{project_id}` with the actual project ID literal (e.g. `2`). The other `{event.properties.X}` and `{person.X}` placeholders are valid PostHog template syntax and resolve at send time.

### Step 7 — Verify

Trigger the feature yourself in production. Within a minute or two:

1. The `$ai_generation` event should appear in LLM Analytics
2. The eval should auto-run and emit an `$ai_evaluation` event
3. The Slack alert should fire in the configured channel
4. Click "View Trigger Session" — should land on the recording of you using the feature, not the homepage

If "View Trigger Session" lands on the replay homepage, `$session_id` is missing on the `$ai_evaluation` event (different from the `$ai_generation` event). Backend fix needed — see prerequisites.

## Worked example: group session summary use cases

Cory Slater (PM) used this exact pattern in April 2026 to set up the `group_summary_use_case_feed` eval streaming to `#team-replay-usage-feed`. The feature gets ~1k uses/week. Trace prefix: `session-summary:group:`. Slack channel showed e.g.:

> 📊 *group_summary_use_case_feed* triggered by *some user*
> "A user ran a group summary on Finco onboarding sessions from the last 7 days. They were trying to understand why account activation rates are low. The summary surfaced that most users abandon at the company onboarding wizard after creating accounts."
> [View Trace] [View Trigger Session] [View Person]

The PRs that made this work (linked here as worked examples of the session_id threading pattern, not as steps in the skill itself):

- PostHog/posthog#54952 — threads `trigger_session_id` through to `$ai_generation` events on the session summary backend
- (Followup PR — threads `$session_id` onto `$ai_evaluation` events specifically)

## Validating signal quality after launch

Once the feed has been running for a day or two, sanity-check the eval output at scale:

```json
posthog:llm-analytics-evaluation-summary-create
{
  "evaluation_id": "<uuid>",
  "filter": "fail"
}
```

If the FAIL bucket is large, the classification step is too strict — relax it. If the PASS bucket has lots of generic reasonings, iterate on the prompt to enforce concreteness. The summary tool gives a quick read on this without you having to scroll through individual events.

Spot-check raw events when needed:

```sql
SELECT
    properties.$ai_evaluation_reasoning AS reasoning,
    properties.$ai_trace_id AS trace_id,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_name = '<your eval name>'
    AND properties.$ai_evaluation_result = 'PASS'
    AND timestamp > now() - INTERVAL 1 DAY
ORDER BY timestamp DESC
LIMIT 25
```

## Tips

- The reasoning field IS the Slack message — design the prompt for that, not for "chain of thought before classification." Models can produce structured Slack-ready text in one pass.
- LLM judges are non-deterministic across reruns. Expect 1-5% noise even with a fixed prompt and model. If you need reproducibility, pin a deterministic provider/seed in `model_configuration`.
- Keep the eval scoped tightly via `conditions.filters` on `$ai_trace_id` prefix. Otherwise it fans out to every `$ai_generation` event in the project and burns LLM cost.
- For high-volume features (>10k traces/week), consider sampling — set the eval to run on a percentage of matching events rather than all of them. Slack flooding is a real failure mode.
- The "View Trigger Session" button is the highest-value link in the alert. Without it, the feed is just text — you can't watch what the user was actually doing. Verify it works in step 7 before considering the feed shipped.
- Once the feed is live, periodically re-run the eval summary tool with `filter: "pass"` to surface the dominant use case clusters. That's how you turn the feed into actual product insights instead of just a notification stream.
