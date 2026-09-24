import { useActions, useValues } from 'kea'
import React from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import type { ObservationSeekbarMark, ObservationSeekbarMarkEntry } from '../utils/observation'
import { visionSurfaceShown } from '../utils/visionSurface'

interface ObservationSeekbarMarksProps {
    endTimeMs: number
    onSeek: (timestampMs: number) => void
}

/** Shared by the seekbar and the sidebar timeline. */
export function ObservationMarkTooltip({ mark }: { mark: ObservationSeekbarMark }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span className="font-medium">{colonDelimitedDuration(Math.floor(mark.timestampMs / 1000), null)}</span>
            {mark.entries.map((entry, i) => (
                <div key={i} className="flex flex-col">
                    <span>{[entry.scannerName, entry.headline].filter(Boolean).join(' · ')}</span>
                    {entry.sentence && (
                        <span className="text-xs opacity-75">
                            <CitedSentence entry={entry} />
                        </span>
                    )}
                </div>
            ))}
        </div>
    )
}

function CitedSentence({ entry }: { entry: ObservationSeekbarMarkEntry }): JSX.Element {
    const sentence = entry.sentence ?? ''
    const clause = entry.snippet?.replace(/^…|…$/g, '') ?? ''
    const at = clause ? sentence.toLowerCase().indexOf(clause.toLowerCase()) : -1
    if (at < 0) {
        return <>{sentence}</>
    }
    return (
        <>
            {sentence.slice(0, at)}
            <strong>{sentence.slice(at, at + clause.length)}</strong>
            {sentence.slice(at + clause.length)}
        </>
    )
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
    const { seekbarMarks, hoveredMarkMs } = useValues(logic)
    const { setHoveredMark } = useActions(logic)

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
                return (
                    <Tooltip key={mark.timestampMs} title={<ObservationMarkTooltip mark={mark} />} placement="top">
                        <div
                            className={cn(
                                'PlayerSeekbar__observation',
                                mark.flagged && 'PlayerSeekbar__observation--flagged',
                                hoveredMarkMs === mark.timestampMs && 'PlayerSeekbar__observation--hovered'
                            )}
                            data-attr="vision-seekbar-observation-mark"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${position}%` }}
                            onMouseEnter={() => setHoveredMark(mark.timestampMs)}
                            onMouseLeave={() => setHoveredMark(null)}
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
