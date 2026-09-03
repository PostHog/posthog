// Ported from PostHog Desktop `packages/core/src/scouts/scoutRunsWindow.ts`
// and `scoutPresentation.ts`. Pure metrics + display helpers over scout runs and
// configs; no I/O. Two different run sets feed them: the per-scout stats read
// `scoutFleetLogic.loadScoutRuns` (each scout's last N runs, one request), while the
// fleet findings feed reads `loadRunsWindow` (a fixed lookback assembled by walking
// the runs endpoint's `date_to` cursor past its 100-row page cap).

import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { SignalScoutRunStatus, SignalScoutRunSummary } from '../types'

/**
 * How many of each scout's most recent runs the per-scout stats describe — the count the
 * `recent-per-scout` endpoint is asked for, mirrored here so the labels match the data.
 *
 * Scouts run on their own schedules, so a shared time window can't serve them all: an hourly scout
 * fills a fleet-wide result cap on its own, and the daily and weekly ones end up with a history
 * that gets shorter the busier the rest of the fleet is. Counting per scout gives each the same
 * depth whatever its cadence.
 */
export const SCOUT_RUNS_PER_SCOUT = 25

/** Label for per-scout stats, e.g. "last 25 runs". */
export const SCOUT_RUNS_PER_SCOUT_LABEL = `last ${SCOUT_RUNS_PER_SCOUT} runs`

/**
 * The span every fleet-level number on the roster describes: runs, reports filed and edited, and
 * scratchpad entries learned. Per-scout depth is a run count, but summing "last 25 each" across a
 * fleet is bounded by fleet size, so the fleet headline needs a common time span - and a week is
 * the shortest one that gives a daily scout enough runs to say anything.
 */
export const SCOUT_ROSTER_WINDOW_DAYS = 7
export const SCOUT_ROSTER_WINDOW_HOURS = SCOUT_ROSTER_WINDOW_DAYS * 24
export const SCOUT_ROSTER_WINDOW_LABEL = `last ${SCOUT_ROSTER_WINDOW_DAYS} days`

/**
 * Empty-state copy for a scout the window returned nothing for. Deliberately not "no runs in the
 * last 30 days": the endpoint's staleness guard stretches with each scout's own cadence, so the
 * cutoff a given scout was judged against is not a number the client knows.
 */
export const SCOUT_NO_RECENT_RUNS = 'No recent runs.'

/**
 * The time window the fleet-wide findings feed describes. Unlike the per-scout stats, that feed
 * answers "what has the troop surfaced lately?", which is a recency question — so it stays on a
 * fixed lookback, walked page by page from the runs endpoint's 100-row cap.
 */
export const SCOUT_RUNS_WINDOW_HOURS = 72

/** Human-friendly span the findings window covers, e.g. "3 days". */
export const SCOUT_RUNS_WINDOW_SPAN = ((): string => {
    if (SCOUT_RUNS_WINDOW_HOURS % 24 !== 0) {
        return `${SCOUT_RUNS_WINDOW_HOURS}h`
    }
    const days = SCOUT_RUNS_WINDOW_HOURS / 24
    return `${days} day${days === 1 ? '' : 's'}`
})()

// Fleet-wide findings views fetch/tally only the most recent N emitted runs, to bound the per-run
// fan-out. Shared so the page (`findingsLogic`) and the callout summary count the exact same set.
export const MAX_FLEET_EMITTED_RUNS = 120

/** The most recent output-producing runs across the fleet — runs that emitted a finding OR
 * authored/edited a report via the report channel — newest first, capped at `MAX_FLEET_EMITTED_RUNS`. */
export function mostRecentEmittedRuns(runs: SignalScoutRunSummary[]): SignalScoutRunSummary[] {
    return (
        runs
            .filter((run) => runProducedOutput(run))
            .slice()
            // "Most recently emitted" — a run can complete (and emit) later than one created after it, so
            // order by completion, falling back to creation. Matches `emittedFindingsSummary`'s `latestAt`.
            .sort((a, b) => (b.completed_at ?? b.created_at ?? '').localeCompare(a.completed_at ?? a.created_at ?? ''))
            .slice(0, MAX_FLEET_EMITTED_RUNS)
    )
}

// ── Scout skill-name helpers ──────────────────────────────────────────────────

