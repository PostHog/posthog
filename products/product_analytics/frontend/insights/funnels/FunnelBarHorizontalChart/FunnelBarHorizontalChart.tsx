import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ErrorInfo, useMemo } from 'react'

import { type TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { type ChartParams, FunnelStepReference, type FunnelStepWithConversionMetrics, StepOrderValue } from '~/types'

import { FunnelBarHorizontalTooltip } from './FunnelBarHorizontalTooltip'
import {
    buildFunnelBarHorizontalCompareData,
    buildFunnelBarHorizontalData,
    type FunnelBarHorizontalSegmentMeta,
} from './funnelBarHorizontalTransforms'
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
    const theme = useChartTheme()
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
        isComparedFunnel,
        insightData,
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

    const buildOptions = useMemo(
        () => ({
            stepReference,
            breakdownFilter,
            getColor: getFunnelsColor,
            getLabel: (variant: FunnelStepWithConversionMetrics) =>
                String(variant.breakdown_value ?? variant.name ?? ''),
            fillerColor,
        }),
        [stepReference, breakdownFilter, getFunnelsColor, fillerColor]
    )

    const stepsData = useMemo(
        () => (isComparedFunnel ? [] : buildFunnelBarHorizontalData(steps, buildOptions)),
        [steps, buildOptions, isComparedFunnel]
    )
    const compareStepsData = useMemo(
        () => (isComparedFunnel ? buildFunnelBarHorizontalCompareData(steps, buildOptions) : []),
        [steps, buildOptions, isComparedFunnel]
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
                        // Stacked breakdown + compare: the drop-off band aggregates every value for the
                        // period, so it can't be scoped to one value and isn't clickable. Pure compare tags
                        // each drop-off with its period's breakdownIndex, so it stays interactive.
                        if (isComparedFunnel && meta.isDropOff && meta.breakdownIndex == null) {
                            return
                        }
                        // Compare: both the bar and its drop-off filler carry a period breakdownIndex, so
                        // route the matching period series (converted vs. dropped-off) — handled before the
                        // generic drop-off branch, which would otherwise open the aggregate step.
                        if (
                            isComparedFunnel &&
                            meta.breakdownIndex != null &&
                            step.nested_breakdown?.[meta.breakdownIndex]
                        ) {
                            openPersonsModalForSeries({
                                step,
                                series: step.nested_breakdown[meta.breakdownIndex],
                                converted: !meta.isDropOff,
                            })
                            return
                        }
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
                            resolvedDateRange={insightData?.resolved_date_range}
                            compareTo={querySource?.compareFilter?.compare_to}
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
                                {isComparedFunnel ? (
                                    compareStepsData[stepIndex]?.bars.map((bar) => (
                                        <SingleStepBar
                                            key={bar.series[0].key}
                                            stepData={bar}
                                            theme={theme}
                                            interactive={interactive}
                                            onSegmentClick={onSegmentClick}
                                            renderTooltip={renderTooltip}
                                            onError={handleChartError}
                                            heightClassName="h-5"
                                        />
                                    ))
                                ) : (
                                    <SingleStepBar
                                        stepData={stepsData[stepIndex]}
                                        theme={theme}
                                        interactive={interactive}
                                        onSegmentClick={onSegmentClick}
                                        renderTooltip={renderTooltip}
                                        onError={handleChartError}
                                    />
                                )}
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
