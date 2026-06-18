# Error tracking alert trigger events

The three lifecycle events that error tracking alerts ride on. Each is fired by a different part of the
ingestion / detection pipeline, has a different cadence, and exposes a different property surface.

## `$error_tracking_issue_created`

**Fires:** once, the first time a fingerprint produces an exception that maps to a new issue. Subsequent
exceptions on the same fingerprint do not re-fire this event.

**Cadence:** proportional to the number of distinct exception types in your project. A new project may
fire dozens per hour; a mature project may fire once or twice a day.

**Best for:**

- Small projects where every new error type is genuinely worth a look.
- Projects right after enabling error tracking, to learn the shape of incoming errors.
- Routing into a "triage" Slack channel that humans only check during business hours.

**Avoid for:** large or noisy projects. A single bad release can produce hundreds of new issues; a
firehose into the user's primary channel will train them to ignore it.

**Useful event properties for templating:**

- `event.properties.name` — issue title (typically the exception class).
- `event.properties.description` — truncated body / message.
- `event.properties.status` — `"active"` at this point.
- `event.properties.fingerprint` — used in the deep link.
- `event.properties.exception_timestamp` — used in the deep link.
- `event.distinct_id` — the issue id.
- The originating exception's event properties are also spread onto the alert event, so property
  filters can reference keys like `$exception_issue_id` (per-issue scoping) and `$exception_types`.

## `$error_tracking_issue_reopened`

**Fires:** when an issue previously marked `resolved` starts emitting again. The status flips back to
`active` and this event fires once per re-open transition. Spike detection on a resolved issue will
**not** fire `_reopened` — only the explicit status flip back to active does.

**Cadence:** roughly proportional to how often someone actually marks issues resolved. In projects
where issues are auto-resolved on release, this can be noisy; in projects where resolution is manual,
this is rare and high-signal.

**Best for:** catching regressions on issues someone has already triaged. The safest "I want to know
if this comes back" trigger.

**Useful event properties for templating:** same as `_created`, plus the issue's current `status` will
be `"active"` (the reopen has already taken effect).

## `$error_tracking_issue_spiking`

**Fires:** when the spike detector flags an issue as having abnormal volume. The detector uses the
configured baseline window, multiplier, and threshold (configured via the spike detection config
endpoint per project — not per alert). Each spiking issue fires its own event; one project-wide
spike can therefore trigger many `_spiking` events in quick succession.

**Cadence:** depends entirely on the spike config. With default thresholds, expect a handful per day on
a typical production project; tighter thresholds make this much noisier.

**Best for:**

- Production projects with high baseline volume where `_created` and `_reopened` are too rare or too
  noisy.
- Routing into an oncall channel (this is the closest thing to "wake someone up" the lifecycle events
  offer).

**Avoid for:** projects where the spike detector hasn't been configured. Without a tuned baseline the
detector either over-fires or under-fires.

**Useful event properties for templating** — spiking events carry a smaller surface than `_created`:
no `status`, no `fingerprint`, no `exception_timestamp`, and no exception properties (so no per-issue
property scoping). Available:

- `event.properties.name` — issue title.
- `event.properties.description` — truncated body / message.
- `event.distinct_id` — the issue id.
- `event.properties.current_bucket_value` — exception count in the current detection window (typically
  5 minutes).
- `event.properties.computed_baseline` — the historical baseline the current value is being compared
  to. May be 0 on the first spike if there isn't enough history yet — the canonical Slack template
  guards against this with a conditional expression.

**Pre-flight check:** before creating a `_spiking` alert, verify the spike detection config has been
turned on for the project. There is no MCP tool for this today — direct the user to the error tracking
spike config UI in product settings if it is not enabled. An alert on `_spiking` is silent until the
detector is running.

## Common to all three

**Project context** is exposed as `{project.url}` (already includes `/project/<team_id>`), `{project.id}`,
and `{project.name}`. The alert's own metadata is exposed as `{source.url}` and `{source.name}` —
useful for "manage this alert" links inside the message body.

**Deep-link shape** for the issue page (used by the canonical block templates):

```text
{project.url}/error_tracking/{event.distinct_id}?fingerprint={event.properties.fingerprint}&timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack
```

`utm_medium` matches the destination (`slack`, `discord`, `microsoft_teams`). For `_spiking` links, drop
the `fingerprint` and `timestamp` params — spiking events do not carry those properties. The `utm_*`
tags let the team measure how often issues get clicked from alerts later via product analytics on
`$pageview`.