/** The shared `signals-scout-*` skill-name prefix. The fleet prefix is noise inside the scouts surface. */
export const SIGNALS_SCOUT_SKILL_PREFIX = 'signals-scout-'

/** Strip the fleet prefix, leaving the bare scout code name verbatim. `signals-scout-apm` → `apm`. */
export function stripScoutPrefix(skillName: string): string {
    return skillName.startsWith(SIGNALS_SCOUT_SKILL_PREFIX)
        ? skillName.slice(SIGNALS_SCOUT_SKILL_PREFIX.length)
        : skillName
}

/** "signals-scout-error-tracking" → "Error tracking" */
export function prettifyScoutSkillName(skillName: string): string {
    const cleaned = stripScoutPrefix(skillName).replace(/[-_]/g, ' ').trim()
    if (!cleaned) {
        return skillName
    }
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}

// ── Run status / outcome ─────────────────────────────────────────────────────

export type ScoutRunStatus = 'completed' | 'failed' | 'running' | 'queued' | 'unknown'

export function normalizeRunStatus(status: SignalScoutRunStatus): ScoutRunStatus {
    if (status === 'completed') {
        return 'completed'
    }
    if (status === 'failed' || status === 'cancelled') {
        return 'failed'
    }
    if (status === 'in_progress') {
        return 'running'
    }
    if (status === 'queued' || status === 'not_started') {
        return 'queued'
    }
    return 'unknown'
}

/** Returns true when a run's status has settled — not running or queued.
 * Settled runs can be safely reused across polls without freezing wall-clock renders. */
export function isSettledRun(run: SignalScoutRunSummary): boolean {
    const status = normalizeRunStatus(run.status)
    return status !== 'running' && status !== 'queued'
}

export function runDurationSeconds(run: SignalScoutRunSummary, now: Date): number | null {
    if (!run.started_at) {
        return null
    }
    const started = new Date(run.started_at).getTime()
    if (Number.isNaN(started)) {
        return null
    }
    const ended = run.completed_at ? new Date(run.completed_at).getTime() : now.getTime()
    if (Number.isNaN(ended) || ended < started) {
        return null
    }
    return (ended - started) / 1000
}

/** Format a run's duration for display, e.g. "1m 30s". Empty string when unknown. */
export function formatRunDuration(seconds: number | null): string {
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}

/**
 * Scout runs are hard-killed at the ~31-minute Temporal activity deadline and
 * surface as bare "failed" with no error field. Until the serializer carries a
 * failure kind, infer a timeout from the run length.
 */
const TIMEOUT_THRESHOLD_SECONDS = 29 * 60

export type ScoutRunFailureKind = 'timed_out' | 'error'

export function deriveRunFailureKind(run: SignalScoutRunSummary, now: Date): ScoutRunFailureKind | null {
    if (normalizeRunStatus(run.status) !== 'failed') {
        return null
    }
    const duration = runDurationSeconds(run, now)
    if (duration !== null && duration >= TIMEOUT_THRESHOLD_SECONDS) {
        return 'timed_out'
    }
    return 'error'
}

/**
 * A SIGKILL mid-run can strand a TaskRun in IN_PROGRESS with no self-heal. Past
 * the run deadline we can be sure the run is not actually still working.
 */
const STUCK_THRESHOLD_SECONDS = 35 * 60

export function isRunStuck(run: SignalScoutRunSummary, now: Date): boolean {
    if (normalizeRunStatus(run.status) !== 'running') {
        return false
    }
    const duration = runDurationSeconds(run, now)
    return duration !== null && duration >= STUCK_THRESHOLD_SECONDS
}

// ── Report channel (emit_report / edit_report) ───────────────────────────────
// A second emit channel: instead of a weak `emit_signal` finding (which drives `emitted_count`), an
// opted-in scout authors a full inbox report directly (`emitted_report_ids`) or edits an existing one
// (`edited_report_ids`). This activity is invisible to `emitted_count`, so it's tracked separately here
// and folded into the run-outcome model so a report-authoring run never reads as "quiet".

/** The reports a single run touched via the report channel — authored (emit_report) and edited (edit_report). */
export function runReportActivity(run: SignalScoutRunSummary): { authored: string[]; edited: string[] } {
    return { authored: run.emitted_report_ids ?? [], edited: run.edited_report_ids ?? [] }
}

