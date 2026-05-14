import { colonDelimitedDuration } from 'lib/utils'

export function sessionDurationMs(firstSeen: string, lastSeen: string): number {
    const first = Date.parse(firstSeen)
    const last = Date.parse(lastSeen)
    if (Number.isNaN(first) || Number.isNaN(last)) {
        return 0
    }
    return Math.max(0, last - first)
}

export function relativeOffset(start: string, at: string): string {
    const startMs = Date.parse(start)
    const atMs = Date.parse(at)
    if (Number.isNaN(startMs) || Number.isNaN(atMs)) {
        return '—'
    }
    const diffSeconds = Math.max(0, Math.round((atMs - startMs) / 1000))
    return colonDelimitedDuration(diffSeconds, null)
}
