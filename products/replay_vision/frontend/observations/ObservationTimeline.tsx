import { useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { RecordingTimeline } from '../components/RecordingTimeline'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { currentRowIndex, recordingTimeline, timelineRows } from '../utils/recordingTimeline'

/** A summary's chapters on a time rail, following the observation page's embedded player. */
export default function ObservationTimeline({
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
    const currentIndex = currentRowIndex(rows, currentPlayerTime)
    const scrollRef = useRef<HTMLDivElement>(null)

    // Keeps the playing chapter in view. Scrolls only the rail's own box, so the page itself never moves.
    useEffect(() => {
        const box = scrollRef.current
        const row = box?.querySelector<HTMLElement>('[data-current-moment]')
        if (!box || !row) {
            return
        }
        const boxRect = box.getBoundingClientRect()
        const rowRect = row.getBoundingClientRect()
        if (rowRect.top < boxRect.top || rowRect.bottom > boxRect.bottom) {
            const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
            box.scrollTo({
                top: box.scrollTop + rowRect.top - boxRect.top - boxRect.height / 3,
                behavior: reduceMotion ? 'auto' : 'smooth',
            })
        }
    }, [currentIndex])

    return (
        // Capped so a long recording scrolls inside the tab rather than stretching the column.
        <div ref={scrollRef} className="-mx-2 max-h-[min(36rem,calc(100vh-20rem))] overflow-y-auto">
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
