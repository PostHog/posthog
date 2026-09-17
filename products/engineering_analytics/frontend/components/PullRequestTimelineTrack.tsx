import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { PRTimelineApi } from '../generated/api.schemas'
import { compactAgeLabel } from '../lib/format'
import {
    NIGHT_START_HOUR,
    SEGMENT_KIND_STYLES,
    TIMELINE_TIME_FORMAT,
    TimeAxis,
    secondsBetween,
    segmentBackground,
    timelineSpan,
} from '../lib/pullRequestTimeline'

// Past this span a day is a few pixels wide, so shading only adds DOM nodes.
const MAX_SHADED_DAYS = 60

export function PullRequestTimelineTrack({
    pr,
    axis,
    className,
}: {
    pr: PRTimelineApi
    axis: TimeAxis
    className?: string
}): JSX.Element {
    const { position, width } = axis
    const segments = pr.segments
    const isOpen = pr.state === 'open'
    const endMs = dayjs(timelineSpan(pr).endedAt).valueOf()

    return (
        <div className={cn('relative overflow-hidden rounded-sm', className)}>
            {(axis.dayStarts.length <= MAX_SHADED_DAYS ? axis.dayStarts : []).map((day) => {
                const dayMs = day.valueOf()
                // Calendar times, not elapsed hours, so daylight saving days still shade 22:00 to 06:00.
                const nextDayMs = day.add(1, 'day').valueOf()
                const nightMs = day.hour(NIGHT_START_HOUR).valueOf()
                return (
                    <div key={dayMs}>
                        {(day.day() === 0 || day.day() === 6) && (
                            <div
                                className="absolute inset-y-0 bg-fill-secondary"
                                style={{ left: position(dayMs), width: width(dayMs, nextDayMs) }}
                            />
                        )}
                        <div
                            className="absolute inset-y-0 bg-fill-tertiary"
                            style={{ left: position(nightMs), width: width(nightMs, nextDayMs) }}
                        />
                        {dayMs > axis.fromMs && (
                            <div
                                className="absolute inset-y-0 w-px bg-border-primary"
                                style={{ left: position(dayMs) }}
                            />
                        )}
                    </div>
                )
            })}
            {segments.map((segment, index) => {
                const startMs = dayjs(segment.started_at).valueOf()
                if (startMs >= axis.toMs) {
                    return null
                }
                const live = isOpen && index === segments.length - 1
                const style = SEGMENT_KIND_STYLES[segment.kind]
                return (
                    <Tooltip
                        key={segment.started_at}
                        title={`${style.label} · ${compactAgeLabel(secondsBetween(segment.started_at, segment.ended_at))}${live ? ' so far' : ''} · from ${dayjs(segment.started_at).format(TIMELINE_TIME_FORMAT)}`}
                    >
                        <div
                            className="absolute inset-y-px min-w-0.5 rounded-sm"
                            style={{
                                left: position(startMs),
                                width: width(startMs, dayjs(segment.ended_at).valueOf()),
                                ...segmentBackground(segment.kind),
                            }}
                        />
                    </Tooltip>
                )
            })}
            {isOpen && segments.length > 0 && endMs <= axis.toMs && (
                <Tooltip title={`Now, ${dayjs(endMs).format(TIMELINE_TIME_FORMAT)}`}>
                    <div
                        className="absolute -inset-y-px w-[3px] -translate-x-px rounded-sm bg-[var(--text-3000)]"
                        style={{ left: position(endMs) }}
                    />
                </Tooltip>
            )}
            {endMs > axis.toMs && (
                <span className="absolute inset-y-0 right-0 flex w-3.5 items-center justify-center bg-surface-primary text-[11px] font-bold">
                    ›
                </span>
            )}
        </div>
    )
}
