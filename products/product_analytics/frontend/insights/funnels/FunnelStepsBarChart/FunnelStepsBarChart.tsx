import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { DEFAULT_MARGINS, FunnelChart, ValueLabels } from '@posthog/quill-charts'
import type { FunnelChartConfig, FunnelStepClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { ChartParams } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { FunnelStepsBarTooltip } from './FunnelStepsBarTooltip'
import {
    buildFunnelStepsBarData,
    formatFunnelStepBarLabel,
    FUNNEL_STEPS_BAR_TOOLTIP_CONFIG,
    resolveFunnelStepClick,
    type FunnelStepsBarSeriesMeta,
} from './funnelStepsBarTransforms'
import { StepLegend } from './StepLegend'
import { StepNameLabel } from './StepNameLabel'

const MIN_STEP_WIDTH_PX = 144
const MAX_STEP_WIDTH_PX = 240
const PER_BAR_WIDTH_PX = 20

const LEGACY_CHART_CONFIG: FunnelChartConfig = {
    animateHover: true,
    // Keep the chart from collapsing under a tall StepLegend footer.
    chartMinHeight: 150,
    margins: { left: DEFAULT_MARGINS.left },
    tooltip: FUNNEL_STEPS_BAR_TOOLTIP_CONFIG,
}

const CHART_CONFIG: FunnelChartConfig = { ...LEGACY_CHART_CONFIG, stepFooterAlign: 'center' }

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
    const { featureFlags } = useValues(featureFlagLogic)
    const hasBarLabels = !!featureFlags[FEATURE_FLAGS.FUNNEL_STEPS_BAR_LABELS]
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
    const chartWidth = (stepWidthPx: number): number =>
        DEFAULT_MARGINS.left +
        steps.length * Math.max(stepWidthPx, breakdownCount * PER_BAR_WIDTH_PX) +
        DEFAULT_MARGINS.right

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
            return hasBarLabels ? (
                <StepNameLabel step={step} stepIndex={stepIndex} />
            ) : (
                <StepLegend
                    step={step}
                    stepIndex={stepIndex}
                    showTime={showTime}
                    showPersonsModal={showPersonsModal}
                    inCardView={inCardView}
                />
            )
        },
        [steps, hasBarLabels, showTime, showPersonsModal, inCardView]
    )

    if (steps.length === 0) {
        return null
    }

    return (
        <ScrollableShadows direction="horizontal" className="flex-1" contentClassName="flex h-full flex-col">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div
                className={clsx('flex flex-1 flex-col', hasBarLabels && 'w-full')}
                style={
                    hasBarLabels
                        ? { minWidth: chartWidth(MIN_STEP_WIDTH_PX), maxWidth: chartWidth(MAX_STEP_WIDTH_PX) }
                        : { width: chartWidth(MAX_STEP_WIDTH_PX) }
                }
                data-attr="funnel-steps-bar-chart"
            >
                <FunnelChart<FunnelStepsBarSeriesMeta>
                    steps={stepLabels}
                    series={series}
                    theme={theme}
                    config={hasBarLabels ? CHART_CONFIG : LEGACY_CHART_CONFIG}
                    tooltip={renderTooltip}
                    onStepClick={showPersonsModal ? onStepClick : undefined}
                    stepFooter={renderStepFooter}
                    dataAttr="funnel-steps-bar-chart-canvas"
                    onError={handleChartError}
                >
                    {hasBarLabels && <ValueLabels valueFormatter={formatFunnelStepBarLabel} offset={4} />}
                </FunnelChart>
            </div>
        </ScrollableShadows>
    )
}
