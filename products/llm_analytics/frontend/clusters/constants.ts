// Noise/outlier cluster ID from HDBSCAN
export const NOISE_CLUSTER_ID = -1

// Color for outlier/noise cluster
export const OUTLIER_COLOR = '#888888'

// Pagination
export const TRACES_PER_PAGE = 50

// Query limits
export const MAX_CLUSTERING_RUNS = 20

// Cluster detail URL pattern. Mirrored in `manifest.tsx`'s route registration so any
// `tabAwareUrlToAction` matcher (e.g. `clusterDetailLogic`, `llmAnalyticsSharedLogic`)
// stays in lockstep with the actual route.
export const LLM_ANALYTICS_CLUSTER_URL_PATTERN = '/llm-analytics/clusters/:runId/:clusterId'

// Scene names used as ClickHouse query tags. These match the route registrations in
// `manifest.tsx`, and the query runner pulls them off `query.tags.scene` to attach to
// every executed query for analytics. Centralised so the tags don't drift if the scene
// names ever change.
export const LLM_ANALYTICS_CLUSTERS_SCENE_TAG = 'LLMAnalyticsClusters'
export const LLM_ANALYTICS_CLUSTER_SCENE_TAG = 'LLMAnalyticsCluster'

// Cluster items are keyed by UUIDs from precomputed clustering events. Restrict to
// hex / dashes before interpolating into a HogQL `IN` literal so a malformed key
// can't break out of the string. UUIDs already match this character set.
export const SAFE_ID_RE = /^[a-f0-9-]+$/i

// Mirrors `MAX_SELECT_RETURNED_ROWS` in `posthog/hogql/constants.py`. EventsQuery rows above
// this are silently truncated server-side, so post-hoc property-filter queries against the
// full set of cluster items must either fit under the cap or fall back to "no filtering".
export const FILTER_QUERY_MAX_ROWS = 50000

/**
 * Centroid detection for chart.js scatter datasets.
 *
 * Two label shapes exist:
 *   - Overview plot (ClusterScatterPlot): per-cluster label with "(centroid)" suffix,
 *     e.g. "Auth failures (centroid)" — so one cluster's points and centroid stay visually paired.
 *   - Single-cluster detail plot (ClusterDetailScatterPlot): just "Centroid" since the dataset
 *     only holds one cluster's worth of data.
 *
 * Centralising keeps tooltip/click suppression in sync across both views.
 */
export function isCentroidDataset(dataset: { label?: string } | undefined | null): boolean {
    const label = dataset?.label
    if (!label) {
        return false
    }
    return label === 'Centroid' || label.includes('(centroid)')
}
