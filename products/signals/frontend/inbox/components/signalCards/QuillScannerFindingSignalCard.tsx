import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'

import { getVisionObservationsThumbnailRetrieveUrl } from 'products/replay_vision/frontend/generated/api'
import type { ReplayVisionScannerFindingSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { QuillRecordingPreview } from './QuillRecordingPreview'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { findingSeekTime, recordingDurationSummary, shortDistinctId } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Quill sibling of `ScannerFindingSignalCard`: thumbnail preview and a play affordance that seeks to the observation. */
export function QuillScannerFindingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const extra = signal.extra as Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi

    const activeDuration =
        extra.recording_active_seconds != null ? humanFriendlyDuration(extra.recording_active_seconds) : undefined
    const totalDuration = extra.recording_duration != null ? humanFriendlyDuration(extra.recording_duration) : undefined
    const durationSummary = recordingDurationSummary(activeDuration, totalDuration)

    const findingWindow = `${colonDelimitedDuration(extra.start_time, 2)} to ${colonDelimitedDuration(extra.end_time, 2)}`

    return (
        <QuillSignalCardShell signal={signal} label={extra.scanner_name}>
            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            <QuillRecordingPreview
                sessionId={extra.session_id}
                seekTime={findingSeekTime(extra.recording_start_time, extra.start_time)}
                thumbnailSrc={
                    currentTeamId !== null
                        ? getVisionObservationsThumbnailRetrieveUrl(String(currentTeamId), extra.observation_id)
                        : undefined
                }
                alt={`Recording preview for ${extra.scanner_name}`}
            />

            {/* Dot-separated meta line: affected user, finding window, active/total duration. */}
            <Text size="xs" variant="muted" render={<div />} className="flex flex-wrap items-center gap-1.5">
                {extra.distinct_id && (
                    <>
                        <span className="font-mono">{shortDistinctId(extra.distinct_id)}</span>
                        <span>·</span>
                    </>
                )}
                <span className="font-mono">{findingWindow}</span>
                {durationSummary && (
                    <>
                        <span>·</span>
                        <span>{durationSummary}</span>
                    </>
                )}
            </Text>
        </QuillSignalCardShell>
    )
}
