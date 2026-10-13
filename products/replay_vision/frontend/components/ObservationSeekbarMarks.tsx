import { useActions, useValues } from 'kea'
import React from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import type { TimelineMarker } from '../utils/recordingTimeline'
import { visionSurfaceShown } from '../utils/visionSurface'

interface ObservationSeekbarMarksProps {
    endTimeMs: number
    onSeek: (timestampMs: number) => void
}

export const ObservationSeekbarMarks = React.memo(function ObservationSeekbarMarks(
    props: ObservationSeekbarMarksProps
): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    if (!visionSurfaceShown(logicProps) || !sessionRecordingId) {
        return null
    }
    return <ObservationSeekbarMarksContent sessionId={sessionRecordingId} {...props} />
})

function ObservationSeekbarMarksContent({
    sessionId,
    endTimeMs,
    onSeek,
}: ObservationSeekbarMarksProps & { sessionId: string }): JSX.Element | null {
    const logic = observationsDockLogic({ sessionId })
    const { timeline, hoveredMarkMs } = useValues(logic)
    const { setHoveredMark, focusObservation } = useActions(logic)

    if (timeline.markers.length === 0 || endTimeMs <= 0) {
        return null
    }

    // Scans can share a key moment, and stacked marks would hide all but the top one.
    const groups = new Map<number, TimelineMarker[]>()
    for (const marker of timeline.markers) {
        groups.set(marker.timestampMs, [...(groups.get(marker.timestampMs) ?? []), marker])
    }

    return (
        <>
            {[...groups.entries()].map(([timestampMs, markers]) => {
                const position = (timestampMs / endTimeMs) * 100
                if (position < 0 || position > 100) {
                    return null
                }
                const marker = markers[0]
                return (
                    <Tooltip
                        key={timestampMs}
                        title={
                            <div className="flex flex-col gap-0.5">
                                <span className="font-medium">
                                    {colonDelimitedDuration(Math.floor(timestampMs / 1000), null)}
                                </span>
                                {markers.map((m) => (
                                    <span key={m.observationId}>
                                        {[m.scannerName, m.result].filter(Boolean).join(' · ')}
                                    </span>
                                ))}
                            </div>
                        }
                        placement="top"
                    >
                        <div
                            className={cn(
                                'PlayerSeekbar__observation',
                                markers.some((m) => m.flagged) && 'PlayerSeekbar__observation--flagged',
                                hoveredMarkMs === marker.timestampMs && 'PlayerSeekbar__observation--hovered'
                            )}
                            data-attr="vision-seekbar-observation-mark"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${position}%` }}
                            onMouseEnter={() => setHoveredMark(marker.timestampMs)}
                            onMouseLeave={() => setHoveredMark(null)}
                            // The slider scrubs on mousedown. Without this the pointer-position seek overrides the exact one.
                            onMouseDown={(e) => e.stopPropagation()}
                            onTouchStart={(e) => e.stopPropagation()}
                            onClick={(e) => {
                                e.stopPropagation()
                                onSeek(marker.timestampMs)
                                focusObservation(marker.observationId)
                            }}
                        />
                    </Tooltip>
                )
            })}
        </>
    )
}
