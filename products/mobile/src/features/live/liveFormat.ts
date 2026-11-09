import type { LiveStatus } from './liveController'

/** "just now", "12 s ago", "3 min ago": live data is never older than a few minutes on screen. */
export function agoText(at: number, now: number): string {
    const seconds = Math.max(0, Math.floor((now - at) / 1000))
    if (seconds < 5) {
        return 'just now'
    }
    if (seconds < 60) {
        return `${seconds} s ago`
    }
    const minutes = Math.floor(seconds / 60)
    return minutes < 60 ? `${minutes} min ago` : `${Math.floor(minutes / 60)} h ago`
}

export function statusText(status: LiveStatus, updatedAt: number | null, now: number): string {
    switch (status) {
        case 'paused':
            return 'Paused'
        case 'reconnecting':
            return 'Reconnecting…'
        case 'loading':
            return 'Loading…'
        case 'live':
            return updatedAt === null ? 'Live' : `Live · updated ${agoText(updatedAt, now)}`
    }
}
