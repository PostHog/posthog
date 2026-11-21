import { Badge, Card, CardContent, Text } from '@posthog/quill'
import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    formatReportMetricParts,
    reportMetricChartType,
    reportMetricUnitWord,
    reportMetricWindowLabel,
} from '../../../utils/reportMetrics'
import { ReportStageProse } from './ReportStageProse'

function goalUnit(metric: ReportMetricApi, unit: string | null): string {
    const word = unit ?? reportMetricUnitWord(metric)
    return metric.goal_grain === 'per_interval' ? `${word} per day`.trim() : word
}

/**
 * The two figures a reader weighs a report by: the result the fix should produce, and what was
 * measured when the report was written.
 */
export function ReportImpactCards({
    metric,
    expectedImpact,
}: {
    metric: ReportMetricApi
    /** The summary's "Expected impact" section, as markdown. */
    expectedImpact: string | null
}): JSX.Element {
    const theme = useChartTheme()
    const goal = formatReportMetricParts(metric, metric.goal_value)
    const observed = formatReportMetricParts(metric, metric.value)
    const windowLabel = reportMetricWindowLabel(metric.query)
    const series = metric.series ?? []

    return (
        <div className="grid grid-cols-1 gap-3 @xl:grid-cols-3" data-attr="inbox-report-impact-cards">
            <Card size="sm" className="@xl:col-span-2">
                <CardContent className="flex flex-col gap-2">
                    <Text size="xs" variant="muted" weight="medium" render={<h3 className="m-0" />}>
                        Expected impact
                    </Text>
                    {goal && (
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                            <span className="text-2xl font-semibold tabular-nums text-success-foreground">
                                {goal.value}
                            </span>
                            <Text size="sm" variant="muted" render={<span />}>
                                {goalUnit(metric, goal.unit)}
                            </Text>
                            {metric.role === 'primary' && <Badge variant="info">Primary</Badge>}
                        </div>
                    )}
                    <Text size="sm" weight="medium" render={<p className="m-0" />}>
                        {metric.title}
                    </Text>
                    {expectedImpact && <ReportStageProse markdown={expectedImpact} tone="muted" size="xs" />}
                </CardContent>
            </Card>
            <Card size="sm">
                <CardContent className="flex h-full flex-col gap-2">
                    <Text size="xs" variant="muted" weight="medium" render={<h3 className="m-0" />}>
                        Observed
                    </Text>
                    {observed && (
                        <div className="flex flex-wrap items-baseline gap-x-2">
                            <span className="text-2xl font-semibold tabular-nums">{observed.value}</span>
                            <Text size="sm" variant="muted" render={<span />}>
                                {observed.unit ?? reportMetricUnitWord(metric)}
                            </Text>
                        </div>
                    )}
                    {windowLabel && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {windowLabel}
                        </Text>
                    )}
                    {series.length > 1 && (
                        <div className="mt-auto pt-2">
                            <Sparkline data={series} type={reportMetricChartType(metric)} theme={theme} height={40} />
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    )
}
