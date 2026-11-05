import { useValues } from 'kea'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'

import { getVisionObservationsThumbnailRetrieveUrl } from 'products/replay_vision/frontend/generated/api'
import type { ReplayVisionScannerFindingSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { RecordingPreview } from './RecordingPreview'
import { findingSeekTime, recordingDurationSummary, shortDistinctId } from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/** Live card for a replay-vision scanner finding: thumbnail preview and a play affordance that seeks to the observation. */
export function ScannerFindingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const extra = signal.extra as Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi

    const activeDuration =
        extra.recording_active_seconds != null ? humanFriendlyDuration(extra.recording_active_seconds) : undefined
    const totalDuration = extra.recording_duration != null ? humanFriendlyDuration(extra.recording_duration) : undefined

    const findingWindow = `${colonDelimitedDuration(extra.start_time, 2)} to ${colonDelimitedDuration(extra.end_time, 2)}`
    const durationSummary = recordingDurationSummary(activeDuration, totalDuration)

    return (
        <SignalCardShell signal={signal} label={extra.scanner_name}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <RecordingPreview
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
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-tertiary">
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
            </div>
        </SignalCardShell>
    )
}
