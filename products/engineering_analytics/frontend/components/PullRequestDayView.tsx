// Every pull request of one author on a shared clock: each row starts at 06:00 on the day the pull
// request went ready (or Monday 06:00 of that week), so nights and weekends line up across rows and a
// long wait reads as the days it spanned. Replaces a pull request table on the author page.

import { LemonCard, LemonSegmentedButton, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { AuthorPullRequestTimelinesApi } from '../generated/api.schemas'
import { compactAgeLabel, compactUsd } from '../lib/format'
import {
    DAY_START_HOUR,
    DayViewAlignment,
    DayViewGroup,
    DayViewRow,
    NIGHT_START_OFFSET_HOURS,
    SEGMENT_KIND_STYLES,
    SEGMENT_LEGEND_GROUPS,
    hoursFromOrigin,
    rowOrigin,
    segmentBackground,
} from '../lib/pullRequestDayView'
import { withCurrentScope } from '../lib/scope'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const ROW_GRID =
    'grid grid-cols-[minmax(6rem,11rem)_minmax(0,1fr)_3rem] items-center gap-2 @min-[48rem]:grid-cols-[minmax(9rem,16rem)_minmax(0,1fr)_3rem_11rem]'

function DayViewTrack({
    row,
    alignment,
    days,
    generatedAt,
}: {
    row: DayViewRow
    alignment: DayViewAlignment
    days: number
    generatedAt: string
}): JSX.Element {
    const origin = rowOrigin(row.pr.started_at, alignment)
    const hours = days * 24
    const pct = (value: number): string => `${(100 * value) / hours}%`
    const segments = row.pr.segments
    const end = hoursFromOrigin(origin, segments[segments.length - 1].ended_at)

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
                const live = row.isOpen && index === segments.length - 1
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
            {row.isOpen && end <= hours && (
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

function DayViewRowItem({
    row,
    alignment,
    days,
    generatedAt,
    sourceId,
}: {
    row: DayViewRow
    alignment: DayViewAlignment
    days: number
    generatedAt: string
    sourceId: string | null
}): JSX.Element {
    const { pr } = row
    const highlight = SEGMENT_KIND_STYLES[row.highlightKind]
    const hover = [
        pr.title,
        `${pr.is_draft ? 'opened' : 'ready'} ${dayjs(pr.started_at).format('ddd D MMM HH:mm')}`,
        pluralize(pr.pushes, 'push', 'pushes'),
        pr.estimated_cost_usd != null ? `CI cost ${compactUsd(pr.estimated_cost_usd)}` : null,
    ]
        .filter(Boolean)
        .join(' · ')
    return (
        <div className={`${ROW_GRID} py-0.5 text-xs`}>
            <Tooltip title={hover}>
                <Link
                    to={withCurrentScope(
                        urls.engineeringAnalyticsPullRequest(pr.repo.owner, pr.repo.name, pr.number),
                        sourceId
                    )}
                    className="flex min-w-0 items-baseline gap-1.5"
                >
                    <span className="shrink-0 tabular-nums">#{pr.number}</span>
                    <span className="truncate text-[11px] text-secondary">{pr.title}</span>
                </Link>
            </Tooltip>
            <DayViewTrack row={row} alignment={alignment} days={days} generatedAt={generatedAt} />
            <span className="text-right text-[11px] tabular-nums text-tertiary">
                {row.isOpen && <span className="mr-1 inline-block size-1.5 rounded-full bg-success align-middle" />}
                {compactAgeLabel(row.lengthSeconds)}
            </span>
            <span className="hidden min-w-0 items-center gap-1 truncate text-[11px] text-secondary @min-[48rem]:flex">
                <span className="size-2 shrink-0 rounded-sm" style={segmentBackground(row.highlightKind)} />
                <span className="truncate">
                    {row.isOpen ? 'now: ' : 'most: '}
                    <span className="font-semibold text-primary">{highlight.short}</span>{' '}
                    {compactAgeLabel(row.highlightSeconds)}
                </span>
            </span>
        </div>
    )
}

export function PullRequestDayView({
    timelines,
    groups,
    days,
    alignment,
    onAlignmentChange,
    loading,
    sourceId,
}: {
    timelines: AuthorPullRequestTimelinesApi | null
    groups: DayViewGroup[]
    days: number
    alignment: DayViewAlignment
    onAlignmentChange: (alignment: DayViewAlignment) => void
    loading: boolean
    sourceId: string | null
}): JSX.Element {
    const step = days > 7 ? 2 : 1
    const ticks = Array.from({ length: Math.ceil(days / step) }).map((_, index) => index * step)
    const alignmentNote =
        alignment === 'weeks'
            ? `Rows start at Monday ${DAY_START_HOUR}:00 of the week each pull request went ready, so weekdays line up.`
            : `Rows start at ${DAY_START_HOUR}:00 on the day each pull request went ready, so nights and weekends line up.`

    return (
        <LemonCard hoverEffect={false} className="@container p-4" data-attr="engineering-analytics-author-day-view">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-secondary">
                    {SEGMENT_LEGEND_GROUPS.map((group) => (
                        <span key={group.label} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="text-tertiary">{group.label}</span>
                            {group.kinds.map((kind) => (
                                <span key={kind} className="flex items-center gap-1">
                                    <span className="h-2.5 w-3 rounded-sm" style={segmentBackground(kind)} />
                                    {SEGMENT_KIND_STYLES[kind].short}
                                </span>
                            ))}
                        </span>
                    ))}
                </div>
                <div className="flex items-center gap-2">
                    <Tooltip
                        title={`${alignmentNote} Shaded: nights 22:00 to 06:00 and weekends, in your time zone. The axis stretches to fit 90% of the pull requests; longer bars end in ›.`}
                    >
                        <span className="cursor-default text-[11px] text-tertiary">
                            axis fits {pluralize(days, 'day')}
                        </span>
                    </Tooltip>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={alignment}
                        onChange={onAlignmentChange}
                        options={[
                            { value: 'days', label: 'Days' },
                            { value: 'weeks', label: 'Weeks' },
                        ]}
                        data-attr="engineering-analytics-author-day-view-alignment"
                    />
                </div>
            </div>
            {loading && !timelines ? (
                <div className="flex flex-col gap-2">
                    {Array.from({ length: 6 }).map((_, index) => (
                        <LemonSkeleton key={index} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : groups.length === 0 ? (
                <div className="py-6 text-center text-xs text-secondary">
                    No open pull requests, and nothing merged in the window.
                </div>
            ) : (
                <>
                    <div className={`${ROW_GRID} mb-1 text-[10px] text-tertiary`}>
                        <span />
                        <div className="relative h-3.5 overflow-hidden">
                            {ticks.map((day) => (
                                <span
                                    key={day}
                                    className="absolute whitespace-nowrap pl-0.5"
                                    style={{ left: `${(100 * day) / days}%` }}
                                >
                                    {alignment === 'weeks' ? WEEKDAYS[day % 7] : `Day ${day + 1}`}
                                </span>
                            ))}
                        </div>
                    </div>
                    {groups.map((group, index) => (
                        <div key={group.key}>
                            <div
                                className={`mb-1 flex items-center gap-2 text-[11px] font-semibold text-secondary ${index > 0 ? 'mt-2 border-t border-primary pt-2' : ''}`}
                            >
                                {group.label}
                                <span className="font-normal text-tertiary">{group.rows.length}</span>
                            </div>
                            {group.rows.map((row) => (
                                <DayViewRowItem
                                    key={`${row.pr.repo.owner}/${row.pr.repo.name}#${row.pr.number}`}
                                    row={row}
                                    alignment={alignment}
                                    days={days}
                                    generatedAt={timelines?.generated_at ?? ''}
                                    sourceId={sourceId}
                                />
                            ))}
                        </div>
                    ))}
                    {timelines?.truncated && (
                        <div className="mt-2 text-[11px] text-tertiary">
                            Showing the newest {timelines.limit} pull requests. Narrow the window to see the rest.
                        </div>
                    )}
                </>
            )}
        </LemonCard>
    )
}
