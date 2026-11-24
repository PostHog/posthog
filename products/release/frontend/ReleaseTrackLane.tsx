import { useActions, useMountedLogic, useSelector } from 'kea'
import { useEffect, useMemo } from 'react'

import { cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { ActivityEntry, ReleaseChange, describeChanges, laneActivity } from './releaseChanges'
import { ReleaseChangeSteps } from './ReleaseChangeSteps'
import { ReleaseRolloutBar } from './ReleaseRolloutBar'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import { Lane, SPAN_LOOK, Scale, laneHeight, sendLabel } from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'

function useLaneChanges(lane: Lane): ReleaseChange[] {
    useMountedLogic(releaseCalendarLogic)
    const { loadObjectActivity } = useActions(releaseCalendarLogic)
    const source = laneActivity(lane)
    const objectKey = source?.key ?? null
    const flagId = lane.kind === 'flag' ? lane.flag.id : null

    useEffect(() => {
        if (objectKey) {
            loadObjectActivity([objectKey])
        }
    }, [objectKey, loadObjectActivity])

    const entries: readonly ActivityEntry[] | undefined = useSelector((state) =>
        flagId !== null
            ? releaseCalendarLogic.selectors.flagActivity(state)[flagId]
            : objectKey
              ? releaseCalendarLogic.selectors.objectActivity(state)[objectKey]
              : undefined
    )
    const kind = source?.kind
    return useMemo(() => (kind && entries ? describeChanges(kind, entries) : []), [kind, entries])
}

const BAR_HEIGHT = 18

export function ReleaseTrackLane({
    lane,
    color,
    scale,
    detailed,
    flush,
    stickyOffset,
}: {
    lane: Lane
    color: string
    scale: Scale
    detailed?: boolean
    flush?: boolean
    stickyOffset?: number
}): JSX.Element {
    const height = laneHeight(detailed)
    const barTop = (height - BAR_HEIGHT) / 2
    const changes = useLaneChanges(lane)
    const stepColor = lane.kind !== 'flag' && 'span' in lane && lane.span ? SPAN_LOOK[lane.span.kind].color : color
    return (
        <div className={cn('relative', !detailed && !flush && 'border-t border-border/60')} style={{ height }}>
            {lane.kind === 'flag' && !lane.steps.length ? (
                <ReleaseTrackSpan
                    span={lane.span}
                    scale={scale}
                    top={barTop}
                    height={BAR_HEIGHT}
                    stickyOffset={stickyOffset}
                    lane={lane}
                />
            ) : lane.kind === 'flag' ? (
                <ReleaseRolloutBar
                    steps={lane.steps}
                    scale={scale}
                    color={color}
                    top={barTop}
                    height={BAR_HEIGHT}
                    stickyOffset={stickyOffset}
                    lane={lane}
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
                    top={barTop}
                    height={BAR_HEIGHT}
                    stickyOffset={stickyOffset}
                    lane={lane}
                />
            ) : null}
            <ReleaseChangeSteps changes={changes} scale={scale} top={barTop} height={BAR_HEIGHT} color={stepColor} />
        </div>
    )
}
