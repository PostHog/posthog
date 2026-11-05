import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

interface VisionInsightChartProps {
    query: InsightVizNode
    /** Must be stable (memoized) — it keys the underlying insight logic. */
    insightProps: InsightLogicProps
    /** Sizing classes for the chart container — pass the same layout the chart sat in before, the chart sizes against it. */
    className?: string
    /** Custom handler for data point clicks (must be stable/memoized). Without one, charts stay static. */
    onDataPointClick?: QueryContext['onDataPointClick']
}

/** Vision events all belong to one synthetic person, so the generic persons modal would only list meaningless actors. */
export function embeddedVisionChartQuery(query: InsightVizNode): InsightVizNode {
    return { ...query, hidePersonsModal: true }
}

/** Only `new-AdHoc.`-keyed props push `query` into insightDataLogic (its `propsQuery` selector), which is what lets `hidePersonsModal` stick. */
export function adHocInsightProps(insightProps: InsightLogicProps, query: InsightVizNode): InsightLogicProps {
    const id = insightProps.dashboardItemId ?? 'vision-chart'
    return {
        ...insightProps,
        dashboardItemId: id.startsWith('new-AdHoc.') ? (id as `new-${string}`) : `new-AdHoc.${id}`,
        query,
    }
}

export type ChartOverlayState = 'none' | 'loading' | 'error'

// The lazy renderer can mount after this overlay, before any query has started.
export function chartOverlayState(
    insightData: { result?: unknown } | null | undefined,
    loading: boolean,
    hasError: boolean
): ChartOverlayState {
    if (insightData?.result != null) {
        return 'none'
    }
    return !loading && hasError ? 'error' : 'loading'
}

/** Embedded charts need their own overlay because InsightViz reserves its loading fallbacks for dashboards. */
export function VisionInsightChart({
    query,
    insightProps,
    className,
    onDataPointClick,
}: VisionInsightChartProps): JSX.Element {
    const chartQuery = useMemo(() => embeddedVisionChartQuery(query), [query])
    const chartProps = useMemo(() => adHocInsightProps(insightProps, chartQuery), [insightProps, chartQuery])
    const context = useMemo<QueryContext>(
        () => ({ insightProps: chartProps, onDataPointClick }),
        [chartProps, onDataPointClick]
    )
    const logic = insightVizDataLogic(chartProps)
    const { insightData, insightDataLoading, insightDataError } = useValues(logic)
    const { loadData } = useActions(logic)

    const overlay = chartOverlayState(insightData, insightDataLoading, insightDataError != null)

    useEffect(() => {
        if (overlay === 'error') {
            posthog.capture('replay_vision_chart_error_shown', { query_kind: query.source.kind })
        }
    }, [overlay, query.source.kind])

    return (
        <div className={clsx('relative', className)}>
            <Query query={chartQuery} readOnly embedded inSharedMode context={context} />
            {overlay !== 'none' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-bg-light">
                    {overlay === 'loading' ? (
                        <Spinner className="text-2xl" />
                    ) : (
                        <>
                            <span className="text-muted text-sm">Couldn't load this chart.</span>
                            <LemonButton size="small" type="secondary" onClick={() => loadData('force_async')}>
                                Retry
                            </LemonButton>
                        </>
                    )}
                </div>
            )}
        </div>
    )
}
