# Setup decisions from project facts

Use this file after `experiment-setup-context` returned. Each section maps the tool's facts to one configuration choice and to a tier for the summary:

- **Confident**: the facts decide it.
- **Best guess**: a reasonable default that the facts support but do not prove. Say what would change it.
- **Not decided**: the facts cannot decide it. Say what is missing and how the user can decide.

Every section has the shape `{status, data}`. The field paths below are inside `data`: `target_surface.anonymous_share` means `target_surface.data.anonymous_share`.
A `[]` in a path means a list: `previous_experiments.experiments[].primary_metric_types` is a field on each row.
Write every dotted path from its section name, never from below it: `previous_experiments.summary.using_custom_exposure`, not `summary.using_custom_exposure`. A test resolves the full paths against the response and cannot check a shorthand. A bare field name is fine in a sentence whose section is already named.
A section whose `status` is not `ok` gives no facts. Choices that depend on it drop to "best guess" at most, and the summary says which section was missing.

## Bucketing and persistence

Read these facts:

- `target_surface.anonymous_share`: among the distinct IDs that sent the target event and say whether they are identified, the share that were anonymous. Every SDK's events count, not only the web SDK's. A high share usually means logged-out visitors. It is null only when no target event carried `$is_identified` at all.
- `target_surface.device_id_share`: the share of target events that carry a device ID, across every SDK that sent them. Null when there were no target events.
- `target_surface.libs[]`: `target_surface.libs[].anonymous_share` and `target_surface.libs[].device_id_share` per SDK that reached the surface, plus a `target_surface.libs[].category` of `web`, `mobile`, `server` or `other`. A row's `device_id_share` is always a number, because the row exists only where that SDK sent target events.
- `sdk_profile.libs[]`: per SDK, `sdk_profile.libs[].device_id_share` and `sdk_profile.libs[].locally_evaluated_share` on flag calls, plus a `sdk_profile.libs[].category` read the same way. It covers the whole project, not one page, so use `target_surface.libs` to pick the rows that apply to this page. It is empty when the project sent no multivariate flag calls in the last 7 days.
- `sdk_profile.libs_on_any_event[]`: which SDKs the project sends any event from. Set only when `sdk_profile.libs` is empty.

| Facts                                                                                                                                           | Choice                                                                                                 | Tier                                                                                                        |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `anonymous_share` above about 0.9, or below about 0.1: the page is seen mostly by one kind of visitor                                           | User-id bucketing. Leave `ensure_experience_continuity` out, so the team's persistence default applies | Best guess                                                                                                  |
| Between: the same people likely see the page before and after they are identified, and user-id bucketing can switch their variant at that point | The steps below                                                                                        | Best guess, always listed for review                                                                        |
| `anonymous_share` is null                                                                                                                       | User-id bucketing, team persistence default                                                            | Not decided: say no target event reported whether its sender was identified, so the identity mix is unknown |

### Placement beats precedent

When `anonymous_share` is in the middle band, work through the steps below whatever the project has done before.
A summary showing `previous_experiments.summary.using_persistence` and `previous_experiments.summary.using_device_id_bucketing` both at 0 is not a reason to skip them.
A project whose surfaces cross identification and that has never used either has most likely been splitting the same person across two variants all along, and a run of experiments agreeing with each other does not make that right.
Name it in the report: say the project's earlier experiments bucket on the user id and that this surface needs more, then follow the steps.

Precedent can confirm a choice these facts already allow. It never overrides this one.

### The steps, in order

Device-id bucketing is a web option. A mobile SDK puts no `$device_id` on its events, flag calls included, so both device-id shares step 1 reads sit near 0 on a mobile row and step 1 can never pass.
When every `target_surface.libs[]` row that reaches the surface has `category: "mobile"` and `target_surface.libs_truncated` is false, go straight to step 2: the choice is persistence or user-id bucketing, and reporting "not decided" over a share that can never arrive is wrong.

1. **Device-id bucketing**, if `target_surface.device_id_share` is near 1, at least one `sdk_profile.libs` row has a `lib` that appears in `target_surface.libs`, and every matching row has `sdk_profile.libs[].device_id_share` near 1. A flag call without a device ID gets no variant, so a server SDK must forward the browser's device ID; local evaluation works when it does. `target_surface.device_id_share` is read from the target events; a `sdk_profile.libs` row's `device_id_share` is read from flag-call events. Neither is read from the flag requests, so neither proves that the request carried a device ID. The web SDK sends the device ID on flag requests from posthog-js 1.307.1. An older version puts a device ID on events and still gets no variant, so tell the user to check the SDK version. Set it up with the device-id recipe in `configuring-experiment-rollout`. `experiment-create` cannot set it.
2. **Persistence** (`ensure_experience_continuity: true`), if no matching `sdk_profile.libs` row evaluates flags locally: every row that matches a `lib` in `target_surface.libs` has `sdk_profile.libs[].locally_evaluated_share` near 0, or null on a web or mobile row. Null on a server row is unknown: go to step 3. Persistence also needs person profiles for anonymous users, no bootstrapping, and `$anon_distinct_id` on server flag calls. The tool cannot see those three, so list them for the user to check.
3. **Otherwise**: user-id bucketing, and mark it "not decided". Say what would unlock the other options: a device ID on every flag call, or no local evaluation.

