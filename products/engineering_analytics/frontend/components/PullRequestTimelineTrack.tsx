// One pull request's timeline as a track on a shared clock. The day view stacks one per row, and a
// single pull request page can draw one on its own with the same axis rules.

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { PRTimelineApi } from '../generated/api.schemas'
import { compactAgeLabel } from '../lib/format'
import {
    DayViewAlignment,
    NIGHT_START_OFFSET_HOURS,
    SEGMENT_KIND_STYLES,
    hoursFromOrigin,
    rowOrigin,
    segmentBackground,
} from '../lib/pullRequestDayView'

export function PullRequestTimelineTrack({
    pr,
    alignment,
    days,
    generatedAt,
}: {
    pr: PRTimelineApi
    alignment: DayViewAlignment
    /** Days the axis spans (see axisDays); a longer timeline ends in a clip marker. */
    days: number
    /** The "now" an open pull request's last segment ends at. */
    generatedAt: string
}): JSX.Element {
    const origin = rowOrigin(pr.started_at, alignment)
    const hours = days * 24
    const pct = (value: number): string => `${(100 * value) / hours}%`
    const segments = pr.segments
    const isOpen = pr.state === 'open'
    const end = segments.length ? hoursFromOrigin(origin, segments[segments.length - 1].ended_at) : 0

    return (
        <div className="relative h-3.5 overflow-hidden rounded-sm">
            {Array.from({ length: days }).map((_, day) => {
                const weekday = origin.add(day, 'day').day()
                return (
                    <div key={day}>
                        {(weekday === 0 || weekday === 6) && (
                            <div
                                className="absolute inset-y-0 bg-fill-secondary"
                                style={{ left: pct(day * 24), width: pct(24) }}
                            />
                        )}
                        <div
                            className="absolute inset-y-0 bg-fill-tertiary"
                            style={{
                                left: pct(day * 24 + NIGHT_START_OFFSET_HOURS),
                                width: pct(24 - NIGHT_START_OFFSET_HOURS),
                            }}
                        />
                        {day > 0 && (
                            <div
                                className="absolute inset-y-0 w-px bg-border-primary"
                                style={{ left: pct(day * 24) }}
                            />
                        )}
                    </div>
                )
            })}
            {segments.map((segment, index) => {
                const start = hoursFromOrigin(origin, segment.started_at)
                if (start >= hours) {
                    return null
                }
                const segmentEnd = Math.min(hoursFromOrigin(origin, segment.ended_at), hours)
                const live = isOpen && index === segments.length - 1
                const duration = dayjs(segment.ended_at).diff(dayjs(segment.started_at), 'second')
                const style = SEGMENT_KIND_STYLES[segment.kind]
                return (
                    <Tooltip
                        key={segment.started_at}
                        title={`${style.label} · ${compactAgeLabel(duration)}${live ? ' so far' : ''} · from ${dayjs(segment.started_at).format('ddd D MMM HH:mm')}`}
                    >
                        <div
                            className="absolute inset-y-px min-w-0.5 rounded-sm"
                            style={{
                                left: pct(start),
                                width: pct(Math.max(segmentEnd - start, 0.05)),
                                ...segmentBackground(segment.kind),
                            }}
                        />
                    </Tooltip>
                )
            })}
            {isOpen && segments.length > 0 && end <= hours && (
                <Tooltip title={`Now, ${dayjs(generatedAt).format('ddd HH:mm')}`}>
                    <div
                        className="absolute -inset-y-px w-[3px] -translate-x-px rounded-sm bg-[var(--text-3000)]"
                        style={{ left: pct(end) }}
                    />
                </Tooltip>
            )}
            {end > hours && (
                <span className="absolute inset-y-0 right-0 flex w-3.5 items-center justify-center bg-surface-primary text-[11px] font-bold">
                    ›
                </span>
            )}
        </div>
    )
}
