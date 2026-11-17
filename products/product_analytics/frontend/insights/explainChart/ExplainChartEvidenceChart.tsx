import { useChartTheme } from 'lib/charts/hooks'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

import type { StoryEvidence } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { StoryEvidenceChart } from 'products/product_analytics/mcp/apps/explainChart/StoryEvidenceChart'
import { isSeriesNamedIn } from 'products/product_analytics/mcp/apps/explainChart/storyNamedSeries'

type EvidenceSeries = { custom_name?: string; event?: string | null; name?: string }

// The chart has no title, so a legend tells several lines apart and an axis label names a single one.
function evidenceTrendsFilter(query: Record<string, unknown>): Record<string, unknown> {
    const trendsFilter = (query.trendsFilter as Record<string, unknown> | undefined) ?? {}
    const breakdownFilter = query.breakdownFilter as { breakdown?: unknown; breakdowns?: unknown[] } | undefined
    const series = (query.series as EvidenceSeries[] | undefined) ?? []
    if (breakdownFilter?.breakdown || breakdownFilter?.breakdowns?.length || series.length > 1) {
        return { ...trendsFilter, showLegend: true, legendPosition: 'bottom' }
    }
    const name = series[0]?.custom_name || series[0]?.event || series[0]?.name
    return name ? { yAxisLabel: name, ...trendsFilter } : trendsFilter
}

function seriesNames(result: TrendResult): string[] {
    return [result.label ?? '', ...[result.breakdown_value ?? []].flat().map(String)]
}

export function ExplainChartEvidenceChart({ item }: { item: StoryEvidence }): JSX.Element | null {
    const theme = useChartTheme()
    if (item.chart) {
        return <StoryEvidenceChart chart={item.chart} theme={theme} className="h-(--insight-viz-min-height)" />
    }
    if (!item.query) {
        return null
    }
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            ...item.query,
            // A trends query may leave out `kind`. Other kinds reject `trendsFilter`.
            ...((item.query.kind ?? NodeKind.TrendsQuery) === NodeKind.TrendsQuery
                ? { trendsFilter: evidenceTrendsFilter(item.query) }
                : {}),
        } as unknown as InsightVizNode['source'],
        full: false,
        showHeader: false,
        showTable: false,
    }
    return (
        <div data-not-quill className="flex h-(--insight-viz-min-height) flex-col">
            <Query
                key={JSON.stringify(item.query)}
                uniqueKey="explain-chart-evidence"
                query={query}
                context={{ isSeriesHighlighted: (result) => isSeriesNamedIn(seriesNames(result), item.text) }}
                readOnly
                embedded
            />
        </div>
    )
}
