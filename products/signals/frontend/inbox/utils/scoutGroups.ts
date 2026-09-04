import { describeCron, nextCronOccurrence } from 'lib/cron'
import { dayjs } from 'lib/dayjs'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { dailyCronToTime, formatRunIntervalShort, prettifyScoutSkillName, ScoutRollup } from './scoutRunsWindow'

/**
 * Where a scout sits in the roster, in the backend's own lifecycle vocabulary.
 *
 * `needs_you`, `off`, `dry_run` and `settling_in` each read straight off a stored field
 * (`status` / `emit` / `created_at`), so the roster groups by what the scheduler already decided
 * rather than by a second opinion computed in the UI. Only `working` vs `watching` is derived,
 * from whether the run window produced output.
 */
export type ScoutGroupKey = 'needs_you' | 'working' | 'watching' | 'dry_run' | 'settling_in' | 'off'

// Working leads: the roster's first job is to show the troop earning its keep, and trouble is
// legible wherever it sits — the group heading is the only red band on the page.
export const SCOUT_GROUP_ORDER: ScoutGroupKey[] = ['working', 'needs_you', 'watching', 'dry_run', 'settling_in', 'off']

export const SCOUT_GROUP_LABEL: Record<ScoutGroupKey, string> = {
    needs_you: 'Needs you',
    working: 'Working',
    watching: 'Watching',
    dry_run: 'Dry run',
    settling_in: 'Settling in',
    off: 'Off',
}

/** Matches `SignalScoutConfig.COLD_START_GRACE` — how long the sweep leaves a new scout alone. */
export const SCOUT_COLD_START_DAYS = 14

/**
 * A scout counts as producing when the window holds any output on either emit channel. Mirrors
 * `runProducedOutput` at rollup scope: a report-channel scout that authors reports without ever
 * emitting a weak finding is producing just as much as one that emits.
 */
function rollupProducedOutput(rollup: ScoutRollup | undefined): boolean {
    if (!rollup) {
        return false
    }
    return rollup.emittedCount > 0 || rollup.authoredReportIds.size > 0 || rollup.editedReportIds.size > 0
}

/**
 * When the scout's current cold-start grace began: creation, or the later re-enable if there was one.
 * `status_changed_at` is null on a freshly created scout and stamped on every later status change,
 * so it restarts the grace on a human re-enable, matching the sweep's own anchor.
 */
function coldStartAnchor(config: SignalScoutConfig): { at: string; reenabled: boolean } | null {
    const changedAt = config.status_changed_at
    if (changedAt && (!config.created_at || dayjs(changedAt).isAfter(dayjs(config.created_at)))) {
        return { at: changedAt, reenabled: true }
    }
    return config.created_at ? { at: config.created_at, reenabled: false } : null
}

function isWithinColdStart(config: SignalScoutConfig, now: Date): boolean {
    const anchor = coldStartAnchor(config)
    if (!anchor) {
        return false
    }
    return dayjs(now).diff(dayjs(anchor.at), 'day', true) < SCOUT_COLD_START_DAYS
}

export function scoutGroup(config: SignalScoutConfig, rollup: ScoutRollup | undefined, now: Date): ScoutGroupKey {
    // Status first: a system pause or warning outranks everything else the scout looks like, and a
    // human pause means "off" no matter what the scout was doing when it stopped.
    if (config.status === 'paused_by_system' || config.status === 'pending_pause') {
        return 'needs_you'
    }
    if (!config.enabled || config.status === 'paused_by_user') {
        return 'off'
    }
    if (!config.emit) {
        return 'dry_run'
    }
    if (isWithinColdStart(config, now)) {
        return 'settling_in'
    }
    return rollupProducedOutput(rollup) ? 'working' : 'watching'
}

/** A roster row: a scout config paired with the lifecycle group it currently sits in. */
export interface ScoutRosterRow {
    config: SignalScoutConfig
    group: ScoutGroupKey
}

/** A→Z by display name — the roster's default order and the Scout column's sort. */
export function compareScoutsByName(a: SignalScoutConfig, b: SignalScoutConfig): number {
    return prettifyScoutSkillName(a.skill_name).localeCompare(prettifyScoutSkillName(b.skill_name))
}

/** Longest run summary the roster shows before it stops being scannable. */
const SUBTITLE_MAX_CHARS = 110

