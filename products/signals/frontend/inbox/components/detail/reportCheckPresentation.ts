import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportArtefact } from '../../types'
import { prettifyScoutSkillName } from '../../utils/scoutRunsWindow'
import type {
    CheckCancelledContent,
    CheckExpiredContent,
    CheckLifecycleContent,
    CheckResultContent,
    CheckScheduledContent,
} from './artefactTypes'

/** Rows past this many collapse the ones that only record how a check ended. */
const REPORT_CHECK_ROWS_BEFORE_COLLAPSE = 4

/** Mirrors `report_check_agent.FALLBACK_CHECK_SKILL_NAME`'s role: the lane a check with no scout runs on. */
const FALLBACK_LANE_LABEL = 'The follow-up scout'

export interface ReportCheckRowData {
    check: SignalReportCheckApi
    tag: { label: string; type: LemonTagType }
    /** The line under the title: when it runs, who runs it, or what the verdict said. */
    detail: string
    /** A check a person stopped. The row renders faded with a struck title. */
    cancelled: boolean
    /** Open checks can still be stopped; terminal ones cannot. */
    cancellable: boolean
}

/** A soak window in the words the copy needs: "7 days", "36 hours", "90 minutes". */
function soakLabel(minutes: number): string {
    if (minutes % 1440 === 0) {
        const days = minutes / 1440
        return `${days} ${days === 1 ? 'day' : 'days'}`
    }
    if (minutes % 60 === 0) {
        const hours = minutes / 60
        return `${hours} ${hours === 1 ? 'hour' : 'hours'}`
    }
    return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`
}

/** Which scout answers an `agent` check. A `metric_threshold` check has no lane: the coordinator measures it. */
function scoutLaneLabel(kind: string | undefined, skillName: string | null | undefined): string | null {
    if (kind !== 'agent') {
        return null
    }
    return skillName ? prettifyScoutSkillName(skillName) : FALLBACK_LANE_LABEL
}

/** The lane as a clause: "Error tracking scout runs it", or "The follow-up scout runs it". */
function laneRunsIt(kind: string | undefined, skillName: string | null | undefined): string | null {
    if (kind !== 'agent') {
        return null
    }
    return skillName ? `${prettifyScoutSkillName(skillName)} scout runs it` : `${FALLBACK_LANE_LABEL} runs it`
}

function laneLabel(check: SignalReportCheckApi): string | null {
    return scoutLaneLabel(check.kind, 'skill_name' in check.config ? check.config.skill_name : null)
}

function shortDate(value: string): string {
    return dayjs(value).format('MMM D')
}

/** Mirrors `SignalReportCheck.OPEN_STATUSES`: the two statuses a check can still produce a verdict from. */
const OPEN_STATUSES = ['pending', 'active']

/** A check is running when its scout run is open; dispatch also pushes `next_run_at` out to the result window. */
function isRunning(check: SignalReportCheckApi): boolean {
    return check.status === 'active' && !!check.dispatched_at
}

/** A check that ended without a verdict. Nothing is owed on it, so it is the first row to fold away. */
function isRetired(check: SignalReportCheckApi): boolean {
    return check.status === 'expired' || check.status === 'cancelled'
}

function joinDetail(parts: (string | null | undefined)[]): string {
    return parts.filter((part): part is string => !!part).join(' · ')
}

function openCheckRow(check: SignalReportCheckApi): Pick<ReportCheckRowData, 'tag' | 'detail'> {
    const lane = laneLabel(check)

    if (check.status === 'pending') {
        const start = check.soak_minutes
            ? `Starts ${soakLabel(check.soak_minutes)} after this report is resolved`
            : 'Starts when this report is resolved'
        return { tag: { label: 'Waiting', type: 'muted' }, detail: joinDetail([start, lane && `${lane} runs it`]) }
    }

    if (isRunning(check)) {
        const startedAgo = dayjs(check.dispatched_at).fromNow()
        return {
            tag: { label: 'Running', type: 'primary' },
            detail: lane ? `${lane} started ${startedAgo}` : `Started ${startedAgo}`,
        }
    }

    const work = lane ? `${lane} re-probes the claim` : 'Measures the metric again'
    const runs = check.runs_remaining > 1 ? `${check.runs_remaining} runs left` : '1 run'
    return {
        tag: { label: `Runs ${shortDate(check.next_run_at)}`, type: 'primary' },
        detail: joinDetail([work, runs, check.soak_minutes ? `${soakLabel(check.soak_minutes)} soak` : null]),
    }
}

function terminalCheckRow(
    check: SignalReportCheckApi,
    explanation: string | undefined
): Pick<ReportCheckRowData, 'tag' | 'detail'> {
    const ranOn = check.last_run_at ? shortDate(check.last_run_at) : null

    switch (check.status) {
        case 'passed':
            return { tag: { label: 'Still holds', type: 'success' }, detail: joinDetail([ranOn, explanation]) }
        case 'failed':
            return { tag: { label: 'No longer holds', type: 'danger' }, detail: joinDetail([ranOn, explanation]) }
        case 'errored':
            return {
                tag: { label: "Couldn't measure", type: 'warning' },
                detail: joinDetail([`Gave up after ${check.consecutive_errors} tries`, ranOn, explanation]),
            }
        case 'cancelled':
            return { tag: { label: 'Cancelled', type: 'muted' }, detail: `Stopped ${shortDate(check.updated_at)}` }
    }

    // Expired: the sweep retired the check when its horizon passed. It may still have run first,
    // because a check that errors its way to its expiry lands here rather than in `errored`.
    return check.last_run_at
        ? {
              tag: { label: 'Expired', type: 'muted' },
              detail: joinDetail([`Last ran ${ranOn}`, `expired ${shortDate(check.updated_at)}`]),
          }
        : {
              tag: { label: 'Never ran', type: 'muted' },
              detail: `Expired ${shortDate(check.updated_at)} before it ever ran`,
          }
}

/**
 * Rank a check for the rail: what is happening now, then what is about to, then what is waiting on
 * the resolve, then the verdicts, and last the checks that ended without one. Scheduled checks sort
 * by their run date and finished ones by how recently they spoke, so the row a reader wants leads
 * each band. Retired rows trail the verdicts because they are also the ones that fold away.
 */
function orderingKey(check: SignalReportCheckApi): [number, number] {
    if (isRunning(check)) {
        return [0, 0]
    }
    if (check.status === 'active') {
        return [1, dayjs(check.next_run_at).valueOf()]
    }
    if (check.status === 'pending') {
        return [2, dayjs(check.next_run_at).valueOf()]
    }
    if (isRetired(check)) {
        return [4, -dayjs(check.updated_at).valueOf()]
    }
    return [3, -dayjs(check.last_run_at ?? check.updated_at).valueOf()]
}

/** The newest `check_result` explanation per check, so a terminal row can say what the verdict found. */
export function latestCheckExplanations(artefacts: SignalReportArtefact[]): Map<string, string> {
    const explanations = new Map<string, string>()
    // Artefacts arrive newest first, so the first entry seen for a check is the one that stands.
    for (const artefact of artefacts) {
        if (artefact.type !== 'check_result') {
            continue
        }
        const content = artefact.content as CheckResultContent
        if (content?.check_id && content.explanation?.trim() && !explanations.has(content.check_id)) {
            explanations.set(content.check_id, content.explanation.trim())
        }
    }
    return explanations
}

export function buildReportCheckRows(
    checks: SignalReportCheckApi[],
    explanations: Map<string, string>
): ReportCheckRowData[] {
    return [...checks]
        .sort((a, b) => {
            const [bandA, withinA] = orderingKey(a)
            const [bandB, withinB] = orderingKey(b)
            return bandA - bandB || withinA - withinB
        })
        .map((check) => {
            const open = OPEN_STATUSES.includes(check.status)
            return {
                check,
                ...(open ? openCheckRow(check) : terminalCheckRow(check, explanations.get(check.id))),
                cancelled: check.status === 'cancelled',
                cancellable: open,
            }
        })
}

/**
 * Split the rows into the ones the section always shows and the ones behind "Show more". Only rows
 * that record how a check ended without a verdict are foldable, so a long history never buries a
 * check that is still running.
 */
export function splitReportCheckRows(rows: ReportCheckRowData[]): {
    visible: ReportCheckRowData[]
    hidden: ReportCheckRowData[]
} {
    const visible: ReportCheckRowData[] = []
    const hidden: ReportCheckRowData[] = []
    for (const row of rows) {
        if (isRetired(row.check) && visible.length >= REPORT_CHECK_ROWS_BEFORE_COLLAPSE) {
            hidden.push(row)
        } else {
            visible.push(row)
        }
    }
    return { visible, hidden }
}

/** The section header's right-hand summary: how many checks, and then the next thing that happens. */
export function reportChecksMeta(checks: SignalReportCheckApi[]): string {
    if (checks.some(isRunning)) {
        // A dispatched check's `next_run_at` is the deadline its run has to answer by, so quoting it
        // as the next date would promise a run that is already under way.
        return `${checks.length} · running now`
    }
    const scheduled = checks
        .filter((check) => check.status === 'active')
        .map((check) => dayjs(check.next_run_at))
        .sort((a, b) => a.valueOf() - b.valueOf())
    if (scheduled.length > 0) {
        return `${checks.length} · next ${scheduled[0].format('MMM D')}`
    }
    if (checks.some((check) => check.status === 'pending')) {
        return `${checks.length} · waiting for resolve`
    }
    return `${checks.length} · all done`
}

// ── Lifecycle log entries ────────────────────────────────────────────────────────────────────

/** How a check's activity entry reads: the tag beside its header, and the line under its title. */
export interface CheckLifecycleEntry {
    tag: { label: string; type: LemonTagType }
    detail: string
}

const CHECK_CANCELLED_REASONS: Record<string, string> = {
    stopped_by_person: 'Stopped from the report before it could settle',
    stopped_by_scout: 'A scout run stopped it before it could settle',
    replaced_by_research: 'Replaced when research re-ran on this report and wrote a new check',
}

/**
 * The entry written when a check is attached. A check on an open report has no date to give yet,
 * so it says what starts the clock instead of naming a day it cannot keep.
 */
export function checkScheduledEntry(content: CheckScheduledContent): CheckLifecycleEntry {
    const lane = laneRunsIt(content.kind, content.skill_name)
    const runs = content.runs && content.runs > 1 ? `${content.runs} runs` : null

    if (content.arms_on_resolve) {
        const start = content.soak_minutes
            ? `Starts ${soakLabel(content.soak_minutes)} after this report is resolved`
            : 'Starts when this report is resolved'
        return {
            tag: { label: 'Waiting for resolve', type: 'muted' },
            detail: joinDetail([start, lane, runs]),
        }
    }

    return {
        tag: {
            label: content.next_run_at ? `Runs ${shortDate(content.next_run_at)}` : 'Scheduled',
            type: 'primary',
        },
        detail: joinDetail([lane ?? 'The coordinator measures it', runs]),
    }
}

/** The entry written when the sweep retires a check at its horizon. */
export function checkExpiredEntry(content: CheckExpiredContent): CheckLifecycleEntry {
    if (!content.last_run_at) {
        return {
            tag: { label: 'Never ran', type: 'muted' },
            detail: 'Retired at its horizon without running, so this claim was never re-measured',
        }
    }
    return {
        tag: { label: 'Expired', type: 'muted' },
        detail: `Last ran ${shortDate(content.last_run_at)} · retired at its horizon before it settled`,
    }
}

/** The entry written when a person, a scout run, or a re-research pass stops a check. */
export function checkCancelledEntry(content: CheckCancelledContent): CheckLifecycleEntry {
    return {
        tag: { label: 'Cancelled', type: 'muted' },
        detail: CHECK_CANCELLED_REASONS[content.reason ?? ''] ?? 'Stopped before it could settle',
    }
}

/** Which builder reads each lifecycle entry, so the renderer needs one arm rather than three. */
export const CHECK_LIFECYCLE_ENTRIES: Record<string, (content: CheckLifecycleContent) => CheckLifecycleEntry> = {
    check_scheduled: checkScheduledEntry,
    check_expired: checkExpiredEntry,
    check_cancelled: checkCancelledEntry,
}
