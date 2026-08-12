const POLL_INTERVAL_MS = 3000
const POLL_KEY = 'pollObservations'

interface ObservationPollDisposables {
    add: (setup: () => () => void, key?: string) => void
    dispose: (key: string) => void
}

/**
 * Start or stop the recurring observation refresh. Keyed so a repeat call replaces the prior timer;
 * the kea-disposables plugin clears it on unmount and pauses it while the tab is hidden.
 */
export function scheduleObservationPoll(
    disposables: ObservationPollDisposables,
    shouldPoll: boolean,
    poll: () => void
): void {
    if (shouldPoll) {
        disposables.add(() => {
            const id = setTimeout(poll, POLL_INTERVAL_MS)
            return () => clearTimeout(id)
        }, POLL_KEY)
    } else {
        disposables.dispose(POLL_KEY)
    }
}

// Observe only starts the workflow — poll through this grace window so the new card appears before its row lands.
export const OBSERVE_POLL_GRACE_MS = 30_000

export function shouldPollObservations(hasInFlight: boolean, pollUntil: number): boolean {
    return hasInFlight || Date.now() < pollUntil
}
