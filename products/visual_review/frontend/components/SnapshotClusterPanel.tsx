import type { ClusterSummaryApi } from '../generated/api.schemas'

interface SnapshotClusterPanelProps {
    clusterSummary: ClusterSummaryApi
    /** Total pixels in the diff image — used to render each cluster's % share. */
    totalPixels?: number | null
    highlightedIndex: number | null
    onHighlight: (index: number | null) => void
}

function formatNumber(n: number): string {
    return n.toLocaleString('en-US')
}

// Same warm-orange chip color as the bbox overlay so panel rows and
// image overlays read as a single visual system.
const CHIP_BG = 'rgb(245, 134, 52)'

/**
 * Sidebar overview of the diff's connected change regions. One row per
 * region — position, size, pixel count, share-of-image. Rows are
 * always visible (not collapsible) since the sidebar already gives them
 * a natural home; hovering a row highlights the matching bbox in the
 * image overlay, and overlay hover lights up the row.
 *
 * Pixelhog returns up to `CLUSTER_MAX` clusters ranked by pixel count,
 * with `total` carrying the true count when truncated. The header
 * surfaces both so users know whether they're seeing the full picture.
 */
export function SnapshotClusterPanel({
    clusterSummary,
    totalPixels,
    highlightedIndex,
    onHighlight,
}: SnapshotClusterPanelProps): JSX.Element | null {
    const { items, total, truncated } = clusterSummary
    if (items.length === 0) {
        return null
    }
    const totalShownPixels = items.reduce((sum, c) => sum + c.pixel_count, 0)
    const count = items.length
    // pixelhog 1.2 semantics: `total` is the pre-merge raw CCL count;
    // `truncated` fires only when max_clusters dropped some pre-merge.
    // When total > count without truncation, merging compressed
    // pre-merge clusters — surface as context, not as missing data.
    let regionCountLabel = `${count} ${count === 1 ? 'region' : 'regions'}`
    if (total > count) {
        regionCountLabel += ` · merged from ${total} raw`
    }
    if (truncated) {
        regionCountLabel += ' · cap reached'
    }

    return (
        <div>
            <h4 className="text-xs font-semibold text-muted mb-1">Change clusters</h4>
            <div className="text-[11px] text-muted mb-2 tabular-nums">
                {regionCountLabel} · {formatNumber(totalShownPixels)} px
            </div>
            <div
                className="flex flex-col rounded-md border bg-bg-light overflow-hidden"
                onMouseLeave={() => onHighlight(null)}
            >
                {items.map((cluster, i) => {
                    const isHighlighted = highlightedIndex === i
                    const pctOfImage = totalPixels && totalPixels > 0 ? (cluster.pixel_count / totalPixels) * 100 : null
                    return (
                        <button
                            type="button"
                            key={i}
                            onMouseEnter={() => onHighlight(i)}
                            onFocus={() => onHighlight(i)}
                            onBlur={() => onHighlight(null)}
                            className={`flex items-center gap-2 px-2 py-1.5 text-left border-b last:border-b-0 transition-colors ${
                                isHighlighted ? 'bg-warning-highlight' : 'hover:bg-bg-3000'
                            }`}
                            data-attr="visual-review-cluster-row"
                        >
                            <span
                                className="shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-full text-white text-[11px] font-bold tabular-nums shadow-sm ring-1 ring-white/70"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ background: CHIP_BG }}
                            >
                                {i + 1}
                            </span>
                            <div className="flex-1 min-w-0 text-[11px] font-mono tabular-nums leading-tight">
                                <div className="text-default truncate">
                                    {cluster.x},{cluster.y} · {cluster.width}×{cluster.height}
                                </div>
                                <div className="text-muted">
                                    {formatNumber(cluster.pixel_count)} px
                                    {pctOfImage != null && ` · ${pctOfImage.toFixed(2)}%`}
                                </div>
                            </div>
                        </button>
                    )
                })}
            </div>
        </div>
    )
}
