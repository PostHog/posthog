// PROTOTYPE (throwaway): one number with its change and a 30-day line.
import { Card } from '@posthog/quill'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { useChartTheme } from 'lib/charts/hooks'

import { SERIES_LABELS, TODAY } from './prototypeData'

export function OverviewMetric({
    title,
    value,
    data,
    change,
    goodDirection = 'up',
    subtitle,
    format,
}: {
    title: string
    value: number
    data?: number[]
    change?: number
    goodDirection?: 'up' | 'down'
    subtitle?: string
    format?: (value: number) => string
}): JSX.Element {
    const theme = useChartTheme()
    return (
        <Card flush className="min-w-0 pt-3">
            <Metric
                value={value}
                data={data}
                labels={data ? SERIES_LABELS : undefined}
                formatLabel={(label) => (TODAY.isSame(label, 'day') ? 'Today' : label)}
                theme={theme}
                change={change === undefined ? null : { value: change }}
                goodDirection={goodDirection}
                restingSubtitle={subtitle ?? 'Last 30 days'}
                formatValue={format}
                sparklineHeight={36}
                hoverIntentMs={0}
            >
                <MetricHeader>
                    <MetricTitle>{title}</MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue />
                <MetricSubtitle />
                {data ? <MetricSparkline /> : <div className="h-3" />}
            </Metric>
        </Card>
    )
}