/** Whether a run produced any report-channel output (authored or edited at least one report). */
export function runTouchedReports(run: SignalScoutRunSummary): boolean {
    const { authored, edited } = runReportActivity(run)
    return authored.length > 0 || edited.length > 0
}

/** Whether a completed run produced any output at all — a weak finding OR report-channel activity. */
export function runProducedOutput(run: SignalScoutRunSummary): boolean {
    return (run.emitted_count ?? 0) > 0 || runTouchedReports(run)
}

/** A short label for a run's report-channel activity, e.g. "1 report authored · 2 reports edited", or
 * null when the run touched no report. */
export function scoutReportActivityLabel(run: SignalScoutRunSummary): string | null {
    const { authored, edited } = runReportActivity(run)
    const parts: string[] = []
    if (authored.length > 0) {
        parts.push(`${pluralize(authored.length, 'report')} authored`)
    }
    if (edited.length > 0) {
        parts.push(`${pluralize(edited.length, 'report')} edited`)
    }
    return parts.length > 0 ? parts.join(' · ') : null
}

export type ScoutRunOutcome =
    | 'emitted'
    | 'reported'
    | 'quiet'
    | 'error'
    | 'timed_out'
    | 'running'
    | 'stuck'
    | 'queued'
    | 'unknown'

export function deriveRunOutcome(run: SignalScoutRunSummary, now: Date): ScoutRunOutcome {
    const status = normalizeRunStatus(run.status)
    if (status === 'completed') {
        if ((run.emitted_count ?? 0) > 0) {
            return 'emitted'
        }
        // A run that emitted no finding but authored/edited a report is not quiet — it produced output
        // through the report channel.
        return runTouchedReports(run) ? 'reported' : 'quiet'
    }
    if (status === 'failed') {
        return deriveRunFailureKind(run, now) === 'timed_out' ? 'timed_out' : 'error'
    }
    if (status === 'running') {
        return isRunStuck(run, now) ? 'stuck' : 'running'
    }
    if (status === 'queued') {
        return 'queued'
    }
    return 'unknown'
}

/** The run-history filter chips on the scout detail surface. */
export type ScoutRunFilter = 'all' | 'emitted' | 'quiet' | 'failed'

/**
 * Whether a run belongs under a given filter chip. Emitted/Quiet split completed runs by whether they
 * produced any output — a weak finding OR report-channel activity (authored/edited a report); Failed is
 * any failed/cancelled run. There is no server-side `status` filter yet (api gap 1), so the detail view
 * filters its window client-side.
 */
export function runMatchesFilter(run: SignalScoutRunSummary, filter: ScoutRunFilter): boolean {
    const status = normalizeRunStatus(run.status)
    switch (filter) {
        case 'all':
            return true
        case 'emitted':
            return runProducedOutput(run)
        case 'quiet':
            return status === 'completed' && !runProducedOutput(run)
        case 'failed':
            return status === 'failed'
    }
}

export function scoutRunOutcomeLabel(run: SignalScoutRunSummary, now: Date): string {
    switch (deriveRunOutcome(run, now)) {
        case 'emitted': {
            const count = run.emitted_count ?? 0
            return `${pluralize(count, 'signal')} emitted`
        }
        case 'reported':
            // `reported` is only produced when the run touched a report, so the label is always present.
            // The `?? ''` is an unreachable type guard (the helper is `string | null`) — keeps the string
            // return without an unsafe `as` cast; never rendered.
            return scoutReportActivityLabel(run) ?? ''
        case 'quiet':
            return '0 signals emitted'
        case 'error':
            return 'failed'
        case 'timed_out':
            return 'timed out'
        case 'running':
            return 'running now'
        case 'stuck':
            return 'running past the deadline – may be stuck'
        case 'queued':
            return 'queued'
        case 'unknown':
            return run.status
    }
}

// ── Per-scout rollups ────────────────────────────────────────────────────────

