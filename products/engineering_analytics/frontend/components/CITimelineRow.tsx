import { IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { isExternalLink } from 'lib/utils/url'

import { TimelineRow, timelineDuration } from '../lib/ciTimeline'
import { TimeAxis } from '../lib/pullRequestTimeline'
import { CITimelineBar, CI_TIMELINE_STATUS_FILL } from './CITimelineBar'

/** The label column and the time track, shared by the header, the gridlines and every row so they line up. */
export const CI_TIMELINE_COLUMNS = 'grid-cols-[minmax(16rem,38%)_1fr]'
/** Insets of the time scale inside the track; the right one leaves room for the last bar's duration label. */
export const CI_TIMELINE_SCALE = 'absolute inset-y-0 left-2 right-14'
/** Every row and the header are `h-7`, so the virtualized list never measures one. */
export const CI_TIMELINE_ROW_HEIGHT_PX = 28

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
                        CI_TIMELINE_STATUS_FILL[node.status],
                        node.status === 'skipped' && 'opacity-50'
                    )}
                />
                {node.url ? (
                    <Link
                        to={node.url}
                        target={isExternalLink(node.url) ? '_blank' : undefined}
                        targetBlankIcon={false}
                        subtle
                        className={nameClass}
                        data-attr="engineering-analytics-ci-timeline-open"
                    >
                        {node.name}
                    </Link>
                ) : (
                    <span className={nameClass}>{node.name}</span>
                )}
                <span className="ml-auto shrink-0 pl-2 text-xs tabular-nums text-secondary">
                    {timelineDuration(node)}
                </span>
            </div>
            <div className="relative">
                <div className={CI_TIMELINE_SCALE}>
                    <CITimelineBar node={node} axis={axis} />
                </div>
            </div>
        </div>
    )
}
