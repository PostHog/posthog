# Assessing a scout's health and performance

There is no single "is my scout good" number.
A scout's job is to be quiet most of the time and right when it speaks — so a naive "it wrote nothing" reads as broken when it's usually correct.
Judge a scout across a window of runs along the dimensions below, and reach for the matching diagnosis when one looks off.

Pull the window first:

```json
signals-scout-runs-list
{ "date_from": "2026-05-01T00:00:00Z", "limit": 100 }
```

Filter the result to the scout's `skill_name`, then reason across the dimensions, reading each run's `summary`.
Learned memory comes from `signals-scout-scratchpad-search`.
Note up front: each run carries `emitted_report_ids` / `edited_report_ids` (and the list endpoint takes an `emitted` filter), so report volume is a clean metric off the runs themselves — and `inbox-reports-list { "source_product": "signals_scout" }` lists the reports the fleet surfaced.
Read the two together: the runs tell you how often the scout wrote, the inbox filter what that output looks like to the user.

## The dimensions

### 1. Cadence adherence — is it running on schedule?

Compare the gaps between consecutive `started_at` timestamps against `run_interval_minutes` from the config.
Roughly-on-schedule is healthy.
Persistent large gaps mean the coordinator isn't dispatching it as often as configured.

- **Diagnosis if gaps are large:** check `enabled` (a paused scout never runs), confirm the project is still enrolled in the `signals-scout` feature flag, and remember busy ticks are capped — a team with many overdue scouts may see some run late.
  See the coordinator notes in [`scout-data-model.md`](scout-data-model.md).

### 2. Success rate — are runs completing cleanly?

Count clean completions vs. `failed` runs over the window.
Distinguish failure modes by duration: a `failed` run that ran ~30 minutes (the per-run budget) before failing **timed out**; a `failed` run that died quickly is more likely genuinely broken.
Most timeouts are over-investigation — the scout ran to the wall, common and semi-expected on high-volume surfaces (logs, error tracking), and the fleet self-corrects by writing "tight-run recipe" scratchpad entries.
But a timeout can also be a **false timeout**: the scout finished in a few minutes and the run then hung on a dropped close-out, so don't infer over-investigation from the ~30-minute duration alone.

- **Diagnosis:** read a failed run's transcript (the error is not in the run payload) — open `task_url`, or pull it as data with `tasks-runs-session-logs-retrieve` (filter out the noisy `tool_call_update` / `usage_update` events to get a readable action timeline).
  Tool calls right up to the wall mean genuine over-investigation; silence long before it means a false timeout.
  A quick failure from a query tool erroring, a body referencing an event/table that no longer exists, or a changed surface schema is an authoring fix — hand off to `authoring-scouts`.
  Recurring over-investigation timeouts on a firehose surface point at a too-broad body that needs a cheaper discriminator, also an authoring fix.

### 3. Report rate — how often does it speak?

Of completed runs, what fraction wrote or edited a report vs. closed out empty?
Read it straight off each run's `emitted_report_ids` / `edited_report_ids`, or split the window with `runs-list?emitted=true` / `?emitted=false` and compare counts (remembering an edit-only run reads as `emitted=false`).
Judge it against the surface, not in the abstract — **most healthy scouts write rarely**, and on a quiet, mature project nearly every run legitimately closes out empty.

- **Near-zero over a long window:** either the watched surface is genuinely quiet (confirm with `signals-scout-project-profile-get` — is the surface even in use?), or the scout's signal-vs-noise discriminator is too strict.
  Read a few run summaries: if the scout keeps saying "saw X but below threshold", the bar may be too high.
- **Near-100%:** the scout is too noisy — its discriminator isn't separating baseline from anomaly.
  Expect lots of suppressed or dismissed reports downstream (dimension 4).
- Both fixes are authoring changes (retune the discriminator / thresholds / disqualifiers).

### 4. Signal-to-noise — was the output worth it?

Of what the scout wrote, how much was actionable vs. suppressed or dismissed as noise?
`emitted_report_ids` names each authored report — resolve them via `inbox-reports-retrieve` and read the statuses: a live, non-suppressed report a human acted on is a hit; a suppressed or dismissed one is noise.
`inbox-reports-list { "source_product": "signals_scout" }` gives the fleet-wide view — cross-check its states against the write volume, and read the run summaries plus the scratchpad for the qualitative picture: a healthy scout's summaries describe deliberate, calibrated reports and the scratchpad fills with `dedupe:` / `noise:` / `addressed:` / `report:` entries as it learns what not to re-raise.

- **Diagnosis if it looks noisy:** if summaries show the same thing filed repeatedly, or the scratchpad lacks `report:` / `dedupe:` entries for things it has flagged, its dedupe memory isn't working — an authoring fix to the save-memory and disqualifier sections.

### 5. Memory growth — is it learning?

A scout that has run many times should have accumulated `pattern:` (baselines), `noise:`, and `dedupe:` scratchpad entries.
Search the scratchpad and look at `created_by_run_id` and timestamps.

- **Diagnosis if the scratchpad is empty after many runs:** the scout isn't internalizing what it sees, so every run re-reasons from cold and is prone to re-filing.
  The body's save-memory guidance may be weak — an authoring fix.

## Putting it together

A **healthy** scout looks like: runs landing on cadence, almost all completing cleanly, the large majority closing out empty, the rare report mostly surviving as actionable, and a scratchpad that grows `pattern:`/`noise:`/`dedupe:` entries over time.

An **unhealthy** scout shows one of: frequent errors (broken — read the transcript), a flood of reports most of which get suppressed (too noisy — retune), dead silence on a surface the profile shows is active (too strict — retune), or no memory growth despite many runs (not learning).

When the diagnosis points at the scout's instructions — discriminator, thresholds, disqualifiers, save-memory, schedule, or posture — that's where exploration ends and authoring begins.
Hand off to the `authoring-scouts` skill, which covers the test loop and `signals-scout-config-update`.
