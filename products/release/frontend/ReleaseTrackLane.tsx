import { ReleaseRolloutChart } from './ReleaseRolloutChart'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import { FLAG_LANE, Lane, Scale, laneHeight, sendLabel } from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'

export function ReleaseTrackLane({ lane, color, scale }: { lane: Lane; color: string; scale: Scale }): JSX.Element {
    const height = laneHeight(lane)
    return (
        <div className="relative border-t border-border/60" style={{ height }}>
            {lane.kind === 'flag' ? (
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
            ) : lane.kind === 'broadcast' ? (
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
