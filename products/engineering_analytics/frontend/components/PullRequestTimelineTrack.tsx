// One pull request's timeline as a track between two instants. The day view stacks one per row on a
// shared clock, and the pull request page draws one on the pull request's own span.

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { PRTimelineApi } from '../generated/api.schemas'
import { compactAgeLabel } from '../lib/format'
import {
    NIGHT_START_OFFSET_HOURS,
    SEGMENT_KIND_STYLES,
    dayStartsBetween,
    secondsBetween,
    segmentBackground,
} from '../lib/pullRequestDayView'

const HOUR_MS = 3600 * 1000
const TIME_FORMAT = 'ddd D MMM HH:mm'

export function PullRequestTimelineTrack({
    pr,
    fromMs,
    toMs,
    className,
}: {
    pr: PRTimelineApi
    fromMs: number
    /** A timeline that runs past this ends in a clip marker. */
    toMs: number
    className: string
}): JSX.Element {
    const span = toMs - fromMs
    const clip = (ms: number): number => Math.min(Math.max(ms, fromMs), toMs)
    const left = (ms: number): string => `${(100 * (clip(ms) - fromMs)) / span}%`
    const width = (startMs: number, endMs: number): string => `${(100 * (clip(endMs) - clip(startMs))) / span}%`
    const segments = pr.segments
    const isOpen = pr.state === 'open'
    // An open pull request's last segment ends now.
    const endMs = segments.length ? dayjs(segments[segments.length - 1].ended_at).valueOf() : fromMs

    return (
        <div className={cn('relative overflow-hidden rounded-sm', className)}>
            {dayStartsBetween(fromMs, toMs).map((day) => {
                const dayMs = day.valueOf()
                const nightMs = dayMs + NIGHT_START_OFFSET_HOURS * HOUR_MS
                const nextDayMs = dayMs + 24 * HOUR_MS
                return (
                    <div key={dayMs}>
                        {(day.day() === 0 || day.day() === 6) && (
                            <div
                                className="absolute inset-y-0 bg-fill-secondary"
                                style={{ left: left(dayMs), width: width(dayMs, nextDayMs) }}
                            />
                        )}
                        <div
                            className="absolute inset-y-0 bg-fill-tertiary"
                            style={{ left: left(nightMs), width: width(nightMs, nextDayMs) }}
                        />
                        {dayMs > fromMs && (
                            <div className="absolute inset-y-0 w-px bg-border-primary" style={{ left: left(dayMs) }} />
                        )}
                    </div>
                )
            })}
            {segments.map((segment, index) => {
                const startMs = dayjs(segment.started_at).valueOf()
                if (startMs >= toMs) {
                    return null
                }
                const live = isOpen && index === segments.length - 1
                const style = SEGMENT_KIND_STYLES[segment.kind]
                return (
                    <Tooltip
                        key={segment.started_at}
                        title={`${style.label} · ${compactAgeLabel(secondsBetween(segment.started_at, segment.ended_at))}${live ? ' so far' : ''} · from ${dayjs(segment.started_at).format(TIME_FORMAT)}`}
                    >
                        <div
                            className="absolute inset-y-px min-w-0.5 rounded-sm"
                            style={{
                                left: left(startMs),
                                width: width(startMs, dayjs(segment.ended_at).valueOf()),
                                ...segmentBackground(segment.kind),
                            }}
                        />
                    </Tooltip>
                )
            })}
            {isOpen && segments.length > 0 && endMs <= toMs && (
                <Tooltip title={`Now, ${dayjs(endMs).format(TIME_FORMAT)}`}>
                    <div
                        className="absolute -inset-y-px w-[3px] -translate-x-px rounded-sm bg-[var(--text-3000)]"
                        style={{ left: left(endMs) }}
                    />
                </Tooltip>
            )}
            {endMs > toMs && (
                <span className="absolute inset-y-0 right-0 flex w-3.5 items-center justify-center bg-surface-primary text-[11px] font-bold">
                    ›
                </span>
            )}
        </div>
    )
}
