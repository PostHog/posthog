import { dayjs, Dayjs } from 'lib/dayjs'

import type { ObservationLabelDayCountApi, ObservationVersionMarkerApi } from '../generated/api.schemas'

export interface LabelChartData {
    labels: string[]
    /** Full YYYY-MM-DD date per bar; markers must match on this, since bar labels drop the year. */
    dates: string[]
    up: number[]
    down: number[]
}

/** Expands the sparse by-day label counts into a contiguous `days`-long window ending today, for charting.
 * Defaults to the UTC day so the window lines up with the server's UTC date buckets. */
export function fillLabelDays(
    byDay: ObservationLabelDayCountApi[],
    days: number,
    today: Dayjs = dayjs.utc()
): LabelChartData {
    const byDate = new Map(byDay.map((entry) => [entry.date, entry]))
    const labels: string[] = []
    const dates: string[] = []
    const up: number[] = []
    const down: number[] = []
    const start = today.startOf('day').subtract(days - 1, 'day')
    for (let i = 0; i < days; i++) {
        const day = start.add(i, 'day')
        const date = day.format('YYYY-MM-DD')
        const entry = byDate.get(date)
        labels.push(day.format('MMM D'))
        dates.push(date)
        up.push(entry?.up ?? 0)
        down.push(entry?.down ?? 0)
    }
    return { labels, dates, up, down }
}

export interface VersionAccuracyEntry {
    version: number
    rated: number
    scanned: number
    /** Thumbs-up share (0-100) of this version's rated sessions, null while nothing is rated. */
    pct: number | null
    /** Percentage-point change vs the previous rated version, null when there is no earlier rated version. */
    delta: number | null
    isCurrent: boolean
}

/** Chips for the per-version accuracy strip: every version with rated sessions, plus the active version
 * even while it is still unrated or unscanned, so a freshly applied prompt never vanishes from the readout.
 * Returns [] when there are fewer than two chips, since a single chip compares nothing. */
export function versionAccuracyStrip(
    markers: ObservationVersionMarkerApi[],
    activeVersion: number | undefined
): VersionAccuracyEntry[] {
    const entries: VersionAccuracyEntry[] = markers
        .map((marker) => {
            const rated = marker.up + marker.down
            return {
                version: marker.version,
                rated,
                scanned: marker.total,
                pct: rated > 0 ? Math.round((marker.up / rated) * 100) : null,
                delta: null,
                isCurrent: false,
            }
        })
        .filter((entry) => entry.pct !== null || entry.version === activeVersion)
        .sort((a, b) => a.version - b.version)
    if (activeVersion !== undefined && !markers.some((marker) => marker.version === activeVersion)) {
        entries.push({ version: activeVersion, rated: 0, scanned: 0, pct: null, delta: null, isCurrent: false })
    }
    if (entries.length < 2) {
        return []
    }
    let previousPct: number | null = null
    for (const entry of entries) {
        if (entry.pct !== null) {
            entry.delta = previousPct !== null ? entry.pct - previousPct : null
            previousPct = entry.pct
        }
    }
    const current =
        activeVersion !== undefined
            ? entries.find((entry) => entry.version === activeVersion)
            : entries[entries.length - 1]
    if (current) {
        current.isCurrent = true
    }
    return entries
}
