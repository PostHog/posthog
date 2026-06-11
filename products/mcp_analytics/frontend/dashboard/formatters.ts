import { humanFriendlyDuration, humanFriendlyLargeNumber } from 'lib/utils'

const EMPTY = '—'

export function formatNumber(n: number): string {
    if (!isFinite(n)) {
        return EMPTY
    }
    return humanFriendlyLargeNumber(n)
}

export function formatMs(n: number): string {
    if (!isFinite(n) || n === 0) {
        return EMPTY
    }
    if (n < 1000) {
        return `${Math.round(n)}ms`
    }
    return humanFriendlyDuration(n / 1000, { secondsPrecision: 1 })
}

export function formatDuration(seconds: number): string {
    if (!seconds || !isFinite(seconds)) {
        return EMPTY
    }
    if (seconds < 60) {
        return `${seconds}s`
    }
    return humanFriendlyDuration(seconds, { secondsPrecision: 0 })
}

export function truncateSessionId(id: string): string {
    if (id.length <= 12) {
        return id
    }
    return `${id.slice(0, 4)}…${id.slice(-4)}`
}
