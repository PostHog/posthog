---
name: rolling-out-feature-flags
description: 'Run a staged feature flag rollout with monitoring: confirm the gated code is live and emitting signal, agree a soak period, percentage steps, go and no-go gates and a rollback, watch a dashboard that compares flagged and unflagged traffic, then widen one step at a time. Use when the user wants a gradual, staged, phased, canary or monitored rollout, wants to ramp up or widen a flag, wants a flag to soak before going further, or asks how to roll a flag out safely. Also use when someone raises the percentage on a flag that serves production traffic and has not said how they will know it is safe. Not for adding a flag to code (`instrument-feature-flags`) or for the variant split of an experiment (`configuring-experiment-rollout`).'
---

# Rolling out feature flags

A staged rollout can run close to fire and forget once a person has agreed the plan.
Most of the work is in the first three steps, because a rollout that is watched by a broken gate is worse than one nobody claims to watch.

If someone asks for one percentage change on a flag that serves production traffic, make that change when they want it.
Offer the staged version once, in one line, for example: "Do you want this as a staged rollout with gates, so a bad step stops by itself?"
A one-off change on an internal or low-risk flag does not need this skill.

## 1. Confirm the code is live and emitting signal

A flag at 100% for an internal org does nothing until the gated code has shipped, and it looks exactly like a healthy rollout with no problems.
Establish these facts before you discuss any percentage:

- **The flag.** Read `posthog:feature-flag-get-definition-by-key`, then `posthog:feature-flags-activity-retrieve`, `posthog:scheduled-changes-list` (with `model_name: "FeatureFlag"` and `record_id`) and `posthog:feature-flags-dependent-flags-retrieve`. A pending schedule can move the rollout underneath the plan.
- **The route.** Stop and use a different path in these cases:
  - A running experiment in `experiment_set_metadata`: use `configuring-experiment-rollout`, because widening changes the analysis.
  - `filters.feature_enrollment` is true: the early access feature decides who is served, not the release conditions.
  - `filters.version` is 2: the rollout tools refuse the flag with `unsupported_config_version`. Raise the percentage on the existing rule with `posthog:feature-flag-rules-update`, and keep its `id` and `seed` unchanged.
- **The deploy.** Find the commit that reads the flag and confirm that it runs in production. An open pull request or a merged commit that has not deployed is not live. If you cannot see the repository, ask for the release, and say that the rollout waits for the answer.
- **The signal.** Find flagged traffic in the metric the rollout will be judged on, from the last 24 hours. No flagged traffic means stop here, whatever the flag says.

Three kinds of evidence look alike and prove different things:

