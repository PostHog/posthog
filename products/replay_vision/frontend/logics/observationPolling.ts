const POLL_INTERVAL_MS = 3000
const POLL_KEY = 'pollObservations'
const OBSERVE_INFLIGHT_KEY = 'observeInFlightTimeout'

// A hung observe POST would otherwise spin the trigger until the logic remounts. If the request
// hasn't settled by here, release the in-flight lock and the loading state so the button recovers.
const OBSERVE_INFLIGHT_TIMEOUT_MS = 30_000

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

/**
 * Arm or disarm the observe self-heal. Keyed so a repeat call replaces the prior timer; the plugin
 * clears it on unmount. Fires `onTimeout` if an observe request never settles.
 */
export function scheduleObserveTimeout(
    disposables: ObservationPollDisposables | null,
    arm: boolean,
    onTimeout: () => void
): void {
    if (!disposables) {
        // Unmount already cleared every armed disposable; a late disarm has nothing to do.
        return
    }
    if (arm) {
        disposables.add(() => {
            const id = setTimeout(onTimeout, OBSERVE_INFLIGHT_TIMEOUT_MS)
            return () => clearTimeout(id)
        }, OBSERVE_INFLIGHT_KEY)
    } else {
        disposables.dispose(OBSERVE_INFLIGHT_KEY)
    }
}

// Observe only starts the workflow — poll through this grace window so the new card appears before its row lands.
export const OBSERVE_POLL_GRACE_MS = 30_000

export function shouldPollObservations(hasInFlight: boolean, pollUntil: number): boolean {
    return hasInFlight || Date.now() < pollUntil
}
