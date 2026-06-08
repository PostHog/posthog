import { humanFriendlyDuration, humanFriendlyLargeNumber } from 'lib/utils'

export function formatNumber(n: number): string {
    if (!isFinite(n)) {
        return '—'
    }
    return humanFriendlyLargeNumber(n)
}

export function formatPercent(n: number): string {
    if (!isFinite(n)) {
        return '—'
    }
    return `${n.toFixed(n >= 10 ? 0 : 1)}%`
}

export function formatMs(n: number): string {
    if (!isFinite(n) || n === 0) {
        return '—'
    }
    if (n < 1000) {
        return `${Math.round(n)}ms`
    }
    return humanFriendlyDuration(n / 1000, { secondsPrecision: 1 })
}

export function formatDuration(seconds: number): string {
    if (!seconds || !isFinite(seconds)) {
        return '—'
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
