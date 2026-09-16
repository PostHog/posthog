// One pull request's timeline on its own clock: time per state, grouped by who can move it on, and its
// milestones. Pure functions, so the pull request page's arithmetic is testable without a render.

import { dayjs } from 'lib/dayjs'

import { PRTimelineApi, PRTimelineSegmentKindEnumApi as Kind } from '../generated/api.schemas'
import { SEGMENT_LEGEND_GROUPS, secondsBetween } from './pullRequestDayView'

const MINUTE_MS = 60 * 1000

export interface StateTime {
    kind: Kind
    seconds: number
    /** Share of the whole timeline, 0 to 1. */
    share: number
}

export interface StateTimeGroup {
    label: string
    seconds: number
    share: number
    /** Longest first. */
    states: StateTime[]
}

export interface TimeInStates {
    wholeSeconds: number
    /** In legend order. A group with no time in any of its states drops out. */
    groups: StateTimeGroup[]
    longest: StateTime | null
}

export function timeInStates(pr: PRTimelineApi): TimeInStates {
    const segments = pr.segments
    const wholeSeconds = segments.length
        ? secondsBetween(segments[0].started_at, segments[segments.length - 1].ended_at)
        : 0
    const totals = new Map<Kind, number>()
    for (const segment of segments) {
        totals.set(segment.kind, (totals.get(segment.kind) ?? 0) + secondsBetween(segment.started_at, segment.ended_at))
    }
    const share = (seconds: number): number => (wholeSeconds > 0 ? seconds / wholeSeconds : 0)
    const groups = SEGMENT_LEGEND_GROUPS.map((group) => {
        const states = group.kinds
            .map((kind) => ({ kind, seconds: totals.get(kind) ?? 0 }))
            .filter((state) => state.seconds > 0)
            .map((state) => ({ ...state, share: share(state.seconds) }))
            .sort((a, b) => b.seconds - a.seconds)
        const seconds = states.reduce((sum, state) => sum + state.seconds, 0)
        return { label: group.label, seconds, share: share(seconds), states }
    }).filter((group) => group.states.length > 0)
    const longest = groups
        .flatMap((group) => group.states)
        .reduce<StateTime | null>((best, state) => (!best || state.seconds > best.seconds ? state : best), null)
    return { wholeSeconds, groups, longest }
}

export type MilestoneKind = 'start' | 'push' | 'out_of_queue' | 'merged' | 'closed'

export interface Milestone {
    kind: MilestoneKind
    at: string
    label: string
}

/** A push to the pull request, at the time its CI started. */
export interface TimelinePush {
    headSha: string
    at: string
}

/** An open draft's timeline starts when it opened. Any other starts at its last ready for review. */
export function timelineStartLabel(pr: PRTimelineApi): string {
    return pr.state === 'open' && pr.is_draft ? 'Opened' : 'Ready for review'
}

/** A push before the start is left out, because the track begins there. */
export function timelineMilestones(pr: PRTimelineApi, pushes: TimelinePush[]): Milestone[] {
    const segments = pr.segments
    if (segments.length === 0) {
        return []
    }
    const start = dayjs(segments[0].started_at)
    const end = dayjs(segments[segments.length - 1].ended_at)
    const milestones: Milestone[] = [{ kind: 'start', at: segments[0].started_at, label: timelineStartLabel(pr) }]
    for (const push of pushes) {
        const at = dayjs(push.at)
        if (at.isAfter(start) && !at.isAfter(end)) {
            milestones.push({ kind: 'push', at: push.at, label: `Push ${push.headSha.slice(0, 7)}` })
        }
    }
    for (const segment of segments) {
        if (segment.kind === Kind.OutOfMergeQueue) {
            milestones.push({ kind: 'out_of_queue', at: segment.started_at, label: 'Out of the merge queue' })
        }
    }
    if (pr.merged_at) {
        milestones.push({ kind: 'merged', at: pr.merged_at, label: 'Merged' })
    } else if (pr.state === 'closed') {
        milestones.push({ kind: 'closed', at: segments[segments.length - 1].ended_at, label: 'Closed' })
    }
    return milestones.sort((a, b) => dayjs(a.at).valueOf() - dayjs(b.at).valueOf())
}

export interface TrackAxis {
    fromMs: number
    toMs: number
}

/** One pull request has no sibling rows to line up with, so the axis is its own span, padded. */
export function trackAxis(pr: PRTimelineApi): TrackAxis {
    const segments = pr.segments
    const start = segments.length ? dayjs(segments[0].started_at).valueOf() : 0
    const end = segments.length ? dayjs(segments[segments.length - 1].ended_at).valueOf() : 0
    const pad = Math.max(0.02 * (end - start), 10 * MINUTE_MS)
    return { fromMs: start - pad, toMs: end + pad }
}
