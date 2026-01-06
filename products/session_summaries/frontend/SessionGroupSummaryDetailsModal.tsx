import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconShare, IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'

import { SessionRecordingSidebarTab } from '~/types'

import { SessionGroupSummaryDetailsMetadata } from './SessionGroupSummaryDetailsMetadata'
import { PatternAssignedEventSegmentContext } from './types'
import { getIssueTags } from './utils'

interface SessionDetailsModalProps {
    isOpen: boolean
    onClose: () => void
    event: PatternAssignedEventSegmentContext | null
}

export function SessionGroupSummaryDetailsModal({ isOpen, onClose, event }: SessionDetailsModalProps): JSX.Element {
    const playerKey = 'session-details-modal'
    const sessionRecordingId = event?.target_event?.session_id
    const logicProps = {
        sessionRecordingId: sessionRecordingId || '',
        playerKey,
        autoPlay: false,
    }
    const { seekToTime } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { sessionPlayerData } = useValues(sessionRecordingPlayerLogic(logicProps))
    const { setTab } = useActions(playerSidebarLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))
    const { sessionSummary } = useValues(playerMetaLogic(logicProps))
    // Scrolling to a bit before the moment to better notice it
    const timeToSeekTo = (ms: number): number => Math.max(ms - 4000, 0)
    // Seek to target event timestamp when modal opens and player is loaded
    useEffect(() => {
        if (isOpen && event?.target_event && sessionPlayerData) {
            seekToTime(timeToSeekTo(event.target_event.milliseconds_since_start))
        }
    }, [isOpen, event, sessionPlayerData, seekToTime])
    // Automatically open sidebar, select AI summary tab, and trigger summary fetch when modal opens
    useEffect(() => {
        if (isOpen && sessionPlayerData) {
            setSidebarOpen(true)
            setTab(SessionRecordingSidebarTab.SESSION_SUMMARY)
            // Only trigger summary fetch if it hasn't been fetched yet
            if (!sessionSummary) {
                summarizeSession()
            }
        }
    }, [isOpen, sessionPlayerData, sessionSummary, setSidebarOpen, setTab, summarizeSession])
    // Handle conditional rendering after all hooks
    if (!event || !event.target_event) {
        return <></>
    }
    // Raise error if recording id is not found
    if (!sessionRecordingId) {
        throw new Error('Session recording id not found')
    }
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
                            <h2 className="text-lg font-semibold mb-1">
                                {event.target_event.description}
                                <span className="text-muted font-normal ml-2">
                                    @ {colonDelimitedDuration(event.target_event.milliseconds_since_start / 1000)}
                                </span>
                            </h2>
                            <SessionGroupSummaryDetailsMetadata
                                event={event}
                                issueTags={getIssueTags(event.target_event)}
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            {/* TODO: Enable thumbs up/down for feedback */}
                            {/* <LemonButton size="small" icon={<IconThumbsUp />} />
                            <LemonButton size="small" icon={<IconThumbsDown />} />
                            <div className="h-6 w-px bg-border mx-2" /> */}
                            <LemonButton
                                size="small"
                                icon={<IconShare />}
                                onClick={() => void copyToClipboard(window.location.href, 'link')}
                            />
                            <LemonButton size="small" icon={<IconX />} onClick={onClose} />
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
                                    <p className="text-sm mb-0">
                                        {event.target_event.description}
                                        {event.target_event.event && (
                                            <>
                                                {' ('}
                                                <code className="text-xs text-muted bg-fill-secondary px-1 py-0.5 rounded">
                                                    {event.target_event.event}
                                                    {event.target_event.event_type &&
                                                        ` (${event.target_event.event_type})`}
                                                </code>
                                                )
                                            </>
                                        )}
                                    </p>
                                </div>
                                <div>
                                    <h4 className="text-sm font-medium text-muted mb-1">Where it happened</h4>
                                    <p
                                        className="text-sm mb-0 break-all truncate"
                                        title={event.target_event.current_url || undefined}
                                    >
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
