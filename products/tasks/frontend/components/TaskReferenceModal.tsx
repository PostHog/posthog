import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPerson, IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
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

    const timestamp = reference.timestamp ? dayjs(reference.timestamp) : null

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple title="" width={1400} closable hideCloseButton>
            <LemonModal.Content embedded>
                <div className="flex flex-col">
                    {/* Header */}
                    <header className="flex items-center justify-between p-4 border-b">
                        <div className="flex-1 min-w-0">
                            <h2 className="text-lg font-semibold mb-1 line-clamp-2">
                                {reference.content || 'Reference'}
                            </h2>
                            <div className="flex items-center gap-3 text-sm text-muted">
                                <span className="font-mono">
                                    {reference.start_time} - {reference.end_time}
                                </span>
                                {timestamp && <span>{timestamp.format('MMM D, YYYY HH:mm')}</span>}
                            </div>
                        </div>
                        <LemonButton size="small" icon={<IconX />} onClick={onClose} />
                    </header>

                    {/* Context Grid */}
                    <div className="grid grid-cols-2 gap-6 p-4 border-b bg-bg-light">
                        {/* User Info */}
                        <div className="space-y-3">
                            <h4 className="text-xs font-semibold text-muted uppercase">User</h4>
                            <div className="flex items-center gap-2">
                                <IconPerson className="w-4 h-4 text-muted" />
                                <span className="font-mono text-sm truncate" title={reference.distinct_id}>
                                    {reference.distinct_id}
                                </span>
                            </div>
                            <div>
                                <span className="text-xs text-muted">Session ID</span>
                                <p className="font-mono text-xs truncate" title={reference.session_id}>
                                    {reference.session_id}
                                </p>
                            </div>
                        </div>

                        {/* Clustering Info */}
                        <div className="space-y-3">
                            <h4 className="text-xs font-semibold text-muted uppercase">Clustering</h4>
                            {reference.distance_to_centroid !== null && (
                                <div>
                                    <span className="text-xs text-muted">Distance to centroid</span>
                                    <p className="text-sm font-mono">{reference.distance_to_centroid.toFixed(4)}</p>
                                </div>
                            )}
                            <div>
                                <span className="text-xs text-muted">Linked at</span>
                                <p className="text-sm">{dayjs(reference.created_at).format('MMM D, YYYY HH:mm')}</p>
                            </div>
                        </div>
                    </div>

                    {/* Player */}
                    <div className="w-full">
                        <SessionRecordingPlayer
                            sessionRecordingId={sessionRecordingId}
                            playerKey={playerKey}
                            autoPlay={false}
                            noBorder
                        />
                    </div>
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