export interface ScoutRollup {
    runCount: number
    completedCount: number
    failedCount: number
    emittedCount: number
    /** Distinct reports authored via `emit_report` across the window (a report authored once, even if
     * later edited, counts here). Deduped across runs since the same report can recur run-to-run. */
    authoredReportIds: Set<string>
    /** Distinct reports edited via `edit_report` across the window, deduped across runs. */
    editedReportIds: Set<string>
    latestRun: SignalScoutRunSummary | null
    runningRun: SignalScoutRunSummary | null
    /** This scout's runs in the window, oldest first (timeline order). */
    runs: SignalScoutRunSummary[]
}

function emptyRollup(): ScoutRollup {
    return {
        runCount: 0,
        completedCount: 0,
        failedCount: 0,
        emittedCount: 0,
        authoredReportIds: new Set(),
        editedReportIds: new Set(),
        latestRun: null,
        runningRun: null,
        runs: [],
    }
}

/**
 * Client-side rollup over the recent fleet runs, keyed by skill_name. The runs
 * endpoint has no per-scout filter or aggregate stats yet and caps at 100 rows,
 * so these numbers describe "the recent window we can see", not all time.
 */
export function computeScoutRollups(runs: SignalScoutRunSummary[]): Map<string, ScoutRollup> {
    const rollups = new Map<string, ScoutRollup>()
    for (const run of runs) {
        let rollup = rollups.get(run.skill_name)
        if (!rollup) {
            rollup = emptyRollup()
            rollups.set(run.skill_name, rollup)
        }
        rollup.runCount += 1
        const status = normalizeRunStatus(run.status)
        if (status === 'completed') {
            rollup.completedCount += 1
        }
        if (status === 'failed') {
            rollup.failedCount += 1
        }
        rollup.emittedCount += run.emitted_count ?? 0
        for (const reportId of run.emitted_report_ids ?? []) {
            rollup.authoredReportIds.add(reportId)
        }
        for (const reportId of run.edited_report_ids ?? []) {
            rollup.editedReportIds.add(reportId)
        }
        rollup.runs.push(run)
        const startedAt = run.started_at ? new Date(run.started_at).getTime() : 0
        const latestStartedAt = rollup.latestRun?.started_at ? new Date(rollup.latestRun.started_at).getTime() : -1
        if (startedAt > latestStartedAt) {
            rollup.latestRun = run
        }
        if (status === 'running' && !rollup.runningRun) {
            rollup.runningRun = run
        }
    }
    for (const rollup of rollups.values()) {
        rollup.runs.sort((a, b) => {
            const aStarted = a.started_at ? new Date(a.started_at).getTime() : 0
            const bStarted = b.started_at ? new Date(b.started_at).getTime() : 0
            return aStarted - bStarted
        })
    }
    return rollups
}

// ── Fleet summary ────────────────────────────────────────────────────────────

export interface FleetSummary {
    totalCount: number
    enabledCount: number
    runningCount: number
    emittedCount: number
    /** Distinct reports the fleet touched via the report channel (authored or edited) in the window,
     * deduped across runs, scouts, and channels — the report-side counterpart of `emittedCount`. */
    touchedReportCount: number
    /** Completed / (completed + failed) over the window, or null when no finished runs. */
    successRate: number | null
    /** Share of runs in the window that produced output — a signal OR report-channel activity — or null
     * when no runs. Mirrors the per-scout "Emitted" filter so the two surfaces agree. */
    emitRate: number | null
}

export function computeFleetSummary(configs: SignalScoutConfig[], rollups: Map<string, ScoutRollup>): FleetSummary {
    let runningCount = 0
    let emittedCount = 0
    let completedCount = 0
    let failedCount = 0
    let runCount = 0
    let emittedRunCount = 0
    const touchedReportIds = new Set<string>()
    for (const rollup of rollups.values()) {
        if (rollup.runningRun) {
            runningCount += 1
        }
        emittedCount += rollup.emittedCount
        completedCount += rollup.completedCount
        failedCount += rollup.failedCount
        runCount += rollup.runCount
        for (const reportId of rollup.authoredReportIds) {
            touchedReportIds.add(reportId)
        }
        for (const reportId of rollup.editedReportIds) {
            touchedReportIds.add(reportId)
        }
        for (const run of rollup.runs) {
            // Output = a weak finding OR report-channel activity, consistent with `runMatchesFilter('emitted')`
            // so the fleet emit rate and the per-scout "Emitted" chip never disagree about the same runs.
            if (runProducedOutput(run)) {
                emittedRunCount += 1
            }
        }
    }
    const finished = completedCount + failedCount
    return {
        totalCount: configs.length,
        enabledCount: configs.filter((config) => config.enabled).length,
        runningCount,
        emittedCount,
        touchedReportCount: touchedReportIds.size,
        successRate: finished > 0 ? completedCount / finished : null,
        emitRate: runCount > 0 ? emittedRunCount / runCount : null,
    }
}

