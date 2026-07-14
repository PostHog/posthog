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

import { FUNNEL_STEPS_BAND_PADDING } from '../shared/funnelStepsBarShared'
import { FunnelStepsBarTooltip } from './FunnelStepsBarTooltip'
import {
    buildFunnelStepsBarData,
    funnelStepsBarTooltipConfig,
    resolveFunnelStepClick,
    type FunnelStepsBarSeriesMeta,
} from './funnelStepsBarTransforms'

const BASE_STEP_WIDTH_PX = 240
const PER_BAR_WIDTH_PX = 20

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

    // Display step labels for the chart's bands. The built-in x-axis is hidden (`hideStepLabels`) —
    // the StepLegend footer row renders the visible labels — but they still feed the tooltip header.
    const stepLabels = useMemo(() => steps.map((step) => String(step.custom_name ?? step.name ?? '')), [steps])

    const config = useMemo<FunnelChartConfig>(
        () => ({
            hideStepLabels: true,
            animateHover: true,
            margins: { left: DEFAULT_MARGINS.left },
            tooltip: funnelStepsBarTooltipConfig(),
        }),
        []
    )

    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural
    const showTime = steps.some((step) => step.average_conversion_time != null)

    const breakdownCount = series.length
    const stepWidthPx = Math.max(BASE_STEP_WIDTH_PX, breakdownCount * PER_BAR_WIDTH_PX)
    const barsWidth = steps.length * stepWidthPx
    const chartWidth = DEFAULT_MARGINS.left + barsWidth + DEFAULT_MARGINS.right

    const stepBandWidthPx = stepWidthPx * (1 - FUNNEL_STEPS_BAND_PADDING)

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

    if (steps.length === 0) {
        return null
    }

    return (
        <ScrollableShadows direction="horizontal" className="flex-1" contentClassName="flex h-full flex-col">
            <div className="flex flex-1 flex-col" data-attr="funnel-steps-bar-chart">
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div
                    className="flex min-h-[150px] flex-1"
                    style={{ width: chartWidth }}
                    data-attr="funnel-steps-bar-chart-canvas"
                >
                    <FunnelChart<FunnelStepsBarSeriesMeta>
                        steps={stepLabels}
                        series={series}
                        theme={theme}
                        config={config}
                        tooltip={renderTooltip}
                        onStepClick={showPersonsModal ? onStepClick : undefined}
                        onError={handleChartError}
                    />
                </div>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div
                    className="flex shrink-0"
                    style={{ paddingLeft: DEFAULT_MARGINS.left, paddingRight: DEFAULT_MARGINS.right }}
                >
                    <div className="flex shrink-0" style={{ width: barsWidth }}>
                        {steps.map((step, stepIndex) => (
                            <div
                                key={stepIndex}
                                className={`flex min-w-0 flex-1 ${stepIndex === 0 ? 'justify-start' : 'justify-center'}`}
                            >
                                {/* eslint-disable-next-line react/forbid-dom-props */}
                                <div className="min-w-0 overflow-hidden" style={{ width: stepBandWidthPx }}>
                                    <StepLegend
                                        step={step}
                                        stepIndex={stepIndex}
                                        showTime={showTime}
                                        showPersonsModal={showPersonsModal}
                                        inCardView={inCardView}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </ScrollableShadows>
    )
}
