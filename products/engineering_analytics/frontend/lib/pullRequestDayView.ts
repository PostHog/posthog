import { Dayjs, dayjs } from 'lib/dayjs'

import { PRTimelineApi, PRTimelineSegmentKindEnumApi as Kind } from '../generated/api.schemas'
import { dayStartAtOrBefore, longestState, secondsBetween, stateSeconds, timelineSpan } from './pullRequestTimeline'

export type DayViewAlignment = 'days' | 'weeks'

/** The longest axis the day view draws; longer bars end in a clip marker. */
export const MAX_AXIS_DAYS = 14

const HOUR_SECONDS = 3600
const DAY_HOURS = 24

/** Current states an open pull request's author can clear without waiting on anyone else. */
const AUTHOR_CAN_CLEAR: ReadonlySet<Kind> = new Set([
    Kind.OutOfMergeQueue,
    Kind.ApprovedNotEnqueued,
    Kind.ChangesRequested,
    Kind.RedFixedByPush,
    Kind.RedPassedOnRerun,
    Kind.RedNotProvable,
])

// Without synced reviews nobody is known to be blocking the PR, so it gets its own group.
const UNKNOWN_OWNER: ReadonlySet<Kind> = new Set([Kind.ReviewStateUnknown])

export interface DayViewRow {
    pr: PRTimelineApi
    isOpen: boolean
    /** Ready to merged, or ready to now for an open pull request. */
    lengthSeconds: number
    /** The last segment for an open pull request, the longest state for a merged one. */
    highlightKind: Kind
    highlightSeconds: number
}

export interface DayViewGroup {
    key: string
    label: string
    rows: DayViewRow[]
}

function toRow(pr: PRTimelineApi): DayViewRow | null {
    const current = pr.segments[pr.segments.length - 1]
    if (!current) {
        return null
    }
    const isOpen = pr.state === 'open'
    const longest = longestState(stateSeconds(pr))
    const highlight =
        isOpen || !longest
            ? { kind: current.kind, seconds: secondsBetween(current.started_at, current.ended_at) }
            : longest
    return {
        pr,
        isOpen,
        lengthSeconds: timelineSpan(pr).seconds,
        highlightKind: highlight.kind,
        highlightSeconds: highlight.seconds,
    }
}

const byHighlightDesc = (a: DayViewRow, b: DayViewRow): number => b.highlightSeconds - a.highlightSeconds
const byLengthDesc = (a: DayViewRow, b: DayViewRow): number => b.lengthSeconds - a.lengthSeconds

/** Most useful first: open work the author can move now, open work waiting on others, merged work
 *  from the longest wait down, then drafts. Empty groups are dropped; nothing else is hidden. */
export function groupTimelines(items: PRTimelineApi[]): DayViewGroup[] {
    const rows = items.map(toRow).filter((row): row is DayViewRow => row !== null)
    const openReady = rows.filter((row) => row.isOpen && !row.pr.is_draft)
    const merged = rows.filter((row) => row.pr.merged_at != null)
    const day = DAY_HOURS * HOUR_SECONDS
    const groups: DayViewGroup[] = [
        {
            key: 'open-author',
            label: "Open, the author's move",
            rows: openReady.filter((row) => AUTHOR_CAN_CLEAR.has(row.highlightKind)).sort(byHighlightDesc),
        },
        {
            key: 'open-others',
            label: 'Open, waiting on others',
            rows: openReady
                .filter((row) => !AUTHOR_CAN_CLEAR.has(row.highlightKind) && !UNKNOWN_OWNER.has(row.highlightKind))
                .sort(byHighlightDesc),
        },
        {
            key: 'open-unknown',
            label: 'Open, review state unknown',
            rows: openReady.filter((row) => UNKNOWN_OWNER.has(row.highlightKind)).sort(byHighlightDesc),
        },
        {
            key: 'merged-long',
            label: 'Merged, took over 2 days',
            rows: merged.filter((row) => row.lengthSeconds > 2 * day).sort(byLengthDesc),
        },
        {
            key: 'merged-medium',
            label: 'Merged, 1 to 2 days',
            rows: merged.filter((row) => row.lengthSeconds > day && row.lengthSeconds <= 2 * day).sort(byLengthDesc),
        },
        {
            key: 'merged-short',
            label: 'Merged, under a day',
            rows: merged.filter((row) => row.lengthSeconds <= day).sort(byLengthDesc),
        },
        {
            key: 'drafts',
            label: 'Open, still draft',
            rows: rows.filter((row) => row.isOpen && row.pr.is_draft).sort(byLengthDesc),
        },
    ]
    return groups.filter((group) => group.rows.length > 0)
}

/** Where a row's clock starts: 06:00 local on the day it went ready (the day before when it went
 *  ready in the small hours), or Monday 06:00 of that week so weekdays line up across rows. */
export function rowOrigin(startedAt: string, alignment: DayViewAlignment): Dayjs {
    const dayStart = dayStartAtOrBefore(dayjs(startedAt).valueOf())
    return alignment === 'weeks' ? dayStart.subtract((dayStart.day() + 6) % 7, 'day') : dayStart
}

export function hoursFromOrigin(origin: Dayjs, at: string): number {
    return dayjs(at).diff(origin, 'second') / HOUR_SECONDS
}

/** Days the axis spans: it fits 90% of the rows' ends, so the bulk fills the width. Capped at
 *  MAX_AXIS_DAYS; the weeks alignment rounds up to whole weeks. */
export function axisDays(items: PRTimelineApi[], alignment: DayViewAlignment): number {
    const ends = items
        .filter((pr) => pr.segments.length > 0)
        .map((pr) => hoursFromOrigin(rowOrigin(pr.started_at, alignment), timelineSpan(pr).endedAt))
        .sort((a, b) => a - b)
    if (ends.length === 0) {
        return 1
    }
    const p90 = ends[Math.floor(0.9 * (ends.length - 1))]
    const days = Math.min(MAX_AXIS_DAYS, Math.max(1, Math.ceil(p90 / DAY_HOURS)))
    return alignment === 'weeks' ? Math.min(MAX_AXIS_DAYS, Math.ceil(days / 7) * 7) : days
}

export interface RedTimeByCause {
    mergedCount: number
    /** Red seconds per merged pull request, per cause, in RED_KINDS order. */
    secondsPerMergedPr: { kind: Kind; seconds: number }[]
    totalSecondsPerMergedPr: number
}
