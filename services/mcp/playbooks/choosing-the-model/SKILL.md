# Skill — choosing the model

Load whenever you're about to set `spec.models` on a new or
edited agent, OR the user asks "which model should I use?" / "is
this the right model?" / "what's the cheapest model that'll work?".

Your job: **recommend a model policy based on the agent's actual
job, explain the tradeoff clearly, and let the user decide.** Don't
default to the most expensive model out of habit. Don't default to
the cheapest either. Match the policy to the job.

## auto is the default — start there

`spec.models` is a discriminated union on `mode`. For the exact shape —
every field, enum, and default — call
`@posthog/agent-applications-spec-schema` with `section: "models"` rather
than reciting it from memory; it stays current as the schema moves. The
`mode`, `level`, and `reasoning` names used throughout this skill are the
set that exists _today_ — if the schema returns a different set, the schema
wins. The judgment that schema can't give you is below.

- **`auto`** (the default for almost every agent) — pick a `level`
  (`low` / `medium` / `high`) and the platform resolves it to a
  maintained, priority-ordered, cross-provider list at runtime, so the
  agent rides model upgrades and cross-provider fallback for free.
- **`manual`** — an explicit, author-ordered priority list. Reach for it
  only when the agent genuinely needs a specific model (a fine-tune, a
  capability only one model has, a contractual / compliance pin); it opts
  you OUT of platform upgrades.

`optimize_for` (on either mode) trades cost for resilience: `cost`
(default) pins one model for the session to keep its prompt cache warm;
`availability` fails over on outage at the price of a one-time cold
re-read. Leave it at `cost` unless uptime matters more than spend.

## The cost / quality axes

Three independent dials in roughly increasing cost:

1. **Level / model** — `auto` `low` < `medium` < `high`; or, in
   `manual`, the specific model you pin. Within a vendor each step up
   is ~3-8× the per-token cost.
2. **Reasoning** — `minimal` < `low` < `medium` < `high` < `xhigh`.
   Set it on the policy (`auto.reasoning`) or per-model
   (`models[].reasoning`, which overrides). Adds deliberation tokens,
   multiplies per-turn cost. Only meaningful for `high`+ on
   reasoning-heavy tasks; for skim-and-respond agents it's pure waste.
3. **Context budget** (`spec.limits.max_output_tokens` + conversation
   length over multi-turn) — longer conversations re-feed the whole
   history each turn, so multi-turn agents pay quadratically.

A `low` agent with `reasoning: minimal` on short conversations runs
~$0.01/session. A `high` agent at `reasoning: high` on 50-turn
debugging sessions runs ~$3/session. Two orders of magnitude, same
platform.

## Picking the level

Walk this with the user — out loud, not in your head. The skill
they're paying for is your reasoning, not your answer.

```text
What's the job?
├── Short, formulaic, no reasoning ........ auto/low, reasoning: minimal
│     ("look up a thing and reply")          (slack lookup bots, FAQ bots,
│                                             webhook responders)
├── Multi-step but bounded ................ auto/medium, reasoning unset
│     ("query data, format an answer")       (analytics summaries, status
│                                             reports, structured drafts)
├── Open-ended reasoning, single hop ...... auto/medium, reasoning: medium
│     ("triage this alert, suggest a fix")   (oncall triage, code review,
│                                             planning, light debugging)
├── Long, branching, with backtracking .... auto/high, reasoning: high
│     ("debug this failing session, work     (the Agent Builder itself, deep
│       through hypotheses")                 investigations, multi-turn
│                                             editing flows)
└── Cutting edge / research-grade ......... auto/high, reasoning: xhigh
      ("solve this novel problem")           (rare — flag the cost
                                              explicitly to the user)
```

Default recommendation when uncertain: **`{ mode: "auto", level:
"medium" }`, reasoning unset.** Good enough for almost anything, not
embarrassingly expensive for the simple cases — and it tracks model
upgrades for free.

## When manual is worth it — and how to order it

Reach for `manual` only when the job needs a specific model. When you
do, **order the list provider-diverse.** The list is a fallback chain:
the runner tries each in order until one answers. A fallback to the
same provider as the primary doesn't help when that provider is the
thing that's down — list a different vendor next so an outage degrades
instead of failing.

- Good: a primary from one vendor, then a model from a _different_ vendor —
  if the first vendor has an outage, the other still answers.
- Pointless: two models from the _same_ vendor — one provider outage takes
  out both.

