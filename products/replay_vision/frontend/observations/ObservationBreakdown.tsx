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
    // The page has no recording length before the player loads, so the last chapter's end closes the rail.
    const endMs = Math.max(0, ...timeline.chapters.map((c) => c.endMs))
    const rows = useMemo(() => timelineRows(timeline, endMs), [timeline, endMs])
    const { currentPlayerTime } = useValues(
        sessionRecordingPlayerLogic({ playerKey, sessionRecordingId: observation.session_id })
    )
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
