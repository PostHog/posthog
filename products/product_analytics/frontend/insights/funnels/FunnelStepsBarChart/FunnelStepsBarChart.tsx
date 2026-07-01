import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { BarChart, DEFAULT_MARGINS } from '@posthog/quill-charts'
import type { PointClickData, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { StepLegend } from 'scenes/funnels/FunnelBarVertical/StepLegend'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { hasBreakdown } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { ChartParams } from '~/types'

import { buildFunnelStepsBarConfig, FUNNEL_STEPS_BAND_PADDING } from '../shared/funnelStepsBarShared'
import { FunnelStepsBarTooltip } from './FunnelStepsBarTooltip'
import {
    buildFunnelStepsBarData,
    type FunnelStepsBarSeriesMeta,
    resolveFunnelStepClick,
} from './funnelStepsBarTransforms'

const BASE_STEP_WIDTH_PX = 240
const PER_BAR_WIDTH_PX = 20

const chartConfig = buildFunnelStepsBarConfig({
    hideXAxis: true,
    animateHover: true,
    tooltipPlacement: 'top',
    margins: { left: DEFAULT_MARGINS.left },
})

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
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]
    // buildTheme() reads CSS vars; we re-memo on isDarkModeOn so the theme refreshes
    // when the user toggles dark mode even though the function takes no arguments.
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics, getFunnelsColor, breakdownFilter, querySource, insightData } = useValues(
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
                // Breakdown + compare bars share a breakdown value across periods, so the legend
                // must also name the period; plain breakdown/compare bars keep their single label.
                getLabel: (variant) =>
                    variant.compare_label && hasBreakdown(variant.breakdown_value)
                        ? `${String(variant.breakdown_value)} · ${
                              variant.compare_label === 'current' ? 'Current' : 'Previous'
                          }`
                        : String(variant.breakdown_value ?? variant.name ?? ''),
            }),
        [steps, getFunnelsColor]
    )

    // Only breakdown + compare needs a legend mapping color → breakdown value (and period); plain
    // breakdown reads off the results table and pure compare is self-evident, so neither regresses.
    const isBreakdownCompare = steps[0]?.nested_breakdown?.some(
        (variant) => variant.compare_label != null && hasBreakdown(variant.breakdown_value)
    )
    const config = useMemo(() => {
        const base = isBreakdownCompare ? { ...chartConfig, legend: { show: true, interactive: false } } : chartConfig
        if (quillTooltipEnabled) {
            return { ...base, tooltip: { pinnable: true, placement: 'cursor' as const } }
        }
        return base
    }, [isBreakdownCompare, quillTooltipEnabled])

    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural
    const showTime = steps.some((step) => step.average_conversion_time != null)

    const breakdownCount = series.length
    const stepWidthPx = Math.max(BASE_STEP_WIDTH_PX, breakdownCount * PER_BAR_WIDTH_PX)
    const barsWidth = steps.length * stepWidthPx
    const chartWidth = DEFAULT_MARGINS.left + barsWidth + DEFAULT_MARGINS.right

    const stepBandWidthPx = stepWidthPx * (1 - FUNNEL_STEPS_BAND_PADDING)

    const onPointClick = useCallback(
        (clickData: PointClickData<FunnelStepsBarSeriesMeta>): void => {
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
                    <BarChart<FunnelStepsBarSeriesMeta>
                        series={series}
                        labels={labels}
                        theme={theme}
                        config={config}
                        tooltip={renderTooltip}
                        onPointClick={showPersonsModal ? onPointClick : undefined}
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
