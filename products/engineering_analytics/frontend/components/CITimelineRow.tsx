import { IconChevronRight } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { TimelineRow, TimelineStatus } from '../lib/ciTimeline'
import { TimeAxis } from '../lib/pullRequestTimeline'

/** The label column and the time track, shared by the header, the gridlines and every row so they line up. */
export const CI_TIMELINE_COLUMNS = 'grid-cols-[minmax(16rem,38%)_1fr]'
/** Insets of the time scale inside the track; the right one leaves room for the last bar's duration label. */
export const CI_TIMELINE_SCALE = 'absolute inset-y-0 left-2 right-14'

const STATUS_FILL: Record<TimelineStatus, string> = {
    success: 'bg-success',
    failure: 'bg-danger',
    running: 'bg-warning',
    neutral: 'bg-muted',
    skipped: 'bg-muted',
}

const GUIDE_LINE = 'before:absolute before:left-[7px] before:top-0 before:border-l before:border-primary'
const GUIDE_BRANCH = 'after:absolute after:left-[7px] after:right-0 after:top-1/2 after:border-t after:border-primary'

export function CITimelineRow({
    row,
    axis,
    expanded,
    onToggle,
}: {
    row: TimelineRow
    axis: TimeAxis
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    const { node } = row
    // Top-level rows have no parent row, so they get no guide column.
    const levels = row.lastAtLevel.slice(1)
    const seconds = node.startMs != null && node.endMs != null ? (node.endMs - node.startMs) / 1000 : null
    const duration = seconds != null ? humanFriendlyDuration(seconds) : null
    const isParent = node.children.length > 0
    const nameClass = cn(
        'truncate',
        node.kind === 'step' ? 'text-secondary' : 'font-semibold',
        node.status === 'skipped' && 'text-tertiary'
    )

    return (
        <div className={cn('relative grid h-7 hover:bg-fill-highlight-50', CI_TIMELINE_COLUMNS)}>
            <div className="flex h-full min-w-0 items-center border-r border-primary pl-2 pr-2">
                {levels.map((isLast, level) => {
                    const isOwn = level === levels.length - 1
                    return (
                        <span
                            key={level}
                            className={cn(
                                'relative h-full w-4 shrink-0',
                                isOwn && GUIDE_BRANCH,
                                (isOwn || !isLast) && GUIDE_LINE,
                                isOwn && isLast ? 'before:h-1/2' : 'before:bottom-0'
                            )}
                        />
                    )
                })}
                {isParent ? (
                    <button
                        type="button"
                        className="flex h-full w-4 shrink-0 cursor-pointer items-center justify-center text-tertiary hover:text-primary"
                        onClick={onToggle}
                        aria-expanded={expanded}
                        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.name}`}
                        data-attr="engineering-analytics-ci-timeline-toggle"
                    >
                        <IconChevronRight className={cn('size-3 transition-transform', expanded && 'rotate-90')} />
                    </button>
                ) : (
                    <span
                        className={cn(
                            'relative h-full w-4 shrink-0',
                            levels.length > 0 && GUIDE_BRANCH,
                            'after:left-0'
                        )}
                    />
                )}
                <span
                    className={cn(
                        'mr-1.5 ml-0.5 size-2 shrink-0 rounded-sm',
                        STATUS_FILL[node.status],
                        node.status === 'skipped' && 'opacity-50'
                    )}
                />
                {node.url ? (
                    <Link to={node.url} subtle className={nameClass} data-attr="engineering-analytics-ci-timeline-open">
                        {node.name}
                    </Link>
                ) : (
                    <span className={nameClass}>{node.name}</span>
                )}
                <span className="ml-2 min-w-0 flex-1 truncate text-xs text-tertiary">{node.detail}</span>
                <span className="ml-2 shrink-0 text-xs tabular-nums text-secondary">{duration}</span>
            </div>
            <div className="relative">
                <div className={CI_TIMELINE_SCALE}>
                    {node.startMs == null ? (
                        <span className="absolute top-1/2 left-0 -translate-y-1/2 text-xs text-tertiary">
                            {node.status === 'skipped' ? 'Skipped' : 'Not started'}
                        </span>
                    ) : node.endMs == null ? (
                        <span
                            className="absolute top-1/2 -translate-y-1/2 text-xs whitespace-nowrap text-tertiary"
                            style={{ left: axis.position(node.startMs) }}
                        >
                            No update for over a day
                        </span>
                    ) : (
                        <>
                            <Tooltip
                                title={`${node.name}: ${node.status === 'running' ? 'running for' : 'ran'} ${duration}, starting ${humanFriendlyDuration((node.startMs - axis.fromMs) / 1000)} in`}
                            >
                                <span
                                    className={cn(
                                        'absolute top-1/2 min-w-0.5 -translate-y-1/2 rounded-sm',
                                        node.kind === 'step' ? 'h-1.5' : 'h-2.5',
                                        node.kind === 'step' && node.status !== 'failure' && 'opacity-60',
                                        STATUS_FILL[node.status]
                                    )}
                                    style={{
                                        left: axis.position(node.startMs),
                                        width: axis.width(node.startMs, node.endMs),
                                    }}
                                />
                            </Tooltip>
                            <span
                                className="absolute top-1/2 -translate-y-1/2 pl-1.5 text-[11px] tabular-nums whitespace-nowrap text-tertiary"
                                style={{ left: axis.position(node.endMs) }}
                            >
                                {duration}
                            </span>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
