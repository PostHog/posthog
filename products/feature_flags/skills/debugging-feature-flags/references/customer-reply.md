# Writing the customer reply

The deliverable is a reply the customer can act on: what's happening, how to fix it, and the
evaluation that proves it. Voice follows the PostHog support values — reassuringly human, humble,
clear, no jargon.

## Rules

- **Lead with the cause, then the fix.** One line on what's happening, then what to do.
- **Bold the problem and each action** so they're scannable.
- **Show the evaluation you reproduced.** The customer is looking at a value they didn't expect; cite
  the reproduced value and the reason in plain terms ("for that user the flag evaluates to `false`
  with reason _out of rollout bound_ — they're outside the 20% you've rolled out to").
- **Use the labels the customer sees in the UI, never internal field names or reason enums.** Common
  mappings:

  | Internal / code term                   | What the customer sees                                                                   |
  | -------------------------------------- | ---------------------------------------------------------------------------------------- |
  | release condition / `filters.groups[]` | a **release condition**                                                                  |
  | `rollout_percentage`                   | the **rollout percentage**                                                               |
  | `no_condition_match`                   | **none of your release conditions matched this user**                                    |
  | `out_of_rollout_bound`                 | the user is **outside the rolled-out percentage**                                        |
  | `no_group_type`                        | the flag is **aggregated by a group** and the call didn't pass the group                 |
  | `super_condition_value`                | the user's **early access feature** enrollment decided it                                |
  | `holdout_condition_value`              | the user is in the **holdout**                                                           |
  | `missing_dependency`                   | this flag **depends on another flag** that isn't available                               |
  | `disabled`                             | the flag is **turned off** in your project                                               |
  | `flag_not_found`                       | resolve the cause first: either **turned off**, or **not available to that kind of SDK** |
  | multivariate `variant`                 | a **variant**                                                                            |
  | `$feature_flag_called`                 | the flag being **called / evaluated** in your app                                        |

- **Link the flag by ID for the right instance** (US vs EU — match the customer's):
  `https://<us|eu>.posthog.com/project/<id>/feature_flags/<flag_id>`.
- **Predict the expected outcome** so they can verify the fix ("once you pass `groups` in the
  call, that user will match the organization condition and get the flag").
- **Async-first voice.** Don't offer to "hop on a call." Close with an offer to follow up.
- **Never leak internals** — no MCP tool names, code paths, reason enum strings, Django admin, staff
  impersonation, or anything belonging to another customer. Keep it to product concepts a customer
  recognizes.
- **Write like a person typed it.** No em dashes, no "here's the thing" preambles, no rule-of-three
  padding. If a humanizer skill is available, run the draft through it before sending.

## Reply skeleton

```text
Hi <name>,

<one line: you looked into it and found why the flag evaluates the way it does.>

**The problem:** <what's happening, with the reproduced value and reason in plain terms.>

**The fix:**
1. **<action>** <why / how, in UI or SDK terms.>
2. **<second action if needed>** <why / how.>

Once you <fix>, that user should get <expected value> going forward.

Here's the flag: https://<us|eu>.posthog.com/project/<id>/feature_flags/<flag_id>

We're always here if you need a follow-up.
```

## Worked example — "the flag isn't rolling out to me" (out of rollout bound)

Use when the reproduced reason is `out_of_rollout_bound`. The point is that it's deterministic, not
broken.

```text
Hi Sam,

Thanks for flagging this. The flag is working as configured, and the reason you're not seeing it is
down to the rollout percentage rather than a bug.

**The problem:** your flag is rolled out to 20% of users, and assignment is a fixed hash of each
user's ID. Your test user lands outside that 20%, so the flag correctly evaluates to off for them. It
isn't random, so retrying or clearing cookies won't change it for that specific user.

**The fix:**
1. **To include that user, raise the rollout percentage** until it passes their position, or add a
   release condition that targets them directly (for example by email).
2. **To sanity-check, test with a user you know is inside the rollout** rather than assuming a given
   user should be in.

Once you raise the rollout or add a targeted condition, that user will start getting the flag on
their next evaluation.

Here's the flag: https://us.posthog.com/project/1234/feature_flags/5678

We're always here if you need a follow-up.
```

## Worked example — "the flag returns false for a user who should get it" (group not passed)

Use when the reproduced reason is `no_group_type` and the flag is group-aggregated. This one says the
fix is in their code, so it's written to be concrete and blameless.

```text
Hi Alex,

I dug into this and it traces back to how the flag is being called rather than to your targeting.

**The problem:** this flag is aggregated by organization, so it decides on/off per organization, not
per person. When your app calls the flag it isn't passing the organization along, so PostHog has no
group to evaluate the condition against and safely returns false. That's why a user in an enabled
organization still sees it off.

**The fix:**
1. **Pass the group in the flag call.** In posthog-js, set the group once at identify time with
   `posthog.group('organization', 'org_123')`. That reloads the flags in the background, so read the
   value inside `posthog.onFeatureFlags(() => posthog.getFeatureFlag('your-flag'))`. In server-side
   SDKs it's a per-call option, for example
   `posthog.getFeatureFlag('your-flag', distinctId, { groups: { organization: 'org_123' } })`. The
   matching group properties also need to be set on that organization.

Once the call includes the organization, that user will match the organization's release condition
and get the flag.

Happy to take another look once the change is out if the value doesn't move.
```
