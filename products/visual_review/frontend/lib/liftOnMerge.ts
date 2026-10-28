import type { QuarantineLiftEntryApi, QuarantinedIdentifierEntryApi, SnapshotApi } from '../generated/api.schemas'

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

export interface CleanQuarantinedStory {
    snapshot: SnapshotApi
    liftRequest: QuarantineLiftEntryApi | null
    quarantineReason: string | null
    /** The pending request waits for another picture than this run rendered, so it fails after the merge. */
    expectsOtherPicture: boolean
}

export interface CleanQuarantinedGroups {
    liftRequested: CleanQuarantinedStory[]
    notRequested: CleanQuarantinedStory[]
}

/** Splits the still quarantined stories that rendered clean by whether a pending lift request covers them. */
export function groupCleanQuarantinedStories(
    snapshots: SnapshotApi[],
    liftRequestByIdentifier: Record<string, QuarantineLiftEntryApi>,
    quarantinedIdentifiers: QuarantinedIdentifierEntryApi[]
): CleanQuarantinedGroups {
    const groups: CleanQuarantinedGroups = { liftRequested: [], notRequested: [] }
    for (const snapshot of snapshots) {
        // The snapshot list loads once per run, so a story unquarantined since then drops out here.
        const quarantine = quarantinedIdentifiers.find((q) => q.identifier === snapshot.identifier)
        if (!quarantine) {
            continue
        }
        const liftRequest = liftRequestByIdentifier[snapshot.identifier] ?? null
        const pendingRequest = liftRequest?.state === 'pending' ? liftRequest : null
        const renderedHash = snapshot.current_artifact?.content_hash
        const story: CleanQuarantinedStory = {
            snapshot,
            liftRequest,
            quarantineReason: quarantine.reason,
            // Without a linked artifact the rendered hash is unknown, which is not a mismatch.
            expectsOtherPicture: !!pendingRequest && !!renderedHash && pendingRequest.expected_hash !== renderedHash,
        }
        if (pendingRequest) {
            groups.liftRequested.push(story)
        } else {
            groups.notRequested.push(story)
        }
    }
    return groups
}
