import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { DEFAULT_MARGINS, FunnelChart } from '@posthog/quill-charts'
import type { FunnelChartConfig, FunnelStepClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { StepLegend } from 'scenes/funnels/FunnelBarVertical/StepLegend'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { ChartParams } from '~/types'

import { FunnelStepsBarTooltip } from './FunnelStepsBarTooltip'
import {
    buildFunnelStepsBarData,
    FUNNEL_STEPS_BAR_TOOLTIP_CONFIG,
    resolveFunnelStepClick,
    type FunnelStepsBarSeriesMeta,
} from './funnelStepsBarTransforms'

const BASE_STEP_WIDTH_PX = 240
const PER_BAR_WIDTH_PX = 20

const CHART_CONFIG: FunnelChartConfig = {
    animateHover: true,
    // Keep the chart from collapsing under a tall StepLegend footer.
    chartMinHeight: 150,
    margins: { left: DEFAULT_MARGINS.left },
    tooltip: FUNNEL_STEPS_BAR_TOOLTIP_CONFIG,
}

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'funnels-steps-bar-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function FunnelStepsBarChart({
    showPersonsModal: showPersonsModalProp = true,
    inCardView,
}: ChartParams): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics, getFunnelsColor, breakdownFilter, querySource, insightData } = useValues(
        funnelDataLogic(insightProps)
    )
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const steps = visibleStepsWithConversionMetrics

    const { series } = useMemo(
        () =>
            buildFunnelStepsBarData(steps, {
                getColor: getFunnelsColor,
                getLabel: (variant) => String(variant.breakdown_value ?? variant.name ?? ''),
            }),
        [steps, getFunnelsColor]
    )

    // Feeds the tooltip header only; the visible labels come from the StepLegend footer.
    const stepLabels = useMemo(() => steps.map((step) => String(step.custom_name ?? step.name ?? '')), [steps])

    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural
    const showTime = steps.some((step) => step.average_conversion_time != null)

    const breakdownCount = series.length
    const stepWidthPx = Math.max(BASE_STEP_WIDTH_PX, breakdownCount * PER_BAR_WIDTH_PX)
    const chartWidth = DEFAULT_MARGINS.left + steps.length * stepWidthPx + DEFAULT_MARGINS.right

    const onStepClick = useCallback(
        (clickData: FunnelStepClickData<FunnelStepsBarSeriesMeta>): void => {
            const target = resolveFunnelStepClick(steps, clickData)
            if (!target) {
                return
            }
            openPersonsModalForSeries(target)
        },
        [steps, openPersonsModalForSeries]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<FunnelStepsBarSeriesMeta>): JSX.Element => (
            <FunnelStepsBarTooltip
                context={ctx}
                steps={steps}
                breakdownFilter={breakdownFilter}
                groupTypeLabel={groupTypeLabel}
                showPersonsModal={showPersonsModal}
                resolvedDateRange={insightData?.resolved_date_range}
                compareTo={querySource?.compareFilter?.compare_to}
            />
        ),
        [steps, breakdownFilter, groupTypeLabel, showPersonsModal, insightData?.resolved_date_range, querySource]
    )

    const renderStepFooter = useCallback(
        (stepIndex: number): JSX.Element | null => {
            const step = steps[stepIndex]
            if (!step) {
                return null
            }
            return (
                <StepLegend
                    step={step}
                    stepIndex={stepIndex}
                    showTime={showTime}
                    showPersonsModal={showPersonsModal}
                    inCardView={inCardView}
                />
            )
        },
        [steps, showTime, showPersonsModal, inCardView]
    )

    if (steps.length === 0) {
        return null
    }

    return (
        <ScrollableShadows direction="horizontal" className="flex-1" contentClassName="flex h-full flex-col">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="flex flex-1 flex-col" style={{ width: chartWidth }} data-attr="funnel-steps-bar-chart">
                <FunnelChart<FunnelStepsBarSeriesMeta>
                    steps={stepLabels}
                    series={series}
                    theme={theme}
                    config={CHART_CONFIG}
                    tooltip={renderTooltip}
                    onStepClick={showPersonsModal ? onStepClick : undefined}
                    stepFooter={renderStepFooter}
                    dataAttr="funnel-steps-bar-chart-canvas"
                    onError={handleChartError}
                />
            </div>
        </ScrollableShadows>
    )
}
