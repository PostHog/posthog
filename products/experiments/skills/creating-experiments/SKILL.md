---
name: creating-experiments
description: "Guides agents through experiment creation: reading the project's setup with experiment-setup-context, defining the hypothesis, configuring rollout and bucketing, setting up analytics and running time, and reporting which choices are guesses. Delegates rollout decisions to configuring-experiment-rollout and metric setup to configuring-experiment-analytics.\nTRIGGER when: user asks to create a new experiment or A/B test, OR when you are about to call experiment-create.\nDO NOT TRIGGER when: user is updating an existing experiment, managing lifecycle, or only browsing experiments."
---

# Creating experiments

This skill walks through creating a new A/B test experiment: read the project, then the 3-step flow, then report the draft.

## Core principle: draft first, iterate on details

Create the experiment as a draft quickly, then iterate on metrics and configuration.
The user gets a tangible draft immediately and can refine it.
Choose settings from the project's facts rather than asking, and say which choices are guesses.

## Step 0: Read the project

The right bucketing, metric and running time depend on the project: who sees the page, which SDKs evaluate the flag, how often the metric event happens.
Read that before configuring anything.

1. From the request, infer the **target** (the event that marks someone reaching the change, usually `$pageview` for a page) and a **candidate metric event**.
   Confirm both exist with `read-data-schema`. Don't ask the user for event names you can find.
   For a page, read `event_property_values` for `$host` and `$pathname` on the target event as well.
   The response samples the values rather than listing them all, so read it for the shape the project records (a trailing slash, a `www.` prefix, the casing) rather than as proof that a value is absent.
   An exact filter has to carry that shape: `/pricing` matches nothing where every pageview says `/pricing/`, and `example.com` matches nothing where the host is `www.example.com`.
2. If the `experiment-setup-context` tool is available, call it once with `target_event` and `metric_event`.
   For a web surface, add `target_properties` with an exact `$host`.
   Add an exact `$pathname` as well when the surface is one page.
   `target_url_contains` is a substring match on `$current_url`.
   A bare domain matches any host that contains it, `notexample.com` included, and a homepage path matches every page under it.
   Both overstate the traffic and the exposure rate.
   For a surface that spans several pages, keep the exact `$host` and put only the path fragment in `target_url_contains`.
   Add `metric_properties` in the same call when the candidate metric counts only some occurrences of its event.
   Pass `previous_experiments_limit: 5`. Five experiments are enough to read a precedent, and the default of 10 roughly doubles the response for no more signal.
   If the tool is not available, continue without it and treat every choice below as a best guess. Never call a tool you can't see.

   Each filter needs a `type` of `event` or `person`, a `key`, an `operator` and a `value`.
   The call rejects the `flag_evaluates_to` operator with a 400 that names it.
   For the homepage of one domain:

   ```json
   {
     "target_event": "$pageview",
     "target_properties": [
       { "key": "$host", "type": "event", "operator": "exact", "value": ["www.example.com"] },
       { "key": "$pathname", "type": "event", "operator": "exact", "value": ["/"] }
     ],
     "metric_event": "your_conversion_event",
     "previous_experiments_limit": 5
   }
   ```

3. Apply [references/setup-decisions.md](references/setup-decisions.md) to the result. It maps each fact to a choice (bucketing, where the flag is evaluated, exposure, primary metric, running time, precedent) and to a tier for the summary.
4. Carry those choices into steps 1 to 3.

Ask the user only when a choice is "not decided" and the user is in the conversation.
If the user said they are away, or asked for a draft without questions, decide with the defaults and list the open points in the report.

## The 3-step creation flow

### Step 1: What are we testing?

Gather these before calling `experiment-create`:

- **Experiment name** — descriptive, inferred from context when possible
- **Hypothesis** — what you expect to happen (goes in `description`)
- **Feature flag key** — kebab-case. Infer a new key unless the user names an existing flag.
  The flag is auto-created — do NOT create one separately. The one exception is device-id bucketing, which `experiment-create` cannot set (see the recipe in `configuring-experiment-rollout`).
- **Type** — leave empty (will internally default to `"product"`. The `"web"` value is reserved for no-code experiments configured visually with the PostHog
  toolbar in a browser; it cannot be meaningfully driven via MCP. If a user asks for a
  no-code/toolbar experiment, point them to the PostHog UI instead of creating one here.)

If the user gives enough context to infer these, don't ask — just proceed.

### Step 2: Who sees what variant?

This is about rollout configuration.

