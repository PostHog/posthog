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

Report the mix and leave the choice to the user. Tier: **not decided**.
These facts give the identity mix on the surface, not whether the same individuals cross identification on it, so they cannot decide bucketing.
A surface with an even mix may be two separate populations that never cross, and a surface that is almost all identified may still route every one of those people through an anonymous first pageview.
Say what the mix is, name the options the surface can support under the caveats below, and say what each one would need.
Ask before you call `experiment-create`. Device-id bucketing needs the flag to exist first, so the choice cannot wait until the draft is made.

Say it plainly when the project has used neither persistence nor device-id bucketing (`previous_experiments.summary.using_persistence` and `previous_experiments.summary.using_device_id_bucketing` both 0), because that is the case where the user has no in-house precedent to reason from. Report it as context, not as a fault.

### What each option needs

- **User-id bucketing** is the default. A person's variant follows their distinct ID, so it can change when they are identified.
- **Device-id bucketing** needs a device ID on every flag call: a call without one gets no variant. Read `target_surface.device_id_share`, and `sdk_profile.libs[].device_id_share` on the rows whose `lib` appears in `target_surface.libs`. Both near 1 is the signal that the surface can carry it. A server SDK must forward the browser's device ID, and local evaluation works when it does. The web SDK sends the device ID on flag requests from posthog-js 1.307.1; an older version puts one on events and still gets no variant, so name the version as something to check. `experiment-create` cannot set it, so use the device-id recipe in `configuring-experiment-rollout`.
- **Persistence** (`ensure_experience_continuity: true`) cannot work where an SDK evaluates the flag locally, because a local evaluation never consults the override store. Read `sdk_profile.libs[].locally_evaluated_share` on the rows whose `lib` appears in `target_surface.libs`. It also needs person profiles for anonymous users, no bootstrapping, and `$anon_distinct_id` on server flag calls. The tool cannot see those three, so list them for the user to check.

Both of those reads match `sdk_profile.libs` rows to `target_surface.libs`, so an SDK the match misses is unchecked rather than safe.
A `target_surface.libs[]` row with no `sdk_profile.libs` row of the same `lib` is unchecked, and so is every row when `sdk_profile.libs` is empty, which is what an empty profile means: the project sent no multivariate flag call in the last 7 days, the normal state before its first experiment.
`target_surface.libs` holds at most 5 SDKs and reports the cap in `target_surface.libs_truncated`, so an unseen SDK can reach the surface when that flag is true.
In each of those cases say the option is unchecked, and name the SDK or the cap you could not read.
An unread server SDK is the one that breaks both options, because it may send flag calls without a device ID and may evaluate them locally.

Read the shares rather than the platform, and read them in one direction only. Both count events and never the flag request: `target_surface.device_id_share` reads target events, and a `sdk_profile.libs` row reads flag-call events.
A row near 1 says a device ID is present in that traffic. A row near 0 says only that those events carried none, which leaves the option unchecked rather than unavailable: a server SDK can forward the browser's device ID on the flag request while its own events carry no `$device_id`.
So never rule device-id bucketing out from a share. Say it is unchecked, and name what would settle it, which is whether the SDK puts a device ID on the flag request.
`sdk_profile.libs_on_any_event[]` names the platforms the project sends from, and that is all it does. It reads no flag call, so it cannot say whether a device ID reaches one or whether an SDK evaluates locally. Do not decide bucketing from it.

Device-id bucketing and persistence cannot be combined, and the API rejects the pair.
When `ensure_experience_continuity` is omitted, `experiment-create` applies the team's default (`team_defaults.flags_persistence_default`).
`create-feature-flag` leaves persistence off unless you set it, and `experiment-create` rejects a `feature_flag` object for a flag that already exists.
So pass `ensure_experience_continuity: false` in the call that sets device-id bucketing on a flag `experiment-create` already made, because that flag carries the team default and the pair is refused.
When `team_defaults.flags_persistence_default` is true and a matching `sdk_profile.libs` row evaluates the flag locally, say so: leaving the field out gives the flag a persistence setting that cannot work there. Set it to `false` only if the user asks, because the team chose that default.

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

If most listed experiments use one setting, follow it unless the facts above contradict it, and say you followed precedent. Tier: best guess. Three limits:

- Bucketing and persistence sit outside this rule. "Bucketing and persistence" leaves both to the user, so a count of earlier experiments does not settle them either. Report the precedent as context and still ask.
- Do not add configuration the project has never used, unless a fact above calls for it. A custom exposure and an activation event each narrow what counts as an exposure, and a project whose `previous_experiments.summary.using_custom_exposure` and `using_activation` are 0 has given you no reason to narrow it.
- One fact above overrides a count of 0, and only this one: a flag evaluated more widely than the surface under test, for a custom exposure. That is the case "Feasibility and running time" describes, and it is the right first use of a custom exposure in a project that has never had one.

Read `previous_experiments.experiments[].serving_single_variant` before you trust `previous_experiments.summary.using_uneven_split`. Shipping a variant rewrites the flag to serve that variant to everyone it matches, so an ended experiment's flag no longer carries the split it ran with. The summary leaves those experiments out of `using_uneven_split`, and `previous_experiments.experiments[].split_even` is null on any row where `serving_single_variant` is set.

`previous_experiments.summary.using_exposure_property_filters` counts experiments whose exposure is narrowed by properties on whichever event it counts. A narrowed default event is not a custom exposure, so `using_custom_exposure` does not count it, but it is still a deliberate choice about what an exposure means. Read `previous_experiments.experiments[].exposure_property_filters`: an experiment that counted exposure only where `$pathname` was `/pricing` is the precedent for a new test on that page.

For a holdout, look at `previous_experiments.experiments[].has_holdout`.

## Statistics

Leave `stats_config` out, so the experiment follows the team's defaults (`stats_method`, `confidence_level`, CUPED, sequential testing). Set it only when the user asks for a different method. Tier: confident.
