import { useActions, useValues } from 'kea'

import { MetricOptions } from 'lib/components/ChartOptions/MetricOptions'
import { METRIC_SUMMARY_DEFAULT } from 'lib/components/Metric/metricSummary'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import type { MetricChartSettings, TrendsFilter } from '~/queries/schema/schema-general'

function toTrendsFilter(changes: Partial<MetricChartSettings>): Partial<TrendsFilter> {
    return {
        ...('summary' in changes && { metricSummary: changes.summary }),
        ...('showChange' in changes && { metricShowChange: changes.showChange }),
        ...('changeIncreaseColor' in changes && { metricChangeIncreaseColor: changes.changeIncreaseColor }),
        ...('changeDecreaseColor' in changes && { metricChangeDecreaseColor: changes.changeDecreaseColor }),
        ...('colorByDirection' in changes && { metricColorByDirection: changes.colorByDirection }),
        ...('lineIncreaseColor' in changes && { metricLineIncreaseColor: changes.lineIncreaseColor }),
        ...('lineDecreaseColor' in changes && { metricLineDecreaseColor: changes.lineDecreaseColor }),
    }
}

export function MetricFilters(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <MetricOptions
            settings={{
                summary: trendsFilter?.metricSummary,
                showChange: trendsFilter?.metricShowChange,
                changeIncreaseColor: trendsFilter?.metricChangeIncreaseColor,
                changeDecreaseColor: trendsFilter?.metricChangeDecreaseColor,
                colorByDirection: trendsFilter?.metricColorByDirection,
                lineIncreaseColor: trendsFilter?.metricLineIncreaseColor,
                lineDecreaseColor: trendsFilter?.metricLineDecreaseColor,
            }}
            defaultSummary={METRIC_SUMMARY_DEFAULT}
            onChange={(changes) => updateInsightFilter(toTrendsFilter(changes))}
        />
    )
}
