import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

const EMPTY = '—'

// Sparkline hover label for a bucket key ('YYYY-MM-DD' or 'YYYY-MM-DD HH:mm:ss'). Date only,
// matching the metric insight's hover labels.
export function formatBucketLabel(bucket: string): string {
    const d = dayjs(bucket)
    return d.isValid() ? d.format('MMM D') : bucket
}

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

// Seconds-first duration for chart axes and tooltips: 500 → "0.5s", 1500 → "1.5s",
// 2000 → "2s". One unit for the whole scale so axis ticks stay comparable; only
// sub-100ms values keep ms, where seconds would round to a flat 0.1s.
export function formatMsAsSeconds(n: number): string {
    if (!isFinite(n)) {
        return EMPTY
    }
    if (n === 0) {
        return '0'
    }
    if (n < 100) {
        return `${Math.round(n)}ms`
    }
    const rounded = Math.round(n / 100) / 10
    return `${rounded}s`
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
