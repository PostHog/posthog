import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { SingleStepBar } from 'products/product_analytics/frontend/insights/funnels/FunnelBarHorizontalChart/SingleStepBar'
import { buildFunnelBars } from 'products/product_analytics/frontend/insights/funnels/shared/funnelBarHorizontalShared'

import { CHART_THEME, FILLER_COLOR, FUNNEL_COLOR } from './charts/theme'
import type { FunnelVisualizerProps } from './types'
import { formatNumber, formatPercent, normalizeFunnelSteps } from './utils'

const NOOP = (): void => {}
const NO_TOOLTIP = (): null => null

export function FunnelVisualizer({ results }: FunnelVisualizerProps): ReactElement {
    const { rows, overall } = buildFunnelBars(normalizeFunnelSteps(results), {
        color: FUNNEL_COLOR,
        fillerColor: FILLER_COLOR,
    })

    if (rows.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>{emptyStateIllustration('funnel')}</EmptyMedia>
                    <EmptyDescription>No funnel data available</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div data-attr="funnel-bar-horizontal" className="w-full">
            <div className="flex flex-col">
                {rows.map((row) => (
                    <div key={row.stepIndex} className="pb-3">
                        <div className="flex items-baseline justify-between text-sm">
                            <span className="font-medium text-foreground">
                                {row.stepIndex + 1}. {row.name}
                            </span>
                            <span className="text-muted-foreground">
                                {formatPercent(row.fractionOfBasis)} · {formatNumber(row.count)}
                            </span>
                        </div>
                        <SingleStepBar
                            stepData={row.stepData}
                            theme={CHART_THEME}
                            interactive={false}
                            onSegmentClick={NOOP}
                            renderTooltip={NO_TOOLTIP}
                            onError={NOOP}
                        />
                        {row.stepIndex > 0 && (
                            <div className="text-xs text-muted-foreground">
                                {formatPercent(row.fromPrevious)} from previous step
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {rows.length >= 2 && (
                <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                    <strong className="text-foreground">Overall conversion:</strong> {formatPercent(overall.rate)} (
                    {formatNumber(overall.lastCount)} of {formatNumber(overall.firstCount)})
                </div>
            )}
        </div>
    )
}
