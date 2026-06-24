import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

interface VisionInsightChartProps {
    query: InsightVizNode
    /** Must be stable (memoized) — it keys the underlying insight logic. */
    insightProps: InsightLogicProps
    /** Sizing classes for the chart container — pass the same layout the chart sat in before, the chart sizes against it. */
    className?: string
}

export type ChartOverlayState = 'none' | 'loading' | 'error'

/**
 * `insightData` is always a truthy object, but `insightData.result` is `undefined` until a query resolves (an empty
 * result is `[]`), so it — not the object — is the real "is there anything to render" signal. No data while loading is
 * a spinner; no data once settled is a failed/cancelled query we surface as a retry rather than a blank box.
 */
export function chartOverlayState(
    insightData: { result?: unknown } | null | undefined,
    loading: boolean
): ChartOverlayState {
    if (insightData?.result != null) {
        return 'none'
    }
    return loading ? 'loading' : 'error'
}

/**
 * Embedded insight chart with a guaranteed loading/error state. Off a dashboard, InsightViz can fall through to a
 * blank box when a query is cancelled or hasn't resolved (its empty/refresh fallbacks are dashboard-only), so we
 * overlay our own spinner/retry whenever there's no response to render.
 */
export function VisionInsightChart({ query, insightProps, className }: VisionInsightChartProps): JSX.Element {
    const logic = insightVizDataLogic(insightProps)
    const { insightData, insightDataLoading } = useValues(logic)
    const { loadData } = useActions(logic)

    const overlay = chartOverlayState(insightData, insightDataLoading)

    return (
        <div className={clsx('relative', className)}>
            <Query query={query} readOnly embedded inSharedMode context={{ insightProps }} />
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
