import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ChartOptionNumberInput } from 'lib/components/ChartOptions/ChartOptionNumberInput'
import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { ExcludeOutliersOption } from 'lib/components/ChartOptions/ExcludeOutliersOption'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { AnnotationsPicker } from 'products/product_analytics/frontend/insights/editor/filters/AnnotationsPicker'
import { AxisLabelFilter } from 'products/product_analytics/frontend/insights/editor/filters/AxisLabelFilter'
import { HideIncompleteConversionWindowPeriodsFilter } from 'products/product_analytics/frontend/insights/editor/filters/HideIncompleteConversionWindowPeriodsFilter'
import { LegendOptionsFilter } from 'products/product_analytics/frontend/insights/editor/filters/LegendOptionsFilter'
import { LineStylePicker } from 'products/product_analytics/frontend/insights/editor/filters/LineStylePicker'
import { MetricFilters } from 'products/product_analytics/frontend/insights/editor/filters/MetricFilters'
import { PercentStackViewFilter } from 'products/product_analytics/frontend/insights/editor/filters/PercentStackViewFilter'
import { ResultCustomizationByPicker } from 'products/product_analytics/frontend/insights/editor/filters/ResultCustomizationByPicker'
import { ScalePicker } from 'products/product_analytics/frontend/insights/editor/filters/ScalePicker'
import { ShowAlertAnomalyPointsFilter } from 'products/product_analytics/frontend/insights/editor/filters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'products/product_analytics/frontend/insights/editor/filters/ShowAlertThresholdLinesFilter'
import { ShowLegendFilter } from 'products/product_analytics/frontend/insights/editor/filters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from 'products/product_analytics/frontend/insights/editor/filters/ShowMultipleYAxesFilter'
import { ShowPieTotalFilter } from 'products/product_analytics/frontend/insights/editor/filters/ShowPieTotalFilter'
import { ShowTrendLinesFilter } from 'products/product_analytics/frontend/insights/editor/filters/ShowTrendLinesFilter'
import { SliceNamesFilter } from 'products/product_analytics/frontend/insights/editor/filters/SliceNamesFilter'
import { StackBreakdownFilter } from 'products/product_analytics/frontend/insights/editor/filters/StackBreakdownFilter'
import { ValueOnSeriesFilter } from 'products/product_analytics/frontend/insights/editor/filters/ValueOnSeriesFilter'
import { YAxisRangeFilter } from 'products/product_analytics/frontend/insights/editor/filters/YAxisRangeFilter'
import { LifecyclePercentagesFilter } from 'products/product_analytics/frontend/insights/lifecycle/filters/LifecyclePercentagesFilter'
import { LifecycleStackingFilter } from 'products/product_analytics/frontend/insights/lifecycle/filters/LifecycleStackingFilter'
import { RetentionCohortLabelStartIndexPicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionCohortLabelStartIndexPicker'
import { RetentionDashboardDisplayPicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionDashboardDisplayPicker'
import { RetentionMeanLineToggle } from 'products/product_analytics/frontend/insights/retention/filters/RetentionMeanLineToggle'
import { RetentionSeriesColorModePicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionSeriesColorModePicker'
import { ConfidenceLevelInput } from 'products/product_analytics/frontend/insights/trends/filters/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'products/product_analytics/frontend/insights/trends/filters/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { displayMatches, isDefaultTrendsLineDisplay, LINE_DISPLAYS } from './displayTypes'

function useLineGraphState(): { isLineGraph: boolean; isLinearScale: boolean } {
    const { insightProps } = useValues(insightLogic)
    const { querySource, display, yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const isLineDisplay = isDefaultTrendsLineDisplay(display, querySource) || displayMatches(display, LINE_DISPLAYS)
    const isCumulativeLineDisplay = display === ChartDisplayType.ActionsLineGraphCumulative
    return {
        isLineGraph: isLineDisplay && !isCumulativeLineDisplay,
        isLinearScale: !yAxisScaleType || yAxisScaleType === 'linear',
    }
}

function ExcludeOutliers(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <ExcludeOutliersOption
            checked={trendsFilter?.excludeBoxPlotOutliers !== false}
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, excludeBoxPlotOutliers: checked },
                    })
                }
            }}
        />
    )
}

