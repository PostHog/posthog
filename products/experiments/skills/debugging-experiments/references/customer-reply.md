# Writing the customer reply

The deliverable is a reply the customer can act on: what's happening, how to fix it, and the
numbers that prove it. Voice follows the PostHog support values — reassuringly human, humble,
clear, no jargon.

## Rules

- **Lead with the cause, then the fix.** One line on what's happening, then what to do.
- **Bold the problem and each action** so they're scannable.
- **Show the numbers you pulled.** The customer is staring at a results page; cite the exact
  figures that explain it ("the smaller variant lost about 8% of its users to the multiple-
  variant exclusion"). This is the "review the data" part of the ask.
- **Use the labels the customer sees in the UI, never internal field names.** Grep
  `frontend/src/scenes/experiments/` for the real string if unsure. Common mappings:

  | Internal / code term                      | What the customer sees                                                                                  |
  | ----------------------------------------- | ------------------------------------------------------------------------------------------------------- |
  | `multiple_variant_handling`               | **Multiple variant handling**                                                                           |
  | `multiple_variant_handling: "exclude"`    | **Exclude from analysis**                                                                               |
  | `multiple_variant_handling: "first_seen"` | **Use first seen variant**                                                                              |
  | `$multiple` bucket                        | users **exposed to more than one variant**                                                              |
  | exposure / `$feature_flag_called`         | an **exposure** (a user seeing the experiment)                                                          |
  | `filterTestAccounts`                      | the **Filter out internal and test users** setting                                                      |
  | `only_count_matured_users`                | the option to exclude users whose **conversion/retention window hasn't elapsed**                        |
  | SRM                                       | the **split not matching what you configured** (say "sample ratio mismatch" only if they used the term) |
  | rollout / split                           | keep **rollout** (overall %) distinct from **split** (between variants)                                 |

- **Link every entity by ID for the right instance** (US vs EU — match the customer's):
  - Experiment: `https://<us|eu>.posthog.com/project/<id>/experiments/<experiment_id>`
  - Feature flag: `https://<us|eu>.posthog.com/project/<id>/feature_flags/<flag_id>`
  - Cohort: `https://<us|eu>.posthog.com/project/<id>/cohorts/<cohort_id>`
- **Predict the expected outcome** so they can verify the fix ("once you switch to Use first
  seen variant, the two variants should line up going forward").
- **Async-first voice.** Don't offer to "hop on a call." Close with an offer to follow up.
- **Never leak internals** — no MCP tool names, code paths, file names, constants, Django
  admin, or staff impersonation. Keep it to product concepts a customer recognizes.
- **Write like a person typed it.** No em dashes, no "here's the thing" preambles, no
  rule-of-three padding. If a humanizer skill is available, run the draft through it before
  sending.

## Reply skeleton

```text
Hi <name>,

<one line: you looked into it and found the cause in plain terms.>

**The problem:** <what's happening, with the numbers you pulled, e.g. the split, the
share of users exposed to more than one variant, or the exposure counts.>

**The fix:**
1. **<action>** <why / how, in UI terms.>
2. **<action, if there's a second step>** <why / how.>

You should see <expected outcome> going forward.

<optional, softened since aged configs are often mid-edit: "While you're in there,
it's worth double-checking <secondary finding>.">

We're always here if you need a follow-up.
```

## Worked example — uneven exposures from the bias banner

```text
Hi Sam,

Thanks for flagging this. The uneven variant numbers are coming from your setup rather than
anything random, and it's a quick fix.

**The problem:** your experiment runs an 80/20 split, and "Multiple variant handling" is set
to **Exclude from analysis**. About 2% of your users were exposed to more than one variant,
and excluding them hits the smaller (20%) variant harder, which is why it looks worse than it
should. That's what the "Setup likely introduced bias" banner is telling you.

**The fix:**
1. **Switch "Multiple variant handling" to Use first seen variant.** That keeps those users in
   the analysis under the first variant they saw, instead of dropping them unevenly.
2. **Consider an even 50/50 split** on your next experiment for the most reliable read.

Once you switch to Use first seen variant, the two variants should line up much more closely
going forward.

We're always here if you need a follow-up.
```

## Worked example — one variant looks short because the flag is read too early

Use when the decisive test came back capture-side and the dropped `false`/`null` bucket lines
up with the short arm. This one says the fix is in their code, so it's written to be concrete and
blameless.

```text
Hi Alex,

Thanks for your patience while I dug into this. Your split is set to 50/50, but the results are
running about 43/57, and it comes from how the experiment loads rather than the randomization itself.

**The problem:** some of your control-side users are checking the experiment flag before PostHog has
finished loading, so they come back with no variant and drop out of the results instead of being
counted. About 290 users came back with no variant, almost all on your web app, which is close to the
gap between the two variants. That is why control looks smaller than test.

**The fix:**
1. **Read the flag after flags are ready** rather than on first render. In posthog-js you can wait for
   the `onFeatureFlags` callback, or use the bootstrap option so a variant is available immediately on
   load.
2. **Check any early redirect or gate** that reads the flag on the first paint, since that is usually
   where the early reads come from.

Once the flag is only read after it is ready, those users will be counted under a variant and the
split should settle back toward 50/50.

Happy to take another look once the change is out if the numbers do not move.
```

## Worked example — one variant reaches a page the other does not

Use when the surface split shows one path near 100% a single variant while other paths sit near the
configured split.

```text
Hi Jordan,

I looked into the uneven numbers, and it traces back to where the experiment is being measured rather
than to the randomization.

**The problem:** your split is 50/50, but the experiment flag is being read on a page that mainly the
test experience links to. On your main pages the split is a healthy 50/50, but on the tools page it is
almost all test users, and that page adds exposures on the test side that control never gets the
chance to record. That pulls the overall split toward test.

**The fix:**
1. **Measure the experiment on a surface both groups reach**, or add a custom exposure event at a
   point every eligible user passes through, so both variants are counted on equal footing.

Once exposures are recorded somewhere both groups land, the split should even out.

We are here if you want a second look after the change.
```
