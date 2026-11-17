// Pinned: URL search param. The Anomalies tab adds it to a row link, and a bookmark can hold it.
export const ANOMALY_SCORES_SEARCH_PARAM = 'anomaly_scores'

export function withAnomalyScoresParam(path: string): string {
    return `${path}${path.includes('?') ? '&' : '?'}${ANOMALY_SCORES_SEARCH_PARAM}=true`
}
