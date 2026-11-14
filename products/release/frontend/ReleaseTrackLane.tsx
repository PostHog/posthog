import { cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { ReleaseRolloutChart } from './ReleaseRolloutChart'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import { FLAG_LANE, Lane, Scale, laneHeight, sendLabel } from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'

export function ReleaseTrackLane({
    lane,
    color,
    scale,
    detailed,
}: {
    lane: Lane
    color: string
    scale: Scale
    detailed?: boolean
}): JSX.Element {
    const height = laneHeight(lane, detailed)
    return (
        <div className={cn('relative', !detailed && 'border-t border-border/60')} style={{ height }}>
            {lane.kind === 'flag' && !lane.steps.length ? (
                <ReleaseTrackSpan span={lane.span} scale={scale} top={(height - 18) / 2} height={18} />
            ) : lane.kind === 'flag' ? (
                <ReleaseRolloutChart
                    color={color}
                    steps={lane.steps}
                    start={scale.start}
                    days={scale.days}
                    dayWidth={scale.day}
                    height={FLAG_LANE}
                    labelRoom={18}
                    className="!absolute left-0 top-0"
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
                    top={2}
                />
            )}
            {lane.kind === 'flag' ? null : lane.kind === 'broadcast' ? (
                <ReleaseTrackMarkers
                    events={lane.events.map((event) => ({ ...event, title: sendLabel(event) }))}
                    scale={scale}
                    top={(height - 16) / 2}
                />
            ) : lane.span ? (
                <ReleaseTrackSpan span={lane.span} scale={scale} top={(height - 18) / 2} height={18} />
            ) : null}
        </div>
    )
}
