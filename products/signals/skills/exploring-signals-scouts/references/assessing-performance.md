# Assessing a scout's health and performance

There is no single "is my scout good" number. A scout's job is to be quiet most of the time and
right when it speaks — so a naive "it emitted nothing" reads as broken when it's usually correct.
Judge a scout across a window of runs along the dimensions below, and reach for the matching
diagnosis when one looks off.

Pull the window first:

```json
signals-scout-runs-list
{ "date_from": "2026-05-01T00:00:00Z", "limit": 100 }
```

Filter the result to the scout's `skill_name`, then reason across the dimensions, reading each
run's `summary`. Learned memory comes from `signals-scout-scratchpad-search`. Note up front: there
is **no emit flag or finding count on a run**, and `inbox-reports-list { "source_product":
"signals_scout" }` does not reliably surface scout output (grouping attributes findings to the
underlying product) — so emit-related dimensions below are read from the run summaries, not a clean
metric.

## The dimensions

### 1. Cadence adherence — is it running on schedule?

Compare the gaps between consecutive `started_at` timestamps against `run_interval_minutes` from
the config. Roughly-on-schedule is healthy. Persistent large gaps mean the coordinator isn't
dispatching it as often as configured.

- **Diagnosis if gaps are large:** check `enabled` (a paused scout never runs), confirm the project
  is still enrolled in the `signals-scout` feature flag, and remember busy ticks are capped — a
  team with many overdue scouts may see some run late. See the coordinator notes in
  [`scout-data-model.md`](scout-data-model.md).

### 2. Success rate — are runs completing cleanly?

Count clean completions vs. `failed` runs over the window. Distinguish two failure modes by
duration: a `failed` run that ran ~30 minutes (the per-run budget) before failing **timed out** —
the scout over-investigated, which is common and semi-expected on high-volume surfaces (logs, error
tracking), and the fleet self-corrects by writing "tight-run recipe" scratchpad entries. A `failed`
run that died quickly is more likely genuinely broken.

- **Diagnosis:** open the `task_url` of a failed run (the error is not in the run payload) to read
  the transcript. A quick failure from a query tool erroring, a body referencing an event/table
  that no longer exists, or a changed surface schema is an authoring fix — hand off to
  `authoring-signals-scouts`. Recurring timeouts on a firehose surface point at a too-broad body
  that needs a cheaper discriminator, also an authoring fix.

### 3. Emit rate — how often does it speak?

Of completed runs, what fraction emitted a finding vs. closed out empty? You read this from the run
`summaries` (no emit metric exists). Judge it against the surface, not in the abstract — **most
healthy scouts emit rarely**, and on a quiet, mature project nearly every run legitimately closes
out empty.

- **Near-zero over a long window:** either the watched surface is genuinely quiet (confirm with
  `signals-scout-project-profile-get` — is the surface even in use?), or the scout's
  signal-vs-noise discriminator is too strict. Read a few run summaries: if the scout keeps saying
  "saw X but below threshold", the bar may be too high.
- **Near-100%:** the scout is too noisy — its discriminator isn't separating baseline from
  anomaly. Expect lots of suppressed reports downstream (dimension 4).
- Both fixes are authoring changes (retune the discriminator / thresholds / disqualifiers).

### 4. Signal-to-noise — was the output worth it?

Of what the scout emitted, how much was actionable vs. dismissed as noise? You can't filter the
inbox to `source_product: "signals_scout"` (grouping attributes findings to the underlying product,
so that filter returns nothing), so judge this from the run summaries plus the scratchpad: a
healthy scout's summaries describe deliberate, calibrated emits and the scratchpad fills with
`dedupe:` / `noise:` / `addressed:` entries as it learns what not to re-raise.

- **Diagnosis if it looks noisy:** if summaries show the same thing emitted repeatedly, or the
  scratchpad lacks `dedupe:` entries for things it has flagged, its dedupe memory isn't working —
  an authoring fix to the save-memory and disqualifier sections.

### 5. Memory growth — is it learning?

A scout that has run many times should have accumulated `pattern:` (baselines), `noise:`, and
`dedupe:` scratchpad entries. Search the scratchpad and look at `created_by_run_id` and timestamps.

- **Diagnosis if the scratchpad is empty after many runs:** the scout isn't internalizing what it
  sees, so every run re-reasons from cold and is prone to re-emitting. The body's save-memory
  guidance may be weak — an authoring fix.

## Putting it together

A **healthy** scout looks like: runs landing on cadence, almost all completing cleanly, the large
majority closing out empty, the rare emit mostly surviving as an actionable report, and a
scratchpad that grows `pattern:`/`noise:`/`dedupe:` entries over time.

An **unhealthy** scout shows one of: frequent errors (broken — read the transcript), a flood of
emits most of which get suppressed (too noisy — retune), dead silence on a surface the profile shows
is active (too strict — retune), or no memory growth despite many runs (not learning).

When the diagnosis points at the scout's instructions — discriminator, thresholds, disqualifiers,
save-memory, schedule, or posture — that's where exploration ends and authoring begins. Hand off to
[`../../authoring-signals-scouts/SKILL.md`](../../authoring-signals-scouts/SKILL.md), which covers
the dry-run-first test loop and `signals-scout-config-update`.
