import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { SingleStepBar } from 'products/product_analytics/frontend/insights/funnels/FunnelBarHorizontalChart/SingleStepBar'
import {
    buildFunnelConversionStep,
    funnelConversionRate,
} from 'products/product_analytics/frontend/insights/funnels/shared/funnelBarHorizontalShared'

import { CHART_THEME, FILLER_COLOR, FUNNEL_COLOR } from './charts/theme'
import type { FunnelVisualizerProps } from './types'
import { formatNumber, formatPercent, normalizeFunnelSteps } from './utils'

const NOOP = (): void => {}
const NO_TOOLTIP = (): null => null

export function FunnelVisualizer({ results }: FunnelVisualizerProps): ReactElement {
    const steps = normalizeFunnelSteps(results)

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

    const firstCount = steps[0]?.count ?? 0
    const lastCount = steps[steps.length - 1]?.count ?? 0

    return (
        <div data-attr="funnel-bar-horizontal" className="w-full">
            <div className="flex flex-col">
                {steps.map((step, stepIndex) => {
                    const fractionOfBasis = funnelConversionRate(step.count, firstCount)
                    const fromPrevious = funnelConversionRate(step.count, steps[stepIndex - 1]?.count ?? 0)
                    const stepData = buildFunnelConversionStep({
                        stepIndex,
                        label: step.name,
                        fractionOfBasis,
                        color: FUNNEL_COLOR,
                        fillerColor: FILLER_COLOR,
                    })

                    return (
                        <div key={stepIndex} className="pb-3">
                            <div className="flex items-baseline justify-between text-sm">
                                <span className="font-medium text-foreground">
                                    {stepIndex + 1}. {step.name}
                                </span>
                                <span className="text-muted-foreground">
                                    {formatPercent(fractionOfBasis)} · {formatNumber(step.count)}
                                </span>
                            </div>
                            <SingleStepBar
                                stepData={stepData}
                                theme={CHART_THEME}
                                interactive={false}
                                onSegmentClick={NOOP}
                                renderTooltip={NO_TOOLTIP}
                                onError={NOOP}
                            />
                            {stepIndex > 0 && (
                                <div className="text-xs text-muted-foreground">
                                    {formatPercent(fromPrevious)} from previous step
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>

            {steps.length >= 2 && (
                <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                    <strong className="text-foreground">Overall conversion:</strong>{' '}
                    {formatPercent(lastCount / firstCount)} ({formatNumber(lastCount)} of {formatNumber(firstCount)})
                </div>
            )}
        </div>
    )
}
