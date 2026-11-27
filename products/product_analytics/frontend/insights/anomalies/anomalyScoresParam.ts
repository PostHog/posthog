// Pinned: URL search params. The Anomalies tab adds them to a row link, and a bookmark can hold them.
export const ANOMALY_SCORES_SEARCH_PARAM = 'anomaly_scores'
export const ANOMALY_SERIES_SEARCH_PARAM = 'anomaly_series'

// Before the hash, which can hold the query of the insight.
export function withAnomalyScoresParam(path: string, seriesKey?: string): string {
    const hashStart = path.indexOf('#')
    const base = hashStart === -1 ? path : path.slice(0, hashStart)
    const hash = hashStart === -1 ? '' : path.slice(hashStart)
    const params = new URLSearchParams({ [ANOMALY_SCORES_SEARCH_PARAM]: 'true' })
    if (seriesKey) {
        params.set(ANOMALY_SERIES_SEARCH_PARAM, seriesKey)
    }
    return `${base}${base.includes('?') ? '&' : '?'}${params.toString()}${hash}`
}

// Read from the raw search string, because the router turns a number-like value into a number, and a series key is a
// hex hash that can hold only digits.
export function anomalySeriesKeyFromSearch(search: string): string | null {
    return new URLSearchParams(search).get(ANOMALY_SERIES_SEARCH_PARAM) || null
}

// The series of a link is isolated once, so a reader who shows the other series again keeps them when the chart
// mounts again. A new open from the Anomalies tab isolates the series again.
const isolatedSeries = new Set<string>()

export function claimAnomalySeriesIsolation(insightId: number, seriesKey: string): boolean {
    const key = `${insightId}:${seriesKey}`
    if (isolatedSeries.has(key)) {
        return false
    }
    isolatedSeries.add(key)
    return true
}

export function resetAnomalySeriesIsolation(insightId: number, seriesKey: string): void {
    isolatedSeries.delete(`${insightId}:${seriesKey}`)
}