// ── Run interval formatting ──────────────────────────────────────────────────

export interface RunIntervalOption {
    minutes: number
    label: string
}

export const RUN_INTERVAL_OPTIONS: RunIntervalOption[] = [
    { minutes: 30, label: 'Every 30 minutes' },
    { minutes: 60, label: 'Hourly' },
    { minutes: 120, label: 'Every 2 hours' },
    { minutes: 180, label: 'Every 3 hours' },
    { minutes: 360, label: 'Every 6 hours' },
    { minutes: 720, label: 'Every 12 hours' },
    { minutes: 1440, label: 'Daily' },
]

export const SCOUT_DAILY_AT_SCHEDULE_MODE = 'daily_at'
export const SCOUT_WEEKLY_ON_SCHEDULE_MODE = 'weekly_on'
export const SCOUT_CUSTOM_CRON_SCHEDULE_MODE = 'custom_cron'
export const DEFAULT_SCOUT_DAILY_TIME = '09:00'

/** Cron day-of-week numbers, offered from Monday so the working week reads first. */
export const SCOUT_WEEKDAY_OPTIONS: { value: string; label: string }[] = [
    { value: '1', label: 'Monday' },
    { value: '2', label: 'Tuesday' },
    { value: '3', label: 'Wednesday' },
    { value: '4', label: 'Thursday' },
    { value: '5', label: 'Friday' },
    { value: '6', label: 'Saturday' },
    { value: '0', label: 'Sunday' },
]

export const DEFAULT_SCOUT_WEEKLY_DAY = '1'

interface ScoutScheduleFields {
    run_interval_minutes: number
    run_cron_schedule?: string | null
}

export function getScoutScheduleMode(config: ScoutScheduleFields): string {
    if (!config.run_cron_schedule) {
        return String(config.run_interval_minutes)
    }
    if (dailyCronToTime(config.run_cron_schedule)) {
        return SCOUT_DAILY_AT_SCHEDULE_MODE
    }
    if (weeklyCronToDayTime(config.run_cron_schedule)) {
        return SCOUT_WEEKLY_ON_SCHEDULE_MODE
    }
    return SCOUT_CUSTOM_CRON_SCHEDULE_MODE
}

/**
 * `customCronEditable` says whether the surface can edit a raw expression. Where it cannot, the
 * custom option only appears for a config that already carries one, so the picker still shows what
 * the scout runs on.
 */
export function getScoutScheduleOptions(
    config: ScoutScheduleFields,
    { customCronEditable = false }: { customCronEditable?: boolean } = {}
): { value: string; label: string }[] {
    const options = RUN_INTERVAL_OPTIONS.map((option) => ({
        value: String(option.minutes),
        label: option.label,
    }))
    if (!RUN_INTERVAL_OPTIONS.some((option) => option.minutes === config.run_interval_minutes)) {
        options.push({
            value: String(config.run_interval_minutes),
            label: formatRunInterval(config.run_interval_minutes),
        })
    }
    options.push({ value: SCOUT_DAILY_AT_SCHEDULE_MODE, label: 'Daily at a set time' })
    options.push({ value: SCOUT_WEEKLY_ON_SCHEDULE_MODE, label: 'Weekly on a set day' })
    if (customCronEditable) {
        options.push({ value: SCOUT_CUSTOM_CRON_SCHEDULE_MODE, label: 'Custom cron' })
    } else if (getScoutScheduleMode(config) === SCOUT_CUSTOM_CRON_SCHEDULE_MODE) {
        options.push({ value: SCOUT_CUSTOM_CRON_SCHEDULE_MODE, label: `Custom (${config.run_cron_schedule})` })
    }
    return options
}

export function formatRunInterval(minutes: number): string {
    const preset = RUN_INTERVAL_OPTIONS.find((option) => option.minutes === minutes)
    if (preset) {
        return preset.label
    }
    if (minutes % 1440 === 0) {
        return `Every ${minutes / 1440} days`
    }
    if (minutes % 60 === 0) {
        return `Every ${minutes / 60} hours`
    }
    return `Every ${minutes} minutes`
}

