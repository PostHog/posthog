import { useValues } from 'kea'

import { normalizeAxisLabel } from '@posthog/quill-charts'

import { countTruthy, DisplayOptionTab, groupDisplayOptions } from 'lib/components/ChartOptions/displayOptionLayout'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { PART_OF_WHOLE_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import type { RetentionFilter, TrendsFilter } from '~/queries/schema/schema-general'
import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'
import { LifecyclePercentagesFilter } from 'products/product_analytics/frontend/insights/lifecycle/filters/LifecyclePercentagesFilter'
import { LifecycleStackingFilter } from 'products/product_analytics/frontend/insights/lifecycle/filters/LifecycleStackingFilter'
import { RetentionCohortLabelStartIndexPicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionCohortLabelStartIndexPicker'
import { RetentionDashboardDisplayPicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionDashboardDisplayPicker'
import { RetentionMeanLineToggle } from 'products/product_analytics/frontend/insights/retention/filters/RetentionMeanLineToggle'
import { RetentionSeriesColorModePicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionSeriesColorModePicker'
import { ConfidenceLevelInput } from 'products/product_analytics/frontend/insights/trends/filters/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'products/product_analytics/frontend/insights/trends/filters/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { BAR_DISPLAYS, displayMatches, isDefaultTrendsLineDisplay, LINE_DISPLAYS } from './displayTypes'
import { AnnotationsPicker } from './filters/AnnotationsPicker'
import { AxisLabelFilter } from './filters/AxisLabelFilter'
import { ConfidenceIntervalFilter } from './filters/ConfidenceIntervalFilter'
import { DecimalPlacesFilter } from './filters/DecimalPlacesFilter'
import { ExcludeOutliersFilter } from './filters/ExcludeOutliersFilter'
import { HideIncompleteConversionWindowPeriodsFilter } from './filters/HideIncompleteConversionWindowPeriodsFilter'
import { LegendOptionsFilter } from './filters/LegendOptionsFilter'
import { LineStylePicker } from './filters/LineStylePicker'
import { MetricFilters } from './filters/MetricFilters'
import { MovingAverageFilter } from './filters/MovingAverageFilter'
import { PercentStackViewFilter } from './filters/PercentStackViewFilter'
import { ResultCustomizationByPicker } from './filters/ResultCustomizationByPicker'
import { ScalePicker } from './filters/ScalePicker'
import { ShowAlertAnomalyPointsFilter } from './filters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from './filters/ShowAlertThresholdLinesFilter'
import { ShowLegendFilter } from './filters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from './filters/ShowMultipleYAxesFilter'
import { ShowPieTotalFilter } from './filters/ShowPieTotalFilter'
import { ShowTrendLinesFilter } from './filters/ShowTrendLinesFilter'
import { SliceNamesFilter } from './filters/SliceNamesFilter'
import { StackBreakdownFilter } from './filters/StackBreakdownFilter'
import { ValueOnSeriesFilter } from './filters/ValueOnSeriesFilter'
import { YAxisRangeFilter } from './filters/YAxisRangeFilter'

// The "Options" panel in the insight editor's display config bar. `count` is the total number of
// non-default active options across all tabs, badged on the Options button.
export function useInsightDisplayOptions(): { tabs: DisplayOptionTab[]; count: number } {
    const { insightProps } = useValues(insightLogic)
    const {
        querySource,
        isTrends,
        isRetention,
        isStickiness,
        isLifecycle,
        display,
        breakdownFilter,
        trendsFilter,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        supportsBarValueStacking,
        supportsResultCustomizationBy,
        yAxisScaleType,
        showMultipleYAxes,
        showAlertThresholdLines,
        showAnnotations,
        annotationsScope,
        isNonTimeSeriesDisplay,
        interval,
        usesInChartLegend,
        insightFilter,
    } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const {
        showValuesOnSeries,
        showPercentagesOnSeries,
        mightContainFractionalNumbers,
        showConfidenceIntervals,
        showMovingAverage,
    } = useValues(trendsDataLogic(insightProps))
    const lineFilter = insightFilter as TrendsFilter | undefined

    // The slope graph shows the first vs last interval, so it drops the options that need the points
    // between them (smoothing, multiple axes, alert/annotation overlays, statistical analysis).
    const isSlopeGraph = display === ChartDisplayType.SlopeGraph
    const isMetric = display === ChartDisplayType.Metric
    const isBoxPlot = display === ChartDisplayType.BoxPlot
    const isCalendarHeatmap = display === ChartDisplayType.CalendarHeatmap
    const isPie = !!display && PIE_DISPLAY_TYPES.includes(display)
    const isPartOfWhole = !!display && PART_OF_WHOLE_DISPLAY_TYPES.includes(display)
    const hideContinuousChartOptions = isNonTimeSeriesDisplay || isMetric || isSlopeGraph
    // Stickiness defaults to its line chart when display is unset, same as trends does — but
    // isDefaultTrendsLineDisplay only matches TrendsQuery, so we handle the stickiness case here.
    const isLineDisplay =
        isDefaultTrendsLineDisplay(display, querySource) ||
        displayMatches(display, LINE_DISPLAYS) ||
        (!display && isStickiness)
    const isBarDisplay = displayMatches(display, BAR_DISPLAYS)
    // Only the quill line charts (trends/stickiness line and area, retention and funnel-trends
    // graphs) draw curves, so they're the only ones with curvature to straighten. Retention and
    // funnel trends default to their line graph when display is unset.
    const isLineChartInsight = isLineDisplay || ((isRetention || isTrendsFunnel) && !display)

    const showDisplaySection =
        (isTrends && !isCalendarHeatmap) || isRetention || isTrendsFunnel || isStickiness || isLifecycle
    // The box plot and slope graph show only a legend (and the box plot its outliers toggle).
    const showFullDisplayList = showDisplaySection && !isBoxPlot && !isSlopeGraph
    const showFunnelLegendConfig = isTrendsFunnel && hasBreakdownFilter(breakdownFilter)
    // When the chart draws its own positioned in-chart legend, show the position selector instead
    // of the legacy show/hide checkbox. usesInChartLegend is the single source of truth (same
    // selector used by InsightVizDisplay to suppress the side legend). Funnel trends with breakdown
    // also get the position selector since they render the quill legend via config.legend.
    const useQuillLegendOptions = showFullDisplayList && (usesInChartLegend || showFunnelLegendConfig)
    const showLegendOption = showFullDisplayList
        ? useQuillLegendOptions || hasLegend || showFunnelLegendConfig
        : showDisplaySection && hasLegend
    // A proportion bar shows its legend by default, so only the user's own choice counts as a change.
    const legendIsChanged =
        display === ChartDisplayType.ActionsProportionBar ? trendsFilter?.showLegend !== undefined : showLegend

    const showAlertThresholdLinesConfig = isTrends && !hideContinuousChartOptions
    const showYAxisScale = !hideContinuousChartOptions && isTrends && !isCalendarHeatmap
    // Bars encode magnitude as length from zero, so a bounded baseline misreads them: 10 vs 11
    // would draw as 1 vs 2.
    const showYAxisRange = showYAxisScale && isLineDisplay
    const showAxisLabels = isTrends && (isLineDisplay || isBarDisplay)
    const showStatisticalOverlays = showYAxisScale && !isBoxPlot
    // Percent stacking swaps the raw values out for percentages, so there is no unit left to pick.
    // A pie is the exception: it can show the value and the percentage together.
    const showsRawValues = !showPercentStackView || (isPie && !!showValuesOnSeries)
    const showUnit = showsRawValues && isTrends && !isCalendarHeatmap
    const showRetentionLineOptions = isRetention && isLineChartInsight
    const yAxisStartsAtZero = trendsFilter?.yAxisStartAtZero !== false

    return groupDisplayOptions(
        {
            metric: showFullDisplayList &&
                isMetric && {
                    element: <MetricFilters />,
                    changedCount: countTruthy(
                        trendsFilter?.metricShowChange === false,
                        trendsFilter?.metricColorByDirection,
                        !!trendsFilter?.metricSummary && trendsFilter.metricSummary !== 'total'
                    ),
                },
            lifecycleStacking: showFullDisplayList && isLifecycle && { element: <LifecycleStackingFilter /> },
            valuesOnSeries: showFullDisplayList &&
                supportsValueOnSeries && {
                    element: <ValueOnSeriesFilter />,
                    changedCount: countTruthy(showValuesOnSeries),
                },
            lifecyclePercentages: showFullDisplayList &&
                isLifecycle && {
                    element: <LifecyclePercentagesFilter />,
                    changedCount: countTruthy(showPercentagesOnSeries),
                },
            percentStack: showFullDisplayList &&
                supportsPercentStackView && {
                    element: <PercentStackViewFilter />,
                    changedCount: countTruthy(showPercentStackView),
                },
            stackBreakdown: showFullDisplayList && supportsBarValueStacking && { element: <StackBreakdownFilter /> },
            sliceNames: showFullDisplayList &&
                isPie && {
                    element: <SliceNamesFilter />,
                    changedCount: countTruthy(trendsFilter?.showLabelsOnSeries),
                },
            pieTotal: showFullDisplayList && isPartOfWhole && { element: <ShowPieTotalFilter /> },
            hideIncompleteFunnelPeriods: showFullDisplayList &&
                isTrendsFunnel &&
                !hideContinuousChartOptions && { element: <HideIncompleteConversionWindowPeriodsFilter /> },
            alertAnomalyPoints: showFullDisplayList &&
                showAlertThresholdLinesConfig && { element: <ShowAlertAnomalyPointsFilter /> },
            legend: showLegendOption && {
                element: useQuillLegendOptions ? <LegendOptionsFilter /> : <ShowLegendFilter />,
                changedCount: countTruthy((hasLegend || showFunnelLegendConfig) && legendIsChanged),
            },
            excludeOutliers: showDisplaySection && isBoxPlot && { element: <ExcludeOutliersFilter /> },

            annotations: ((isTrends && !hideContinuousChartOptions) || isTrendsFunnel) &&
                !isBoxPlot && {
                    element: <AnnotationsPicker />,
                    changedCount: countTruthy(showAnnotations === false || !!annotationsScope),
                },
            unit: showUnit && {
                element: <UnitPicker />,
                changedCount: countTruthy(
                    !!trendsFilter?.aggregationAxisFormat && trendsFilter.aggregationAxisFormat !== 'numeric'
                ),
            },
            resultCustomizationBy: supportsResultCustomizationBy && { element: <ResultCustomizationByPicker /> },
            decimalPlaces: mightContainFractionalNumbers &&
                isTrends &&
                !isCalendarHeatmap && { element: <DecimalPlacesFilter /> },
            retentionDashboardDisplay: isRetention && { element: <RetentionDashboardDisplayPicker /> },
            retentionCohortLabelStart: isRetention && { element: <RetentionCohortLabelStartIndexPicker /> },

            xAxisLabel: showAxisLabels && {
                element: <AxisLabelFilter axis="x" />,
                changedCount: countTruthy(normalizeAxisLabel(trendsFilter?.xAxisLabel)),
            },
            yAxisLabel: showAxisLabels && {
                element: <AxisLabelFilter axis="y" />,
                changedCount: countTruthy(normalizeAxisLabel(trendsFilter?.yAxisLabel)),
            },
            yAxisRange: showYAxisRange && {
                element: <YAxisRangeFilter />,
                changedCount: countTruthy(
                    !yAxisStartsAtZero,
                    !yAxisStartsAtZero && typeof trendsFilter?.yAxisMin === 'number',
                    typeof trendsFilter?.yAxisMax === 'number'
                ),
            },
            multipleYAxes: (isTrends || isStickiness) &&
                !hideContinuousChartOptions &&
                !isBoxPlot && {
                    element: <ShowMultipleYAxesFilter />,
                    changedCount: countTruthy(showMultipleYAxes),
                },
            yAxisScale: showYAxisScale && {
                element: <ScalePicker />,
                changedCount: countTruthy(!!yAxisScaleType && yAxisScaleType !== 'linear'),
            },

            lineStyle: (isTrends || isStickiness || isRetention || isTrendsFunnel) &&
                isLineChartInsight && {
                    element: <LineStylePicker />,
                    changedCount: countTruthy(lineFilter?.chartStyle?.curve === 'linear'),
                },
            smoothing: isTrends &&
                !hasBreakdownFilter(breakdownFilter) &&
                (!display ||
                    display === ChartDisplayType.ActionsLineGraph ||
                    display === ChartDisplayType.ActionsAreaGraph) &&
                !!interval &&
                (smoothingOptions[interval]?.length ?? 0) > 0 && {
                    element: <SmoothingFilter />,
                    changedCount: countTruthy((trendsFilter?.smoothingIntervals ?? 1) !== 1),
                },
            retentionSeriesColorMode: showRetentionLineOptions && {
                element: <RetentionSeriesColorModePicker />,
                changedCount: countTruthy(lineFilter?.chartStyle?.seriesColorMode === 'opacity'),
            },
            trendLines: (isTrends || isRetention || isTrendsFunnel) &&
                !hideContinuousChartOptions &&
                !isBoxPlot && {
                    element: <ShowTrendLinesFilter />,
                    changedCount: countTruthy(lineFilter?.showTrendLines),
                },
            movingAverage: showStatisticalOverlays && {
                element: <MovingAverageFilter />,
                changedCount: countTruthy(showMovingAverage),
            },
            movingAverageIntervals: showStatisticalOverlays &&
                showMovingAverage && { element: <MovingAverageIntervalsInput /> },
            confidenceInterval: showStatisticalOverlays && {
                element: <ConfidenceIntervalFilter />,
                changedCount: countTruthy(showConfidenceIntervals),
            },
            confidenceLevel: showStatisticalOverlays &&
                showConfidenceIntervals && { element: <ConfidenceLevelInput /> },
            alertThresholdLines: showAlertThresholdLinesConfig &&
                !isBoxPlot && {
                    element: <ShowAlertThresholdLinesFilter />,
                    changedCount: countTruthy(showAlertThresholdLines),
                },
            retentionMeanLine: showRetentionLineOptions && {
                element: <RetentionMeanLineToggle />,
                changedCount: countTruthy((insightFilter as RetentionFilter | undefined)?.showMeanLine),
            },
        },
        // Only trends has enough options to need tabs; the other insight types keep one flat list.
        { singleTab: !isTrends }
    )
}
