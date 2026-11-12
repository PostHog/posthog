import { useValues } from 'kea'

import { METRIC_SHOW_CHANGE_DEFAULT } from 'lib/components/Metric/metricSummary'
import { formatAggregationAxisValue } from 'lib/insights/aggregationAxisFormat'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { AnalyticsFragmentMetricApi } from 'products/ui_customization/frontend/generated/api.schemas'
import { SidebarMetric } from 'products/ui_customization/frontend/SidebarMetric'

import { isTrendsInsight, todayAnalyticsMetricLogic } from './todayAnalyticsMetricLogic'

interface TodayAnalyticsMetricProps {
    item: AnalyticsFragmentMetricApi
    value: string
    active: boolean
}

/** A number from a trends insight, with its sparkline. Opens the insight. */
export function TodayAnalyticsMetric({ item, value, active }: TodayAnalyticsMetricProps): JSX.Element {
    const { insight, insightLoading, loadFailed, metric } = useValues(
        todayAnalyticsMetricLogic({ shortId: item.insight })
    )
    const { baseCurrency } = useValues(teamLogic)
    return (
        <SidebarMetric
            value={value}
            label={item.label}
            active={active}
            to={urls.insightView(item.insight as InsightShortId)}
            dataAttr="analytics-sidebar-metric"
            meta={
                loadFailed
                    ? 'Couldn’t load'
                    : insightLoading
                      ? undefined
                      : !insight
                        ? 'Not found'
                        : !isTrendsInsight(insight)
                          ? 'Not a trends insight'
                          : undefined
            }
            metric={
                metric
                    ? { ...metric, showChange: metric.trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT }
                    : null
            }
            formatValue={(number) => formatAggregationAxisValue(metric?.trendsFilter, number, baseCurrency)}
        />
    )
}
