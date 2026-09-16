import { IconGlobe, IconGraph, IconPieChart, IconRetentionHeatmap, IconTrends } from '@posthog/icons'

import {
    Icon123,
    IconAreaChart,
    IconCumulativeChart,
    IconDonutChart,
    IconTableChart,
    IconTrendingUp,
} from 'lib/lemon-ui/icons'

import type { ChartDisplayIcon as ChartDisplayIconKind } from './chartDisplayOptions'

export function ChartDisplayIcon({ icon }: { icon: ChartDisplayIconKind }): JSX.Element {
    switch (icon) {
        case 'area':
            return <IconAreaChart />
        case 'bar':
            return <IconGraph />
        case 'calendarHeatmap':
            return <IconRetentionHeatmap />
        case 'cumulative':
            return <IconCumulativeChart />
        case 'donut':
            return <IconDonutChart />
        case 'horizontalBar':
            return <IconGraph className="rotate-90" />
        case 'line':
            return <IconTrends />
        case 'metric':
            return <IconTrendingUp />
        case 'number':
            return <Icon123 />
        case 'pie':
            return <IconPieChart />
        case 'table':
            return <IconTableChart />
        case 'worldMap':
            return <IconGlobe />
    }
}
