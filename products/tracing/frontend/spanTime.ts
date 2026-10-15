export function formatDuration(durationNano: number): string {
    const us = durationNano / 1_000
    if (us < 100) {
        return `${us.toFixed(1)}\u00B5s`
    }
    const ms = us / 1_000
    if (ms < 1000) {
        return `${ms.toFixed(ms < 10 ? 2 : 1)}ms`
    }
    return `${(ms / 1000).toFixed(2)}s`
}

/**
 * Parse an ISO 8601 timestamp string to microseconds since epoch.
 * `Date.getTime()` only gives millisecond resolution, losing sub-ms
 * precision from timestamps like "2024-01-15T10:30:00.123456Z".
 */
export function parseTimestampUs(iso: string): number {
    const ms = new Date(iso).getTime()
    // Extract fractional seconds beyond milliseconds
    const dot = iso.indexOf('.')
    if (dot === -1) {
        return ms * 1_000
    }
    // Find the end of fractional digits (before 'Z')
    const fracEnd = iso.search(/[Z+-](\d\d:\d\d)?$/i)
    if (fracEnd === -1) {
        return ms * 1_000
    }
    const fracStr = iso.slice(dot + 1, fracEnd)
    // Pad or truncate to 6 digits (microseconds)
    const padded = fracStr.padEnd(6, '0').slice(0, 6)
    const totalUs = parseInt(padded, 10)
    // ms already includes the first 3 fractional digits, so add the remaining sub-ms part
    const subMsUs = totalUs % 1_000
    return ms * 1_000 + subMsUs
}
