const WAITING_STATUS_CHECK_INTERVAL_MS = 10_000

interface Disposables {
    add: (setup: () => () => void) => void
}

export function checkWaitingStatusWhileVisible(disposables: Disposables, checkStatus: () => void): void {
    // Setup runs again each time a hidden tab shows. The person often verifies the domain in another
    // tab, so check at once on return instead of waiting for the next tick.
    disposables.add(() => {
        checkStatus()
        const timer = window.setInterval(checkStatus, WAITING_STATUS_CHECK_INTERVAL_MS)
        return () => clearInterval(timer)
    })
}
