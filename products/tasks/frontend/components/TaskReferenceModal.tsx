import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { TaskReference } from '../types'

export interface TaskReferenceModalProps {
    isOpen: boolean
    onClose: () => void
    reference: TaskReference | null
}

function parseTimeToMs(timeStr: string): number {
    // Parse time strings like "00:01:23" or "01:23" to milliseconds
    const parts = timeStr.split(':').map(Number)
    if (parts.length === 3) {
        // HH:MM:SS
        return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000
    } else if (parts.length === 2) {
        // MM:SS
        return (parts[0] * 60 + parts[1]) * 1000
    }
    return 0
}

export function TaskReferenceModal({ isOpen, onClose, reference }: TaskReferenceModalProps): JSX.Element {
    const playerKey = 'task-reference-modal'
    const sessionRecordingId = reference?.session_id || ''

    const logicProps = {
        sessionRecordingId,
        playerKey,
        autoPlay: false,
    }

    const { seekToTime } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { sessionPlayerData } = useValues(sessionRecordingPlayerLogic(logicProps))

    // Seek to reference start when modal opens and player is ready
    useEffect(() => {
        if (isOpen && reference && sessionPlayerData?.start && sessionPlayerData?.durationMs) {
            const startTimeMs = parseTimeToMs(reference.start_time)
            // Back up 2 seconds for context
            const timeToSeekTo = Math.max(startTimeMs - 2000, 0)
            seekToTime(timeToSeekTo)
        }
    }, [isOpen, reference, sessionPlayerData?.start, sessionPlayerData?.durationMs, seekToTime])

    if (!reference) {
        return <></>
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple title="" width={1200} closable hideCloseButton>
            <LemonModal.Content embedded>
                <div className="flex flex-col">
                    <header className="flex items-center justify-between gap-2 p-2 border-b">
                        <span className="text-sm text-muted-alt flex-1 min-w-0 truncate">
                            {reference.content || 'Reference'}
                        </span>
                        <LemonButton size="xsmall" icon={<IconX />} onClick={onClose} />
                    </header>
                    <SessionRecordingPlayer
                        sessionRecordingId={sessionRecordingId}
                        playerKey={playerKey}
                        autoPlay={false}
                        noBorder
                    />
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
