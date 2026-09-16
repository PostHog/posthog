// The pull request page's timeline: the day view's states for one pull request on its own clock, with
// its milestones and where the time went, grouped by who can move it on.

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { PRTimelineApi } from '../generated/api.schemas'
import { compactAgeLabel, percent } from '../lib/format'
import { NIGHT_START_OFFSET_HOURS, SEGMENT_KIND_STYLES, segmentBackground } from '../lib/pullRequestDayView'
import {
    MilestoneKind,
    TimelinePush,
    timeInStates,
    timelineMilestones,
    timelineStartLabel,
    trackAxis,
} from '../lib/pullRequestTimeline'
import { PullRequestTimelineLegend } from './PullRequestTimelineLegend'

const HOUR_MS = 3600 * 1000
const TIME_FORMAT = 'ddd D MMM HH:mm'
const MAX_DAY_LABELS = 8

const MILESTONE_STYLES: Record<MilestoneKind, { glyph: string; className: string }> = {
    start: { glyph: '○', className: 'text-secondary' },
    push: { glyph: '▲', className: 'text-[var(--data-color-12)]' },
    out_of_queue: { glyph: '✕', className: 'text-danger' },
    merged: { glyph: '●', className: 'text-success' },
    closed: { glyph: '●', className: 'text-danger' },
}

function endLabel(pr: PRTimelineApi): string {
    return pr.merged_at ? 'Merged' : pr.state === 'closed' ? 'Closed' : 'Now'
}

