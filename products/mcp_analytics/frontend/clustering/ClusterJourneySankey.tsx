import { useMemo } from 'react'

import { SankeyChart } from '@posthog/quill-charts'
import type {
    ChartTheme,
    SankeyChartConfig,
    SankeyLinkInput,
    SankeyNodeInput,
    SankeyTooltipContext,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { MCPIntentClusterJourneyApi } from '../generated/api.schemas'
import {
    buildJourneyGraph,
    describeJourneyPath,
    JOURNEY_COLUMN_LABELS,
    type JourneyLinkMeta,
    type JourneyNodeKind,
    type JourneyNodeMeta,
} from './clusterJourneyGraph'
import { JourneyTooltip } from './JourneyTooltip'
import { ERROR_SERIES, PRIMARY_SERIES, seriesColor } from './seriesColors'

// Flows that end early stay in their own stage column instead of being pushed to the outcome.
const CHART_CONFIG: SankeyChartConfig = {
    columnLabels: JOURNEY_COLUMN_LABELS,
    nodeAlign: 'left',
    preserveNodeOrder: true,
    linkOpacity: 0.45,
}

function nodeFill(kind: JourneyNodeKind, theme: ChartTheme): string {
    switch (kind) {
        case 'init':
            return 'var(--muted)'
        case 'ended':
            return 'var(--muted-3000)'
        case 'completed':
            return 'var(--success)'
        case 'error':
            return seriesColor(theme, ERROR_SERIES)
        case 'tool':
        default:
            return seriesColor(theme, PRIMARY_SERIES)
    }
}

// Shares divide by every session in the cluster, not just the displayed top paths, so a subset never reads as 100%.
function makeJourneyTooltip(totalSessions: number) {
    return function JourneyTooltipAdapter({
        hit,
    }: SankeyTooltipContext<JourneyNodeMeta, JourneyLinkMeta>): JSX.Element {
        return <JourneyTooltip hit={hit} totalSessions={totalSessions} />
    }
}

interface Props {
    journey: MCPIntentClusterJourneyApi | null | undefined
}

export function ClusterJourneySankey({ journey }: Props): JSX.Element | null {
    const theme = useChartTheme()

    const graph = useMemo(() => {
        if (!journey) {
            return null
        }
        const built = buildJourneyGraph(journey.paths)
        const nodes: SankeyNodeInput<JourneyNodeMeta>[] = built.nodes.map((node) => ({
            ...node,
            color: nodeFill(node.meta?.kind ?? 'tool', theme),
        }))
        const links: SankeyLinkInput<JourneyLinkMeta>[] = built.links.map((link) => ({
            ...link,
            color: seriesColor(theme, link.meta?.outcome === 'error' ? ERROR_SERIES : PRIMARY_SERIES),
        }))
        return { nodes, links }
    }, [journey, theme])

    const tooltip = useMemo(() => makeJourneyTooltip(journey?.total_sessions ?? 0), [journey?.total_sessions])

    if (!journey || !graph || graph.links.length === 0) {
        return (
            <div className="bg-surface-secondary rounded p-4 text-xs text-muted">
                Not enough session data yet to plot a journey. Recompute after more sessions are summarised.
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="text-xs text-muted">
                {journey.total_sessions} session{journey.total_sessions === 1 ? '' : 's'} · top {journey.paths.length}{' '}
                path{journey.paths.length === 1 ? '' : 's'}
            </div>
            <div className="flex h-[300px] w-full">
                <SankeyChart
                    nodes={graph.nodes}
                    links={graph.links}
                    theme={theme}
                    config={CHART_CONFIG}
                    tooltip={tooltip}
                    dataAttr="mcp-cluster-journey-sankey"
                />
            </div>
            {journey.leak ? (
                <div className="text-xs text-muted leading-relaxed">
                    <span className="text-danger font-medium">Biggest leak:</span>{' '}
                    <span>
                        {describeJourneyPath(journey.leak)} drains{' '}
                        <span className="font-medium">
                            {journey.leak.count} session{journey.leak.count === 1 ? '' : 's'}
                        </span>{' '}
                        into {journey.leak.outcome === 'error' ? 'Error' : 'Other'}.
                    </span>
                </div>
            ) : (
                <div className="text-xs text-muted">No failing paths in this cluster.</div>
            )}
        </div>
    )
}
