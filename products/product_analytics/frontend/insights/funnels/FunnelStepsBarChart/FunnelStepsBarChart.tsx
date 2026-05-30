import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart, DEFAULT_MARGINS } from 'lib/hog-charts'
import type { BarChartConfig, PointClickData, TooltipContext } from 'lib/hog-charts'
import { StepLegend } from 'scenes/funnels/FunnelBarVertical/StepLegend'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { ChartParams, type FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepsBarTooltip } from './FunnelStepsBarTooltip'
import { buildFunnelStepsBarData, type FunnelStepsBarSeriesMeta } from './funnelStepsBarTransforms'

// Per-step width — caps bars and legend column width together so few-step funnels don't
// stretch across the whole chart with huge gaps. Gridlines still span the full width.
const STEP_WIDTH_PX = 320

const baseChartConfig: BarChartConfig = {
    barLayout: 'grouped',
    showGrid: true,
    barCornerRadius: 10,
    barTrack: true,
    barShadow: true,
    animateHover: true,
    hideXAxis: true,
    yTickFormatter: (value) => `${Math.round(value)}%`,
    tooltip: { placement: 'top' },
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
    const { isDarkModeOn } = useValues(themeLogic)
    // buildTheme() reads CSS vars; we re-memo on isDarkModeOn so the theme refreshes
    // when the user toggles dark mode even though the function takes no arguments.
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics, getFunnelsColor, breakdownFilter, querySource } = useValues(
        funnelDataLogic(insightProps)
    )
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const steps = visibleStepsWithConversionMetrics

    const { series, labels } = useMemo(
        () =>
            buildFunnelStepsBarData(steps, {
                getColor: getFunnelsColor,
                getLabel: (variant) => String(variant.breakdown_value ?? variant.name ?? ''),
            }),
        [steps, getFunnelsColor]
    )

    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural
    const showTime = steps.some((step) => step.average_conversion_time != null)
    const barsWidth = steps.length * STEP_WIDTH_PX
    const chartConfig = useMemo<BarChartConfig>(() => ({ ...baseChartConfig, maxBandRange: barsWidth }), [barsWidth])

    const onPointClick = useCallback(
        (clickData: PointClickData<FunnelStepsBarSeriesMeta>): void => {
            const step = steps[clickData.dataIndex]
            if (!step) {
                return
            }
            const breakdownIndex = clickData.series.meta?.breakdownIndex ?? 0
            const variant: FunnelStepWithConversionMetrics = step.nested_breakdown?.[breakdownIndex] ?? step
            openPersonsModalForSeries({ step, series: variant, converted: true })
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
            />
        ),
        [steps, breakdownFilter, groupTypeLabel, showPersonsModal]
    )

    if (steps.length === 0) {
        return null
    }

    return (
        <div className="flex w-full flex-1 flex-col overflow-x-auto" data-attr="funnel-steps-bar-chart">
            <div className="flex flex-1 flex-col">
                <div className="flex min-h-[150px] flex-1">
                    <BarChart<FunnelStepsBarSeriesMeta>
                        series={series}
                        labels={labels}
                        theme={theme}
                        config={chartConfig}
                        tooltip={renderTooltip}
                        onPointClick={showPersonsModal ? onPointClick : undefined}
                        onError={handleChartError}
                    />
                </div>
                {/* Legend padding matches the chart's left margin and bars-width so
                    legend columns align with the bars above. */}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div className="flex" style={{ paddingLeft: DEFAULT_MARGINS.left }}>
                    <div className="flex" style={{ width: barsWidth }}>
                        {steps.map((step, stepIndex) => (
                            <div key={stepIndex} className="min-w-0 flex-1 overflow-hidden">
                                <StepLegend
                                    step={step}
                                    stepIndex={stepIndex}
                                    showTime={showTime}
                                    showPersonsModal={showPersonsModal}
                                    inCardView={inCardView}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