| Evidence                                | What it proves                         | Trap                                                                                                                                                     |
| --------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$feature_flag_called`                  | Some code evaluated the flag           | It is not a traffic count, because SDKs send it once per person, value and process. A caller can turn it off, so its absence proves nothing on a server. |
| `$feature/<key>` on an event            | That event knew the flag value         | Client SDKs attach it. Server SDKs mostly do not, unless the capture call passes `send_feature_flags`.                                                   |
| A product metric tagged with flag state | The gated path ran, and how it behaved | This is the evidence gates need. If it does not exist, the team has to add it before the rollout can be monitored.                                       |

`posthog:feature-flags-status-retrieve` reports whether a flag was recently called. It does not show that the gated code ran.

For a server flag, check how the call site evaluates it:

- With `only_evaluate_locally`, an inconclusive evaluation does not fall back to the server. The SDK returns nothing, and the caller treats that as off.
- On a group flag, a call without `groups` is off. A call without `group_properties` for that group type is inconclusive, so it is also off under `only_evaluate_locally`. The same applies when a condition filters on a property the call does not pass.
- `posthog:feature-flags-test-evaluation-create` shows what the server would answer. A match there does not show that a local call site gets the same answer.

If flagged traffic stays at zero after the flag matches, suspect the call site before you widen.

## 2. Agree the plan with a person

Propose concrete values and ask for changes. Do not start until a person has agreed all of it:

- **Unit and starting point.** Check `aggregation_group_type_index` on the condition and on `filters`. When it is set, percentages count groups, so say groups in every report.
- **Steps.** For example 5, 25, 50, 100. Smaller first steps suit riskier changes and larger units.
- **Soak.** The time at each step, long enough to include the traffic pattern that matters. A step that soaks only on a weekday has not seen the weekend batch jobs.
- **Gates.** See below.
- **Rollback.** Which call, who may make it, and whether anything the feature wrote needs cleanup. Lowering the percentage keeps the first units in and removes the last ones. `posthog:feature-flag-disable` turns off every condition, returns 400 when active flags depend on this one, and sends every caller to its own default.
- **Who approves each step.** See step 5.

A percentage of groups is not a percentage of load, because a few large groups can carry most of the traffic.
Before you pick steps, measure how much of the gate metric comes from the top groups, with the query in [comparing flagged and unflagged traffic](./references/comparing-flagged-traffic.md).
If a few groups dominate, a 25% step can carry almost nothing or almost everything, depending on which side of the hash they fall.
Say this to the person, and consider a condition that holds the largest groups back until the last step.

`posthog:feature-flags-user-blast-radius-create` ignores `rollout_percentage`.
It counts who matches the condition's properties, in people or groups, not how much traffic they send.
Use it to size the audience of a condition, and not to size a step.

### Gates

Every gate has a metric, a threshold and a minimum amount of traffic in the flagged group.
A gate has three outcomes, and "no data" is never a pass:

| Outcome         | Meaning                                                  | Action                                                 |
| --------------- | -------------------------------------------------------- | ------------------------------------------------------ |
| Go              | Traffic minimum met and every threshold holds            | Widen if the step is approved                          |
| No-go           | Traffic minimum met and a threshold fails                | Stop and hand back to a person                         |
| Not enough data | Traffic minimum not met, or the query failed or is empty | Hold. Extend the soak once, then hand back to a person |

An invented example of a complete plan, for a flag named `faster-report-cache` on organizations:

```text
Steps:    5 -> 25 -> 50 -> 100 percent of organizations
Soak:     48 hours per step, and the 5 percent step includes a weekend
Traffic:  at least 2,000 flagged requests from at least 20 organizations in the soak window
Go:       error rate at most 0.5 points above unflagged
          p95 duration at most 110% of the same organizations in the week before
