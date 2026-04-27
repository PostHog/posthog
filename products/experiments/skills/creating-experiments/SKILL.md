---
name: creating-experiments
description: "Guides agents through the 3-step experiment creation flow: defining the hypothesis, configuring rollout, and setting up analytics. Delegates rollout decisions to configuring-experiment-rollout and metric setup to configuring-experiment-analytics.\nTRIGGER when: user asks to create a new experiment or A/B test, OR when you are about to call experiment-create.\nDO NOT TRIGGER when: user is updating an existing experiment, managing lifecycle, or only browsing experiments."
---

# Creating experiments

This skill walks through the 3-step flow for creating a new A/B test experiment.

## Core principle: draft first, iterate on details

Create the experiment as a draft quickly, then iterate on metrics and configuration.
The user gets a tangible draft immediately and can refine it.

## The 3-step creation flow

### Step 1: What are we testing?

Gather these before calling `experiment-create`:

- **Experiment name** — descriptive, inferred from context when possible
- **Hypothesis** — what you expect to happen (goes in `description`)
- **Feature flag key** — kebab-case. Ask if they want a new flag or to reuse an existing one.
  The flag is auto-created — do NOT create one separately.
- **Type** — leave empty (will internally default to `"product"`. The `"web"` value is reserved for no-code experiments configured visually with the PostHog
  toolbar in a browser; it cannot be meaningfully driven via MCP. If a user asks for a
  no-code/toolbar experiment, point them to the PostHog UI instead of creating one here.)

If the user gives enough context to infer these, don't ask — just proceed.

### Step 2: Who sees what variant?

This is about rollout configuration. **Load the `configuring-experiment-rollout` skill** for guidance.

Key decision points:

- Variant split (how many variants, what percentage each)
- Overall rollout percentage (what % of all users enter the experiment)
- Whether to persist the flag across authentication steps

**CRITICAL**: If the user mentions a specific percentage (e.g. "roll out to 25%"), this is ambiguous.
You MUST clarify before proceeding — see the `configuring-experiment-rollout` skill.

If the user doesn't mention rollout specifics, use defaults: 50/50 control/test, 100% rollout.

### Step 3: How to measure impact?

This is about analytics and metrics. **Load the `configuring-experiment-analytics` skill** for guidance.

**Do NOT configure metrics on creation.** Metrics are not passed to `experiment-create` — they are added
afterwards via `experiment-update`. This keeps the creation call lightweight.

When the user specifies metrics upfront, acknowledge them and add them immediately after creation.
When they don't, create the draft and then guide them through metric setup as a follow-up.

## How to create

Call `experiment-create` with:

```json
{
  "name": "Descriptive experiment name",
  "feature_flag_key": "kebab-case-key",
  "description": "Hypothesis: [what you expect to happen]",
  "parameters": {
    "feature_flag_variants": [
      { "key": "control", "name": "Control", "split_percent": 50 },
      { "key": "test", "name": "Test", "split_percent": 50 }
    ],
    "rollout_percentage": 100
  }
}
```

Two different percentages — do NOT mix them up:

- `feature_flag_variants[].split_percent` — how users **inside** the experiment are split across variants (must sum to 100, recommended to have an even split).
- `parameters.rollout_percentage` — what fraction of **all** users enter the experiment at all (0-100, defaults to 100).

Key details:

- First variant must have key `"control"`. Minimum 2, maximum 20 variants.
- `rollout_percentage` defaults to 100 if omitted.
- Stats default to Bayesian. Only set `stats_config` if the user requests Frequentist.

## After creation

1. **Always show the experiment URL.** The `experiment-create` response includes `_posthogUrl` — always display this link so the user can view and configure the experiment in the UI.

2. **Remind the user to implement the feature flag in code.** Link to the experiment page and say "implement the flag as shown here" — the experiment detail page shows implementation snippets for the user's SDK.

3. **Guide through metrics** if not yet configured — load the `configuring-experiment-analytics` skill.

4. **Launch** when ready — use the `experiment-launch` tool.

## Example interaction

```text
User: "Create an experiment to test our new checkout flow with 25% rollout"

Agent thinks: User mentioned a percentage — this is ambiguous. Load configuring-experiment-rollout.

Agent responds:
  "Before I create this, I need to clarify the 25% rollout. There are two ways to achieve this:

  1. **Reduced rollout** (recommended): 50% overall rollout with a 50/50 control/test split.
     25% of all users see the new checkout, and only the 50% in the experiment are analyzed.

  2. **Variant split**: 100% rollout with a 75/25 control/test split.
     25% of all users see the new checkout, but ALL users are included in the analysis.

  Which approach do you prefer?"

User: "Option 1"

Agent: Creates experiment with overall rollout_percentage: 50, 50/50 variant split, no metrics.
  "Created draft experiment 'New checkout flow test':
  http://localhost:8010/project/1/experiments/123

  Next steps:
  1. Implement the flag in your code — see the experiment page for SDK snippets
  2. Add metrics — what event represents a successful checkout?
  3. Launch when ready"
```
