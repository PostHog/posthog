// The author page's day view: every pull request on a shared clock, grouped by what is most useful
// to look at first. Pure functions, so the grouping and the axis fit are testable without a render.

import type { CSSProperties } from 'react'

import { Dayjs, dayjs } from 'lib/dayjs'

import { PRTimelineApi, PRTimelineSegmentKindEnumApi as Kind } from '../generated/api.schemas'

export type DayViewAlignment = 'days' | 'weeks'

/** The longest axis the day view draws; longer bars end in a clip marker. */
export const MAX_AXIS_DAYS = 14
/** Rows start at this local hour, so a working day reads left to right without a split night. */
export const DAY_START_HOUR = 6
/** Night band, in hours after the row origin: 22:00 to 06:00. */
export const NIGHT_START_OFFSET_HOURS = 16

const HOUR_SECONDS = 3600
const DAY_HOURS = 24

export interface SegmentKindStyle {
    label: string
    short: string
    color: string
    pattern?: 'stripes' | 'dots' | 'dashes'
}

export const SEGMENT_KIND_STYLES: Record<Kind, SegmentKindStyle> = {
    [Kind.WaitingForReview]: {
        label: 'Waiting for approval',
        short: 'review wait',
        color: 'var(--data-color-3)',
    },
    [Kind.ChangesRequested]: {
        label: 'Changes requested, no push yet',
        short: 'changes requested',
        color: 'var(--data-color-1)',
    },
    [Kind.ApprovedNotEnqueued]: {
        label: 'Approved, nothing failing or running, not in the merge queue',
        short: 'approved, not enqueued',
        color: 'var(--data-color-1)',
        pattern: 'stripes',
    },
    [Kind.RedFixedByPush]: {
        label: 'Red until the next push',
        short: 'red, fixed by a push',
        color: 'var(--data-color-1)',
        pattern: 'dots',
    },
    [Kind.CiRunning]: { label: 'CI running', short: 'CI running', color: 'var(--data-color-12)' },
    [Kind.MergeQueue]: {
        label: 'In the merge queue, restarts included',
        short: 'merge queue',
        color: 'var(--data-color-10)',
    },
    [Kind.OutOfMergeQueue]: {
        label: 'Out of the merge queue, not added back',
        short: 'out of the queue',
        color: 'var(--data-color-10)',
        pattern: 'stripes',
    },
    [Kind.RedPassedOnRerun]: {
        label: 'Red, passed on a re-run of the same commit',
        short: 'red, flake',
        color: 'var(--data-color-13)',
    },
    [Kind.RedMasterBroken]: {
        label: 'Red, the same job was failing on the default branch',
        short: 'red, master broken',
        color: 'var(--data-color-2)',
    },
    [Kind.RedNotProvable]: {
        label: 'Red, cause not provable',
        short: 'red, cause unknown',
        color: 'var(--muted)',
        pattern: 'dots',
    },
    [Kind.ReviewStateUnknown]: {
        label: 'Review state unknown, reviews are not synced',
        short: 'review state unknown',
        color: 'var(--muted)',
        pattern: 'stripes',
    },
    [Kind.Draft]: {
        label: 'Draft, not ready for review yet',
        short: 'draft',
        color: 'var(--muted)',
        pattern: 'dashes',
    },
}

/** The fill for a segment kind. Patterns separate kinds that share a color, so the author's own states
 *  and the grey "unknown" states stay apart without extra hues. */
export function segmentBackground(kind: Kind): CSSProperties {
    const { color, pattern } = SEGMENT_KIND_STYLES[kind]
    switch (pattern) {
        case 'stripes':
            return {
                backgroundColor: color,
                backgroundImage: 'repeating-linear-gradient(135deg, rgb(255 255 255 / 45%) 0 2px, transparent 2px 5px)',
            }
        case 'dots':
            return {
                backgroundColor: color,
                backgroundImage: 'radial-gradient(rgb(0 0 0 / 35%) 1px, transparent 1.2px)',
                backgroundSize: '4px 4px',
            }
        case 'dashes':
            return { backgroundImage: `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 7px)` }
        default:
            return { backgroundColor: color }
    }
}

