import type { ReactElement, ReactNode } from 'react'

import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'

import { FunnelVisualizer } from './FunnelVisualizer'
import { LifecycleVisualizer } from './LifecycleVisualizer'
import { TrendsVisualizer } from './TrendsVisualizer'
import type { FunnelResult, FunnelsQuery, LifecycleQuery, LifecycleResult, TrendsQuery, TrendsResult } from './types'

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
    if (data.query.kind === 'LifecycleQuery') {
        return (
            <LifecycleVisualizer
                query={data.query as unknown as LifecycleQuery}
                results={data.results as unknown as LifecycleResult}
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
