import type { ComponentProps } from 'react'

import { IconGraph } from '@posthog/icons'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { useChartTheme } from 'lib/charts/hooks'

import { SidebarOption } from '~/layout/today/sidebar/SidebarOption'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'

export interface SidebarMetricProps {
    value: string
    label: string
    active: boolean
    to: string
    dataAttr: string
    meta?: string
    metric: Pick<ComponentProps<typeof Metric>, 'value' | 'change' | 'showChange' | 'data' | 'labels'> | null
    formatValue: (value: number) => string
}

export function SidebarMetric({
    value,
    label,
    active,
    to,
    dataAttr,
    meta,
    metric,
    formatValue,
}: SidebarMetricProps): JSX.Element {
    const theme = useChartTheme()
    if (!metric) {
        // A missing insight and one without a number still open the insight, whose page says why.
        return (
            <SidebarRow
                value={value}
                label={label}
                meta={meta}
                icon={<IconGraph />}
                to={to}
                active={active}
                dataAttr={dataAttr}
            />
        )
    }
    return (
        <SidebarOption
            value={value}
            to={to}
            active={active}
            title={label}
            className="h-auto py-1.5"
            data-attr={dataAttr}
        >
            <Metric
                value={metric.value}
                change={metric.change}
                showChange={metric.showChange}
                data={metric.data}
                labels={metric.labels}
                theme={theme}
                formatValue={formatValue}
                sparklineHeight={24}
                className="w-full px-0"
            >
                <MetricHeader>
                    <MetricTitle className="truncate text-xs font-normal text-muted-foreground">{label}</MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue className="text-xl" />
                <MetricSparkline className="mt-1" />
            </Metric>
        </SidebarOption>
    )
}
