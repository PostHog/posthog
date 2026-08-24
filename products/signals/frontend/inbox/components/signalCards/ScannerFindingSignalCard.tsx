import { LemonTag } from '@posthog/lemon-ui'

import { Dayjs, dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'
import { identifierToHuman } from 'lib/utils/strings'

import type { ReplayVisionScannerFindingSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { RecordingPreview } from './RecordingPreview'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a raw `extra` payload to the replay-vision scanner-finding shape. */
export function isScannerFindingExtra(
    value: unknown
): value is Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.session_id === 'string' && typeof extra.problem_type === 'string' && 'confidence' in extra
}

/**
 * Findings carry `start_time`/`end_time` as second offsets from the recording start, and
 * `recording_start_time` as an absolute datetime. Combine them to get an instant the player can seek to.
 */
function findingSeekTime(recordingStartTime: string | null | undefined, offsetSeconds: number): Dayjs | undefined {
    if (!recordingStartTime) {
        return undefined
    }
    return dayjs(recordingStartTime).add(offsetSeconds, 'second')
}

/** Live card for a replay-vision scanner finding: thumbnail preview and a play affordance that seeks to the observation. */
export function ScannerFindingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi

    const confidencePct = Math.round(extra.confidence * 100)

    const activeDuration =
        extra.recording_active_seconds != null ? humanFriendlyDuration(extra.recording_active_seconds) : undefined
    const totalDuration = extra.recording_duration != null ? humanFriendlyDuration(extra.recording_duration) : undefined

    const findingWindow = `${colonDelimitedDuration(extra.start_time, 2)} to ${colonDelimitedDuration(extra.end_time, 2)}`

    return (
        <SignalCardShell
            signal={signal}
            label={extra.scanner_name}
            rightSlot={
                <div className="flex items-center gap-1 shrink-0">
                    <LemonTag type="caution" size="small">
                        {identifierToHuman(extra.problem_type)}
                    </LemonTag>
                    <LemonTag type="muted" size="small">
                        {confidencePct}% confidence
                    </LemonTag>
                </div>
            }
        >
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <RecordingPreview
                sessionId={extra.session_id}
                seekTime={findingSeekTime(extra.recording_start_time, extra.start_time)}
                exportedAssetId={extra.exported_asset_id}
                alt={`Recording preview for ${extra.scanner_name}`}
            />

            {/* Dot-separated meta line: affected user, finding window, active/total duration. */}
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-tertiary">
                {extra.distinct_id && (
                    <>
                        <span className="font-mono">{extra.distinct_id.slice(0, 10)}…</span>
                        <span>·</span>
                    </>
                )}
                <span className="font-mono">{findingWindow}</span>
                {(activeDuration || totalDuration) && (
                    <>
                        <span>·</span>
                        <span>
                            {activeDuration ? `${activeDuration} active` : null}
                            {activeDuration && totalDuration ? ' / ' : null}
                            {totalDuration ? `${totalDuration} total` : null}
                        </span>
                    </>
                )}
            </div>
        </SignalCardShell>
    )
}

export const scannerFindingSignalCardEntry: SignalCardEntry = {
    key: 'replay_vision',
    matches: (signal) => signal.source_product === 'replay_vision' && isScannerFindingExtra(signal.extra),
    Component: ScannerFindingSignalCard,
}
