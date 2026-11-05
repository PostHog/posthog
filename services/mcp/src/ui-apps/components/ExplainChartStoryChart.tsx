import type { ReactElement, ReactNode } from 'react'

import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'

import { FunnelVisualizer } from './FunnelVisualizer'
import { TrendsVisualizer } from './TrendsVisualizer'
import type { FunnelResult, FunnelsQuery, TrendsQuery, TrendsResult } from './types'

export interface ExplainChartStoryChartProps {
    data: ExplainChartData
    overlay: ReactNode
    chartClassName: string
}

export function ExplainChartStoryChart({ data, overlay, chartClassName }: ExplainChartStoryChartProps): ReactElement {
    if (data.shape === 'funnel_steps') {
        return (
            <FunnelVisualizer
                query={data.query as unknown as FunnelsQuery}
                results={data.steps.map((step, order) => ({ ...step, order })) as unknown as FunnelResult}
                overlay={overlay}
                chartClassName={chartClassName}
                showTitle={false}
            />
        )
    }
    return (
        <TrendsVisualizer
            query={data.query as unknown as TrendsQuery}
            results={data.results as TrendsResult}
            title={data.insightName ?? 'Trends'}
            overlay={overlay}
            showControls={false}
            chartClassName={chartClassName}
            showTitle={false}
        />
    )
}
