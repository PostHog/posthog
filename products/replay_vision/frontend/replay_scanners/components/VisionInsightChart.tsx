import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

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

/**
 * `insightData` is always a truthy object, but `insightData.result` is `undefined` until a query resolves (an empty
 * result is `[]`), so it — not the object — is the real "is there anything to render" signal. No data while loading is
 * a spinner. No data once settled splits by whether the query actually errored: a real failure is already rendered
 * inside the embedded insight (a readable memory-limit / validation message with its own actions), so we defer to it
 * and show no overlay — otherwise two error states stack in the same box. Only a settled query with no error and no
 * result (cancelled, or nothing cached) falls through to the overlay's own retry, which is why the overlay exists.
 */
export function chartOverlayState(
    insightData: { result?: unknown } | null | undefined,
    loading: boolean,
    hasError: boolean
): ChartOverlayState {
    if (insightData?.result != null) {
        return 'none'
    }
    if (loading) {
        return 'loading'
    }
    return hasError ? 'none' : 'error'
}

/**
 * Embedded insight chart with a guaranteed loading state. Off a dashboard, InsightViz can fall through to a blank box
 * when a query is cancelled or hasn't resolved (its empty/refresh fallbacks are dashboard-only), so we overlay our own
 * spinner while loading and a retry for that blank case. A real query failure is left to the embedded insight, which
 * renders one readable error (e.g. the memory-limit message with retry) — the overlay must not stack a second on top.
 */
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