export function PullRequestDeliveryTimeline({
    pr,
    pushes,
}: {
    /** A timeline with at least one segment. */
    pr: PRTimelineApi
    pushes: TimelinePush[]
}): JSX.Element {
    const axis = trackAxis(pr)
    const span = axis.toMs - axis.fromMs
    const clip = (ms: number): number => Math.min(Math.max(ms, axis.fromMs), axis.toMs)
    const left = (ms: number): string => `${(100 * (clip(ms) - axis.fromMs)) / span}%`
    const width = (fromMs: number, toMs: number): string => `${(100 * (clip(toMs) - clip(fromMs))) / span}%`

    const { wholeSeconds, groups, longest } = timeInStates(pr)
    const milestones = timelineMilestones(pr, pushes)
    const segments = pr.segments
    const start = segments[0].started_at
    const end = segments[segments.length - 1].ended_at
    const isOpen = pr.state === 'open'
    const labelStep = Math.ceil(axis.dayStarts.length / MAX_DAY_LABELS)
    const pushCount = milestones.filter((milestone) => milestone.kind === 'push').length

    return (
        <LemonCard
            hoverEffect={false}
            className="@container p-4"
            data-attr="engineering-analytics-pr-delivery-timeline"
        >
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-lg font-semibold tabular-nums">
                    {humanFriendlyDuration(wholeSeconds, { maxUnits: 2 })}
                </span>
                <span className="text-xs text-secondary">
                    {timelineStartLabel(pr).toLowerCase()} to {endLabel(pr).toLowerCase()}
                </span>
                {longest && (
                    <span className="flex items-center gap-1.5 text-xs text-secondary">
                        <span className="text-tertiary">·</span>
                        longest state
                        <span className="h-2.5 w-3 rounded-sm" style={segmentBackground(longest.kind)} />
                        <span className="font-semibold text-primary">{SEGMENT_KIND_STYLES[longest.kind].short}</span>
                        <span className="tabular-nums">{compactAgeLabel(longest.seconds)}</span>
                    </span>
                )}
            </div>

            <div className="relative h-4">
                {milestones.map((milestone, index) => {
                    const style = MILESTONE_STYLES[milestone.kind]
                    return (
                        <Tooltip
                            key={`${milestone.kind}-${index}`}
                            title={`${milestone.label} · ${dayjs(milestone.at).format(TIME_FORMAT)}`}
                        >
                            <span
                                className={cn('absolute top-0 -translate-x-1/2 text-[11px] leading-4', style.className)}
                                style={{ left: left(dayjs(milestone.at).valueOf()) }}
                            >
                                {style.glyph}
                            </span>
                        </Tooltip>
                    )
                })}
            </div>

            <div className="relative h-6 overflow-hidden rounded-sm">
                {axis.dayStarts.map((day) => {
                    const dayMs = day.valueOf()
                    const weekend = day.day() === 0 || day.day() === 6
                    return (
                        <div key={dayMs}>
                            {weekend && (
                                <div
                                    className="absolute inset-y-0 bg-fill-secondary"
                                    style={{ left: left(dayMs), width: width(dayMs, dayMs + 24 * HOUR_MS) }}
                                />
                            )}
                            <div
                                className="absolute inset-y-0 bg-fill-tertiary"
                                style={{
                                    left: left(dayMs + NIGHT_START_OFFSET_HOURS * HOUR_MS),
                                    width: width(dayMs + NIGHT_START_OFFSET_HOURS * HOUR_MS, dayMs + 24 * HOUR_MS),
                                }}
                            />
                            {dayMs > axis.fromMs && (
                                <div
                                    className="absolute inset-y-0 w-px bg-border-primary"
                                    style={{ left: left(dayMs) }}
                                />
                            )}
                        </div>
                    )
                })}
                {segments.map((segment, index) => {
                    const live = isOpen && index === segments.length - 1
                    const seconds = dayjs(segment.ended_at).diff(dayjs(segment.started_at), 'second')
                    return (
                        <Tooltip
                            key={segment.started_at}
                            title={`${SEGMENT_KIND_STYLES[segment.kind].label} · ${compactAgeLabel(seconds)}${live ? ' so far' : ''} · from ${dayjs(segment.started_at).format(TIME_FORMAT)}`}
                        >
                            <div
                                className="absolute inset-y-0.5 min-w-0.5 rounded-sm"
                                style={{
                                    left: left(dayjs(segment.started_at).valueOf()),
                                    width: width(
                                        dayjs(segment.started_at).valueOf(),
                                        dayjs(segment.ended_at).valueOf()
                                    ),
                                    ...segmentBackground(segment.kind),
                                }}
                            />
                        </Tooltip>
                    )
                })}
                {isOpen && (
                    <Tooltip title={`Now, ${dayjs(end).format(TIME_FORMAT)}`}>
                        <div
                            className="absolute inset-y-0 w-[3px] -translate-x-px rounded-sm bg-[var(--text-3000)]"
                            style={{ left: left(dayjs(end).valueOf()) }}
                        />
                    </Tooltip>
                )}
            </div>

            <div className="relative mt-1 h-4 overflow-hidden text-[10px] text-tertiary">
                {axis.dayStarts.map((day, index) =>
                    day.valueOf() > axis.fromMs && index % labelStep === 0 ? (
                        <span
                            key={day.valueOf()}
                            className="absolute pl-1 whitespace-nowrap"
                            style={{ left: left(day.valueOf()) }}
                        >
                            {day.format('ddd D MMM')}
                        </span>
                    ) : null
                )}
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 @min-[48rem]:grid-cols-[minmax(0,1fr)_16rem]">
                <div className="flex flex-col gap-3">
                    <h3 className="m-0 text-xs font-semibold text-secondary">Where the time went</h3>
                    {groups.map((group) => (
                        <div key={group.label} className="flex flex-col gap-1">
                            <div className="flex justify-between text-[11px] text-tertiary">
                                <span>{group.label}</span>
                                <span className="tabular-nums">{percent(group.share)}</span>
                            </div>
                            {group.states.map((state) => (
                                <div
                                    key={state.kind}
                                    className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)_3rem] items-center gap-2 text-xs"
                                >
                                    <span className="flex min-w-0 items-center gap-1.5">
                                        <span
                                            className="h-2.5 w-3 shrink-0 rounded-sm"
                                            style={segmentBackground(state.kind)}
                                        />
                                        <span className="truncate">{SEGMENT_KIND_STYLES[state.kind].short}</span>
                                    </span>
                                    <span className="h-1.5 overflow-hidden rounded-sm bg-fill-secondary">
                                        <span
                                            className="block h-full rounded-sm"
                                            style={{
                                                width: `${100 * state.share}%`,
                                                ...segmentBackground(state.kind),
                                            }}
                                        />
                                    </span>
                                    <span className="text-right tabular-nums">{compactAgeLabel(state.seconds)}</span>
                                </div>
                            ))}
                        </div>
                    ))}
                </div>
                <div className="flex flex-col gap-1 text-xs @min-[48rem]:border-l @min-[48rem]:border-primary @min-[48rem]:pl-4">
                    <h3 className="m-0 mb-1 text-xs font-semibold text-secondary">Milestones</h3>
                    <div className="flex justify-between gap-2">
                        <span className="text-secondary">{timelineStartLabel(pr)}</span>
                        <span className="font-semibold tabular-nums">{dayjs(start).format(TIME_FORMAT)}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                        <span className="text-secondary">{endLabel(pr)}</span>
                        <span className="font-semibold tabular-nums">{dayjs(end).format(TIME_FORMAT)}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                        <span className="text-secondary">Pushes after the start</span>
                        <span className="font-semibold tabular-nums">{pushCount}</span>
                    </div>
                </div>
            </div>

            <div className="mt-4">
                <PullRequestTimelineLegend />
            </div>
        </LemonCard>
    )
}
