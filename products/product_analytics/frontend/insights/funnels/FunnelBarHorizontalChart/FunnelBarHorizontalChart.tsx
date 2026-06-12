import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ErrorInfo, useMemo } from 'react'

import { funnelDataLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelDataLogic'
import { funnelPersonsModalLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelPersonsModalLogic'
import { type ChartTheme, type TooltipContext } from '@posthog/quill-charts'
import { buildTheme } from '@posthog/visualizations/charts/utils/theme'

import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { type ChartParams, FunnelStepReference, StepOrderValue } from '~/types'

import { FunnelBarHorizontalTooltip } from './FunnelBarHorizontalTooltip'
import { buildFunnelBarHorizontalData, type FunnelBarHorizontalSegmentMeta } from './funnelBarHorizontalTransforms'
import { GlyphColumn } from './GlyphColumn'
import { SingleStepBar } from './SingleStepBar'
import { StepFooter } from './StepFooter'
import { StepHeader } from './StepHeader'

function getFillerColor(): string {
    if (typeof document === 'undefined') {
        return 'rgba(0, 0, 0, 0.08)'
    }
    return getComputedStyle(document.body).getPropertyValue('--color-border-primary').trim() || 'rgba(0, 0, 0, 0.08)'
}

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'funnels-bar-horizontal-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function FunnelBarHorizontalChart({
    showPersonsModal: showPersonsModalProp = true,
    inCardView,
}: ChartParams): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])
    const fillerColor = useMemo(() => getFillerColor(), [isDarkModeOn])

    const { insightProps } = useValues(insightLogic)
    const {
        visibleStepsWithConversionMetrics,
        aggregationTargetLabel,
        funnelsFilter,
        breakdownFilter,
        isStepOptional,
        getFunnelsColor,
        querySource,
    } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep, openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const steps = visibleStepsWithConversionMetrics
    const stepReference = funnelsFilter?.funnelStepReference || FunnelStepReference.total
    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const interactive = showPersonsModal && !inCardView
    const isUnordered = funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED
    const hasOptionalSteps = steps.some((_, stepIndex) => isStepOptional(stepIndex + 1))
    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural

    const stepsData = useMemo(
        () =>
            buildFunnelBarHorizontalData(steps, {
                stepReference,
                breakdownFilter,
                getColor: getFunnelsColor,
                getLabel: (variant) => String(variant.breakdown_value ?? variant.name ?? ''),
                fillerColor,
            }),
        [steps, stepReference, breakdownFilter, getFunnelsColor, fillerColor]
    )

    if (steps.length === 0) {
        return null
    }

    return (
        <div data-attr="funnel-bar-horizontal" className="w-full p-4">
            <div className="flex flex-col">
                {steps.map((step, stepIndex) => {
                    const isOptional = isStepOptional(stepIndex + 1)

                    const onSegmentClick = (meta: FunnelBarHorizontalSegmentMeta): void => {
                        if (meta.isDropOff) {
                            openPersonsModalForStep({ step, converted: false })
                            return
                        }
                        if (meta.breakdownIndex != null && step.nested_breakdown?.[meta.breakdownIndex]) {
                            openPersonsModalForSeries({
                                step,
                                series: step.nested_breakdown[meta.breakdownIndex],
                                converted: true,
                            })
                            return
                        }
                        openPersonsModalForStep({ step, converted: true })
                    }

                    const renderTooltip = (ctx: TooltipContext<FunnelBarHorizontalSegmentMeta>): JSX.Element | null => (
                        <FunnelBarHorizontalTooltip
                            context={ctx}
                            step={step}
                            stepIndex={stepIndex}
                            breakdownFilter={breakdownFilter}
                            groupTypeLabel={groupTypeLabel}
                            showPersonsModal={showPersonsModal}
                        />
                    )

                    return (
                        <div className="flex" key={step.order}>
                            <GlyphColumn
                                index={stepIndex}
                                stepCount={steps.length}
                                glyphNumber={step.order + 1}
                                isUnordered={isUnordered}
                                isOptional={isOptional}
                                hasOptionalSteps={hasOptionalSteps}
                            />
                            <div className="flex-1 min-w-0 pb-3 pl-2">
                                <StepHeader
                                    step={step}
                                    stepIndex={stepIndex}
                                    previousStep={steps[stepIndex - 1]}
                                    isUnordered={isUnordered}
                                    isOptional={isOptional}
                                />
                                <SingleStepBar
                                    stepData={stepsData[stepIndex]}
                                    theme={theme}
                                    interactive={interactive}
                                    onSegmentClick={onSegmentClick}
                                    renderTooltip={renderTooltip}
                                    onError={handleChartError}
                                />
                                <StepFooter
                                    step={step}
                                    stepIndex={stepIndex}
                                    funnelsFilter={funnelsFilter}
                                    aggregationTargetLabel={aggregationTargetLabel}
                                    isOptional={isOptional}
                                    showPersonsModal={showPersonsModal}
                                    onOpenConverted={() => openPersonsModalForStep({ step, converted: true })}
                                    onOpenDroppedOff={() => openPersonsModalForStep({ step, converted: false })}
                                />
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