function truncate(text: string): string {
    const collapsed = text.replace(/\s+/g, ' ').trim()
    return collapsed.length > SUBTITLE_MAX_CHARS ? `${collapsed.slice(0, SUBTITLE_MAX_CHARS - 1)}…` : collapsed
}

export type ScoutSubtitleTone = 'danger' | 'warning' | 'muted'

export interface ScoutSubtitle {
    text: string
    tone: ScoutSubtitleTone
}

/**
 * The one line under a scout's name. For a scout in trouble it states the reason the scheduler
 * recorded; for a healthy one it states what its last run actually looked at. Both are the reason
 * a roster row is enough on its own — a status colour alone tells you something is wrong but not
 * whether you can ignore it.
 */
export function scoutSubtitle(
    config: SignalScoutConfig,
    rollup: ScoutRollup | undefined,
    now: Date
): ScoutSubtitle | null {
    if (config.status === 'paused_by_system') {
        if (config.pause_reason === 'repeated_failures') {
            const streak = config.consecutive_failure_count
            return {
                text:
                    streak > 0
                        ? `Paused itself — ${streak} runs in a row failed`
                        : 'Paused itself — its runs kept failing',
                tone: 'danger',
            }
        }
        return {
            text:
                config.pause_reason === 'ignored'
                    ? 'Paused — nobody acted on its reports'
                    : 'Paused — it stopped surfacing anything',
            tone: 'danger',
        }
    }
    if (config.status === 'pending_pause') {
        return {
            text:
                config.pause_reason === 'ignored'
                    ? 'Pauses soon — nobody acted on its reports'
                    : 'Warned — nothing surfaced in the last two weeks',
            tone: 'warning',
        }
    }
    if (config.status === 'paused_by_user' || !config.enabled) {
        const changedAt = config.status_changed_at
        return {
            text: changedAt ? `Turned off ${dayjs(changedAt).format('MMM D, YYYY')}` : 'Turned off',
            tone: 'muted',
        }
    }
    if (!config.emit) {
        return { text: 'Runs and investigates, but files nothing', tone: 'muted' }
    }
    const anchor = coldStartAnchor(config)
    if (anchor && isWithinColdStart(config, now)) {
        // A re-enabled scout is months old; only a fresh one was "created" recently.
        const verb = anchor.reenabled ? 'Turned on' : 'Created'
        return { text: `${verb} ${dayjs(anchor.at).fromNow()}`, tone: 'muted' }
    }
    // What the last settled run actually checked. The scout writes this at close-out, so it reads
    // as work done rather than as an absence of output.
    const summary = rollup?.latestRun?.summary?.trim()
    if (summary) {
        return { text: truncate(summary), tone: 'muted' }
    }
    const description = config.description?.trim()
    return description ? { text: truncate(description), tone: 'muted' } : null
}

/**
 * When this scout is next due, or null when that can't be said: no run yet (the coordinator picks
 * it up on its next tick), a paused scout, or an expression that doesn't parse.
 *
 * A rolling cadence is arithmetic on `last_run_at`; a cron is resolved by `cron-parser` in
 * `timezone`, which must be the project's — that is what the coordinator evaluates cron schedules
 * in, so evaluating in the browser's would drift a scheduled run by the offset between them.
 */
export function nextRunAt(config: SignalScoutConfig, timezone: string, now: Date): Date | null {
    if (!config.enabled) {
        return null
    }
    if (config.run_cron_schedule) {
        return nextCronOccurrence(config.run_cron_schedule, timezone, now)
    }
    if (!config.last_run_at) {
        return null
    }
    return dayjs(config.last_run_at).add(config.run_interval_minutes, 'minutes').toDate()
}

/**
 * The cadence cell. A raw expression like `35 8 * * 1-5` is unreadable at a glance in a table, so
 * a cron is rendered in words; the plain daily case keeps its shorter, friendlier phrasing rather
 * than cronstrue's "At 09:00 AM".
 */
export function scoutCadenceLabel(config: SignalScoutConfig): string {
    if (config.run_cron_schedule) {
        const dailyTime = dailyCronToTime(config.run_cron_schedule)
        if (dailyTime) {
            return `daily at ${dailyTime}`
        }
        return describeCron(config.run_cron_schedule)?.toLowerCase() ?? config.run_cron_schedule
    }
    return formatRunIntervalShort(config.run_interval_minutes)
}
