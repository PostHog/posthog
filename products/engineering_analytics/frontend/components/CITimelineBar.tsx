import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { TimelineNode, TimelineStatus, timelineDuration } from '../lib/ciTimeline'
import { TimeAxis } from '../lib/pullRequestTimeline'
import { formatCost } from './runTables'

export const CI_TIMELINE_STATUS_FILL: Record<TimelineStatus, string> = {
    success: 'bg-success',
    failure: 'bg-danger',
    running: 'bg-warning',
    neutral: 'bg-muted',
    skipped: 'bg-muted',
}

const CENTERED = 'absolute top-1/2 -translate-y-1/2'

export function CITimelineBar({ node, axis }: { node: TimelineNode; axis: TimeAxis }): JSX.Element {
    if (node.startMs == null) {
        return (
            <span className={cn(CENTERED, 'left-0 text-xs text-tertiary')}>
                {node.status === 'skipped' ? 'Skipped' : 'Not started'}
            </span>
        )
    }
    if (node.endMs == null) {
        return (
            <span
                className={cn(CENTERED, 'text-xs whitespace-nowrap text-tertiary')}
                style={{ left: axis.position(node.startMs) }}
            >
                No update for over a day
            </span>
        )
    }
    const duration = timelineDuration(node)
    const offset = humanFriendlyDuration((node.startMs - axis.fromMs) / 1000)
    const isStep = node.kind === 'step'
    return (
        <>
            <Tooltip
                title={`${node.name}: ${node.status === 'running' ? 'running for' : 'ran'} ${duration}, starting ${offset} in${node.runner ? ` on ${node.runner}` : ''}${node.costUsd != null ? `, est. ${formatCost(node.costUsd)}` : ''}`}
            >
                <span
                    className={cn(
                        CENTERED,
                        'min-w-0.5 rounded-sm',
                        isStep ? 'h-1.5' : 'h-2.5',
                        isStep && node.status !== 'failure' && 'opacity-60',
                        CI_TIMELINE_STATUS_FILL[node.status]
                    )}
                    style={{ left: axis.position(node.startMs), width: axis.width(node.startMs, node.endMs) }}
                />
            </Tooltip>
            <span
                className={cn(CENTERED, 'pl-1.5 text-[11px] tabular-nums whitespace-nowrap text-tertiary')}
                style={{ left: axis.position(node.endMs) }}
            >
                {duration}
            </span>
        </>
    )
}
