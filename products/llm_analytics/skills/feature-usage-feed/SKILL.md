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

The workflow is **mixed, and leans UI**. Trace inspection and filter discovery (steps 1-2) are MCP-driven. Eval creation, dry-running, and enabling (steps 4-5) are MCP-driven _when_ `posthog:evaluation-*` tools are exposed to your agent — but they often aren't, in which case fall back to the UI (Data pipeline → destinations for the alert is always UI). Each step flags its UI fallback. Expect to finish in the UI even when you start from chat.

## When to use

- "How are people actually using [feature X] in production?"
- "Can we identify the canonical use cases for [feature X] so we can write better docs / prioritize improvements?"
- "I want a Slack feed of representative usage examples without manually skimming traces."
- "Set up a feed of use cases for [feature X] in #team-[area]-usage."

If the user just wants to debug a single trace or tune an existing eval, redirect to `exploring-llm-traces` or `exploring-llm-evaluations` instead.

## Two filter patterns

This skill supports two different ways to scope an eval to "the feature you care about":

**Pattern A — Feature-native trace_id prefix.** For standalone features that emit their own `$ai_trace_id` pattern (e.g. `session-summary:group:`, `replay-search:`, error-tracking-specific flows). Filter on the prefix.

**Pattern B — PostHog AI agent mode.** For features the user interacts with _via_ PostHog AI in a specific agent mode (error tracking, product analytics, session replay, SQL, flags, surveys, LLM analytics). Filter on `ai_product = 'posthog_ai' AND agent_mode = '<mode>'`. This requires PR #55160 (merged April 2026) to be deployed, which threads `agent_mode` and `supermode` onto every `$ai_generation` emitted by the chat agent loop. A useful ergonomic side-effect: `agent_mode IS NOT NULL` is a reliable "user-facing chat turn" filter — batch jobs and tool-internal LLM calls go through different code paths and have `agent_mode=null`, so they're excluded for free.

If the user asks "what are users trying to DO in [ET / replay / SQL / flags / surveys] mode of PostHog AI", that's Pattern B. If they ask "what use cases does [standalone feature] cover", that's Pattern A. Pick the pattern first — the prompt, filter, and Slack channel naming all follow from it.

## Prerequisites

| Requirement                                                                                              | How to verify                                                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| (Pattern A) Feature emits `$ai_generation` events with a stable `$ai_trace_id` pattern                   | `posthog:execute-sql` for distinct `$ai_trace_id` prefixes                                                                                                                                                                |
| (Pattern B) `agent_mode` property is present on recent `$ai_generation` events                           | `posthog:execute-sql` group-by `properties.agent_mode` on recent `ai_product='posthog_ai'` events. Null bucket is normal (batch jobs + tool-internal calls) — you want non-null coverage across the modes you care about. |
| `$session_id` is attached to the `$ai_generation` events (links trace to trigger session)                | `posthog:execute-sql` for `countIf($session_id IS NOT NULL) / count()`                                                                                                                                                    |
| `$session_id` is also attached to the `$ai_evaluation` events (lets the Slack alert link to the session) | Same query but on `$ai_evaluation` events after the eval has run once                                                                                                                                                     |
| User has organisation-level AI data processing approval                                                  | Required for `llm_judge` evaluations and the eval summary tool                                                                                                                                                            |

If `$session_id` is missing on either event type, file a backend fix before continuing — there is no UI workaround. The session-summary feature has a worked example of the threading pattern in PR #54952. For Pattern B, the agent-mode threading pattern is in PR #55160.

## Tools

