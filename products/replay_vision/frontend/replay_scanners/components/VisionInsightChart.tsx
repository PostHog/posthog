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

/**
 * Embedded insight chart with a guaranteed loading/error state. Off a dashboard, InsightViz can fall through
 * to a blank box when a query is cancelled or hasn't resolved (its empty/refresh fallbacks are dashboard-only),
 * so we overlay our own spinner/retry whenever there's no response to render.
 */
export function VisionInsightChart({ query, insightProps, className }: VisionInsightChartProps): JSX.Element {
    const logic = insightVizDataLogic(insightProps)
    const { insightData, erroredQueryId, timedOutQueryId, validationError } = useValues(logic)
    const { loadData } = useActions(logic)

    const hasResponse = !!insightData
    const hasError = !!erroredQueryId || !!timedOutQueryId || !!validationError

    return (
        <div className={clsx('relative', className)}>
            <Query query={query} readOnly embedded inSharedMode context={{ insightProps }} />
            {!hasResponse && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-bg-light">
                    {hasError ? (
                        <>
                            <span className="text-muted text-sm">Couldn't load this chart.</span>
                            <LemonButton size="small" type="secondary" onClick={() => loadData('force_async')}>
                                Retry
                            </LemonButton>
                        </>
                    ) : (
                        <Spinner className="text-2xl" />
                    )}
                </div>
            )}
        </div>
    )
}