**Before asking any rollout question, load `configuring-experiment-rollout`.** The disambiguation wording, recommendations, and post-answer branches live there — do not formulate rollout questions yourself, and do not assume an example you remember covers the user's path.

Key decision points (covered in detail by `configuring-experiment-rollout`):

- Variant split (how many variants, what percentage each)
- Overall rollout percentage (what % of all users enter the experiment)
- Bucketing and whether to persist the flag across authentication steps — decided from the project's facts in step 0

If the user doesn't mention rollout specifics, use defaults: 50/50 control/test, 100% rollout.

### Step 3: How to measure impact?

This is about analytics and metrics. **Load the `configuring-experiment-analytics` skill** for guidance.
That skill's first step checks for an existing **shared metric** to reuse before building a new one —
don't duplicate a metric the project already has set up.

**Do NOT configure metrics on creation.** Metrics are not passed to `experiment-create` — they are added
afterwards via `experiment-update`. This keeps the creation call lightweight.

When the user specifies metrics upfront, acknowledge them and add them immediately after creation.
When they don't, infer the primary metric from the hypothesis (step 0) and add it after creation; say it was inferred.

If step 0 produced a running-time estimate, pass it to `experiment-create` as `running_time_calculation` so the plan is stored on the experiment.

## How to create

Call `experiment-create` with:

```json
{
  "name": "Descriptive experiment name",
  "feature_flag_key": "kebab-case-key",
  "description": "Hypothesis: [what you expect to happen]",
  "feature_flag": {
    "filters": {
      "multivariate": {
        "variants": [
          { "key": "control", "name": "Control", "rollout_percentage": 50 },
          { "key": "test", "name": "Test", "rollout_percentage": 50 }
        ]
      },
      "groups": [{ "properties": [], "rollout_percentage": 100 }]
    }
  }
}
```

Flag config goes in the `feature_flag` object, in the flag's own filters shape (not the deprecated `parameters` keys).
Two different percentages live in there, do NOT mix them up:

- `filters.multivariate.variants[].rollout_percentage` is how users **inside** the experiment are split across variants (must sum to 100, recommended to have an even split).
- `filters.groups[0].rollout_percentage` is the overall gate: what fraction of **all** users enter the experiment at all (0-100, defaults to 100).

Key details:

- Minimum 2, maximum 20 variants. No specific variant key is required — the analysis baseline defaults to the variant keyed `"control"` when present, else the first variant (override with `stats_config.baseline_variant_key`). Convention: key the baseline `"control"` unless the user asks for specific keys.
- `filters.groups[0].rollout_percentage` defaults to 100 if omitted.
- Bucketing and `ensure_experience_continuity` come from step 0. Keep user-id bucketing unless the page crosses identification. Only then, in this order: device-id bucketing when every flag call carries a device ID, else persistence when no SDK evaluates the flag locally, else user-id bucketing. On a mobile surface device-id bucketing is unavailable, because mobile events carry no device ID, so the choice is persistence or user-id bucketing. A project that has never used either is not a reason to skip them here. Leave `ensure_experience_continuity` out unless you are choosing persistence: when omitted, the team's persistence default applies.
- Stats follow the team's defaults (method, confidence level). Only set `stats_config` if the user asks for a different method.

## After creation

1. **Report the draft in three groups**, so the user can review it quickly:
   - **Set with confidence**: the choice and the fact behind it ("linked the shared metric 'Signups': it counts the signup event per person, as you asked").
   - **Best guess, please check**: the choice, the fact, and what would change it ("user-id bucketing: 94% of visitors are not identified; switch to device id if identified users also see this page").
   - **Not decided**: what is missing and how to decide it ("the flag is also evaluated on your server with local evaluation; check the server and browser use the same distinct ID").

   Also say what you could not read: a missing tool, or a section whose status was not `ok`.

2. **Always show the experiment URL.** The `experiment-create` response includes `_posthogUrl` — always display this link so the user can view and configure the experiment in the UI.

3. **Remind the user to implement the feature flag in code.** Link to the experiment page and say "implement the flag as shown here" — the experiment detail page shows implementation snippets for the user's SDK.

4. **Guide through metrics** if not yet configured — load the `configuring-experiment-analytics` skill.

5. **Launch only when the user asks for it** — creation ends at a draft. A launch turns the feature flag on for real users, so never call `experiment-launch` unprompted.

## Related skills

- **`configuring-experiment-rollout`** — variant splits, rollout percentage, and who sees the test
- **`configuring-experiment-analytics`** — exposure criteria and primary/secondary metrics
- **`managing-experiment-lifecycle`** — launch, pause, ship, and end once the experiment exists