When `sdk_profile.libs` holds rows, steps 1 and 2 read only the ones that match, so a `target_surface.libs[]` row with no `sdk_profile.libs` row of the same `lib` is unchecked rather than safe.
`sdk_profile.libs` reads multivariate flag calls over 7 days while `target_surface.libs` reads target events over 14, so a missing row can mean that SDK evaluates no multivariate flag, or only that it made none in the shorter window.
Name every unmatched SDK in the report.
When an unmatched row has `category: "server"`, take step 3: an unread server SDK is the case that breaks both steps, because it may send its flag calls without a device ID and may evaluate them locally.
Otherwise keep the step's choice and drop the tier to "best guess", naming the SDK that was not checked.

Both lists are capped, so read the truncation flag before you trust a match.
`target_surface.libs` holds at most the 5 SDKs with the most people on the surface, and `target_surface.libs_truncated` is true when the cap dropped a further SDK.
When it is false, the list is complete and the check above is conclusive; when it is true, an unseen SDK can reach the surface, a server one included.
When `target_surface.libs_truncated` is true, say the list is at its cap and drop the tier to "best guess" even when every row matched, because "no unmatched SDK" is then unproven rather than true.
`sdk_profile.libs` is capped at 10 and does report it, in `sdk_profile.libs_truncated`.
When that is true, an SDK can read as unmatched only because its own row was dropped, so name the cap alongside it. The cap cannot add a bad matching row, so steps 1 and 2 stay safe on the rows that did come back.

If `sdk_profile.libs` is empty, read `sdk_profile.libs_on_any_event`.
The endpoint fills that field only on an empty profile, so a profile that holds rows and matches none of them to `target_surface.libs` is not this branch: the unmatched-SDK rules above decide that case, and the field reads null there.
It is null on an empty profile too when its own query timed out. Nothing then names the platforms, so none of the reads below apply: say so and stay on user-id bucketing, marked "not decided".
It names the platforms the project sends from, which settles one case and no other: a project that sends only from mobile SDKs can never reach the share step 1 needs, so the choice there is persistence or user-id bucketing.
Trust that mobile-only read only when `sdk_profile.libs_on_any_event_truncated` is false. When it is true, the cap dropped the SDKs that sent the fewest events, so the project can also send from a web or server SDK that the list does not show.
Every other platform mix stays open, a server-only project included. A server SDK that forwards the browser's device ID puts one on every flag call, and this fallback cannot see whether it does.
It says nothing about device IDs on flag calls or about local evaluation, so steps 1 and 2 still do not pass. Keep user-id bucketing and mark it "not decided".
Say which platforms the project sends from. When `target_surface.device_id_share` is near 1, `target_surface.libs` lists no server SDK, and `target_surface.libs_truncated` is false, say device-id bucketing is the likely fit: with no server SDK in the mix, nothing has to forward the device ID for the flag call to carry one. A mobile-only project never reaches that share, so it is settled above rather than here.
That share counts target events, and this branch read no flag call at all, so step 1's version caveat applies here with nothing to offset it: posthog-js sends the device ID on flag requests only from 1.307.1, and an older version puts one on the events while the request still gets no variant.
Give device-id bucketing as a lead to check, with the version named as the thing to confirm, and leave the choice at user-id bucketing.

Leave `ensure_experience_continuity` out unless you are choosing persistence. When omitted, `experiment-create` applies the team's default (`team_defaults.flags_persistence_default`). Set it to `false` only when the team default is `true` and local evaluation rules persistence out. The device-id recipe needs no such step: `create-feature-flag` leaves persistence off unless you set it, and `experiment-create` rejects a `feature_flag` object for a flag that already exists.

Never change bucketing or persistence on a flag that is already live.

## Where the flag is evaluated

If `sdk_profile.evaluated_on_server_and_web` is true, or `target_surface.libs` lists a server SDK next to `web`:

- The server and the browser must use the same identity and see the same flag value. Otherwise one person gets two variants.
- A custom exposure on a browser event is only safe when the browser holds the server's flag value at that moment, because the exposure reads `$feature/<flag>` from that event.
- With device-id bucketing, the server must forward the browser's device ID on every flag call. A call without one gets no variant.

Tier: **not decided**. The facts show the risk, not whether the code handles it. Tell the user what to check.

## Exposure

