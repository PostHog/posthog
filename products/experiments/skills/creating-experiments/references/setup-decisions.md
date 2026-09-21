# Setup decisions from project facts

Use this file after `experiment-setup-context` returned. Each section maps the tool's facts to one configuration choice and to a tier for the summary:

- **Confident**: the facts decide it.
- **Best guess**: a reasonable default that the facts support but do not prove. Say what would change it.
- **Not decided**: the facts cannot decide it. Say what is missing and how the user can decide.

Every section has the shape `{status, data}`. The field paths below are inside `data`: `target_surface.anonymous_share` means `target_surface.data.anonymous_share`.
A section whose `status` is not `ok` gives no facts. Choices that depend on it drop to "best guess" at most, and the summary says which section was missing.

## Bucketing and persistence

Read these facts:

- `target_surface.anonymous_share`: the share of distinct IDs on the page's web events that were not identified. A high share usually means logged-out visitors. It is null when no web SDK sent the target event (a mobile or server target).
- `target_surface.device_id_share`: the share of the page's web events that carry a device ID.
- `sdk_profile.libs`: per SDK, `device_id_share` and `locally_evaluated_share` on flag calls. It covers the whole project, not one page, so use `target_surface.libs` to pick the rows that apply to this page. It is empty when the project sent no multivariate flag calls in the last 7 days.

| Facts                                                                                                                                           | Choice                                                                                                 | Tier                                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| `anonymous_share` above about 0.9, or below about 0.1: the page is seen mostly by one kind of visitor                                           | User-id bucketing. Leave `ensure_experience_continuity` out, so the team's persistence default applies | Best guess                                                |
| Between: the same people likely see the page before and after they are identified, and user-id bucketing can switch their variant at that point | The steps below                                                                                        | Best guess, always listed for review                      |
| `anonymous_share` is null                                                                                                                       | User-id bucketing, team persistence default                                                            | Not decided: say the identity mix on this page is unknown |

When the page crosses identification, in this order:

1. **Device-id bucketing**, if `target_surface.device_id_share` is near 1, at least one `sdk_profile.libs` row has a `lib` that appears in `target_surface.libs`, and every matching row has `device_id_share` near 1. A flag call without a device ID gets no variant, so a server SDK must forward the browser's device ID; local evaluation works when it does. `target_surface.device_id_share` is read from the target events; a `sdk_profile.libs` row's `device_id_share` is read from flag-call events. Neither is read from the flag requests, so neither proves that the request carried a device ID. The web SDK sends the device ID on flag requests from posthog-js 1.307.1. An older version puts a device ID on events and still gets no variant, so tell the user to check the SDK version. Set it up with the device-id recipe in `configuring-experiment-rollout`. `experiment-create` cannot set it.
2. **Persistence** (`ensure_experience_continuity: true`), if no matching `sdk_profile.libs` row evaluates flags locally: every row that matches a `lib` in `target_surface.libs` has `locally_evaluated_share` near 0, or null on a web or mobile row. Null on a server row is unknown: go to step 3. Persistence also needs person profiles for anonymous users, no bootstrapping, and `$anon_distinct_id` on server flag calls. The tool cannot see those three, so list them for the user to check.
3. **Otherwise**: user-id bucketing, and mark it "not decided". Say what would unlock the other options: a device ID on every flag call, or no local evaluation.

If `sdk_profile.libs` is empty, or no row matches a `lib` in `target_surface.libs`, there is no evidence about device IDs on flag calls or about local evaluation, and steps 1 and 2 do not pass. Keep user-id bucketing and mark it "not decided". Say that device-id bucketing is the likely fit when `target_surface.device_id_share` is near 1 and `target_surface.libs` lists no server SDK.

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

Keep the test-account filter on (creation turns it on by default) and say so. If `team_defaults.test_account_filter_count` is 0, say the project has no test-account filters. Tier: best guess.

## Primary metric

1. Pick the event that expresses the hypothesis. Confirm it exists with `read-data-schema`.
2. A `shared_metrics.metrics` entry with `matches_metric_event: true` is a candidate, not a match: the event appears somewhere in the metric, in any role. Load it with `experiment-saved-metrics-retrieve` and compare its `query` (metric type, the event's role, `math`) with what the user asked for.
   - If it matches, link it after creation through `experiment-update` with `saved_metrics_ids`, instead of building an inline metric. Tier: confident. When the user asked for no questions, link it and report it rather than asking first.
   - If it doesn't, build an inline metric.
3. Otherwise pick a shape from the metric templates in `configuring-experiment-analytics` (`references/metric-templates.md`). Tier: best guess.

Every conversion window carries a unit (`conversion_window_unit`). A window without a unit is ignored.

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

The estimate assumes people are exposed on the target surface. If the flag is evaluated more widely (across the whole app, or on a page before the one that changes), the exposed population is larger and converts less. The baseline and the running time are then too optimistic. Say so, and consider a custom exposure on the surface event.

`target_url_contains` is a substring match on the URL: a bare domain matches every page on it and overstates the page's traffic. Pass the most specific fragment you can.

Tier: confident on the arithmetic, best guess on the inputs (the baseline is an estimate over `candidate_metric.window_days`).

If `candidate_metric.persons_reached` is 0, no one sent the target event in the window: say the target may be wrong. If `persons_reached` is above 0 but `persons_converted` is 0, the metric event never follows the target: say the metric event may be misspelled or not yet instrumented.

## Precedent

Read `previous_experiments.summary`. Its `using_*` counts cover every listed experiment, drafts included, so read them as what the team sets up, not what it launches.

If most listed experiments use one setting (device-id bucketing, persistence, custom exposure), follow it unless the facts above contradict it, and say you followed precedent. For a holdout, look at `has_holdout` on the rows in `previous_experiments.experiments`. Tier: best guess.

## Statistics

Leave `stats_config` out, so the experiment follows the team's defaults (`stats_method`, `confidence_level`, CUPED, sequential testing). Set it only when the user asks for a different method. Tier: confident.
