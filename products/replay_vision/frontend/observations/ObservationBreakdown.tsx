import { useValues } from 'kea'
import { useMemo } from 'react'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { RecordingTimeline } from '../components/RecordingTimeline'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { recordingTimeline, timelineRows } from '../utils/recordingTimeline'

/** A summary's chapters on a time rail, following the observation page's embedded player. */
export default function ObservationBreakdown({
    observation,
    playerKey,
    onSeek,
}: {
    observation: ReplayObservationApi
    playerKey: string
    onSeek: (ms: number) => void
}): JSX.Element {
    const timeline = useMemo(() => recordingTimeline([observation]), [observation])
    const { currentPlayerTime, sessionPlayerData } = useValues(
        sessionRecordingPlayerLogic({ playerKey, sessionRecordingId: observation.session_id })
    )
    // Unknown until the recording loads, and the rail leaves out its end until then.
    const durationMs = sessionPlayerData.durationMs > 0 ? sessionPlayerData.durationMs : null
    const rows = useMemo(() => timelineRows(timeline, durationMs), [timeline, durationMs])
    return (
        // Capped so a long recording scrolls inside the tab rather than stretching the column.
        <div className="-mx-2 max-h-[min(36rem,calc(100vh-20rem))] overflow-y-auto">
            <RecordingTimeline
                timeline={timeline}
                rows={rows}
                currentTimeMs={currentPlayerTime}
                onSeek={onSeek}
                onSummarize={() => {}}
                summarizing={false}
            />
        </div>
    )
}
