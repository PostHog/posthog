import type { App } from '@modelcontextprotocol/ext-apps'
import { type ReactElement, useEffect, useMemo } from 'react'

import { Card, CardContent } from '@posthog/quill'
import { buildYTickFormatter } from '@posthog/quill-charts'

import { trendsFilterToYFormatterConfig } from 'products/product_analytics/frontend/insights/trends/shared/trendsAxisFormat'
import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { ExplainChartView } from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'

import { capture } from '../analytics/posthog'
import { useEvidenceCharts } from '../hooks/useEvidenceCharts'
import { ExplainChartFeedback } from './ExplainChartFeedback'
import { TrendsVisualizer } from './TrendsVisualizer'
import type { TrendsQuery, TrendsResult } from './types'

// The render-ui dispatch imports the data type from this module.
export type { ExplainChartData }

const CHART_CLASS_NAME = 'h-[260px] @3xl/story:h-[400px]'

export interface ExplainChartProps {
    data: ExplainChartData
    openLink: (url: string) => void
    /** The host app, which runs each piece of evidence's query so the explanation can draw it. */
    app?: App | null
}

export function ExplainChart({ data, openLink, app = null }: ExplainChartProps): ReactElement {
    const query = data.query as unknown as TrendsQuery
    const evidenceCharts = useEvidenceCharts(app, CHART_CLASS_NAME)

    useEffect(() => {
        capture('mcp_ui_app_explain_chart_viewed', {
            chapter_count: data.chapters.length,
            unmatched_chapter_count: data.chapters.filter((chapter) => !chapter.range).length,
        })
    }, [data])

    // A number in a sentence reads better in full, so the chart's axis format is only used when it adds a unit.
    const formatValue = useMemo(() => {
        const {
            aggregationAxisFormat: format,
            aggregationAxisPrefix,
            aggregationAxisPostfix,
        } = query.trendsFilter ?? {}
        return (format && format !== 'numeric') || aggregationAxisPrefix || aggregationAxisPostfix
            ? buildYTickFormatter(trendsFilterToYFormatterConfig(query.trendsFilter, false))
            : undefined
    }, [query])

    return (
        <Card>
            <CardContent>
                <ExplainChartView
                    // The host updates `data` in place, so key on the story to start each new one at its summary.
                    key={`${JSON.stringify(data.query)}:${data.headline}`}
                    data={data}
                    title={data.insightName ?? 'Trends'}
                    renderChart={(overlay) => (
                        <TrendsVisualizer
                            query={query}
                            results={data.results as TrendsResult}
                            title={data.insightName ?? 'Trends'}
                            overlay={overlay}
                            showControls={false}
                            chartClassName={CHART_CLASS_NAME}
                            showTitle={false}
                        />
                    )}
                    openLink={openLink}
                    formatValue={formatValue}
                    evidenceCharts={evidenceCharts}
                    onPageChange={({ index, fromIndex, source }) =>
                        capture('mcp_ui_app_explain_chart_page_viewed', {
                            page_index: index,
                            from_page_index: fromIndex,
                            page_count: data.chapters.length + 1,
                            source,
                        })
                    }
                />
                <ExplainChartFeedback />
            </CardContent>
        </Card>
    )
}
