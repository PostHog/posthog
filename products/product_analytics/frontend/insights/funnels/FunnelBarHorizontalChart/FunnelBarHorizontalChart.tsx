import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, useState, type ErrorInfo } from 'react'

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

// Each row is `gap + bar + gap`. The bar keeps a constant thickness; the gaps grow to fit the
// step's header/footer text (which wraps to more lines as the chart narrows), so rows never overlap.
const MIN_GAP_PX = 28
const GAP_BREATHING_PX = 10
const BAR_THICKNESS_PX = 30
const GLYPH_COLUMN_WIDTH_PX = 40

function getTrackColor(): string {
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
    const trackColor = useMemo(() => getTrackColor(), [isDarkModeOn])

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

    const [measuredGapPx, setMeasuredGapPx] = useState<number | null>(null)
    const gapPx = Math.max(MIN_GAP_PX, (measuredGapPx ?? 0) + GAP_BREATHING_PX)
    const rowHeightPx = 2 * gapPx + BAR_THICKNESS_PX
    const bandPadding = (2 * gapPx) / rowHeightPx
    const gapFraction = gapPx / rowHeightPx
    const handleMeasureGap = useCallback((px: number): void => {
        setMeasuredGapPx((prev) => (prev != null && Math.abs(prev - px) < 0.5 ? prev : px))
    }, [])

    const { series, labels } = useMemo(
        () =>
            buildFunnelBarHorizontalData(steps, {
                stepReference,
                breakdownFilter,
                getColor: getFunnelsColor,
                getLabel: (variant) => String(variant.breakdown_value ?? variant.name ?? ''),
            }),
        [steps, stepReference, breakdownFilter, getFunnelsColor]
    )

    const chartConfig = useMemo<BarChartConfig>(
        () => ({
            barLayout: 'stacked',
            bars: { cornerRadius: 6, rounding: 'pill', track: { color: trackColor }, bandPadding },
            axisOrientation: 'horizontal',
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            animateHover: true,
            margins: { top: 0, right: 0, bottom: 0, left: GLYPH_COLUMN_WIDTH_PX },
            tooltip: { placement: 'cursor' },
        }),
        [trackColor, bandPadding]
    )

    const onPointClick = (clickData: PointClickData<FunnelBarHorizontalSegmentMeta>): void => {
        const step = steps[clickData.dataIndex]
        if (!step) {
            return
        }
        // A click in the empty track region is the drop-off remainder.
        if (clickData.inTrack) {
            openPersonsModalForStep({ step, converted: false })
            return
        }
        const meta = clickData.series.meta
        if (meta?.breakdownIndex != null && step.nested_breakdown?.[meta.breakdownIndex]) {
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
        <div data-attr="funnel-bar-horizontal" className="w-full px-1 py-4">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative flex w-full" style={{ height: steps.length * rowHeightPx }}>
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
                        gapFraction={gapFraction}
                        onMeasureGap={handleMeasureGap}
                    />
                </BarChart>
            </div>
        </div>
    )
}