| Tool                                               | Purpose                                                                                                                                                                                                                                                           |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog:query-llm-traces-list`                    | Find sample traces matching the feature's `$ai_trace_id` pattern                                                                                                                                                                                                  |
| `posthog:query-llm-trace`                          | Inspect a specific trace's contents end-to-end                                                                                                                                                                                                                    |
| `posthog:execute-sql`                              | Verify trace volume, session_id coverage, eval result distributions                                                                                                                                                                                               |
| `posthog:evaluation-create`                        | (**often unexposed** — UI fallback: LLM analytics → Evaluations → New) Create the LLM-judge eval (disabled at first)                                                                                                                                              |
| `posthog:evaluation-run`                           | (**often unexposed** — UI fallback: the eval's detail page has a "Run on event" button) Dry-run the eval against specific generations during prompt iteration                                                                                                     |
| `posthog:evaluation-update`                        | (**often unexposed** — UI fallback: edit the eval in LLM analytics → Evaluations) Tweak the prompt / enable when ready                                                                                                                                            |
| `posthog:llm-analytics-evaluation-summary-create`  | (**often unexposed** — UI fallback: the eval detail page has a "Summarize results" button) After the feed is running, get an AI summary of pass/N/A patterns to validate signal quality                                                                           |
| `posthog:workflows-list` / `posthog:workflows-get` | (**often unexposed** — UI: Data pipeline → Workflows) Browse existing workflow configs — useful for cloning an existing feed's structure when setting up a new one. Read-only; no create/update tool is exposed yet, so step 6's Slack workflow setup is UI-only. |

Before starting, **check which of the `posthog:evaluation-*` tools are actually exposed in your agent's MCP tool set.** If they aren't loaded, treat steps 4-5 as UI walkthroughs rather than tool calls.

## Workflow

### Step 1 — Identify the filter

**Pattern A (feature-native trace_id prefix):** find the prefix that maps to your feature.

```sql
SELECT
    splitByChar(':', coalesce(properties.$ai_trace_id, ''))[1] AS root,
    splitByChar(':', coalesce(properties.$ai_trace_id, ''))[2] AS subtype,
    count() AS events
FROM events
WHERE timestamp > now() - INTERVAL 3 DAY
    AND event = '$ai_generation'
    AND properties.$ai_trace_id IS NOT NULL
GROUP BY root, subtype
ORDER BY events DESC
LIMIT 25
```

Note: `coalesce(..., '')` is load-bearing — `splitByChar` on a nullable column errors out in HogQL otherwise.

**Pattern B (PostHog AI agent mode):** verify coverage and volume for the mode you're targeting.

```sql
SELECT
    properties.agent_mode AS agent_mode,
    properties.supermode AS supermode,
    count() AS events,
    count(DISTINCT properties.$ai_trace_id) AS traces
FROM events
WHERE timestamp > now() - INTERVAL 3 DAY
    AND event = '$ai_generation'
    AND properties.ai_product = 'posthog_ai'
GROUP BY agent_mode, supermode
ORDER BY events DESC
LIMIT 20
```

Expected values for `agent_mode`: `error_tracking`, `product_analytics`, `sql`, `session_replay`, `flags`, `survey`, `llm_analytics`, `null`. Null ≈ batch jobs + tool-internal calls (not user chat). `supermode='plan'` splits planning turns from execution turns — worth calling out separately if your feed is about plan-mode specifically.

Record the mode + rough volume. Low-volume modes (<100 events/day) will produce a trickle-feed that's hard to validate early; high-volume modes (>1k/day) may need sampling to avoid Slack flooding. See the "Tips" section on sampling.

### Step 2 — Pull a handful of sample traces

Use these for prompt iteration in step 4.

**Pattern A:**

```json
posthog:query-llm-traces-list
{
  "properties": [
    { "type": "event", "key": "$ai_trace_id", "operator": "icontains", "value": "<your-prefix-here>" }
  ],
  "limit": 10,
  "dateRange": { "date_from": "-2d" },
  "randomOrder": true
}
```

**Pattern B:**

```json
posthog:query-llm-traces-list
{
  "properties": [
    { "type": "event", "key": "ai_product", "operator": "exact", "value": "posthog_ai" },
    { "type": "event", "key": "agent_mode", "operator": "exact", "value": "<mode-here>" }
  ],
  "limit": 10,
  "dateRange": { "date_from": "-2d" },
  "randomOrder": true
}
```

`randomOrder: true` matters — recency bias produces a non-representative sample. Pick 5-10 traces to test against.

**Output size warning:** `query-llm-traces-list` with `limit: 10` routinely returns 3-6MB of JSON (full input/output per generation). This will blow your context window. **Immediately delegate the summarization to a subagent** the moment you see the "result exceeds maximum allowed tokens" error — ask the subagent to extract, per trace: the trace id, the first user message (truncated to ~300 chars), the sampled `$current_url`, and a one-sentence description of what the conversation was about. Don't try to read the raw file in-line.

**Watch for topic drift in Pattern B samples.** The `agent_mode` tag reflects the user's mode selection at the time of the turn — but chat state retains the mode even if the user drifts off-topic within the same conversation (e.g. user selected "error tracking" mode, then asked an unrelated pricing question three turns later). Your eval prompt's classification step needs to be permissive about topic-drift: PASS should mean "user is doing something recognizably in-scope for this mode", FAIL should catch the off-topic drift. If you don't, your feed will include irrelevant PASS entries that happen to carry the mode tag.

### Step 3 — Draft the LLM-judge prompt

The prompt has two responsibilities: (a) classify the trace as relevant or not, (b) produce reasoning text that is **directly postable to Slack** (no preamble, no meta-description). The reasoning field becomes the Slack message body.

Template:

```text
You are analyzing a PostHog [FEATURE NAME] trace to extract its real use case.
Your reasoning text will be posted directly to a Slack channel as a notification.
Write it as a short, ready-to-post message — no preamble, no meta-description.

