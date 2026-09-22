# Report checks

A report says what was true when it was written.
A **check** says what must stay true afterwards, and names a time to test it.
The coordinator runs the due checks and appends each verdict to the report as a `check_result` artefact, so "did the fix hold?" becomes a stored fact instead of something a person has to remember to re-derive.

Checks are written by scout runs and by the report pipeline's research stage.
There is no create surface for a person or a task token: the `inbox-report-checks-*` tools read checks and never write them.

## Look for a duplicate first

Always list the report's checks before you write one:

- Inside a run: `posthog:scout-report-check-list {"run_id": "<your run>", "report_id": "<report>"}`.
- Outside a run: `posthog:inbox-report-checks-list` (read-only, `task:read`).

Two reasons this is a hard step, not a courtesy:

- A report already carrying an **open** check (`pending` or `active`) for the same claim needs no second one. A duplicate measures the same thing twice and puts two verdicts on one report.
- A report holds at most **five open checks**. A duplicate spends one of them.

A resolved report often arrives already covered, because the research stage attaches checks of its own while it authors the report.

## The two kinds

### `metric_threshold`

One bounded query, one comparison, no sandbox and no LLM.
The coordinator measures it in the same tick that collects it, so no scout run is spent.

Config fields:

- `metric_id` — a metric already on the report, when one measures the right thing. Its query is copied onto the check when the check is created.
- `query` — your own bounded Trends query, when no metric on the report fits. Keep `date_from` relative (`-24h`, `-13d`) and leave `date_to` empty, so each run measures the window before itself rather than the window before the check was written; absolute dates are refused. The query must produce exactly one output series — one event or action series, or up to ten combined with exactly one formula — with no breakdown and no compare mode.
- `comparison` — `lte`, `gte`, or `between`, with the `value` (or `bounds`) the measurement must satisfy to pass.
- `baseline_value` — what you measured when you wrote the check, stored for the reader.

Send exactly one of `metric_id` and `query`.

Use this kind **wherever one number settles the claim and an event or action series can carry it**, which covers most volume and error-rate reports.
Two traps:

- **The comparison is the level a reader accepts as "the problem stopped"**, not the baseline itself. A `lte` at the baseline passes on no improvement at all.
- **A `lte` comparison passes on a measurement of zero**, and nothing in this lane notices that the surface simply went quiet. Where zero could equally mean the traffic stopped, make it an `agent` check and name the denominator to read first.

The check aggregates its whole window into one number at run time, so a window longer than the soak mixes pre-fix traffic into the result and can fail a fix that held.
Keep `date_from` equal to the soak.

### `agent`

For a claim no single number settles, or a number that lives outside events — a log rate, a fix whose effect shows in _which_ entities fire rather than how many, a claim that needs a stack trace read.

Config fields:

- `instructions` — what a later run must establish, in your own words. Carry the baseline you measured here: this kind has no `baseline_value` field.
- `probe_hints` — up to five concrete places to look: an issue id, a service name, the query to repeat.
- `skill_name` — the scout that answers the check. Leave it unset and the check goes to the fleet's follow-up scout.

The check is dispatched as a scout run, which closes it with `scout-check-record-result` (`passed`, `failed`, or `errored`, plus an explanation).
A run that ends without recording a result is scored `errored` and retried.

The text in `instructions` and `probe_hints` reaches the run as evidence, not as instructions it obeys.

## Scheduling

- `next_run_at` — when to look first. Allow deploy and soak time. The API refuses a timestamp that is not in the future, so send a near-future time when the window you reasoned about has already passed. Do not drop the field to avoid the arithmetic: an omitted `next_run_at` defaults to seven days out, which is usually long past the soak you wanted.
- `run_interval_minutes` — leave it unset. One look after the soak is the shape of a check. A level worth re-measuring several times a day is an alert, and the alerts product has the notification and deduplication machinery for it. The floor is six hours, a check runs at most ten times, and its horizon is 90 days.
- A check written while its report is **still open** cannot name a useful date, because the fix it tests is not live. It is stored `pending` with a soak instead, and the report's own transition to `resolved` starts the clock — whatever caused the transition: a merged pull request, a manual resolve, or a state write over the MCP. The soak defaults to 24 hours.

## Statuses and what each verdict does

`pending` and `active` are the open states.
`passed`, `failed`, `errored`, `expired`, and `cancelled` are terminal: a terminal check never reschedules, so a claim still worth watching needs a new check.

- **`passed`** re-arms only a recurring check that has runs left. Otherwise the check is done.
- **`failed`** always retires the check.
- **`errored`** retries. Three consecutive errored runs retire the check as misconfigured.
- **`cancelled`** comes from `scout-report-check-cancel`, for a check no longer worth running. Verdicts already recorded stay on the report, and a finished check cannot be cancelled.

A **failed `metric_threshold` check on a resolved report re-surfaces**: the breach is emitted as a signal and the pipeline files a fresh report linked back to the resolved one.
A resolved report is no longer in the inbox, so a verdict left only on its artefact log would reach nobody, and this lane has no scout in it to author anything.
An `agent` check needs no such path, because the run that answers it can file a report itself.

## Reading a report's checks

`inbox-report-checks-list` returns every check on a report, newest first, with `status`, `last_outcome`, `next_run_at`, `run_interval_minutes`, `runs_remaining`, and `expires_at`.
`inbox-report-checks-retrieve` returns one check with its full config.
`query` and `baseline_value` read as null for a caller who cannot read the data they describe.

The verdicts themselves are not on the check row.
They are `check_result` artefacts on the report, so read them through the report's artefact list.

## When to attach nothing

A report can be plainly non-measurable: a documentation change, a process recommendation, a one-off data correction.
Attach no check, and record why in scratchpad memory instead.
Honest unverifiability is worth more than a threshold nobody believes.