No-go:    either threshold fails with the traffic minimum met
Rollback: set the percentage to 0 on the new condition, and alert the on-call engineer
Approval: each step needs a yes from the feature owner
```

Before you trust a gate, run it once and check that it can fail.
A query that returns zero errors because the filter matches nothing looks the same as a healthy feature.

## 3. Point monitoring at a dashboard

Prefer the dashboard the team already watches.
Search with `posthog:execute-sql` against `system.dashboards`, or with `posthog:dashboards-get-all`, then read the candidates with `posthog:dashboard-get`.
Reuse one if it covers the gate metrics, and ask before you add tiles to a dashboard someone else owns.
When none fits, create one with the `building-a-dashboard` skill.

The dashboard needs two comparisons, because each one covers a weakness of the other:

- **Flagged and unflagged in the same window.** Shared events such as an incident or a traffic spike hit both groups. Keep a third bucket for events with no flag state. When that bucket is large, the comparison is not valid.
- **Before and after for the same units.** Compare the units that are flagged now against their own earlier traffic, on the same weekdays. The flagged group can differ from the rest, especially when it starts with your own org.

Add tiles for flagged traffic volume and for the flagged share of total traffic, so you can see load as well as the percentage.
Mark each widening with `posthog:annotation-create` so that people can read the charts later.
The queries are in [comparing flagged and unflagged traffic](./references/comparing-flagged-traffic.md).

The dashboard is for people. Run gates as fresh queries, because a cached tile can show traffic from before the last step.

## 4. Widen one step at a time

Before each step:

1. **Read the flag again.** Confirm that `active`, the conditions and the percentage match the plan, and that no schedule is pending. If someone else changed the flag, stop and ask, because the soak no longer means what you agreed.
2. **Check the soak.** Take the time of the last widening from `posthog:feature-flags-activity-retrieve`, not from memory. Count the soak from the first flagged traffic at this level, because SDKs and caches pick up a change after a delay.
3. **Run every gate.** Report the value, the threshold and the traffic for each one, including on a pass.
4. **Stop on anything but go.** On no-go, hand back the results, the rollback call ready to run, and what you did not check. Do not widen, and do not roll back unless the plan says that you may.
5. **Get the approval for this step**, as described in step 5.
6. **Write the change**, using the path below.
7. **Check it landed.** Read the flag back, then confirm that flagged traffic moved. If the flag changed and the traffic did not, stop.

Which write to use:

- **A condition that already covers the audience.** Use `posthog:feature-flag-set-release-condition-rollout`. It changes only the percentage on that condition, and it needs `condition_index` and the `version` from the read you just made. A 409 means the flag changed: read it again, and decide against what you find. Do not retry with the same version. A 409 can also mean that an approval policy gates the change, so read the error and tell the person.
- **A flag that targets one org by exact match.** You cannot widen through that condition. Its percentage only decides whether that one org is in. Add a new condition with `posthog:update-feature-flag`, with no properties and the first step's percentage, and leave the org condition in place. Send the whole `filters` from a fresh read, keep every `condition_id`, and leave `condition_id` off the new condition. On these flags the tool does not check `version`, so a change made after your read is overwritten: read immediately before you write, then read back and compare. Later steps use `posthog:feature-flag-set-release-condition-rollout` on the new condition.
- **The last step.** Use `posthog:feature-flag-set-release-condition-rollout` to reach 100 on the widening condition, or `posthog:feature-flag-roll-out-to-everyone`. Read that tool's multivariate rules first.
- **A multivariate flag.** The percentage sets how many units get a variant, and not the split between variants. If the person's request could mean either one, ask.

Raising a percentage only adds units. The hash uses the flag key and the unit, so a person or group already in stays in, including across conditions. Changing the flag's bucketing identifier reshuffles everyone.

## 5. Approval and recurring checks

**Never widen a flag on inferred approval.**
Agreeing the plan, asking you to keep an eye on the rollout, or a passing gate does not approve a step.
Approval has to come from a person, name the flag, and name the step or the highest percentage allowed.

The default is one yes per step.
To get closer to fire and forget, a person can write a standing approval, such as "widen `faster-report-cache` to 50 percent when the gates pass, until Friday".
Follow it exactly, and never go past its limit.
A scheduled run has that approval only if the person's words are in its prompt. Otherwise it reports and stops.

**Nothing in the flag watches the gates.**
A flag has no concept of a soak or a gate, and you cannot wake yourself up, so a recurring check needs a schedule outside the flag.
Tell the person this when you agree the plan, and record the plan somewhere a later run can read it, such as a notebook from `posthog:notebooks-create`.
A later run has no memory of this conversation.

Pick the first option that is available and that the person accepts. Each one needs their agreement before you create it:

| Option                                      | What it does                                                              | Limit                                                                                                    |
| ------------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| A scheduler in the person's own agent or CI | Runs a check prompt on a schedule                                         | Only if their tools have one. Check what you actually have rather than assuming.                         |
| A scout, with `posthog:scout-create`        | Runs an agent in PostHog on a schedule, and reports to the inbox or Slack | Scouts cannot hold `feature_flag:write`, so it checks gates and a person widens. See `authoring-scouts`. |
| A reminder, with `posthog:reminder-create`  | Sends the person an in-app notification, linked to the flag               | No agent runs. The person starts the check. See `managing-reminders`.                                    |
| An alert, with `posthog:alert-create`       | Notifies people when a metric crosses a bound, between checks             | It catches failure and does not approve a step. Add one on flagged volume so silence also alerts.        |

`posthog:scheduled-changes-create` is not a gate.
It applies its change at the set time, whatever the metrics say, and it can add a condition or change status but cannot set the percentage on an existing condition.
Use it only when a person explicitly wants a time-based change with no check.

If you cannot create any of these, the rollout still works.
End your turn with the next check time and a prompt the person can paste into a new session, then stop. For example:

```text
Continue the staged rollout of flag `faster-report-cache`, using the rolling-out-feature-flags skill.
The plan is in <notebook link>. The flag is at 5 percent of organizations, and the next step is 25.
Check the gates. Widen only if I approve it in this conversation.
```

## Finishing

Report the final percentage, the gate results for each step, and anything you could not verify.
Remove the alerts, reminders and scouts you created for the rollout, after asking.
When the flag has soaked at 100%, point the person to `cleaning-up-stale-feature-flags`, because the flag check in the code is now debt.
