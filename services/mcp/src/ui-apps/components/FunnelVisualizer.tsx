import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { BarChart, TooltipSurface, type TooltipContext } from '@posthog/quill-charts'

import {
    buildFunnelStepsBarConfig,
    buildFunnelStepsBars,
    type FunnelStepsBarRow,
} from 'products/product_analytics/frontend/insights/funnels/shared/funnelStepsBarShared'

import { CHART_THEME, FUNNEL_COLOR } from './charts/theme'
import type { FunnelVisualizerProps } from './types'
import { formatNumber, formatPercent, normalizeFunnelSteps } from './utils'

const NOOP = (): void => {}

// The web container hides the x-axis and renders its own StepLegend row; this compact UI app instead
// shows the step names on the axis (truncated) and tracks the cursor with the tooltip.
const CHART_CONFIG = buildFunnelStepsBarConfig({ maxCategoryLabelWidth: 120, tooltipPlacement: 'cursor' })

function renderTooltip(rows: FunnelStepsBarRow[]) {
    return function FunnelTooltip(ctx: TooltipContext): ReactElement | null {
        const row = rows[ctx.dataIndex]
        if (!row) {
            return null
        }
        return (
            <TooltipSurface>
                <div className="font-semibold mb-1">
                    {row.stepIndex + 1}. {row.name}
                </div>
                <div>
                    {formatNumber(row.count)} ({formatPercent(row.fractionOfBasis)} of first step)
                </div>
                {row.stepIndex > 0 && <div>{formatPercent(row.fromPrevious)} from previous step</div>}
            </TooltipSurface>
        )
    }
}

export function FunnelVisualizer({ results }: FunnelVisualizerProps): ReactElement {
    const steps = normalizeFunnelSteps(results)
    const { series, labels, rows, overall } = buildFunnelStepsBars(steps, { color: FUNNEL_COLOR })

    if (steps.length === 0) {
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
        <div data-attr="funnel-steps-bar" className="w-full">
            <div className="flex flex-col h-72 w-full">
                <BarChart
                    series={series}
                    labels={labels}
                    theme={CHART_THEME}
                    config={CHART_CONFIG}
                    tooltip={renderTooltip(rows)}
                    onError={NOOP}
                />
            </div>

            {steps.length >= 2 && (
                <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                    <strong className="text-foreground">Overall conversion:</strong> {formatPercent(overall.rate)} (
                    {formatNumber(overall.lastCount)} of {formatNumber(overall.firstCount)})
                </div>
            )}
        </div>
    )
}