/** Legend order: who can move the pull request out of each state. */
export const SEGMENT_LEGEND_GROUPS: { label: string; kinds: Kind[] }[] = [
    { label: 'Reviewers', kinds: [Kind.WaitingForReview] },
    { label: 'Author', kinds: [Kind.ChangesRequested, Kind.ApprovedNotEnqueued, Kind.RedFixedByPush] },
    {
        label: 'CI and merge queue',
        kinds: [Kind.CiRunning, Kind.MergeQueue, Kind.OutOfMergeQueue, Kind.RedPassedOnRerun, Kind.RedMasterBroken],
    },
    { label: 'Other', kinds: [Kind.RedNotProvable, Kind.ReviewStateUnknown, Kind.Draft] },
]

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

export const RED_KINDS: Kind[] = [Kind.RedFixedByPush, Kind.RedPassedOnRerun, Kind.RedMasterBroken, Kind.RedNotProvable]

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

export function secondsBetween(start: string, end: string): number {
    return dayjs(end).diff(dayjs(start), 'second')
}

function toRow(pr: PRTimelineApi): DayViewRow | null {
    const segments = pr.segments
    if (segments.length === 0) {
        return null
    }
    const isOpen = pr.state === 'open'
    const last = segments[segments.length - 1]
    let highlightKind = last.kind
    let highlightSeconds = secondsBetween(last.started_at, last.ended_at)
    if (!isOpen) {
        const totals = new Map<Kind, number>()
        for (const segment of segments) {
            totals.set(
                segment.kind,
                (totals.get(segment.kind) ?? 0) + secondsBetween(segment.started_at, segment.ended_at)
            )
        }
        ;[highlightKind, highlightSeconds] = [...totals.entries()].reduce((best, entry) =>
            entry[1] > best[1] ? entry : best
        )
    }
    return {
        pr,
        isOpen,
        lengthSeconds: secondsBetween(segments[0].started_at, last.ended_at),
        highlightKind,
        highlightSeconds,
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
    const shifted = dayjs(startedAt).subtract(DAY_START_HOUR, 'hour')
    const dayStart = shifted.startOf('day')
    const origin = alignment === 'weeks' ? dayStart.subtract((dayStart.day() + 6) % 7, 'day') : dayStart
    return origin.add(DAY_START_HOUR, 'hour')
}

/** 06:00 local on each day from the one at or before fromMs up to toMs, so a night that began before
 *  fromMs still shades its start. */
export function dayStartsBetween(fromMs: number, toMs: number): Dayjs[] {
    const days: Dayjs[] = []
    for (let day = rowOrigin(dayjs(fromMs).toISOString(), 'days'); day.valueOf() < toMs; day = day.add(1, 'day')) {
        days.push(day)
    }
    return days
}

export function hoursFromOrigin(origin: Dayjs, at: string): number {
    return dayjs(at).diff(origin, 'second') / HOUR_SECONDS
}

/** Days the axis spans: it fits 90% of the rows' ends, so the bulk fills the width. Capped at
 *  MAX_AXIS_DAYS; the weeks alignment rounds up to whole weeks. */
export function axisDays(items: PRTimelineApi[], alignment: DayViewAlignment): number {
    const ends = items
        .filter((pr) => pr.segments.length > 0)
        .map((pr) => hoursFromOrigin(rowOrigin(pr.started_at, alignment), pr.segments[pr.segments.length - 1].ended_at))
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

/** Red time on the merged pull requests, split by what turned the check green. */
export function redTimeByCause(items: PRTimelineApi[]): RedTimeByCause {
    const merged = items.filter((pr) => pr.merged_at != null)
    const totals = new Map<Kind, number>(RED_KINDS.map((kind) => [kind, 0]))
    for (const pr of merged) {
        for (const segment of pr.segments) {
            if (totals.has(segment.kind)) {
                totals.set(
                    segment.kind,
                    (totals.get(segment.kind) ?? 0) + secondsBetween(segment.started_at, segment.ended_at)
                )
            }
        }
    }
    const perPr = RED_KINDS.map((kind) => ({
        kind,
        seconds: merged.length ? (totals.get(kind) ?? 0) / merged.length : 0,
    }))
    return {
        mergedCount: merged.length,
        secondsPerMergedPr: perPr,
        totalSecondsPerMergedPr: perPr.reduce((sum, entry) => sum + entry.seconds, 0),
    }
}
