export function shortenSessionId(sessionId: string): string {
    if (sessionId.length <= 13) {
        return sessionId
    }
    return `${sessionId.slice(0, 8)}…${sessionId.slice(-4)}`
}

export function sessionDurationMs(firstSeen: string, lastSeen: string): number {
    const first = Date.parse(firstSeen)
    const last = Date.parse(lastSeen)
    if (Number.isNaN(first) || Number.isNaN(last)) {
        return 0
    }
    return Math.max(0, last - first)
}

export function formatRelativeOffset(start: string, at: string): string {
    const startMs = Date.parse(start)
    const atMs = Date.parse(at)
    if (Number.isNaN(startMs) || Number.isNaN(atMs)) {
        return '—'
    }
    const totalSeconds = Math.max(0, Math.round((atMs - startMs) / 1000))
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60
    const mm = String(minutes).padStart(2, '0')
    const ss = String(seconds).padStart(2, '0')
    if (hours > 0) {
        return `${String(hours).padStart(2, '0')}:${mm}:${ss}`
    }
    return `${mm}:${ss}`
}

export function formatDuration(ms: number | null | undefined): string {
    if (ms === null || ms === undefined) {
        return '—'
    }
    if (ms < 1000) {
        return `${ms}ms`
    }
    const seconds = ms / 1000
    if (seconds < 60) {
        return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
    }
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.round(seconds - minutes * 60)
    if (minutes < 60) {
        return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`
    }
    const hours = Math.floor(minutes / 60)
    const remainingMinutes = minutes - hours * 60
    return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`
}