/**
 * "30 9 * * *" → "09:30" when the cron is a plain daily time (the shape the settings form
 * writes). Anything richer (multiple slots, day-of-week restrictions) returns null and is
 * displayed as the raw expression instead.
 */
export function dailyCronToTime(cron: string | null | undefined): string | null {
    const match = cron?.trim().match(/^(\d{1,2}) (\d{1,2}) \* \* \*$/)
    if (!match) {
        return null
    }
    return `${match[2].padStart(2, '0')}:${match[1].padStart(2, '0')}`
}

/** "09:30" → "30 9 * * *" — the inverse of `dailyCronToTime` for the settings form's time picker. */
export function timeToDailyCron(time: string): string {
    const [hours, minutes] = time.split(':')
    return `${Number(minutes)} ${Number(hours)} * * *`
}

/**
 * "30 9 * * 4" → `{ day: '4', time: '09:30' }` when the cron is a plain weekly slot (the shape the
 * settings form writes). Multi-day and month-restricted expressions return null and are edited as
 * raw cron instead. Cron takes both 0 and 7 for Sunday; the dropdown offers 0, so 7 maps onto it.
 */
export function weeklyCronToDayTime(cron: string | null | undefined): { day: string; time: string } | null {
    const match = cron?.trim().match(/^(\d{1,2}) (\d{1,2}) \* \* ([0-7])$/)
    if (!match) {
        return null
    }
    return {
        day: match[3] === '7' ? '0' : match[3],
        time: `${match[2].padStart(2, '0')}:${match[1].padStart(2, '0')}`,
    }
}

/** `('4', '09:30')` → "30 9 * * 4" — the inverse of `weeklyCronToDayTime`. */
export function dayTimeToWeeklyCron(day: string, time: string): string {
    const [hours, minutes] = time.split(':')
    return `${Number(minutes)} ${Number(hours)} * * ${day}`
}

/** Longest cron expression the config API stores. */
export const SCOUT_CRON_MAX_LENGTH = 100

/** Shortest gap the scheduler allows between two runs, the same floor as `run_interval_minutes`. */
const SCOUT_CRON_MIN_GAP_MINUTES = 30

const CRON_MONTH_NAMES = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const CRON_DAY_NAMES = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']
const DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

type CronFieldParse = { kind: 'values'; values: number[] } | { kind: 'unmodeled' } | { kind: 'invalid' }

function cronFieldNumber(token: string, offset: number, names: string[] | undefined): number | null {
    const named = names?.indexOf(token.toLowerCase())
    if (named !== undefined && named >= 0) {
        return named + offset
    }
    return /^\d{1,2}$/.test(token) ? Number(token) : null
}

/**
 * The values a single cron field matches. `unmodeled` covers the syntax this check does not
 * model (`L`, `W`, `#`, `?`): the backend decides those, because a client that guessed would
 * refuse an expression the scheduler accepts.
 */
function parseCronField(field: string, min: number, max: number, names?: string[]): CronFieldParse {
    if (!field || /[^0-9a-zA-Z*/,-]/.test(field)) {
        return { kind: 'unmodeled' }
    }
    const values = new Set<number>()
    for (const part of field.split(',')) {
        const [spec, stepToken, ...extra] = part.split('/')
        if (extra.length > 0 || spec === undefined) {
            return { kind: 'invalid' }
        }
        const step = stepToken === undefined ? 1 : Number(stepToken)
        if (!Number.isInteger(step) || step < 1) {
            return { kind: 'invalid' }
        }
        let from = min
        let to = max
        if (spec !== '*') {
            const bounds = spec.split('-')
            if (bounds.length > 2) {
                return { kind: 'invalid' }
            }
            const parsed = bounds.map((token) => cronFieldNumber(token, min === 0 ? 0 : 1, names))
            if (parsed.some((value) => value === null || value < min || value > max)) {
                return { kind: 'invalid' }
            }
            from = parsed[0] as number
            // "5/10" is an open-ended step from 5, while a bare "5" is that one value.
            to = bounds.length === 2 ? (parsed[1] as number) : stepToken === undefined ? from : max
            // A wrapping range like "22-2" is an extension some parsers take and others reject.
            if (to < from) {
                return { kind: 'unmodeled' }
            }
        }
        for (let value = from; value <= to; value += step) {
            values.add(value)
        }
    }
    return { kind: 'values', values: [...values].sort((a, b) => a - b) }
}

