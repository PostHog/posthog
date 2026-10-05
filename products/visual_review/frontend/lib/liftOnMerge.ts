import type { QuarantineLiftEntryApi, SnapshotApi } from '../generated/api.schemas'

/**
 * Why a lift on merge cannot be requested for this snapshot, or null when it can.
 *
 * The lift waits for the default branch to render one exact picture. A changed or new
 * picture qualifies only after a reviewer approves it, and requesting the lift never approves it.
 */
export function liftOnMergeDisabledReason(snapshot: SnapshotApi): string | null {
    if (snapshot.result === 'removed') {
        return 'A removed snapshot has no picture for the default branch to render'
    }
    if (snapshot.result !== 'unchanged' && snapshot.review_state !== 'approved') {
        return 'Approve the new picture first'
    }
    return null
}

/** The request to show per identifier: its pending one, or else its newest. Expects the list newest first. */
export function liftRequestsByIdentifier(requests: QuarantineLiftEntryApi[]): Record<string, QuarantineLiftEntryApi> {
    const byIdentifier: Record<string, QuarantineLiftEntryApi> = {}
    for (const request of requests) {
        const shown = byIdentifier[request.identifier]
        if (!shown || (request.state === 'pending' && shown.state !== 'pending')) {
            byIdentifier[request.identifier] = request
        }
    }
    return byIdentifier
}
