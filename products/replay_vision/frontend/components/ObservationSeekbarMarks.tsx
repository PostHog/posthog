import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils/durations'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'

interface ObservationSeekbarMarksProps {
    endTimeMs: number
    onSeek: (timestampMs: number) => void
}

// Unlike the dock this ignores noMeta, so noMeta surfaces show marks without a dock.
export function ObservationSeekbarMarks(props: ObservationSeekbarMarksProps): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const hasReplayVision = useFeatureFlag('REPLAY_VISION')
    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    if (!hasReplayVision || mode !== SessionRecordingPlayerMode.Standard || !sessionRecordingId) {
        return null
    }
    return <ObservationSeekbarMarksContent sessionId={sessionRecordingId} {...props} />
}

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
        <div className="PlayerSeekbar__observations">
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
                                        <span>
                                            {[entry.scannerName ?? 'Scanner', entry.headline]
                                                .filter(Boolean)
                                                .join(' · ')}
                                        </span>
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
                            onClick={(e) => {
                                e.stopPropagation()
                                onSeek(mark.timestampMs)
                            }}
                        />
                    </Tooltip>
                )
            })}
        </div>
    )
}