/**
 * Why `expression` is not an acceptable scout cron schedule, or null when it is. Mirrors the four
 * rules the config API applies (`cron_schedule_error`) so the picker rejects a typo before the
 * PATCH. Expressions using syntax this check does not model pass and are left to the backend.
 */
export function scoutCronScheduleError(expression: string): string | null {
    const expr = expression.trim()
    if (expr.length > SCOUT_CRON_MAX_LENGTH) {
        return `Cron expressions must be ${SCOUT_CRON_MAX_LENGTH} characters or fewer.`
    }
    const fields = expr.split(/\s+/)
    const invalidShape = 'Enter a five-field cron expression, like 0 9 * * 1-5.'
    if (fields.length !== 5) {
        return invalidShape
    }
    const minutes = parseCronField(fields[0], 0, 59)
    const hours = parseCronField(fields[1], 0, 23)
    const daysOfMonth = parseCronField(fields[2], 1, 31)
    const months = parseCronField(fields[3], 1, 12, CRON_MONTH_NAMES)
    const daysOfWeek = parseCronField(fields[4], 0, 7, CRON_DAY_NAMES)
    const parsedFields = [minutes, hours, daysOfMonth, months, daysOfWeek]
    if (parsedFields.some((field) => field.kind === 'invalid')) {
        return invalidShape
    }
    // Cron matches day-of-month OR day-of-week, so a restricted weekday keeps the schedule alive
    // whatever the day-of-month field says.
    if (fields[2] !== '*' && fields[4] === '*' && daysOfMonth.kind === 'values' && months.kind === 'values') {
        const occurs = months.values.some((month) => daysOfMonth.values.some((day) => day <= DAYS_IN_MONTH[month - 1]))
        if (!occurs) {
            return 'This schedule never matches a real date. Check the day and month.'
        }
    }
    if (minutes.kind === 'values' && hours.kind === 'values') {
        const slots = hours.values.flatMap((hour) => minutes.values.map((minute) => hour * 60 + minute))
        const gaps = slots.slice(1).map((slot, index) => slot - slots[index])
        if (gaps.some((gap) => gap < SCOUT_CRON_MIN_GAP_MINUTES)) {
            return `Runs must be at least ${SCOUT_CRON_MIN_GAP_MINUTES} minutes apart.`
        }
    }
    return null
}

/** Short form for row badges: "hourly", "every 3h". */
export function formatRunIntervalShort(minutes: number): string {
    if (minutes === 60) {
        return 'hourly'
    }
    if (minutes === 1440) {
        return 'daily'
    }
    if (minutes % 1440 === 0) {
        return `every ${minutes / 1440}d`
    }
    if (minutes % 60 === 0) {
        return `every ${minutes / 60}h`
    }
    return `every ${minutes}m`
}

export function sortConfigsForDisplay(configs: SignalScoutConfig[]): SignalScoutConfig[] {
    return [...configs].sort((a, b) => {
        if (a.enabled !== b.enabled) {
            return a.enabled ? -1 : 1
        }
        return prettifyScoutSkillName(a.skill_name).localeCompare(prettifyScoutSkillName(b.skill_name))
    })
}

// The fixed chat-task prompt templates live server-side in
// products/signals/backend/scout_chat.py, keyed by `chat_type`.

/** Per-scout variant of the templated questions, scoped to one skill. */
export function buildScoutCheckinPrompt(skillName: string, displayName: string): string {
    return `How is my ${displayName} scout performing?

Use the exploring-scouts skill from the PostHog MCP to dig into the \`${skillName}\` scout on this project:

- Its config: enabled, cadence, dry-run posture
- Recent run history: successes, failures, timeouts, durations
- Signals it emitted recently and whether they look genuinely actionable
- Scratchpad memory the fleet holds that relates to this scout
- Whether its scope, thresholds, and schedule look right – suggest tuning if not

Lead with a short verdict. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, run emissions, scratchpad search).`
}
