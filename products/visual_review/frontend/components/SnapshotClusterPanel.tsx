import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

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

/**
 * Collapsible overview of the diff's connected change regions. Hover a
 * row to highlight the matching bbox in the image overlay.
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
    const regionCountLabel = truncated
        ? `top ${items.length} of ${total} regions`
        : `${total} ${total === 1 ? 'region' : 'regions'}`
    const headerText = `Change clusters · ${regionCountLabel} · ${formatNumber(totalShownPixels)} px`

    return (
        <LemonCollapse
            embedded
            className="border rounded-lg bg-bg-light"
            panels={[
                {
                    key: 'clusters',
                    header: <span className="text-xs font-semibold uppercase tracking-wide">{headerText}</span>,
                    content: (
                        <div className="flex flex-col divide-y">
                            {items.map((cluster, i) => {
                                const isHighlighted = highlightedIndex === i
                                const pctOfImage =
                                    totalPixels && totalPixels > 0 ? (cluster.pixel_count / totalPixels) * 100 : null
                                return (
                                    <button
                                        type="button"
                                        key={i}
                                        onMouseEnter={() => onHighlight(i)}
                                        onMouseLeave={() => onHighlight(null)}
                                        onFocus={() => onHighlight(i)}
                                        onBlur={() => onHighlight(null)}
                                        className={`flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                                            isHighlighted ? 'bg-primary-highlight' : 'hover:bg-bg-3000'
                                        }`}
                                        data-attr="visual-review-cluster-row"
                                    >
                                        <span className="shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-full bg-[rgb(0,180,235)] text-white text-[11px] font-semibold tabular-nums">
                                            {i + 1}
                                        </span>
                                        <div className="flex-1 min-w-0 text-xs font-mono tabular-nums">
                                            <div className="text-default">
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
                    ),
                },
            ]}
        />
    )
}
