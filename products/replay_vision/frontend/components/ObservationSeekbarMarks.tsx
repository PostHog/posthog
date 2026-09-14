import { useValues } from 'kea'
import React from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
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
    const { seekbarMarks } = useValues(observationsDockLogic({ sessionId }))

    if (seekbarMarks.length === 0 || endTimeMs <= 0) {
        return null
    }

    return (
        <>
            {seekbarMarks.map((mark) => {
                const position = (mark.timestampMs / endTimeMs) * 100
                if (position < 0 || position > 100) {
                    return null
                }
                const timeLabel = colonDelimitedDuration(Math.floor(mark.timestampMs / 1000), null)
                return (
                    <Tooltip
                        key={mark.timestampMs}
                        title={
                            <div className="flex flex-col gap-1">
                                <span className="font-medium">{timeLabel}</span>
                                {mark.entries.map((entry, i) => (
                                    <div key={i} className="flex flex-col">
                                        <span>{[entry.scannerName, entry.headline].filter(Boolean).join(' · ')}</span>
                                        {entry.snippet && <span className="text-xs opacity-75">{entry.snippet}</span>}
                                    </div>
                                ))}
                            </div>
                        }
                        placement="top"
                    >
                        <div
                            className="PlayerSeekbar__observation"
                            data-attr="vision-seekbar-observation-mark"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${position}%` }}
                            // The slider scrubs on mousedown. Without this the pointer-position seek overrides the exact one.
                            onMouseDown={(e) => e.stopPropagation()}
                            onTouchStart={(e) => e.stopPropagation()}
                            onClick={(e) => {
                                e.stopPropagation()
                                onSeek(mark.timestampMs)
                            }}
                        />
                    </Tooltip>
                )
            })}
        </>
    )
}
