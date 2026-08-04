import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconWarning } from '@posthog/icons'
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
    /** Overrides the generic "no matching events" copy shown when the query legitimately returns no rows. */
    emptyStateHeading?: string
    emptyStateDetail?: string
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

export type ChartOverlayState = 'none' | 'loading' | 'timeout' | 'error'

/**
 * `insightData` is always a truthy object, but `insightData.result` is `undefined` until a query resolves (an empty
 * result is `[]`), so it — not the object — is the real "is there anything to render" signal. No data while loading is
 * a spinner, unless the query has already run long enough to flag `timedOut` — then we say so instead of leaving an
 * opaque spinner up with no hint anything is wrong. No data once settled is a failed/cancelled query we surface as a
 * retry rather than a blank box.
 */
export function chartOverlayState(
    insightData: { result?: unknown } | null | undefined,
    loading: boolean,
    timedOut: boolean
): ChartOverlayState {
    if (insightData?.result != null) {
        return 'none'
    }
    if (timedOut) {
        return 'timeout'
    }
    return loading ? 'loading' : 'error'
}

/**
 * Embedded insight chart with a guaranteed loading/error state. Off a dashboard, InsightViz can fall through to a
 * blank box when a query is cancelled or hasn't resolved (its empty/refresh fallbacks are dashboard-only), so we
 * overlay our own spinner/retry whenever there's no response to render.
 */
export function VisionInsightChart({
    query,
    insightProps,
    className,
    onDataPointClick,
    emptyStateHeading,
    emptyStateDetail,
}: VisionInsightChartProps): JSX.Element {
    const chartQuery = useMemo(() => embeddedVisionChartQuery(query), [query])
    const chartProps = useMemo(() => adHocInsightProps(insightProps, chartQuery), [insightProps, chartQuery])
    const context = useMemo<QueryContext>(
        () => ({ insightProps: chartProps, onDataPointClick, emptyStateHeading, emptyStateDetail }),
        [chartProps, onDataPointClick, emptyStateHeading, emptyStateDetail]
    )
    const logic = insightVizDataLogic(chartProps)
    const { insightData, insightDataLoading, timedOutQueryId } = useValues(logic)
    const { loadData } = useActions(logic)

    const overlay = chartOverlayState(insightData, insightDataLoading, !!timedOutQueryId)

    return (
        <div className={clsx('relative', className)}>
            <Query query={chartQuery} readOnly embedded inSharedMode context={context} />
            {overlay !== 'none' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-bg-light">
                    {overlay === 'loading' ? (
                        <Spinner className="text-2xl" />
                    ) : overlay === 'timeout' ? (
                        <>
                            <IconWarning className="text-2xl text-warning" />
                            <span className="text-muted text-sm">This query is taking longer than usual.</span>
                            <LemonButton size="small" type="secondary" onClick={() => loadData('force_async')}>
                                Retry
                            </LemonButton>
                        </>
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
