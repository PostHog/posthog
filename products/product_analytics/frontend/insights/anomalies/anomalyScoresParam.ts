// Pinned: URL search param. The Anomalies tab adds it to a row link, and a bookmark can hold it.
export const ANOMALY_SCORES_SEARCH_PARAM = 'anomaly_scores'

// Before the hash, which can hold the query of the insight.
export function withAnomalyScoresParam(path: string): string {
    const hashStart = path.indexOf('#')
    const base = hashStart === -1 ? path : path.slice(0, hashStart)
    const hash = hashStart === -1 ? '' : path.slice(hashStart)
    return `${base}${base.includes('?') ? '&' : '?'}${ANOMALY_SCORES_SEARCH_PARAM}=true${hash}`
}