Don't hardcode model ids from memory — they get added and retired. Call
`@posthog/agent-applications-models` for the currently served ids (grouped by
provider) and pick the primary + a different-vendor fallback from that.

Set per-model `reasoning` when the fallback should think differently
from the primary (e.g. high on the primary, unset on a cheaper
backstop). If the whole policy wants the same reasoning, set it once
on the spec instead.

## The conversation to have

When the user says "build me an agent that does X" without naming a
model, do this — IN ORDER, don't skip the asking:

1. **Describe the job back to them in one sentence.** "You want a bot
   that, when @-mentioned in Slack, looks up who's on call and
   replies in-thread. Is that right?"
2. **Place the job on the flowchart.** Out loud. "That's a
   short-formulaic-no-reasoning job — one API call, one reply, no
   branching."
3. **Recommend with the cost tradeoff stated.** "I'd recommend
   `{ mode: auto, level: low }` at `reasoning: minimal`. Expected
   cost: ~$0.005-$0.02 per @-mention. A `high`-level equivalent
   would be ~$0.05-$0.20 per @-mention — 10× more for no quality
   difference on this job."
4. **Offer the user the upgrade explicitly.** "If you'd rather pay
   more for slightly better natural-language framing of the reply, I
   can move to `medium`. Or if this is a contractual must-use-vendor-X
   case, we can pin a manual list. Which way do you want to go?"
5. **Wait for the user's pick.** Don't default. Don't assume. Don't
   "just go with medium to be safe."

For the open-ended reasoning cases the conversation flips: lead with
"this job benefits from deliberation; I'd recommend `auto/medium`
with `reasoning: medium`, ~$0.20-$0.50 per session. A `low` version
might cost $0.02/session but you'll see it miss things on harder
inputs. Want me to start there and we can dial down if sessions feel
over-budget?"

## When to push back on the user

The user might ask for the wrong policy. Push back gently:

- **User picks `auto/high` (or pins Opus) for a lookup bot.** "A
  top-tier model on a one-API-call agent is a ~50× cost markup for
  zero quality win on this job. I'd recommend `low` — happy to
  upgrade if you see quality issues, but starting at the top is
  paying for capability you can't use here."
- **User picks `auto/low` for a debugging agent.** "`low` tends to
  miss the subtle hypotheses on multi-turn debugging — the kind of
  agent that helps less than it costs to run. I'd recommend `medium`
  as the starting point. If cost matters, we can put a tight
  `max_wall_seconds` / `max_turns` to cap session cost."
- **User pins a single-provider manual list.** "A same-provider
  fallback doesn't survive that provider having an outage — if you
  want a fallback at all, let's make the second entry a different
  vendor. Otherwise `auto` already gives you cross-provider
  fallback for free."
- **User picks `reasoning: xhigh` on anything that isn't research-
  grade.** "`xhigh` adds 5-10× the per-turn cost for diminishing
  returns past `high`. Worth it for truly novel problems; for almost
  every other case `high` matches the quality at a fraction of the
  cost."

## Cost estimation when the user asks

Don't ballpark from a hardcoded table — prices and the models behind
each `auto` level move. **Call `@posthog/agent-applications-models`**: it
returns every served model with its provider, context window, and
per-million-token pricing. Find the model(s) the policy resolves to and
quote from that. It's also the source of truth for which model ids are
valid in a `models` — promote rejects any that aren't served.

For actual billed spend on an existing agent, use
`@posthog/get-llm-total-costs-for-project`.

Quick session-cost arithmetic, once you have live rates:

```text
session cost ≈ (avg_input_tokens × input_rate)
              + (avg_output_tokens × output_rate)
              × turns
              × reasoning_multiplier
```

Reasoning multipliers (rough): unset/minimal = 1×, low = 1.3×,
medium = 1.8×, high = 3×, xhigh = 6×.

You don't need to be exact. You need to give the user "$0.01 or
$1?" precision so they can make a real choice.

## What "good" looks like

A good model-pick conversation finishes with:

- The user said which policy they want.
- The user understood why you suggested it.
- The user understood roughly what it'll cost per session.
- The agent's `spec.models` is set (`auto` unless the job
  truly needs a `manual` pin).
- Any `manual` list is provider-diverse, ordered primary-first.
- If reasoning matters, it's set explicitly (on the policy or
  per-model), not defaulted.
- If session cost matters, `spec.limits.max_turns` /
  `max_wall_seconds` reflect the cap the user chose.

Don't write the spec until the user has explicitly picked.