Step 1 — Classification:
- PASS = this trace is the [feature kind] you care about
- FAIL = a different LLM call or a false match
- N/A = ambiguous from the trace alone

Step 2 — Reasoning (only matters if PASS). Write 2-3 sentences in this exact format:

"[OPENER] [what they targeted/filtered for]. They were
trying to [understand X / debug Y / find Z]. The result surfaced [key pattern
or finding]."

Your output MUST start with the exact phrase "[OPENER]". No other opening is allowed.

Rules:
- No "This is a [feature]..." or "The input contains..." preamble
- No JSON, field names, system-prompt references, or meta-description
- Concrete > generic. "users hitting error tracking for the first time" beats "user behavior"
- If you cannot infer one of the three pieces from the trace, write "(unclear from trace)" in that slot — do not guess
```

**Pick an `[OPENER]` that matches how users actually interact with the feature.** The forced opener is load-bearing (it prevents the model from drifting into "this trace is a..." meta-description), but the exact verb has to fit the interaction:

| Feature / mode                    | OPENER                                     |
| --------------------------------- | ------------------------------------------ |
| Session summary (group / single)  | `A user ran a summary on`                  |
| Replay AI search                  | `A user searched replays for`              |
| PostHog AI in error tracking mode | `A user asked PostHog AI about`            |
| PostHog AI in session replay mode | `A user asked PostHog AI about`            |
| PostHog AI in SQL mode            | `A user asked PostHog AI to write SQL for` |

Note: `supermode='plan'` is a sub-filter that layers _on top of_ an `agent_mode` row — it's not its own row. If you want plan-mode-only, filter `agent_mode='<mode>' AND supermode='plan'` and pick an opener like `"A user asked PostHog AI to plan"`.

If you force `"A user ran"` on a chat-based feature, the model will produce awkward contortions ("A user ran a question about...") that read wrong in Slack. The forced-opener pattern is the mechanism — the specific phrase is per-feature.

The negative example list ("No 'This is a...' preamble", etc.) is load-bearing regardless of opener. Don't remove it.

### Step 4 — Create the eval (disabled), test, iterate

Create with `enabled: false` so it doesn't immediately fan out to all traces.

**If `posthog:evaluation-create` is exposed**, use this payload:

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
    "provider": "<provider>",
    "model": "<model>"
  },
  "enabled": false,
  "conditions": {
    "filters": [
      // Pattern A — feature-native trace_id prefix:
      { "key": "$ai_trace_id", "operator": "icontains", "value": "<your-prefix>" }

      // Pattern B — PostHog AI agent mode (use these INSTEAD of the trace_id filter):
      // { "key": "ai_product", "operator": "exact", "value": "posthog_ai" },
      // { "key": "agent_mode", "operator": "exact", "value": "<mode>" }
    ]
  }
}
```

Leave model choice to the user — LLM-judge cost scales linearly with event volume, and cheap-vs-capable is a real tradeoff they should make based on their own spend tolerance and signal-quality requirements. Don't pick for them.

