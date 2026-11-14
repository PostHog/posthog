import { cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { ReleaseRolloutBar } from './ReleaseRolloutBar'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import { Lane, Scale, laneHeight, sendLabel } from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'

export function ReleaseTrackLane({
    lane,
    color,
    scale,
    detailed,
    stickyOffset,
}: {
    lane: Lane
    color: string
    scale: Scale
    detailed?: boolean
    stickyOffset?: number
}): JSX.Element {
    const height = laneHeight(detailed)
    return (
        <div className={cn('relative', !detailed && 'border-t border-border/60')} style={{ height }}>
            {lane.kind === 'flag' && !lane.steps.length ? (
                <ReleaseTrackSpan
                    span={lane.span}
                    scale={scale}
                    top={(height - 18) / 2}
                    height={18}
                    stickyOffset={stickyOffset}
                />
            ) : lane.kind === 'flag' ? (
                <ReleaseRolloutBar
                    steps={lane.steps}
                    scale={scale}
                    color={color}
                    top={(height - 18) / 2}
                    height={18}
                    stickyOffset={stickyOffset}
                />
            ) : null}
            {lane.kind === 'flag' && (
                <ReleaseTrackMarkers
                    events={lane.events.filter(
                        (event) =>
                            !lane.steps.some(
                                (step) => step.upcoming && dayjs(step.from).isSame(dayjs(event.date), 'day')
                            )
                    )}
                    scale={scale}
                    top={(height - 16) / 2}
                />
            )}
            {lane.kind === 'flag' ? null : lane.kind === 'broadcast' ? (
                <ReleaseTrackMarkers
                    events={lane.events.map((event) => ({ ...event, title: sendLabel(event) }))}
                    scale={scale}
                    top={(height - 16) / 2}
                />
            ) : 'span' in lane && lane.span ? (
                <ReleaseTrackSpan
                    span={lane.span}
                    scale={scale}
                    top={(height - 18) / 2}
                    height={18}
                    stickyOffset={stickyOffset}
                />
            ) : null}
        </div>
    )
}
