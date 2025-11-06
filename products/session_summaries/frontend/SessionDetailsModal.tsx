import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconEllipsis, IconShare, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

interface SessionKeyAction {
    event_id: string
    event_uuid: string
    session_id: string
    description: string
    abandonment: boolean
    confusion: boolean
    exception: string | null
    timestamp: string
    milliseconds_since_start: number
    window_id: string
    current_url: string
    event: string
    event_type: string | null
    event_index: number
}

interface SessionEvent {
    segment_name: string
    segment_outcome: string
    segment_success: boolean
    segment_index: number
    previous_events_in_segment: SessionKeyAction[]
    target_event: SessionKeyAction
    next_events_in_segment: SessionKeyAction[]
}

interface SessionDetailsModalProps {
    isOpen: boolean
    onClose: () => void
    event: SessionEvent | null
}

export function SessionDetailsModal({ isOpen, onClose, event }: SessionDetailsModalProps): JSX.Element {
    const sessionRecordingId = '019a5952-8c20-7fe7-a254-bfd8fea8a1d3'
    const playerKey = 'session-details-modal'

    const logicProps = {
        sessionRecordingId,
        playerKey,
        autoPlay: false,
    }

    const { seekToTime } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { sessionPlayerData } = useValues(sessionRecordingPlayerLogic(logicProps))

    // Seek to target event timestamp when modal opens and player is loaded
    useEffect(() => {
        if (isOpen && event && sessionPlayerData) {
            seekToTime(event.target_event.milliseconds_since_start)
        }
    }, [isOpen, event, sessionPlayerData, seekToTime])

    if (!event) {
        return <></>
    }

    const formattedTimestamp = dayjs(event.target_event.timestamp).format('MMMM D, YYYY, h:mm A')

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            simple
            title=""
            width={1600}
            closable={true}
            hideCloseButton={true}
        >
            <LemonModal.Content embedded>
                <div className="flex flex-col">
                    {/* Header */}
                    <header className="flex items-center justify-between p-4 border-b">
                        <div>
                            <h2 className="text-lg font-semibold mb-0">Session {event.target_event.session_id}</h2>
                            <p className="text-sm text-muted mb-0">{formattedTimestamp}</p>
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonButton size="small" icon={<IconThumbsUp />} />
                            <LemonButton size="small" icon={<IconThumbsDown />} />
                            <div className="h-6 w-px bg-border mx-2" />
                            <LemonButton size="small" icon={<IconShare />} />
                            <LemonButton size="small" icon={<IconEllipsis />} />
                        </div>
                    </header>

                    {/* Content Grid */}
                    <div className="grid grid-cols-3 gap-8 p-6">
                        {/* Quick Summary Section */}
                        <div className="space-y-4">
                            <div className="space-y-4">
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">What user was doing</h4>
                                    <p className="text-sm mb-0">{event.segment_name}</p>
                                </div>
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">What's the outcome</h4>
                                    <div className="space-y-2">
                                        <div className="text-sm">
                                            <b>{event.segment_success ? 'Successful' : 'Failed'}.</b>{' '}
                                            {event.segment_outcome}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="space-y-4">
                            <div className="space-y-4">
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">What confirmed the pattern</h4>
                                    <p className="text-sm mb-0">{event.target_event.description}</p>
                                </div>
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">Where it happened</h4>
                                    <p className="text-sm mb-0 break-all">
                                        {event.target_event.current_url || 'unknown'}
                                    </p>
                                </div>
                            </div>
                        </div>

                        {/* Outcome Section */}
                        <div className="space-y-4">
                            <div className="space-y-4">
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">What happened before</h4>
                                    {event.previous_events_in_segment.length > 0 ? (
                                        <ul className="text-sm mb-0 list-disc list-inside space-y-1">
                                            {event.previous_events_in_segment.map((e, idx) => (
                                                <li key={idx}>{e.description}</li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <p className="text-sm mb-0">Nothing happened</p>
                                    )}
                                </div>
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">What happened after</h4>
                                    {event.next_events_in_segment.length > 0 ? (
                                        <ul className="text-sm mb-0 list-disc list-inside space-y-1">
                                            {event.next_events_in_segment.map((e, idx) => (
                                                <li key={idx}>{e.description}</li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <p className="text-sm mb-0">Nothing happened</p>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Replay Player */}
                    <div className="w-full">
                        <SessionRecordingPlayer
                            sessionRecordingId={sessionRecordingId}
                            playerKey={playerKey}
                            autoPlay={false}
                            noBorder={true}
                        />
                    </div>
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
