// Noise/outlier cluster ID from HDBSCAN
export const NOISE_CLUSTER_ID = -1

// Color for outlier/noise cluster
export const OUTLIER_COLOR = '#888888'

// Pagination
export const TRACES_PER_PAGE = 50

// Query limits
export const MAX_CLUSTERING_RUNS = 20

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
