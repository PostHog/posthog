import { useChartTheme } from 'lib/charts/hooks'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

import type { StoryEvidence } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { StoryEvidenceChart } from 'products/product_analytics/mcp/apps/explainChart/StoryEvidenceChart'
import { isSeriesNamedIn } from 'products/product_analytics/mcp/apps/explainChart/storyNamedSeries'

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
        source: item.query as unknown as InsightVizNode['source'],
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
