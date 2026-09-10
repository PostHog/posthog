import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

function AutoSeekToTime({
    playerKey,
    sessionRecordingId,
    ms,
    trigger,
}: {
    playerKey: string
    sessionRecordingId: string
    ms: number
    trigger: number
}): null {
    const { sessionPlayerData } = useValues(sessionRecordingPlayerLogic({ playerKey, sessionRecordingId }))
    // `start`/`end` are fresh Dayjs objects on every snapshot batch; compare epochs so deps stay stable.
    const startMs = sessionPlayerData?.start?.valueOf() ?? null
    const endMs = sessionPlayerData?.end?.valueOf() ?? null
    // Latch per-trigger so snapshot-batch arrivals don't re-seek and fight playback.
    const seekedForTrigger = useRef<number | null>(null)
    useEffect(() => {
        if (seekedForTrigger.current === trigger || startMs == null || endMs == null) {
            return
        }
        sessionRecordingPlayerLogic.findMounted({ playerKey, sessionRecordingId })?.actions.seekToTime(ms)
        seekedForTrigger.current = trigger
    }, [startMs, endMs, ms, trigger, playerKey, sessionRecordingId])
    return null
}

export default function ObservationRecording({
    playerKey,
    sessionRecordingId,
    pendingSeek,
}: {
    playerKey: string
    sessionRecordingId: string
    pendingSeek: { ms: number; trigger: number } | null
}): JSX.Element {
    return (
        <>
            <SessionRecordingPlayer
                sessionRecordingId={sessionRecordingId}
                playerKey={playerKey}
                mode={SessionRecordingPlayerMode.Standard}
                autoPlay={false}
                noBorder
                noDock
                withSidebar
            />
            {pendingSeek && (
                <AutoSeekToTime
                    playerKey={playerKey}
                    sessionRecordingId={sessionRecordingId}
                    ms={pendingSeek.ms}
                    trigger={pendingSeek.trigger}
                />
            )}
        </>
    )
}