**UI fallback** (when `evaluation-create` isn't exposed): LLM analytics → Evaluations → New evaluation. Type = `LLM judge`, output = boolean + allow N/A, filters as above, enabled = off. Paste the prompt from step 3.

Then dry-run against your sample traces.

**If `posthog:evaluation-run` is exposed:**

```json
posthog:evaluation-run
{
  "evaluationId": "<uuid from create>",
  "target_event_id": "<a $ai_generation event id from step 2>",
  "timestamp": "<ISO timestamp of that event>"
}
```

**UI fallback:** on the eval detail page, use the "Run on event" button with the trace sample's event id.

Look at the returned `$ai_evaluation_reasoning`. If it preambles, drifts, or describes the input, fix the prompt (via `evaluation-update` or by editing in the UI) and re-run. Iterate on 3-5 traces before enabling.

Common failure modes during iteration:

| Symptom                                                    | Fix                                                                        |
| ---------------------------------------------------------- | -------------------------------------------------------------------------- |
| Reasoning starts with "This is a..."                       | Strengthen the forced opener instruction; add a counter-example            |
| Reasoning is generic ("user behavior", "various patterns") | Add positive examples of concrete phrasing in the prompt                   |
| Model classifies everything as PASS                        | Tighten the FAIL definition; add an example of what a non-match looks like |
| Reasoning is too long for Slack                            | Add a hard sentence cap ("MAX 3 sentences, hard limit")                    |

### Step 5 — Enable the eval

Once 3-5 sample runs produce clean Slack-ready output.

**If `posthog:evaluation-update` is exposed:**

```json
posthog:evaluation-update
{
  "evaluationId": "<uuid>",
  "enabled": true
}
```

**UI fallback:** LLM analytics → Evaluations → open the eval → toggle enabled.

The eval will now run on every new matching `$ai_generation` event.

### Step 6 — Build the workflow (UI only)

Workflow setup is not MCP-accessible for writes (`posthog:workflows-list` / `posthog:workflows-get` are read-only). The steps below are a UI walkthrough.

**Prereq:** before you start, invite the PostHog Slack bot to your target channel (`/invite @PostHog` in the Slack channel). Without this, the Slack dispatch step will fail with an opaque permission error at send time, not at save time — easy to miss.

#### 6.1 Create the workflow

Data pipeline → Workflows → New workflow. Name it `<feature> use case feed` to match the eval name from step 4.

#### 6.2 Trigger step

- **Event:** `AI evaluation (LLM)` — i.e. `$ai_evaluation`. This is the event emitted when an eval runs, and it's the only event that carries `$ai_evaluation_*` properties. The original `$ai_generation` event is **not** enriched with eval results, so filtering on `$ai_generation` here matches nothing.
- **Property filters (both required):**
  - `AI Evaluation Name (LLM)` equals `<your eval name from step 4>`
  - `AI Evaluation Result (LLM)` equals `true`

**⚠️ LOAD-BEARING:** the stored values for `$ai_evaluation_result` are the strings `'True'` / `'False'` / `'None'` — NOT `'PASS'` / `'FAIL'` / `'N/A'` (despite what the prompt template calls them internally). The Workflows UI property filter normalizes `true` → `'True'`, so selecting `equals true` from the dropdown works. But if you were wiring this in raw SQL somewhere else (say a hog function), you'd need the string literal. Verify the stored distribution before saving:

```sql
SELECT DISTINCT toString(properties.$ai_evaluation_result) AS result, count() AS n
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_evaluation_name = '<your eval name>'
  AND timestamp > now() - INTERVAL 1 HOUR
GROUP BY result
```

If the only values are `True`/`False`/`None` and `True` dominates, the UI `equals true` filter will match. If you see anything else, adjust accordingly.

#### 6.3 Slack dispatch step

- **Add step → Slack dispatch**
- **Channel:** `#<your-team>-usage-feed`
- **Sender / bot display name:** something that reads well in the channel (e.g. `PostHog Usage Feed`)
- **Blocks (Slack block-kit JSON)** — paste this and replace `<project_id>` with your actual numeric project ID (e.g. `2`):

```json
[
  {
    "text": {
      "text": "<emoji> *{event.properties.$ai_evaluation_name}* triggered by *{person.name}*",
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
        "url": "https://us.posthog.com/project/<project_id>/llm-analytics/traces/{event.properties.$ai_trace_id}?event={event.properties.$ai_target_event_id}",
        "text": { "text": "View Trace", "type": "plain_text" },
        "type": "button"
      },
      {
        "url": "https://us.posthog.com/project/<project_id>/replay/{event.properties.$session_id}",
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

Pick an `<emoji>` that matches the feature's shape: 📊 product analytics, 🐛 error tracking, 🎬 session replay, 🔎 search/AI search, 🧪 experiments, 🚩 flags, 📋 surveys, 🧠 generic AI.

The `{event.properties.X}` and `{person.X}` placeholders are valid PostHog template syntax and resolve at send time.

#### 6.4 Test before enabling

The Workflows Test panel has two modes — this matters because naively hitting "Test" can look like a broken integration when it isn't:

- **Synthetic event** (default) — the Test panel fabricates an `$ai_evaluation` payload and runs the flow without hitting Slack's real API. Useful as a dry-run of the block template, but `{event.properties.$ai_*}` placeholders may resolve to `null` and Slack's block validator will reject the payload with `invalid_blocks`. That's a test-harness artifact, not a real bug — don't chase it.
- **"Make real HTTPS requests"** — flip this toggle on. Workflows then pulls a recent real `$ai_evaluation` event matching your filters and runs the flow end-to-end, including the actual Slack post. This is the test that tells you "it works" for real. If no matching real event exists yet (common if the eval was just enabled), trigger the feature yourself, wait ~1 minute, and retry.

Recommended flow: synthetic → sanity-check the block template renders → flip real-requests on → confirm an actual post lands in the channel → save + enable the workflow.

### Step 7 — End-to-end verify in production

Once the workflow is enabled, trigger the feature yourself. Within a minute or two:

1. The `$ai_generation` event should appear in LLM Analytics
2. The eval should auto-run and emit an `$ai_evaluation` event
3. The workflow should fire and the Slack post should land in the configured channel
4. Click "View Trigger Session" — should land on the recording of you using the feature, not the replay homepage

If "View Trigger Session" lands on the replay homepage, `$session_id` is missing on the `$ai_evaluation` event (which is separate from the `$ai_generation` event — threading is independent for the two). Backend fix needed — see prerequisites.

## Worked example A (Pattern A): group session summary use cases

Pattern: a `group_summary_use_case_feed` eval streaming to a `#<team>-usage-feed` channel. Trace prefix: `session-summary:group:`. Opener: `"A user ran a group summary on"`. Slack channel showed e.g.:

> 📊 _group_summary_use_case_feed_ triggered by _some user_
> "A user ran a group summary on a company's onboarding sessions from the last 7 days. They were trying to understand why account activation rates are low. The summary surfaced that most users abandon at the company onboarding wizard after creating accounts."
> [View Trace] [View Trigger Session] [View Person]

The PRs that made this work (linked here as worked examples of the session_id threading pattern, not as steps in the skill itself):

- PostHog/posthog#54952 — threads `trigger_session_id` through to `$ai_generation` events on the session summary backend
- (Followup PR — threads `$session_id` onto `$ai_evaluation` events specifically)

## Worked example B (Pattern B): PostHog AI in error tracking mode

Pattern: an `agent_mode = 'error_tracking'` scoped feed streaming to a `#<team>-usage-feed` channel, answering "what are users actually trying to DO when they chat with PostHog AI in error tracking mode?" Mode sizing varies by an order of magnitude or more across agent modes — spot-check volume per §Step 1 before wiring, because a high-volume mode can flood a channel. Opener: `"A user asked PostHog AI about"`.

Enabling PR: PostHog/posthog#55160 — threads `agent_mode` and `supermode` onto every `$ai_generation` emitted by the chat agent loop. Wiring lives in `ee/hogai/core/agent_modes/executables.py` (`AgentExecutable._get_model`) and passes the dict through the existing `posthog_properties` field on `MaxChatMixin` in `ee/hogai/llm.py`. Before this PR, scoping a PostHog AI eval to a specific mode wasn't possible — you'd end up evaluating every PostHog AI generation, which produced noisy feeds with low single-digit PASS rates.

Key observation from setup: the `agent_mode` tag reflects the mode at turn-time, but chat state retains mode selection even when users drift off-topic mid-conversation. Spot-check: a random `agent_mode=error_tracking` sample included a conversation that ended up being about session replay pricing. The eval prompt's classification must be permissive about topic drift — PASS only when the turn is recognizably in-scope for the mode, FAIL when the conversation has drifted to something else entirely.

## Validating signal quality after launch

Once the feed has been running for a day or two, sanity-check the eval output at scale.

**If `posthog:llm-analytics-evaluation-summary-create` is exposed:**

```json
posthog:llm-analytics-evaluation-summary-create
{
  "evaluation_id": "<uuid>",
  "filter": "fail"
}
```

**UI fallback:** open the eval in LLM analytics → Evaluations → "Summarize results" button, filter = fail.

If the FAIL bucket is large, the classification step is too strict — relax it. If the PASS bucket has lots of generic reasonings, iterate on the prompt to enforce concreteness. The summary tool gives a quick read on this without you having to scroll through individual events.

Spot-check raw events when needed (note: the stored result value is `'True'`, not `'PASS'` — see step 6):

```sql
SELECT
    properties.$ai_evaluation_reasoning AS reasoning,
    properties.$ai_trace_id AS trace_id,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_name = '<your eval name>'
    AND properties.$ai_evaluation_result = 'True'
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
