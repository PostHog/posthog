import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart, type BarChartConfig, type PointClickData, type TooltipContext } from 'lib/hog-charts'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { type ChartParams, FunnelStepReference } from '~/types'

import { FunnelBarHorizontalTooltip } from './FunnelBarHorizontalTooltip'
import { buildFunnelBarHorizontalData, type FunnelBarHorizontalSegmentMeta } from './funnelBarHorizontalTransforms'
import { StepDecorations } from './StepDecorations'

const ROW_HEIGHT_PX = 76
const BAR_PADDING = 0.6
const GLYPH_COLUMN_WIDTH_PX = 24

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
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
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
    const hasOptionalSteps = steps.some((_, stepIndex) => isStepOptional(stepIndex + 1))
    const groupTypeLabel = aggregationLabel(querySource?.aggregation_group_type_index).plural

    const { series, labels } = useMemo(
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

    const chartConfig = useMemo<BarChartConfig>(
        () => ({
            barLayout: 'stacked',
            bars: { cornerRadius: 4, bandPadding: BAR_PADDING },
            axisOrientation: 'horizontal',
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            animateHover: true,
            margins: { top: 0, right: 0, bottom: 0, left: GLYPH_COLUMN_WIDTH_PX },
            tooltip: { placement: 'top' },
        }),
        []
    )

    const onPointClick = (clickData: PointClickData<FunnelBarHorizontalSegmentMeta>): void => {
        const meta = clickData.series.meta
        const step = steps[clickData.dataIndex]
        if (!step || !meta) {
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
            steps={steps}
            breakdownFilter={breakdownFilter}
            groupTypeLabel={groupTypeLabel}
            showPersonsModal={showPersonsModal}
        />
    )

    if (steps.length === 0) {
        return null
    }

    return (
        <div data-attr="funnel-bar-horizontal" className="w-full p-4">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative flex w-full" style={{ height: steps.length * ROW_HEIGHT_PX }}>
                <BarChart<FunnelBarHorizontalSegmentMeta>
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={chartConfig}
                    tooltip={renderTooltip}
                    onPointClick={interactive ? onPointClick : undefined}
                    onError={handleChartError}
                >
                    <StepDecorations
                        steps={steps}
                        funnelsFilter={funnelsFilter}
                        aggregationTargetLabel={aggregationTargetLabel}
                        isStepOptional={isStepOptional}
                        hasOptionalSteps={hasOptionalSteps}
                        showPersonsModal={showPersonsModal}
                        openPersonsModalForStep={openPersonsModalForStep}
                        gapFraction={BAR_PADDING / 2}
                    />
                </BarChart>
            </div>
        </div>
    )
}
