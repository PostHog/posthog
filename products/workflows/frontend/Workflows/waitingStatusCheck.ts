const WAITING_STATUS_CHECK_INTERVAL_MS = 10_000
const WAITING_STATUS_CHECK_KEY = 'waitingStatusCheck'

interface Disposables {
    registry: ReadonlyMap<string, unknown>
    add: (setup: () => () => void, key: string) => void
    dispose: (key: string) => boolean
}

export function syncWaitingStatusCheck(disposables: Disposables, isWaiting: boolean, checkStatus: () => void): void {
    if (!isWaiting) {
        disposables.dispose(WAITING_STATUS_CHECK_KEY)
        return
    }
    if (disposables.registry.has(WAITING_STATUS_CHECK_KEY)) {
        return
    }
    let registering = true
    disposables.add(() => {
        // Setup runs again each time a hidden tab shows. The person often verifies the domain in
        // another tab, so check at once on return instead of waiting for the next tick.
        if (!registering) {
            checkStatus()
        }
        const timer = window.setInterval(checkStatus, WAITING_STATUS_CHECK_INTERVAL_MS)
        return () => clearInterval(timer)
    }, WAITING_STATUS_CHECK_KEY)
    registering = false
}
