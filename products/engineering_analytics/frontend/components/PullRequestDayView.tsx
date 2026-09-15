// Pull requests on a shared clock: each row starts at 06:00 on the day the pull request went ready (or
// Monday 06:00 of that week), so nights and weekends line up across rows and a long wait reads as the
// days it spanned. Groups put the work that needs attention first.

import { LemonCard, LemonSegmentedButton, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { PullRequestTimelinesApi } from '../generated/api.schemas'
import { compactAgeLabel, compactUsd } from '../lib/format'
import {
    DAY_START_HOUR,
    DayViewAlignment,
    DayViewGroup,
    DayViewRow,
    SEGMENT_KIND_STYLES,
    segmentBackground,
} from '../lib/pullRequestDayView'
import { withCurrentScope } from '../lib/scope'
import { PullRequestTimelineLegend } from './PullRequestTimelineLegend'
import { PullRequestTimelineTrack } from './PullRequestTimelineTrack'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const ROW_GRID =
    'grid grid-cols-[minmax(6rem,11rem)_minmax(0,1fr)_3rem] items-center gap-2 @min-[48rem]:grid-cols-[minmax(9rem,16rem)_minmax(0,1fr)_3rem_11rem]'

function DayViewRowItem({
    row,
    alignment,
    days,
    generatedAt,
    sourceId,
    showAuthor,
}: {
    row: DayViewRow
    alignment: DayViewAlignment
    days: number
    generatedAt: string
    sourceId: string | null
    showAuthor: boolean
}): JSX.Element {
    const { pr } = row
    const highlight = SEGMENT_KIND_STYLES[row.highlightKind]
    const hover = [
        pr.title,
        showAuthor ? `by ${pr.author.handle}` : null,
        `timeline from ${dayjs(pr.started_at).format('ddd D MMM HH:mm')}`,
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
            <PullRequestTimelineTrack pr={pr} alignment={alignment} days={days} generatedAt={generatedAt} />
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
    showAuthor = false,
}: {
    timelines: PullRequestTimelinesApi | null
    groups: DayViewGroup[]
    days: number
    alignment: DayViewAlignment
    onAlignmentChange: (alignment: DayViewAlignment) => void
    loading: boolean
    sourceId: string | null
    /** Name each pull request's author on hover, for scopes that list several authors (a team). */
    showAuthor?: boolean
}): JSX.Element {
    const step = days > 7 ? 2 : 1
    const ticks = Array.from({ length: Math.ceil(days / step) }).map((_, index) => index * step)
    const alignmentNote =
        alignment === 'weeks'
            ? `Rows start at Monday ${DAY_START_HOUR}:00 of the week each timeline starts, so weekdays line up.`
            : `Rows start at ${DAY_START_HOUR}:00 on the day each timeline starts, so nights and weekends line up.`

    return (
        <LemonCard hoverEffect={false} className="@container p-4" data-attr="engineering-analytics-day-view">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <PullRequestTimelineLegend />
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
                        data-attr="engineering-analytics-day-view-alignment"
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
                    {timelines?.scope_kind === 'github_team' && !timelines.has_membership_data
                        ? 'Team pull requests appear once the team members table on this GitHub source is synced.'
                        : 'No open pull requests, and nothing merged in the window.'}
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
                                    showAuthor={showAuthor}
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