function ConfidenceInterval(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <ChartOptionSwitch
            label="Show confidence intervals"
            checked={showConfidenceIntervals}
            disabledReason={
                !isLineGraph
                    ? 'Confidence intervals are only available for line graphs'
                    : !isLinearScale
                      ? 'Confidence intervals are only supported for linear scale.'
                      : undefined
            }
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, showConfidenceIntervals: checked },
                    })
                }
            }}
        />
    )
}

function MovingAverage(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <ChartOptionSwitch
            label="Show moving average"
            checked={showMovingAverage}
            disabledReason={
                !isLineGraph
                    ? 'Moving average is only available for line and area graphs'
                    : !isLinearScale
                      ? 'Moving average is only supported for linear scale.'
                      : undefined
            }
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, showMovingAverage: checked },
                    })
                }
            }}
        />
    )
}

function DecimalPrecision(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <ChartOptionNumberInput
            label="Decimal places"
            value={trendsFilter?.decimalPlaces}
            min={0}
            max={9}
            placeholder={String(DEFAULT_DECIMAL_PLACES)}
            onChange={(decimalPlaces) => {
                updateInsightFilter({ decimalPlaces })
                posthog.capture('decimal places changed', { decimal_places: decimalPlaces })
            }}
        />
    )
}

export function SectionHeader({
    children,
    tooltip,
    dataAttr,
}: {
    children: ReactNode
    tooltip?: string
    dataAttr?: string
}): JSX.Element {
    return (
        <h5 className="mx-2 my-1" data-attr={dataAttr}>
            {children}
            {tooltip && (
                <>
                    {' '}
                    <Tooltip title={tooltip}>
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </>
            )}
        </h5>
    )
}

// Every insight display toggle, keyed so the Options panel is assembled by referencing
// `DisplayOptions.X` instead of importing each filter component.
export const DisplayOptions = {
    Smoothing: SmoothingFilter,
    Legend: ShowLegendFilter,
    LegendOptions: LegendOptionsFilter,
    ExcludeOutliers,
    Metric: MetricFilters,
    LifecycleStacking: LifecycleStackingFilter,
    LifecyclePercentages: LifecyclePercentagesFilter,
    ValueLabels: ValueOnSeriesFilter,
    PercentStack: PercentStackViewFilter,
    StackBreakdown: StackBreakdownFilter,
    SliceNames: SliceNamesFilter,
    PieTotal: ShowPieTotalFilter,
    AlertThresholdLines: ShowAlertThresholdLinesFilter,
    AlertAnomalyPoints: ShowAlertAnomalyPointsFilter,
    MultipleYAxes: ShowMultipleYAxesFilter,
    TrendLines: ShowTrendLinesFilter,
    HideIncompleteFunnelPeriods: HideIncompleteConversionWindowPeriodsFilter,
    Annotations: AnnotationsPicker,
    ResultCustomizationBy: ResultCustomizationByPicker,
    Unit: UnitPicker,
    Scale: ScalePicker,
    YAxisRange: YAxisRangeFilter,
    LineStyle: LineStylePicker,
    ConfidenceInterval,
    ConfidenceLevel: ConfidenceLevelInput,
    MovingAverage,
    MovingAverageIntervals: MovingAverageIntervalsInput,
    XAxisLabel: () => <AxisLabelFilter axis="x" />,
    YAxisLabel: () => <AxisLabelFilter axis="y" />,
    DecimalPrecision,
    RetentionDashboardDisplay: RetentionDashboardDisplayPicker,
    RetentionCohortLabelStart: RetentionCohortLabelStartIndexPicker,
    RetentionSeriesColorMode: RetentionSeriesColorModePicker,
    RetentionMeanLine: RetentionMeanLineToggle,
} satisfies Record<string, () => JSX.Element | null>

export type DisplayOption = (typeof DisplayOptions)[keyof typeof DisplayOptions]
