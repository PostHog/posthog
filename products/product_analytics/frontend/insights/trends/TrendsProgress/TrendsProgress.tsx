import clsx from 'clsx'
import { useValues } from 'kea'

import { IconTarget } from '@posthog/icons'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartParams, TrendResult } from '~/types'

import { computeProgressFraction, selectProgressTarget } from './progress'

export function TrendsProgress({ showPersonsModal = true, context, inCardView }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { baseCurrency } = useValues(teamLogic)

    const resultSeries = insightData?.result?.[0] as TrendResult | undefined
    if (!resultSeries) {
        return <InsightEmptyState sampleDataVariant="number" />
    }

    const target = selectProgressTarget(trendsFilter?.goalLines)
    if (!target) {
        return (
            <InsightEmptyState
                icon={<IconTarget className="text-5xl mb-2 text-tertiary" />}
                heading="Set a target to see progress"
                detail="Add a goal line under Advanced options. The first one becomes the target this bar fills toward."
            />
        )
    }

    const fraction = computeProgressFraction(resultSeries.aggregated_value, target.value)
    const formatValue = (value: number): string => formatAggregationAxisValue(trendsFilter, value, baseCurrency)

    // Beating the target reads as a win, so it gets the success colour rather than the goal line's own.
    const strokeColor = fraction >= 1 ? 'var(--success)' : target.color || undefined

    const onValueClick = context?.onDataPointClick
        ? () => context?.onDataPointClick?.({ compare: 'current' }, resultSeries)
        : // != is intentional to catch undefined too — `aggregated_value` is typed as a number but can be absent
          showPersonsModal && resultSeries.aggregated_value != null && !hasDataWarehouseSeries
          ? () =>
                openPersonsModal({
                    title: resultSeries.label,
                    query: {
                        kind: NodeKind.InsightActorsQuery,
                        source: querySource!,
                        includeRecordings: true,
                    },
                    additionalSelect: {
                        value_at_data_point: 'event_count',
                        matched_recordings: 'matched_recordings',
                    },
                    orderBy: ['event_count DESC, actor_id DESC'],
                })
          : undefined

    return (
        <div
            className={clsx(
                'TrendsProgress ph-no-capture flex flex-col justify-center gap-3 w-full p-4',
                inCardView && 'flex-1'
            )}
            data-attr="trends-progress"
        >
            <div className="flex items-baseline justify-between gap-2">
                <span
                    className={clsx('text-3xl font-bold', onValueClick && 'cursor-pointer')}
                    data-attr="progress-value"
                    onClick={onValueClick}
                >
                    {formatValue(resultSeries.aggregated_value)}
                </span>
                <span className="text-xl font-semibold text-secondary" data-attr="progress-percent">
                    {percentage(fraction, 1)}
                </span>
            </div>
            <LemonProgress percent={fraction * 100} size="large" strokeColor={strokeColor} />
            <div className="flex items-center justify-between gap-2 text-sm text-secondary">
                <span className="truncate">{target.label || 'Target'}</span>
                <span className="shrink-0">{formatValue(target.value)}</span>
            </div>
        </div>
    )
}
