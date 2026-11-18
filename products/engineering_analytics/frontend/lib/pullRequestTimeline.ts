import type { CSSProperties } from 'react'

import { Dayjs, dayjs } from 'lib/dayjs'

import { PRTimelineApi, PRTimelineSegmentKindEnumApi as Kind } from '../generated/api.schemas'

export const TIMELINE_TIME_FORMAT = 'ddd D MMM HH:mm'
/** Rows start at this local hour, so a working day reads left to right without a split night. */
export const DAY_START_HOUR = 6
export const NIGHT_START_HOUR = 22

const MINUTE_MS = 60 * 1000

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

export function secondsBetween(start: string, end: string): number {
    return dayjs(end).diff(dayjs(start), 'second')
}

export interface TimelineSpan {
    startedAt: string
    endedAt: string
    seconds: number
}

/** A timeline with no segments spans zero seconds at its start. */
export function timelineSpan(pr: PRTimelineApi): TimelineSpan {
    const segments = pr.segments
    const startedAt = segments.length ? segments[0].started_at : pr.started_at
    const endedAt = segments.length ? segments[segments.length - 1].ended_at : startedAt
    return { startedAt, endedAt, seconds: secondsBetween(startedAt, endedAt) }
}

export interface StateTime {
    kind: Kind
    seconds: number
}

export function stateSeconds(pr: PRTimelineApi): StateTime[] {
    const totals = new Map<Kind, number>()
    for (const segment of pr.segments) {
        totals.set(segment.kind, (totals.get(segment.kind) ?? 0) + secondsBetween(segment.started_at, segment.ended_at))
    }
    return [...totals].map(([kind, seconds]) => ({ kind, seconds }))
}

/** On a tie, the state that appeared first. */
export function longestState(states: StateTime[]): StateTime | null {
    return states.reduce<StateTime | null>(
        (best, state) => (!best || state.seconds > best.seconds ? state : best),
        null
    )
}

export interface StateShare extends StateTime {
    share: number
}

export interface StateTimeGroup {
    label: string
    seconds: number
    share: number
    states: StateShare[]
}

export interface TimeInStates {
    wholeSeconds: number
    groups: StateTimeGroup[]
    longest: StateShare | null
}

export function timeInStates(pr: PRTimelineApi): TimeInStates {
    const wholeSeconds = timelineSpan(pr).seconds
    const states = stateSeconds(pr)
    const totals = new Map(states.map((state) => [state.kind, state.seconds]))
    const share = (seconds: number): number => (wholeSeconds > 0 ? seconds / wholeSeconds : 0)
    const groups = SEGMENT_LEGEND_GROUPS.map((group) => {
        const groupStates = group.kinds
            .map((kind) => ({ kind, seconds: totals.get(kind) ?? 0 }))
            .filter((state) => state.seconds > 0)
            .map((state) => ({ ...state, share: share(state.seconds) }))
            .sort((a, b) => b.seconds - a.seconds)
        const seconds = groupStates.reduce((sum, state) => sum + state.seconds, 0)
        return { label: group.label, seconds, share: share(seconds), states: groupStates }
    }).filter((group) => group.states.length > 0)
    const longest = longestState(states)
    return { wholeSeconds, groups, longest: longest && { ...longest, share: share(longest.seconds) } }
}

export type MilestoneKind = 'start' | 'push' | 'out_of_queue' | 'merged' | 'closed'

export interface Milestone {
    kind: MilestoneKind
    at: string
    label: string
}

/** A start at creation means no ready event: opened ready, a draft, or issue events not synced. */
export function timelineStartLabel(pr: PRTimelineApi): string {
    return dayjs(pr.started_at).isSame(pr.created_at) ? 'Opened' : 'Ready for review'
}

export function timelineMilestones(pr: PRTimelineApi): Milestone[] {
    const { startedAt, endedAt } = timelineSpan(pr)
    const start = dayjs(startedAt)
    const end = dayjs(endedAt)
    const milestones: Milestone[] = [{ kind: 'start', at: startedAt, label: timelineStartLabel(pr) }]
    for (const push of pr.pushes) {
        const at = dayjs(push.pushed_at)
        if (at.isAfter(start) && !at.isAfter(end)) {
            milestones.push({ kind: 'push', at: push.pushed_at, label: `Push ${push.head_sha.slice(0, 7)}` })
        }
    }
    for (const segment of pr.segments) {
        if (segment.kind === Kind.OutOfMergeQueue) {
            milestones.push({ kind: 'out_of_queue', at: segment.started_at, label: 'Out of the merge queue' })
        }
    }
    if (pr.merged_at) {
        milestones.push({ kind: 'merged', at: pr.merged_at, label: 'Merged' })
    } else if (pr.state === 'closed') {
        milestones.push({ kind: 'closed', at: endedAt, label: 'Closed' })
    }
    return milestones.sort((a, b) => dayjs(a.at).valueOf() - dayjs(b.at).valueOf())
}

/** DAY_START_HOUR local on the day `ms` falls in, or on the day before when `ms` is in the small hours. */
export function dayStartAtOrBefore(ms: number): Dayjs {
    return dayjs(ms).subtract(DAY_START_HOUR, 'hour').startOf('day').add(DAY_START_HOUR, 'hour')
}

export interface TimeAxis {
    fromMs: number
    toMs: number
    /** The first day starts at or before fromMs, so a night that began before fromMs still shades its start. */
    dayStarts: Dayjs[]
    /** Percent of the axis from its start, clipped to the axis. */
    position: (ms: number) => string
    width: (startMs: number, endMs: number) => string
}

export function timeAxis(fromMs: number, toMs: number): TimeAxis {
    const span = toMs - fromMs
    const clip = (ms: number): number => Math.min(Math.max(ms, fromMs), toMs)
    const dayStarts: Dayjs[] = []
    for (let day = dayStartAtOrBefore(fromMs); day.valueOf() < toMs; day = day.add(1, 'day')) {
        dayStarts.push(day)
    }
    return {
        fromMs,
        toMs,
        dayStarts,
        position: (ms) => `${(100 * (clip(ms) - fromMs)) / span}%`,
        width: (startMs, endMs) => `${(100 * (clip(endMs) - clip(startMs))) / span}%`,
    }
}

/** The span padded on both sides, so its start and end markers stay inside the track. */
export function paddedAxis(span: TimelineSpan): TimeAxis {
    const start = dayjs(span.startedAt).valueOf()
    const end = dayjs(span.endedAt).valueOf()
    const pad = Math.max(0.02 * (end - start), 10 * MINUTE_MS)
    return timeAxis(start - pad, end + pad)
}
