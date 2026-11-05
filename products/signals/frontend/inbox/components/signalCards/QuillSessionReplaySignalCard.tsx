import { useValues } from 'kea'
import { useState } from 'react'

import { IconBug, IconCursorClick, IconGlobe, IconKeyboard } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'

import { getExportsContentRetrieveUrl } from '~/generated/core/api'

import type {
    SessionProblemEventEntryApi,
    SessionProblemSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { QuillRecordingPreview } from './QuillRecordingPreview'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { QuillSignalRecordingButton } from './QuillSignalRecordingButton'
import {
    TIMELINE_PREVIEW_COUNT,
    recordingDurationSummary,
    recordingSeekTime,
    shortDistinctId,
} from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Picks a glyph for a timeline event based on its interaction type. */
function QuillEventGlyph({ entry }: { entry: SessionProblemEventEntryApi }): JSX.Element {
    const className = 'mt-0.5 size-3.5 shrink-0 text-muted-foreground'
    switch (entry.event_type) {
        case 'click':
            return <IconCursorClick className={className} aria-hidden />
        case 'keypress':
        case 'input':
            return <IconKeyboard className={className} aria-hidden />
        case 'exception':
            return <IconBug className={className} aria-hidden />
        default:
            return <IconGlobe className={className} aria-hidden />
    }
}

/** A single row in the problem-event timeline; its time opens the recording at that moment. */
function QuillTimelineRow({
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
            <QuillEventGlyph entry={entry} />
            <div className="flex min-w-0 flex-1 flex-col">
                <Text size="xs" render={<span />} className="truncate">
                    {primaryText}
                </Text>
                {entry.current_url && (
                    <Text size="xs" variant="muted" render={<span />} className="truncate font-mono">
                        {entry.current_url}
                    </Text>
                )}
            </div>
            <QuillSignalRecordingButton
                sessionId={sessionId}
                timestamp={recordingSeekTime(sessionStartTime, entry.timestamp)}
                label={entry.timestamp}
                size="sm"
                className="shrink-0"
            />
        </li>
    )
}

/** Quill sibling of `SessionReplaySignalCard`: a replay link-out and an event timeline. */
export function QuillSessionReplaySignalCard({ signal }: SignalCardProps): JSX.Element {
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
        <QuillSignalCardShell signal={signal} label={extra.segment_title}>
            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            {/* Both open the recording at the segment in the player modal and disable when it wasn't
                captured. The screenshot frame is used when the emitter exported one, since it shows
                what the user saw without opening the player. */}
            {typeof extra.exported_asset_id === 'number' ? (
                <QuillRecordingPreview
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
                    <QuillSignalRecordingButton
                        sessionId={extra.session_id}
                        timestamp={segmentSeekTime}
                        checkRecordingExists
                        label="View replay"
                        variant="outline"
                        loading={recordingExistsLoading}
                        className="self-start"
                    />
                    {recordingExists === false && (
                        <Text size="xs" variant="muted" className="m-0">
                            This recording is no longer available.
                        </Text>
                    )}
                </>
            )}

            {/* Dot-separated meta line: affected user, segment window, active/total duration. */}
            <Text size="xs" variant="muted" render={<div />} className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono">{shortDistinctId(extra.distinct_id)}</span>
                <span>·</span>
                <span className="font-mono">{`${extra.start_time} to ${extra.end_time}`}</span>
                {durationSummary && (
                    <>
                        <span>·</span>
                        <span>{durationSummary}</span>
                    </>
                )}
            </Text>

            {/* Compact problem-event timeline, collapsed past the preview count. */}
            {events.length > 0 && (
                <div className="flex flex-col gap-1 border-t border-border pt-2">
                    <ul className="m-0 flex list-none flex-col p-0">
                        {visibleEvents.map((entry, index) => (
                            <QuillTimelineRow
                                key={`${entry.timestamp}-${index}`}
                                entry={entry}
                                sessionId={extra.session_id}
                                sessionStartTime={extra.session_start_time ?? undefined}
                            />
                        ))}
                    </ul>
                    {events.length > TIMELINE_PREVIEW_COUNT && (
                        <Button size="sm" onClick={() => setShowAllEvents(!showAllEvents)} className="self-start">
                            {showAllEvents ? 'Show fewer events' : `Show all ${events.length} events`}
                        </Button>
                    )}
                </div>
            )}
        </QuillSignalCardShell>
    )
}
