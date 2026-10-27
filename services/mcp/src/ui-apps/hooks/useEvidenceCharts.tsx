import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useMemo, useRef, useState } from 'react'

import { Button, Text } from '@posthog/quill'

import type { StoryEvidenceCharts } from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'
import { isSeriesNamedIn } from 'products/product_analytics/mcp/apps/explainChart/storyNamedSeries'

import { capture } from '../analytics/posthog'
import { loadRenderUiData } from '../apps/render-ui-data'
import { AppLoadingState } from '../components/AppLoadingState'
import { TrendsVisualizer } from '../components/TrendsVisualizer'
import type { TrendsQuery, TrendsResult, TrendsResultItem } from '../components/types'
import { getSeriesLabel } from '../components/utils'

type EvidenceChart =
    | { status: 'loading' }
    | { status: 'error' }
    | { status: 'ready'; query: TrendsQuery; results: TrendsResult }

function seriesNames(item: TrendsResultItem, index: number): string[] {
    return [getSeriesLabel(item, index), ...[item.breakdown_value ?? []].flat().map(String)]
}

function isTrendsQuery(query: Record<string, unknown>): boolean {
    return query.kind === 'TrendsQuery' || (query.kind === undefined && Array.isArray(query.series))
}

export function useEvidenceCharts(app: App | null, chartClassName: string): StoryEvidenceCharts | undefined {
    const [charts, setCharts] = useState<Record<string, EvidenceChart>>({})
    const requested = useRef(new Set<string>())

    const load = useCallback(
        (query: Record<string, unknown>): void => {
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
            loadRenderUiData(app, 'query-trends', query, 'query-results').then(
                (result) => {
                    const payload = result.structuredContent as
                        | { query?: TrendsQuery; results?: TrendsResult }
                        | undefined
                    settle(
                        !result.isError && payload?.results?.length
                            ? {
                                  status: 'ready',
                                  query: payload.query ?? (query as unknown as TrendsQuery),
                                  results: payload.results,
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
        (queries: Record<string, unknown>[]): void => queries.filter(isTrendsQuery).forEach(load),
        [load]
    )

    return useMemo(() => {
        if (!app) {
            return undefined
        }
        return {
            canShow: isTrendsQuery,
            prefetch,
            onShow: (query) => {
                capture('mcp_ui_app_explain_chart_evidence_chart_shown', {
                    was_loaded: charts[JSON.stringify(query)]?.status === 'ready',
                })
                load(query)
            },
            render: (query, text) => {
                const chart = charts[JSON.stringify(query)]
                if (chart?.status === 'ready') {
                    return (
                        <TrendsVisualizer
                            key={JSON.stringify(query)}
                            query={chart.query}
                            results={chart.results}
                            highlightedSeries={chart.results.flatMap((item, index) =>
                                isSeriesNamedIn(seriesNames(item, index), text) ? [index] : []
                            )}
                            showControls={false}
                            showTitle={false}
                            showLegend={chart.results.length > 1}
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
                                    onClick={() => load(query)}
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
    }, [app, chartClassName, charts, load, prefetch])
}
