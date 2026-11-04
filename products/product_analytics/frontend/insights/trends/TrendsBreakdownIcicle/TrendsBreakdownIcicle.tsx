import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { FlameGraph } from '@posthog/quill-charts'
import type { FlameGraphConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { getResultSeries } from 'scenes/insights/utils/resultSeries'
import { teamLogic } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { getResultSeriesName } from '../../shared/resultSeriesName'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { humanizeSeriesLabel } from '../shared/humanizeSeriesLabel'
import { type BreakdownIcicleValue, buildBreakdownIcicle } from './trendsBreakdownIcicleTransforms'

interface TrendsBreakdownIcicleProps {
    context?: QueryContext<InsightVizNode>
}

const handleChartError = makeChartErrorHandler('trends-breakdown-icicle')

export function TrendsBreakdownIcicle({ context }: TrendsBreakdownIcicleProps): JSX.Element {
    const theme = useChartTheme()
    const { insightProps } = useValues(insightLogic)
    const { baseCurrency } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { indexedResults, getTrendsHidden, trendsFilter, querySource, breakdownFilter } = useValues(
        trendsDataLogic(insightProps)
    )

    const seriesLabel = useCallback(
        (result: IndexedTrendResult): string =>
            getResultSeriesName(getResultSeries(querySource, result)) ?? humanizeSeriesLabel(result.label),
        [querySource]
    )

    const data = useMemo(() => {
        const visible = ((indexedResults ?? []) as IndexedTrendResult[]).filter((result) => !getTrendsHidden(result))
        const seriesCount = new Set(visible.map((result) => result.order ?? result.action?.order)).size
        return buildBreakdownIcicle(visible, {
            rootLabel: seriesCount === 1 ? seriesLabel(visible[0]) : 'All series',
            seriesLabel,
            formatValue: (value: BreakdownIcicleValue, level: number) =>
                formatBreakdownLabel(value, breakdownFilter, allCohorts.results, formatPropertyValueForDisplay, level),
        })
    }, [
        indexedResults,
        getTrendsHidden,
        seriesLabel,
        breakdownFilter,
        allCohorts.results,
        formatPropertyValueForDisplay,
    ])

    const config: FlameGraphConfig = useChartConfig(
        () => ({
            preset: 'breakdown',
            // Breakdowns nest two or three levels deep, so taller rows read better than filling the card.
            rowHeight: 32,
            valueFormatter: (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
        }),
        [trendsFilter, baseCurrency]
    )

    if (!data.value) {
        return (
            <InsightEmptyState
                heading={context?.emptyStateHeading}
                detail={context?.emptyStateDetail}
                sampleDataVariant="bar"
            />
        )
    }

    return (
        <div className="flex flex-col w-full flex-1 min-h-0 p-2">
            <FlameGraph
                data={data}
                theme={theme}
                config={config}
                dataAttr="trend-breakdown-icicle"
                onError={handleChartError}
            />
        </div>
    )
}