Keep the team's default exposure event (`team_defaults.default_exposure_event`). Use a custom exposure only when the user names the moment the person sees the change and the flag is evaluated well before it: a prefetch, a server render, or a flag read across the whole app while the change sits on one surface. Tier: best guess.

## Who counts

Keep the test-account filter on and say so. `team_defaults.new_experiments_filter_test_accounts` says what a new experiment does when its own exposure criteria say nothing, and it does not follow the project's insight default. If `team_defaults.test_account_filter_count` is 0, say the project has no test-account filters, so the setting changes nothing. Tier: best guess.

## Primary metric

1. Pick the event that expresses the hypothesis. Confirm it exists with `read-data-schema`.
2. Check `shared_metrics.metrics[]` for one to reuse instead of building an inline metric.
   - `shared_metrics.metrics[].matches_metric_event` set to true says the event appears in the metric somewhere. `shared_metrics.metrics[].metric_event_roles` says where: `funnel_step` and `funnel_final_step` for a funnel, `mean_source` for a mean, `ratio_numerator` or `ratio_denominator` for a ratio, `retention_start` or `retention_completion` for a retention metric.
   - A named role that cannot carry the hypothesis rejects the metric without another call. A metric that only starts a retention window from the event does not answer "did more people convert on it".
   - An empty `shared_metrics.metrics[].metric_event_roles` with a true match is not a rejection. The metric does count the event, but it is stored in a shape the role reader does not parse, which its `shared_metrics.metrics[].metric_type` shows as null or as a type not listed above. Retrieve it and read the query.
   - When the role fits, load the metric with `experiment-saved-metrics-retrieve` and check its `metric_type` and `math` against what the user asked for. The role alone does not prove those, so the tier stays best guess until you have read the query.
   - If it matches, link it after creation through `experiment-update` with `saved_metrics_ids`. Tier: confident. When the user asked for no questions, link it and report it rather than asking first.
   - When no listed metric fits and `shared_metrics.metric_event_match_truncated` is true, the match read only the newest shared metrics, so an older metric that counts the event shows `matches_metric_event` false. Call `experiment-saved-metrics-list` with `event` set to the metric event before you build an inline metric. That filter reads every shared metric.
   - If it doesn't, build an inline metric.
3. Otherwise pick a shape from the metric templates in `configuring-experiment-analytics` (`references/metric-templates.md`). Tier: best guess.

If the metric counts only some occurrences of its event, for example a purchase with one payment method, pass those filters as `metric_properties` on the setup-context call. Use the same filters on the metric you build.
Without them, `candidate_metric` reports a baseline for every occurrence of the event, and the running time below is too optimistic. `candidate_metric.metric_properties` echoes the filters the tool read.

Every conversion window carries a unit (`conversion_window_unit`). A window without a unit is ignored.

### Follow the project's metric shape

Read `previous_experiments.experiments[].primary_metric_types`. It carries one entry per primary metric, so an experiment with two primary metrics of different types carries both.
A row counts only when its list is not empty and every entry in it is the same type, and that type is the row's shape. An empty row ran no primary metric, and a mixed row made two different choices, so neither votes.
Count the rows that qualify. Fewer than three is not a precedent: say the project has too few experiments to read one.
From three qualifying rows up, propose the type held by at least 80% of them - 3 of 3, 4 of 4, 4 of 5 - unless the request asks for something else. Say you followed precedent and out of how many experiments. A project that measures every test as a funnel gets a funnel.

Then read `previous_experiments.experiments[].primary_metric_events`. When the event you picked already appears on a row, say which experiment measured it and as what, reading `primary_metric_types` on the same row. Tier: best guess.

## Feasibility and running time

When `candidate_metric.status` is `ok` and it has baseline stats:

1. Call `experiment-calculate-running-time`:
   - funnel metric: `metric_type: "funnel"`, `baseline_stats` from `candidate_metric.funnel_baseline_stats`
   - count per user: `metric_type: "mean_count"`, `baseline_stats` from `candidate_metric.mean_count_baseline_stats`
   - `minimum_detectable_effect`: `team_defaults.minimum_detectable_effect`, else `team_defaults.product_default_minimum_detectable_effect`
   - `exposure_rate_per_day`: `target_surface.exposures_per_day_estimate`, times the rollout share when the experiment includes less than 100% of traffic
   - `number_of_variants` when there are more than two variants
2. Pass the result to `experiment-create` as `running_time_calculation`, so the plan is stored on the experiment:
   - `minimum_detectable_effect`: the value you sent (the calculator does not return it)
   - `recommended_sample_size`: the calculator's `recommended_sample_size`
   - `recommended_running_time`: the calculator's `recommended_running_time_days`
3. If the running time is over about 8 weeks, say so plainly. Propose a more frequent event earlier in the journey as primary and keep the rare event as secondary.

