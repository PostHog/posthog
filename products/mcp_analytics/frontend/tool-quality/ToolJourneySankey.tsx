import { useMemo, useState } from 'react'

import { SankeyChart, useSankeyLayout } from '@posthog/quill-charts'
import type {
    SankeyChartConfig,
    SankeyHighlight,
    SankeyLinkInput,
    SankeyNodeInput,
    SankeyTooltipContext,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'

import {
    buildJourneyGraph,
    JOURNEY_COLUMN_LABELS,
    type JourneyLinkMeta,
    type JourneyNodeMeta,
} from '../clustering/clusterJourneyGraph'
import { JourneyTooltip } from '../clustering/JourneyTooltip'
import { ERROR_SERIES, PRIMARY_SERIES, seriesColor } from '../clustering/seriesColors'
import { shadeColor } from '../colors'
import type { MCPIntentClusterJourneyPathApi } from '../generated/api.schemas'
import { ToolJourneySummary } from './ToolJourneySummary'
import type { ToolJourney } from './toolReportQueries'

// Labels stay inside the plot, so the columns span the full width. The headers are a row of their own.
const CHART_CONFIG: SankeyChartConfig = { nodeAlign: 'left', preserveNodeOrder: true, linkOpacity: 0.45 }

// Matches the chart's own label gap, so the bold chips sit exactly over the labels they replace.
const LABEL_GAP = 6
// Every label sits on an opaque chip, so it reads on top of the ribbons rather than behind them.
const LABEL_CHIP = 'rounded-sm border border-primary bg-surface-primary px-1'
const CHART_LABEL_CHIPS = [
    '[&_[data-attr=hog-chart-sankey-node-label]]:rounded-sm',
    '[&_[data-attr=hog-chart-sankey-node-label]]:border',
    '[&_[data-attr=hog-chart-sankey-node-label]]:border-primary',
    '[&_[data-attr=hog-chart-sankey-node-label]]:bg-surface-primary',
    '[&_[data-attr=hog-chart-sankey-node-label]]:px-1',
].join(' ')

function headerPosition(index: number, count: number): React.CSSProperties {
    const left = `${(index / (count - 1)) * 100}%`
    const shift = index === 0 ? '0' : index === count - 1 ? '-100%' : '-50%'
    return { left, transform: `translateX(${shift})` }
}

/** Bold chips over this tool's labels; never in the last column. */
function ToolLabels({ nodeIds }: { nodeIds: ReadonlySet<string> }): JSX.Element {
    const { layout } = useSankeyLayout()
    return (
        <>
            {layout.nodes
                .filter((node) => nodeIds.has(node.id))
                .map((node) => (
                    <div
                        key={node.id}
                        className={`pointer-events-none absolute -translate-y-1/2 ${LABEL_CHIP} text-[11px] font-semibold leading-tight text-primary`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: node.x1 + LABEL_GAP, top: (node.y0 + node.y1) / 2 }}
                    >
                        {node.label}
                    </div>
                ))}
        </>
    )
}

export function ToolJourneySankey({
    toolName,
    journey,
    loading,
}: {
    toolName: string
    journey: ToolJourney
    loading: boolean
}): JSX.Element {
    const theme = useChartTheme()

    const graph = useMemo(() => {
        const built = buildJourneyGraph(journey.paths as unknown as MCPIntentClusterJourneyPathApi[])
        const primary = seriesColor(theme, PRIMARY_SERIES)
        // Other tools step back in a lighter shade, so this tool's place in each journey stands out.
        const otherTool = shadeColor(primary, 45) ?? primary
        const nodes: SankeyNodeInput<JourneyNodeMeta>[] = built.nodes.map((node) => {
            const kind = node.meta?.kind ?? 'tool'
            const color =
                kind === 'init'
                    ? 'var(--muted)'
                    : kind === 'ended'
                      ? 'var(--muted-3000)'
                      : kind === 'completed'
                        ? 'var(--success)'
                        : kind === 'error'
                          ? seriesColor(theme, ERROR_SERIES)
                          : node.label === toolName
                            ? primary
                            : otherTool
            return { ...node, color }
        })
        const links: SankeyLinkInput<JourneyLinkMeta>[] = built.links.map((link) => ({
            ...link,
            color: seriesColor(theme, link.meta?.outcome === 'error' ? ERROR_SERIES : PRIMARY_SERIES),
        }))
        // This tool's steps and the ribbons leaving them stay at full strength while the rest dims.
        const toolNodeIds = new Set(
            nodes
                .filter((node) => (node.meta?.kind ?? 'tool') === 'tool' && node.label === toolName)
                .map((node) => node.id)
        )
        const highlight: SankeyHighlight = {
            nodeIds: toolNodeIds,
            linkIndices: new Set(links.flatMap((link, index) => (toolNodeIds.has(link.source) ? [index] : []))),
        }
        return { nodes, links, highlight }
    }, [journey, toolName, theme])
    // A hover hands emphasis back to the chart, so any path can still be traced.
    const [hovering, setHovering] = useState(false)

    const tooltip = useMemo(
        () =>
            function ToolJourneyTooltip({ hit }: SankeyTooltipContext<JourneyNodeMeta, JourneyLinkMeta>): JSX.Element {
                return <JourneyTooltip hit={hit} totalSessions={journey.totalSessions} />
            },
        [journey.totalSessions]
    )

    if (!loading && journey.paths.length === 0) {
        return (
            <div className="rounded bg-surface-secondary p-4 text-xs text-muted">
                No sessions with this tool in this date range.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            {journey.paths.length > 0 && (
                <div className="mb-3">
                    <ToolJourneySummary journey={journey} toolName={toolName} />
                </div>
            )}
            <div className="relative h-4 text-xs font-semibold uppercase tracking-wide text-secondary" aria-hidden>
                {JOURNEY_COLUMN_LABELS.map((label, index) => (
                    <span
                        key={label}
                        className="absolute top-0 whitespace-nowrap"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={headerPosition(index, JOURNEY_COLUMN_LABELS.length)}
                    >
                        {label}
                    </span>
                ))}
            </div>
            <div className={`flex h-[320px] w-full ${CHART_LABEL_CHIPS}`}>
                {loading && journey.paths.length === 0 ? (
                    <Skeleton className="flex-1" aria-busy />
                ) : (
                    <SankeyChart
                        nodes={graph.nodes}
                        links={graph.links}
                        theme={theme}
                        config={CHART_CONFIG}
                        tooltip={tooltip}
                        highlight={hovering ? null : graph.highlight}
                        onHoverChange={(hit) => setHovering(!!hit)}
                        dataAttr="mcp-tool-journey-sankey"
                    >
                        <ToolLabels nodeIds={graph.highlight.nodeIds} />
                    </SankeyChart>
                )}
            </div>
        </div>
    )
}
