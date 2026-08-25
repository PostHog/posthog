import { useValues } from 'kea'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReplayObservationApi } from 'products/replay_vision/frontend/generated/api.schemas'
import { readErrorKind, readReasoning, readSummary, readTitle } from 'products/replay_vision/frontend/utils/observation'

import { replayVisionScanWidgetLogic } from './replayVisionScanWidgetLogic'

export interface ReplayVisionScanWidgetProps {
    scanId: string
    sessionIds: string[]
    /** Sessions the scan did not start, with the reason, so the user is not left waiting on them. */
    skipped: { sessionId: string; reason: string }[]
}

const SKIP_MESSAGES: Record<string, string> = {
    skipped_quota: "this project's monthly Replay Vision credits are used up",
    skipped_scanner_limit: 'this scanner reached its own credit limit',
    skipped_limit: 'too many scans were already running',
    no_replay_data: 'no replay data was saved',
    failed: 'the scan could not be started',
}

// Keyed on the `error_reason` kind, never the message stored beside it: that half is written for us and
// reads as internal text in a chat bubble. Kinds come from `products/replay_vision/backend/error_kinds.py`.
const FAILURE_MESSAGES: Record<string, string> = {
    no_recording: 'No replay data was saved for it.',
    no_snapshots: 'It has no video to watch yet. Try again in a few minutes.',
    no_events: 'It has no events recorded against it.',
    too_short: 'It is too short to watch.',
    too_long: 'It is too long to watch.',
    too_inactive: 'It has too little activity to watch.',
    provider_transient: 'The AI provider was unavailable. Try again.',
    provider_rejected: 'The AI provider could not process it.',
    rasterization_failed: 'It could not be rendered for the AI to watch.',
    validation_failed: 'The scan did not return a usable result.',
    infra_transient: 'PostHog was at capacity. Try again.',
    orphaned: 'The scan stopped before it finished. Try again.',
}

export function ReplayVisionScanWidget({ scanId, sessionIds, skipped }: ReplayVisionScanWidgetProps): JSX.Element {
    const { gaveUp, latestPerSession, pendingCount } = useValues(replayVisionScanWidgetLogic({ scanId, sessionIds }))
    const skippedByReason = Object.entries(
        skipped.reduce<Record<string, number>>((counts, entry) => {
            counts[entry.reason] = (counts[entry.reason] ?? 0) + 1
            return counts
        }, {})
    )

    return (
        <div className="overflow-hidden rounded border bg-surface-primary">
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
                <span className="text-sm font-semibold">
                    {pendingCount === 0
                        ? 'Scan complete'
                        : gaveUp
                          ? `${pendingCount} recording${pendingCount === 1 ? '' : 's'} still running`
                          : `Watching ${pendingCount} of ${sessionIds.length} recordings`}
                </span>
                {pendingCount > 0 && !gaveUp && <Spinner />}
            </div>

            {skippedByReason.length > 0 && (
                <LemonBanner type="warning" className="m-3">
                    {skippedByReason.map(([reason, count]) => (
                        <p key={reason} className="m-0">
                            {count} recording{count === 1 ? ' was' : 's were'} not scanned because{' '}
                            {SKIP_MESSAGES[reason] ?? 'the scan could not be started'}.
                        </p>
                    ))}
                </LemonBanner>
            )}

            <div className="divide-y">
                {latestPerSession.map((observation) => (
                    <ObservationRow key={observation.id} observation={observation} />
                ))}
                {pendingCount > 0 && gaveUp && (
                    <p className="m-0 px-3 py-3 text-sm text-secondary">
                        These are taking longer than usual. Their results will appear on the recordings when they
                        finish.
                    </p>
                )}
                {latestPerSession.length === 0 && pendingCount > 0 && !gaveUp && (
                    <p className="m-0 px-3 py-3 text-sm text-secondary">Starting the scans...</p>
                )}
            </div>
        </div>
    )
}

function ObservationRow({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    if (observation.status === 'pending' || observation.status === 'running') {
        return (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-secondary">
                <Spinner />
                <span>Still watching</span>
            </div>
        )
    }

    if (observation.status !== 'succeeded') {
        const detail = FAILURE_MESSAGES[readErrorKind(observation) ?? '']
        return (
            <div className="px-3 py-2 text-sm">
                <p className="m-0 text-secondary">
                    {['Could not watch this recording.', detail].filter(Boolean).join(' ')}
                </p>
            </div>
        )
    }

    // Summarizers write a title and a body; a monitor scan on the same widget has reasoning instead.
    const title = readTitle(observation)
    const body = readSummary(observation) ?? readReasoning(observation)

    return (
        <div className="px-3 py-2 text-sm">
            {title && <p className="m-0 font-semibold">{title}</p>}
            {body && <p className="m-0 mt-0.5 text-secondary">{body}</p>}
            <Link to={urls.replayVisionObservation(observation.id)} className="text-xs">
                View details
            </Link>
        </div>
    )
}