The estimate assumes people are exposed on the target surface. If the flag is evaluated more widely (across the whole app, or on a page before the one that changes), the exposed population is larger and converts less. The baseline and the running time are then too optimistic. Say so, and consider a custom exposure on the surface event. This is the one case where a custom exposure is right in a project that has never used one, and "Precedent" says so too.
`previous_experiments.experiments[].outcome.control_baseline_value` shows what that dilution looked like: a control baseline far below the rate the surface itself converts at is an experiment that was exposed too widely.

Check how the call scoped the target surface before you trust these numbers. `target_surface.target_properties` and `target_surface.target_url_contains` echo the filters the tool read.
`target_url_contains` is a substring match on `$current_url`, so a bare domain matches any host that contains it, and a homepage path matches every page under it. Both overstate the page's traffic and the exposure rate.
If the echo came back wider than the surface under test, the numbers here are too optimistic.
Correct the scope and call the tool once more: an exact `$host` and an exact `$pathname` in `target_properties` for one page, or an exact `$host` with only the path fragment in `target_url_contains` for a wider surface.
Read the numbers from the second response.
A `candidate_metric.persons_reached` of 0 straight after an exact filter usually means the value is not the one the project records, such as `/pricing` against `/pricing/`.
Read the shape back with `read-data-schema` (`event_property_values`, a sample of the values) and correct the filter, rather than widening it.

`previous_experiments.summary` says how the project's earlier experiments fared for size. When `previous_experiments.summary.launched_with_zero_analyzed_exposures` or `launched_with_under_100_analyzed_exposures` is a large share of `launched`, the project has been launching experiments that could not measure anything. Say so, and treat the running time as the number to get right rather than a formality.

### Read the counts in this order

1. `candidate_metric.persons_reached` is 0: no one sent the target event in the window under `target_properties` and `target_url_contains`. Fix the target before reading the two counts below. Only people who reached the target can convert, so `candidate_metric.persons_converted` is 0 whatever the metric does, and `candidate_metric.event_volume` counts the metric event without the target and says nothing about the pair.
2. `candidate_metric.event_volume` is 0: the metric event never occurred in the window under `metric_properties`. Check the event name with `read-data-schema`, then check the filters. A `candidate_metric.conversion_rate` of 0 says nothing until this is above 0.
3. `candidate_metric.event_volume` is above 0 but `candidate_metric.persons_converted` is 0: the event happens, but never after the target event. Either the metric measures something people do elsewhere in the product, or the target is wrong. `candidate_metric.unique_persons` says how many people send the event at all, which separates a rare event from a misplaced one.

Tier: confident on the arithmetic, best guess on the inputs (the baseline is an estimate over `candidate_metric.window_days`).

## Precedent

Read `previous_experiments.summary`. Its `using_*` counts cover every listed experiment, drafts included, so read them as what the project sets up, not what it launches.
When `previous_experiments.experiments` is empty, the project is creating its first experiment. There is no precedent, and nothing in this section applies. Say that rather than reporting an absent precedent as agreement.

If most listed experiments use one setting, follow it unless the facts above contradict it, and say you followed precedent. Tier: best guess. Two limits:

- The placement rule wins. A precedent of neither persistence nor device-id bucketing does not settle a surface that crosses identification.
- Do not add configuration the project has never used, unless a fact above calls for it. A custom exposure and an activation event each narrow what counts as an exposure, and a project whose `previous_experiments.summary.using_custom_exposure` and `using_activation` are 0 has given you no reason to narrow it.
- Two facts above override a count of 0, and only these two. The placement rule, for persistence and device-id bucketing. And a flag evaluated more widely than the surface under test, for a custom exposure: that is the case "Feasibility and running time" describes, and it is the right first use of a custom exposure in a project that has never had one.

Read `previous_experiments.experiments[].serving_single_variant` before you trust `previous_experiments.summary.using_uneven_split`. Shipping a variant rewrites the flag to serve that variant to everyone it matches, so an ended experiment's flag no longer carries the split it ran with. The summary leaves those experiments out of `using_uneven_split`, and `previous_experiments.experiments[].split_even` is null on any row where `serving_single_variant` is set.

`previous_experiments.summary.using_exposure_property_filters` counts experiments whose exposure is narrowed by properties on whichever event it counts. A narrowed default event is not a custom exposure, so `using_custom_exposure` does not count it, but it is still a deliberate choice about what an exposure means. Read `previous_experiments.experiments[].exposure_property_filters`: an experiment that counted exposure only where `$pathname` was `/pricing` is the precedent for a new test on that page.

For a holdout, look at `previous_experiments.experiments[].has_holdout`.

## Statistics

Leave `stats_config` out, so the experiment follows the team's defaults (`stats_method`, `confidence_level`, CUPED, sequential testing). Set it only when the user asks for a different method. Tier: confident.
