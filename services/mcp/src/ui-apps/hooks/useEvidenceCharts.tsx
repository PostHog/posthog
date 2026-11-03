import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useMemo, useRef, useState } from 'react'

import { Button, Text } from '@posthog/quill'

import type { StoryEvidence } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import type { StoryEvidenceCharts } from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'
import { StoryEvidenceChart } from 'products/product_analytics/mcp/apps/explainChart/StoryEvidenceChart'
import { isSeriesNamedIn } from 'products/product_analytics/mcp/apps/explainChart/storyNamedSeries'

import { capture } from '../analytics/posthog'
import { loadRenderUiData } from '../apps/render-ui-data'
import { AppLoadingState } from '../components/AppLoadingState'
import { useMcpChartTheme } from '../components/charts/theme'
import { QueryVisualization } from '../components/QueryVisualization'
import { TrendsVisualizer } from '../components/TrendsVisualizer'
import type { TrendsQuery, TrendsResult, TrendsResultItem } from '../components/types'
import { getSeriesLabel } from '../components/utils'

type EvidenceChart =
    | { status: 'loading' }
    | { status: 'error' }
    | { status: 'ready'; payload: { query?: Record<string, unknown>; results: unknown[] } }

interface Redraw {
    tool: string
    query: Record<string, unknown>
}

function seriesNames(item: TrendsResultItem, index: number): string[] {
    return [getSeriesLabel(item, index), ...[item.breakdown_value ?? []].flat().map(String)]
}

function redrawOf(item: StoryEvidence): Redraw | null {
    return !item.chart && item.query && item.queryTool ? { tool: item.queryTool, query: item.query } : null
}

export function useEvidenceCharts(app: App | null, chartClassName: string): StoryEvidenceCharts | undefined {
    const theme = useMcpChartTheme()
    const [charts, setCharts] = useState<Record<string, EvidenceChart>>({})
    const requested = useRef(new Set<string>())

    const load = useCallback(
        ({ tool, query }: Redraw): void => {
            const key = JSON.stringify(query)
            if (!app || requested.current.has(key)) {
                return
            }
            requested.current.add(key)
            setCharts((current) => ({ ...current, [key]: { status: 'loading' } }))
            const settle = (chart: EvidenceChart): void => {
                if (chart.status === 'error') {
                    // A later click on "Show chart" tries again.
                    requested.current.delete(key)
                }
                setCharts((current) => ({ ...current, [key]: chart }))
            }
            loadRenderUiData(app, tool, query, 'query-results').then(
                (result) => {
                    const payload = result.structuredContent as
                        | { query?: Record<string, unknown>; results?: unknown[] }
                        | undefined
                    settle(
                        !result.isError && payload?.results?.length
                            ? {
                                  status: 'ready',
                                  payload: { ...payload, query: payload.query ?? query, results: payload.results },
                              }
                            : { status: 'error' }
                    )
                },
                () => settle({ status: 'error' })
            )
        },
        [app]
    )

    const prefetch = useCallback(
        (items: StoryEvidence[]): void =>
            items.forEach((item) => {
                const redraw = redrawOf(item)
                if (redraw) {
                    load(redraw)
                }
            }),
        [load]
    )

    return useMemo(() => {
        if (!app) {
            return undefined
        }
        return {
            canShow: (item) => !!item.chart || !!redrawOf(item),
            prefetch,
            onShow: (item) => {
                const redraw = redrawOf(item)
                capture('mcp_ui_app_explain_chart_evidence_chart_shown', {
                    was_loaded: !redraw || charts[JSON.stringify(redraw.query)]?.status === 'ready',
                    inline: !!item.chart,
                })
                if (redraw) {
                    load(redraw)
                }
            },
            render: (item) => {
                if (item.chart) {
                    return (
                        <StoryEvidenceChart
                            key={JSON.stringify(item.chart)}
                            chart={item.chart}
                            theme={theme}
                            className={chartClassName}
                        />
                    )
                }
                const redraw = redrawOf(item)
                if (!redraw) {
                    return null
                }
                const chart = charts[JSON.stringify(redraw.query)]
                if (chart?.status === 'ready') {
                    if (redraw.tool !== 'query-trends') {
                        return <QueryVisualization key={JSON.stringify(redraw.query)} data={chart.payload} />
                    }
                    const results = chart.payload.results as TrendsResult
                    return (
                        <TrendsVisualizer
                            key={JSON.stringify(redraw.query)}
                            query={chart.payload.query as unknown as TrendsQuery}
                            results={results}
                            highlightedSeries={results.flatMap((result, index) =>
                                isSeriesNamedIn(seriesNames(result, index), item.text) ? [index] : []
                            )}
                            showControls={false}
                            showTitle={false}
                            showLegend={results.length > 1}
                            chartClassName={chartClassName}
                        />
                    )
                }
                return (
                    <div className={`flex items-center justify-center ${chartClassName}`}>
                        {chart?.status === 'error' ? (
                            <div className="flex max-w-xs flex-col items-center gap-2 text-center">
                                <Text size="sm" variant="muted">
                                    Couldn't load this chart. Try again, or use Open in PostHog.
                                </Text>
                                <Button
                                    variant="outline"
                                    size="xs"
                                    onClick={() => load(redraw)}
                                    data-attr="explain-chart-evidence-retry"
                                >
                                    Try again
                                </Button>
                            </div>
                        ) : (
                            <AppLoadingState />
                        )}
                    </div>
                )
            },
        }
    }, [app, chartClassName, charts, load, prefetch, theme])
}
