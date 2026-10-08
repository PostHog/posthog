import { ProportionBar } from '@posthog/quill-charts'
import type { ProportionBarConfig } from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { type TrendsPartOfWholeChartProps, useTrendsPartOfWholeChart } from '../shared/useTrendsPartOfWholeChart'

const handleChartError = makeChartErrorHandler('trends-proportion-bar')

export function TrendsProportionBar(props: TrendsPartOfWholeChartProps): JSX.Element {
    const { context } = props
    const {
        theme,
        legendConfig,
        series,
        hasResults,
        showAggregation,
        formattedTotal,
        valueFormatter,
        renderTooltip,
        onSliceClick,
    } = useTrendsPartOfWholeChart(props)

    const config: ProportionBarConfig = useChartConfig(() => ({ legend: legendConfig }), [legendConfig])

    if (!hasResults) {
        return (
            <InsightEmptyState
                heading={context?.emptyStateHeading}
                detail={context?.emptyStateDetail}
                sampleDataVariant="proportionBar"
            />
        )
    }

    return (
        <div className="flex flex-col w-full flex-1 min-h-0 justify-center gap-6">
            <ProportionBar<TrendsSeriesMeta>
                series={series}
                theme={theme}
                config={config}
                tooltip={renderTooltip}
                onSliceClick={onSliceClick}
                valueFormatter={valueFormatter}
                dataAttr="trend-proportion-bar"
                onError={handleChartError}
            />
            {showAggregation && (
                <div className="text-7xl text-center font-bold m-0" data-attr="trend-total">
                    {formattedTotal}
                </div>
            )}
        </div>
    )
}
