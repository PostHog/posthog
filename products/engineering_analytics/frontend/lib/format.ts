// Compact headline formatting for stat tiles and share rows. Tables keep the precise formats from
// runTables (formatCost) and lib/utils — these are for the big numbers where "$11.4k" beats "$11,400.00".

export function compactUsd(usd: number | null | undefined): string {
    if (usd == null) {
        return '—'
    }
    if (usd >= 10000) {
        return `$${(usd / 1000).toFixed(1)}k`
    }
    if (usd >= 100) {
        return `$${Math.round(usd).toLocaleString()}`
    }
    return `$${usd.toFixed(2)}`
}

export function compactCount(count: number | null | undefined): string {
    if (count == null) {
        return '—'
    }
    if (count >= 10000) {
        return `${(count / 1000).toFixed(count >= 100000 ? 0 : 1)}k`
    }
    return Math.round(count).toLocaleString()
}

// Below this many hours the PR-timing format stays in hours; above, one-decimal days.
const HOURS_BEFORE_DAYS = 48

/** Hours below two days, one-decimal days above — the PR-timing headline format. */
export function compactHours(seconds: number | null | undefined): string {
    if (seconds == null) {
        return '—'
    }
    const hours = seconds / 3600
    return hours < HOURS_BEFORE_DAYS ? `${Math.round(hours)}` : `${(hours / 24).toFixed(1)}`
}

export function compactHoursUnit(seconds: number | null | undefined): string {
    if (seconds == null) {
        return ''
    }
    return seconds / 3600 < HOURS_BEFORE_DAYS ? 'hours' : 'days'
}

/** The compactHours ladder as one short label: "17h" below two days, "3.2d" above. */
export function compactHoursLabel(seconds: number | null | undefined): string {
    if (seconds == null) {
        return '—'
    }
    return `${compactHours(seconds)}${seconds / 3600 < HOURS_BEFORE_DAYS ? 'h' : 'd'}`
}

export function compactMinutes(minutes: number | null | undefined): string {
    if (minutes == null) {
        return '—'
    }
    if (minutes >= 1000) {
        return `${(minutes / 1000).toFixed(0)}k min`
    }
    return `${Math.round(minutes)} min`
}

export function percent(rate: number | null | undefined, precision: number = 0): string {
    return rate == null ? '—' : `${(rate * 100).toFixed(precision)}%`
}
