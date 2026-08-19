import { useValues } from 'kea'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReplayObservationApi } from 'products/replay_vision/frontend/generated/api.schemas'
import {
    readErrorMessage,
    readReasoning,
    readSummary,
    readTitle,
} from 'products/replay_vision/frontend/utils/observation'

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
    failed: 'the scan could not be started',
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
        const reason = readErrorMessage(observation)
        return (
            <div className="px-3 py-2 text-sm">
                <p className="m-0 text-secondary">Could not watch this recording{reason ? `: ${reason}` : '.'}</p>
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
