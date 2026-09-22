import './Paths.scss'

import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { SankeyChart } from '@posthog/quill-charts'
import type { SankeyChartConfig, SankeyHighlight, SankeyTooltipHit } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { PathsLink } from '~/queries/schema/schema-general'
import { shouldQueryBeAsync } from '~/queries/utils'

import { FALLBACK_CANVAS_WIDTH } from './constants'
import { PathNodeCards } from './PathNodeCards'
import { buildPathsGraph, maxPathLayer, pathsChartWidth } from './pathsChartData'
import type { PathsGraphColors } from './pathsChartData'
import { PathsColumnDividers } from './PathsColumnDividers'
import { pathsDataLogic } from './pathsDataLogic'
import { PathsDropoffs } from './PathsDropoffs'
import { pathsInteractionLogic } from './pathsInteractionLogic'

const DEFAULT_PATHS_ID = 'default_paths'
const FALLBACK_COLOR = '#000000'
const NO_MARGINS = { top: 0, right: 0, bottom: 0, left: 0 }

// The cards carry every label and number, so the chart draws bare nodes and ribbons. Node order
// follows the result, as the SVG renderer did, so the two renderers agree on where a step sits.
const CHART_CONFIG: SankeyChartConfig = {
    nodeWidth: 15,
    nodePadding: 8,
    nodeAlign: 'justify',
    preserveNodeOrder: true,
    showNodeLabels: false,
    linkOpacity: 0.35,
    tooltip: { enabled: false },
    margins: NO_MARGINS,
}

/** The paths insight on the quill `SankeyChart`. The chart lays out and paints the graph; the
 *  cards, drop-offs, and hover emphasis stay with the paths logic through overlays. */
export function PathsChart(): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const { width: containerWidth } = useResizeObserver({ ref: containerRef })

    const { insight, insightProps } = useValues(insightLogic)
    const { insightQuery, paths, pathsFilter, funnelPathsFilter, insightDataLoading, insightDataError, theme } =
        useValues(pathsDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))
    const interactionLogic = pathsInteractionLogic(insightProps)
    const { activeIndices, nodes } = useValues(interactionLogic)
    const { hoverNode, hoverLink, requestClearHover } = useActions(interactionLogic)
    const chartTheme = useChartTheme()

    const colors = useMemo<PathsGraphColors>(
        () => ({
            node: theme?.['preset-1'] || FALLBACK_COLOR,
            selectedNode: theme?.['preset-2'] || FALLBACK_COLOR,
            link: theme?.['preset-1'] || FALLBACK_COLOR,
        }),
        [theme]
    )
    const graph = useMemo(
        () => buildPathsGraph(paths, pathsFilter || {}, funnelPathsFilter || undefined, colors),
        [paths, pathsFilter, funnelPathsFilter, colors]
    )
    const chartWidth = pathsChartWidth(containerWidth ?? FALLBACK_CANVAS_WIDTH, maxPathLayer(paths))

    const highlight = useMemo<SankeyHighlight | null>(() => {
        if (activeIndices.nodeIndices.size === 0) {
            return null
        }
        const nodeIds = new Set<string>()
        for (const node of nodes) {
            if (activeIndices.nodeIndices.has(node.index)) {
                nodeIds.add(node.name)
            }
        }
        return { nodeIds, linkIndices: activeIndices.linkIndices }
    }, [activeIndices, nodes])

    const onHoverChange = useCallback(
        (hit: SankeyTooltipHit<unknown, PathsLink> | null) => {
            // A card under the cursor owns the hover until the pointer leaves it.
            if (interactionLogic.values.cardHovered) {
                return
            }
            if (!hit) {
                requestClearHover()
            } else if (hit.kind === 'node') {
                hoverNode(hit.node.index)
            } else {
                hoverLink(hit.link.source.index, hit.link.target.index, hit.link.index)
            }
        },
        [interactionLogic, hoverNode, hoverLink, requestClearHover]
    )

    if (insightDataError) {
        return (
            <InsightErrorState
                query={insightQuery}
                excludeDetail
                onRetry={() => {
                    loadData(shouldQueryBeAsync(insightQuery) ? 'force_async' : 'force_blocking')
                }}
            />
        )
    }

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`
    const isEmpty = !insightDataLoading && paths.nodes.length === 0

    return (
        <div className="h-full w-full overflow-auto" id={id} ref={containerRef}>
            <div
                className="Paths"
                data-attr="paths-viz"
                // Visual tests wait for this; it appears once the logic holds the laid-out nodes.
                data-stable={nodes.length > 0 ? 'true' : undefined}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        width: chartWidth,
                        '--paths-link-hover': colors.selectedNode,
                        '--paths-dropoff': 'rgba(220,53,69,0.7)',
                    } as React.CSSProperties
                }
            >
                {isEmpty ? <InsightEmptyState /> : null}
                {graph.nodes.length > 0 ? (
                    <SankeyChart<unknown, PathsLink>
                        nodes={graph.nodes}
                        links={graph.links}
                        theme={chartTheme}
                        config={CHART_CONFIG}
                        highlight={highlight}
                        onHoverChange={onHoverChange}
                        className="h-full"
                        dataAttr="paths-sankey-chart"
                    >
                        <PathsDropoffs />
                        <PathsColumnDividers />
                        <PathNodeCards insightProps={insightProps} />
                    </SankeyChart>
                ) : null}
            </div>
        </div>
    )
}
