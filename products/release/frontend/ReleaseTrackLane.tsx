import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { activityKey, releaseCalendarLogic } from './releaseCalendarLogic'
import { ReleaseChangeDots } from './ReleaseChangeDots'
import { ChangeKind, ReleaseChange, describeChanges } from './releaseChanges'
import { ReleaseRolloutBar } from './ReleaseRolloutBar'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import { Lane, Scale, laneHeight, sendLabel } from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'

function laneActivity(lane: Lane): { kind: ChangeKind; key: string | null } | null {
    if (lane.kind === 'flag') {
        return { kind: 'flag', key: null }
    }
    if (lane.kind === 'experiment') {
        return { kind: 'experiment', key: activityKey('experiment', lane.key.replace(/^experiment-/, '')) }
    }
    if (lane.kind === 'survey') {
        return { kind: 'survey', key: activityKey('survey', lane.survey.id) }
    }
    return null
}

function useLaneChanges(lane: Lane): ReleaseChange[] {
    const { flagActivity, objectActivity } = useValues(releaseCalendarLogic)
    const { loadObjectActivity } = useActions(releaseCalendarLogic)
    const source = laneActivity(lane)
    const objectKey = source?.key ?? null

    useEffect(() => {
        if (objectKey) {
            loadObjectActivity([objectKey])
        }
    }, [objectKey, loadObjectActivity])

    const entries = !source
        ? undefined
        : lane.kind === 'flag'
          ? flagActivity[lane.flag.id]
          : objectKey
            ? objectActivity[objectKey]
            : undefined
    const kind = source?.kind
    return useMemo(() => (kind && entries ? describeChanges(kind, entries) : []), [kind, entries])
}

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
    const changes = useLaneChanges(lane)
    return (
        <div className={cn('relative', !detailed && !flush && 'border-t border-border/60')} style={{ height }}>
            {lane.kind === 'flag' && !lane.steps.length ? (
                <ReleaseTrackSpan
                    span={lane.span}
                    scale={scale}
                    top={(height - 18) / 2}
                    height={18}
                    stickyOffset={stickyOffset}
                    lane={lane}
                />
            ) : lane.kind === 'flag' ? (
                <ReleaseRolloutBar
                    steps={lane.steps}
                    scale={scale}
                    color={color}
                    top={(height - 18) / 2}
                    height={18}
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
                    top={(height - 18) / 2}
                    height={18}
                    stickyOffset={stickyOffset}
                    lane={lane}
                />
            ) : null}
            <ReleaseChangeDots changes={changes} scale={scale} center={height / 2} />
        </div>
    )
}
