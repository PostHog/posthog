import { useValues } from 'kea'
import { useState } from 'react'

import { IconBug, IconCursorClick, IconGlobe, IconKeyboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'

import { getExportsContentRetrieveUrl } from '~/generated/core/api'

import type {
    SessionProblemEventEntryApi,
    SessionProblemSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { RecordingPreview } from './RecordingPreview'
import {
    TIMELINE_PREVIEW_COUNT,
    recordingDurationSummary,
    recordingSeekTime,
    shortDistinctId,
} from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/** Picks a glyph for a timeline event based on its interaction type. */
function EventGlyph({ entry }: { entry: SessionProblemEventEntryApi }): JSX.Element {
    const className = 'size-3.5 shrink-0 text-tertiary'
    switch (entry.event_type) {
        case 'click':
            return <IconCursorClick className={className} aria-hidden />
        case 'keypress':
        case 'input':
            return <IconKeyboard className={className} aria-hidden />
        case 'exception':
            return <IconBug className={className} aria-hidden />
        case 'pageview':
        case '$pageview':
            return <IconGlobe className={className} aria-hidden />
        default:
            return <IconGlobe className={className} aria-hidden />
    }
}

/** A single row in the problem-event timeline; its time opens the recording at that moment. */
function TimelineRow({
    entry,
    sessionId,
    sessionStartTime,
}: {
    entry: SessionProblemEventEntryApi
    sessionId: string
    sessionStartTime: string | undefined
}): JSX.Element {
    const primaryText = entry.interaction_text?.trim() || entry.event
    return (
        <li className="flex items-start gap-2 py-0.5">
            <EventGlyph entry={entry} />
            <div className="flex-1 min-w-0">
                <div className="text-xs text-primary truncate">{primaryText}</div>
                {entry.current_url && (
                    <div className="text-xs text-tertiary font-mono truncate">{entry.current_url}</div>
                )}
            </div>
            <ViewRecordingButton
                sessionId={sessionId}
                timestamp={recordingSeekTime(sessionStartTime, entry.timestamp)}
                openPlayerIn={RecordingPlayerType.Modal}
                size="xsmall"
                type="tertiary"
                label={entry.timestamp}
            />
        </li>
    )
}

/** Live card for a session-replay problem segment: a replay link-out and an event timeline. */
export function SessionReplaySignalCard({ signal }: SignalCardProps): JSX.Element {
    const [showAllEvents, setShowAllEvents] = useState(false)

    const extra = signal.extra as Record<string, unknown> & SessionProblemSignalExtraApi

    const segmentSeekTime = recordingSeekTime(extra.session_start_time ?? undefined, extra.start_time)

    const { getRecordingExists, isRecordingExistsLoading } = useValues(sessionRecordingInfoLogic)
    const { currentTeamId } = useValues(teamLogic)
    const recordingExists = getRecordingExists(extra.session_id)
    const recordingExistsLoading = isRecordingExistsLoading(extra.session_id)

    const events = extra.event_history ?? []
    const visibleEvents = showAllEvents ? events : events.slice(0, TIMELINE_PREVIEW_COUNT)

    const activeDuration =
        extra.session_active_seconds !== undefined ? humanFriendlyDuration(extra.session_active_seconds) : undefined
    const totalDuration =
        extra.session_duration !== undefined ? humanFriendlyDuration(extra.session_duration) : undefined
    const durationSummary = recordingDurationSummary(activeDuration, totalDuration)

    return (
        <SignalCardShell signal={signal} label={extra.segment_title}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            {/* Both open the recording at the segment in the player modal and disable when it wasn't
                captured. The screenshot frame is used when the emitter exported one, since it shows
                what the user saw without opening the player. */}
            {typeof extra.exported_asset_id === 'number' ? (
                <RecordingPreview
                    sessionId={extra.session_id}
                    seekTime={segmentSeekTime}
                    thumbnailSrc={
                        currentTeamId !== null
                            ? getExportsContentRetrieveUrl(String(currentTeamId), extra.exported_asset_id)
                            : undefined
                    }
                    alt={`Recording preview for ${extra.segment_title}`}
                />
            ) : (
                <>
                    <ViewRecordingButton
                        sessionId={extra.session_id}
                        timestamp={segmentSeekTime}
                        openPlayerIn={RecordingPlayerType.Modal}
                        checkRecordingExists
                        label="View replay"
                        type="secondary"
                        size="small"
                        className="mb-2"
                        loading={recordingExistsLoading}
                    />
                    {recordingExists === false && (
                        <p className="text-xs text-tertiary mb-2">This recording is no longer available.</p>
                    )}
                </>
            )}

            {/* Dot-separated meta line: affected user, segment window, active/total duration. */}
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-tertiary mb-2">
                <span className="font-mono">{shortDistinctId(extra.distinct_id)}</span>
                <span>·</span>
                <span className="font-mono">
                    {extra.start_time} to {extra.end_time}
                </span>
                {durationSummary && (
                    <>
                        <span>·</span>
                        <span>{durationSummary}</span>
                    </>
                )}
            </div>

            {/* Compact problem-event timeline, collapsed past the preview count. */}
            {events.length > 0 && (
                <div className="border-t pt-2">
                    <ul className="flex flex-col">
                        {visibleEvents.map((entry, index) => (
                            <TimelineRow
                                key={`${entry.timestamp}-${index}`}
                                entry={entry}
                                sessionId={extra.session_id}
                                sessionStartTime={extra.session_start_time ?? undefined}
                            />
                        ))}
                    </ul>
                    {events.length > TIMELINE_PREVIEW_COUNT && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setShowAllEvents(!showAllEvents)}
                            className="mt-1"
                        >
                            {showAllEvents ? 'Show fewer events' : `Show all ${events.length} events`}
                        </LemonButton>
                    )}
                </div>
            )}
        </SignalCardShell>
    )
}
