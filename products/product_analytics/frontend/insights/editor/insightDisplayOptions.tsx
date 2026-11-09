import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { normalizeAxisLabel } from '@posthog/quill-charts'

import { DisplayOptionBindings, type DisplayOptionValue } from 'lib/components/ChartOptions/displayOptions'
import type { DisplayOptionsAdapter } from 'lib/components/ChartOptions/useDisplayOptions'
import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_DEFAULT,
} from 'lib/components/Metric/metricSummary'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { PART_OF_WHOLE_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic, type insightLogicType } from 'scenes/insights/insightLogic'
import { insightVizDataLogic, type insightVizDataLogicType } from 'scenes/insights/insightVizDataLogic'

import { hasBreakdownFilter, isFunnelsQuery, isRetentionQuery, isTrendsQuery } from '~/queries/schema/node-guards'
import type { RetentionFilter, TrendsFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, RetentionDashboardDisplayType } from '~/types'

import { QuillFunnelBinCountOption } from 'products/product_analytics/frontend/insights/funnels/filters/QuillFunnelBinCountOption'
import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'
import {
    INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD,
    trendsDataLogic,
    type trendsDataLogicType,
} from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { BAR_DISPLAYS, displayMatches, isDefaultTrendsLineDisplay, LINE_DISPLAYS } from './displayTypes'
import { ShowAlertAnomalyPointsFilter } from './filters/ShowAlertAnomalyPointsFilter'

type VizValues = insightVizDataLogicType['values']
type VizActions = insightVizDataLogicType['actions']
type TrendsValues = trendsDataLogicType['values']

interface InsightDisplayContext
    extends
        Pick<
            VizValues,
            | 'querySource'
            | 'isTrends'
            | 'isRetention'
            | 'isStickiness'
            | 'isLifecycle'
            | 'display'
            | 'interval'
            | 'breakdownFilter'
            | 'trendsFilter'
            | 'lifecycleFilter'
            | 'retentionFilter'
            | 'hasLegend'
            | 'showLegend'
            | 'legendPosition'
            | 'supportsValueOnSeries'
            | 'supportsPercentStackView'
            | 'supportsBarValueStacking'
            | 'supportsResultCustomizationBy'
            | 'showPercentStackView'
            | 'showLabelOnSeries'
            | 'showPercentagesOnSeries'
            | 'yAxisScaleType'
            | 'showMultipleYAxes'
            | 'showAlertThresholdLines'
            | 'showAnnotations'
            | 'annotationsScope'
        >,
        Pick<
            TrendsValues,
            | 'showValuesOnSeries'
            | 'mightContainFractionalNumbers'
            | 'showConfidenceIntervals'
            | 'showMovingAverage'
            | 'confidenceLevel'
            | 'movingAverageIntervals'
            | 'resultCustomizationBy'
            | 'pieChartVizOptions'
        >,
        Pick<insightLogicType['values'], 'canEditInsight' | 'editingDisabledReason'>,
        Pick<VizActions, 'updateInsightFilter' | 'updateQuerySource' | 'updateVizSpecificOptions'> {
    isTrendsFunnel: boolean
    isTimeToConvertFunnel: boolean
    funnelBinCount: number | undefined
    todayRailNav: boolean
    isMetric: boolean
    isBoxPlot: boolean
    isPie: boolean
    isPartOfWhole: boolean
    isCalendarHeatmap: boolean
    isLineDisplay: boolean
    isBarDisplay: boolean
    isLineChartInsight: boolean
    isLinearScale: boolean
    isOverlayLineGraph: boolean
    isTrendLineGraph: boolean
    hideContinuousChartOptions: boolean
    lineFilter: TrendsFilter | undefined
    showDisplaySection: boolean
    showFullDisplayList: boolean
    showFunnelLegendConfig: boolean
    useQuillLegendOptions: boolean
    showYAxisScale: boolean
    showYAxisRange: boolean
    showStatisticalOverlays: boolean
    showAlertThresholdLinesConfig: boolean
    yAxisStartsAtZero: boolean
    yAxisRangeDisabledReason: string | undefined
    showTrendLines: boolean | undefined
}

function useInsightDisplayContext(): InsightDisplayContext {
    const { insightProps, canEditInsight, editingDisabledReason } = useValues(insightLogic)
    const {
        querySource,
        isTrends,
        isRetention,
        isStickiness,
        isLifecycle,
        display,
        breakdownFilter,
        trendsFilter,
        lifecycleFilter,
        retentionFilter,
        hasLegend,
        showLegend,
        legendPosition,
        supportsValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        supportsBarValueStacking,
        supportsResultCustomizationBy,
        showLabelOnSeries,
        showPercentagesOnSeries,
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
    const { updateInsightFilter, updateQuerySource, updateVizSpecificOptions } = useActions(
        insightVizDataLogic(insightProps)
    )
    const {
        isTrendsFunnel: trendsFunnel,
        isTimeToConvertFunnel,
        funnelsFilter,
    } = useValues(funnelDataLogic(insightProps))
    const isTrendsFunnel = !!trendsFunnel
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const {
        showValuesOnSeries,
        mightContainFractionalNumbers,
        showConfidenceIntervals,
        showMovingAverage,
        confidenceLevel,
        movingAverageIntervals,
        resultCustomizationBy,
        pieChartVizOptions,
    } = useValues(trendsDataLogic(insightProps))

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
    // Only the quill line charts (trends/stickiness line and area, retention and funnel-trends
    // graphs) draw curves. Retention and funnel trends default to their line graph when display is unset.
    const isLineChartInsight = isLineDisplay || ((isRetention || isTrendsFunnel) && !display)
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'

    const showDisplaySection =
        (isTrends && !isCalendarHeatmap) || isRetention || isTrendsFunnel || isStickiness || isLifecycle
    // The box plot and slope graph show only a legend (and the box plot its outliers toggle).
    const showFullDisplayList = showDisplaySection && !isBoxPlot && !isSlopeGraph
    const showFunnelLegendConfig = isTrendsFunnel && hasBreakdownFilter(breakdownFilter)
    const showYAxisScale = !hideContinuousChartOptions && isTrends && !isCalendarHeatmap
    const lineFilter = insightFilter as TrendsFilter | undefined
    const showTrendLines = isRetentionQuery(querySource)
        ? querySource.retentionFilter.showTrendLines
        : isTrendsQuery(querySource)
          ? querySource.trendsFilter?.showTrendLines
          : isFunnelsQuery(querySource)
            ? querySource.funnelsFilter?.showTrendLines
            : false
    const isTrendLineGraph = isTrendsQuery(querySource)
        ? [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsLineGraphCumulative].includes(
              trendsFilter?.display || ChartDisplayType.ActionsLineGraph
          )
        : isFunnelsQuery(querySource)
          ? isTrendsFunnel
          : true

    return {
        querySource,
        canEditInsight,
        editingDisabledReason,
        isTrends,
        isRetention,
        isStickiness,
        isLifecycle,
        isTrendsFunnel,
        isTimeToConvertFunnel: !!isTimeToConvertFunnel,
        funnelBinCount: typeof funnelsFilter?.binCount === 'number' ? funnelsFilter.binCount : undefined,
        todayRailNav,
        isMetric,
        isBoxPlot,
        isPie,
        isPartOfWhole,
        isCalendarHeatmap,
        isLineDisplay,
        isBarDisplay: displayMatches(display, BAR_DISPLAYS),
        isLineChartInsight,
        isLinearScale,
        // Every trends line except the cumulative one, which the statistical overlays can't follow.
        isOverlayLineGraph:
            (isDefaultTrendsLineDisplay(display, querySource) || displayMatches(display, LINE_DISPLAYS)) &&
            display !== ChartDisplayType.ActionsLineGraphCumulative,
        isTrendLineGraph,
        hideContinuousChartOptions,
        display,
        interval,
        breakdownFilter,
        trendsFilter,
        lifecycleFilter,
        retentionFilter,
        lineFilter,
        showDisplaySection,
        showFullDisplayList,
        showFunnelLegendConfig,
        // When the chart draws its own positioned in-chart legend, show the position selector instead
        // of the legacy show/hide checkbox. Funnel trends with breakdown also get the position selector
        // since they render the quill legend via config.legend.
        useQuillLegendOptions: showFullDisplayList && (usesInChartLegend || showFunnelLegendConfig),
        hasLegend,
        showLegend,
        legendPosition,
        showYAxisScale,
        // Bars encode magnitude as length from zero, so a bounded baseline misreads them: 10 vs 11
        // would draw as 1 vs 2.
        showYAxisRange: showYAxisScale && isLineDisplay,
        showStatisticalOverlays: showYAxisScale && !isBoxPlot,
        showAlertThresholdLinesConfig: isTrends && !hideContinuousChartOptions,
        yAxisStartsAtZero: trendsFilter?.yAxisStartAtZero !== false,
        yAxisRangeDisabledReason:
            yAxisScaleType === 'log10'
                ? 'Not available on a logarithmic scale'
                : showPercentStackView
                  ? 'Not available while showing percentages'
                  : undefined,
        supportsValueOnSeries,
        supportsPercentStackView,
        supportsBarValueStacking,
        supportsResultCustomizationBy,
        showValuesOnSeries,
        showPercentStackView,
        showLabelOnSeries,
        showPercentagesOnSeries,
        mightContainFractionalNumbers,
        yAxisScaleType,
        showMultipleYAxes,
        showAlertThresholdLines,
        showAnnotations,
        annotationsScope,
        showTrendLines,
        showConfidenceIntervals,
        showMovingAverage,
        confidenceLevel,
        movingAverageIntervals,
        resultCustomizationBy,
        pieChartVizOptions,
        updateInsightFilter,
        updateQuerySource,
        updateVizSpecificOptions,
    }
}

function updateTrendsFilter(c: InsightDisplayContext, patch: Partial<TrendsFilter>): void {
    if (isTrendsQuery(c.querySource)) {
        c.updateQuerySource({ ...c.querySource, trendsFilter: { ...c.querySource.trendsFilter, ...patch } })
    }
}

function retentionMeanLineDisabledReason(c: InsightDisplayContext): string | undefined {
    if ((c.retentionFilter?.selectedInterval ?? null) !== null) {
        return 'Mean line is not available when viewing a single interval.'
    }
    return hasBreakdownFilter(c.breakdownFilter) ? 'Mean line is not available with a breakdown applied.' : undefined
}

function showsMetricChange(c: InsightDisplayContext): boolean {
    return c.trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT
}

function colorsMetricByDirection(c: InsightDisplayContext): boolean {
    return c.trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT
}

const INSIGHT_BINDINGS: DisplayOptionBindings<InsightDisplayContext> = {
    metricSummary: {
        showCondition: (c) => c.showFullDisplayList && c.isMetric,
        value: (c) => c.trendsFilter?.metricSummary ?? METRIC_SUMMARY_DEFAULT,
        onChange: (metricSummary, c) => c.updateInsightFilter({ metricSummary }),
        changedCount: (c) => !!c.trendsFilter?.metricSummary && c.trendsFilter.metricSummary !== 'total',
    },
    metricShowChange: {
        showCondition: (c) => c.showFullDisplayList && c.isMetric,
        value: showsMetricChange,
        onChange: (metricShowChange, c) => c.updateInsightFilter({ metricShowChange }),
        changedCount: (c) => c.trendsFilter?.metricShowChange === false,
    },
    metricChangeColors: {
        showCondition: (c) => c.showFullDisplayList && c.isMetric && showsMetricChange(c),
        value: (c) => ({
            increase: c.trendsFilter?.metricChangeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR,
            decrease: c.trendsFilter?.metricChangeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR,
        }),
        onChange: ({ increase, decrease }, c) =>
            c.updateInsightFilter({ metricChangeIncreaseColor: increase, metricChangeDecreaseColor: decrease }),
    },
    metricColorByDirection: {
        showCondition: (c) => c.showFullDisplayList && c.isMetric,
        value: colorsMetricByDirection,
        onChange: (metricColorByDirection, c) => c.updateInsightFilter({ metricColorByDirection }),
        changedCount: (c) => c.trendsFilter?.metricColorByDirection,
    },
    metricTrendColors: {
        showCondition: (c) => c.showFullDisplayList && c.isMetric && colorsMetricByDirection(c),
        value: (c) => ({
            increase: c.trendsFilter?.metricLineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR,
            decrease: c.trendsFilter?.metricLineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR,
        }),
        onChange: ({ increase, decrease }, c) =>
            c.updateInsightFilter({ metricLineIncreaseColor: increase, metricLineDecreaseColor: decrease }),
    },
    lifecycleStacking: {
        showCondition: (c) => c.showFullDisplayList && c.isLifecycle,
        value: (c) => c.lifecycleFilter?.stacked ?? true,
        onChange: (stacked, c) => c.updateInsightFilter({ stacked }),
    },
    valuesOnSeries: {
        showCondition: (c) => c.showFullDisplayList && c.supportsValueOnSeries,
        value: (c) => !!c.showValuesOnSeries,
        onChange: (showValuesOnSeries, c) => c.updateInsightFilter({ showValuesOnSeries }),
        changedCount: (c) => c.showValuesOnSeries,
    },
    lifecyclePercentages: {
        showCondition: (c) => c.showFullDisplayList && c.isLifecycle,
        value: (c) => !!c.showPercentagesOnSeries,
        onChange: (showPercentagesOnSeries, c) => c.updateInsightFilter({ showPercentagesOnSeries }),
        changedCount: (c) => c.showPercentagesOnSeries,
    },
    percentStack: {
        showCondition: (c) => c.showFullDisplayList && c.supportsPercentStackView,
        value: (c) => !!c.showPercentStackView,
        onChange: (showPercentStackView, c) => c.updateInsightFilter({ showPercentStackView }),
        changedCount: (c) => c.showPercentStackView,
    },
    stackBreakdown: {
        showCondition: (c) => c.showFullDisplayList && c.supportsBarValueStacking,
        value: (c) => !!c.trendsFilter?.stackBreakdownValues,
        onChange: (stackBreakdownValues, c) => c.updateInsightFilter({ stackBreakdownValues }),
    },
    sliceNames: {
        showCondition: (c) => c.showFullDisplayList && c.isPie,
        value: (c) => !!c.showLabelOnSeries,
        onChange: (showLabelsOnSeries, c) => c.updateInsightFilter({ showLabelsOnSeries }),
        changedCount: (c) => c.trendsFilter?.showLabelsOnSeries,
    },
    pieTotal: {
        showCondition: (c) => c.showFullDisplayList && c.isPartOfWhole,
        value: (c) => !c.pieChartVizOptions?.hideAggregation,
        onChange: (showTotal, c) =>
            c.updateVizSpecificOptions({
                // Donut stores its options under the pie key too, so the setting survives switching between them.
                [ChartDisplayType.ActionsPie]: { ...c.pieChartVizOptions, hideAggregation: !showTotal },
            }),
    },
    hideIncompleteFunnelPeriods: {
        showCondition: (c) => c.showFullDisplayList && c.isTrendsFunnel && !c.hideContinuousChartOptions,
        value: (c) =>
            isFunnelsQuery(c.querySource) && !!c.querySource.funnelsFilter?.hideIncompleteConversionWindowPeriods,
        onChange: (hideIncompleteConversionWindowPeriods, c) =>
            c.updateInsightFilter({ hideIncompleteConversionWindowPeriods }),
    },
    alertAnomalyPoints: {
        showCondition: (c) => c.showFullDisplayList && c.showAlertThresholdLinesConfig,
        render: () => <ShowAlertAnomalyPointsFilter />,
    },
    legend: {
        showCondition: (c) =>
            c.showFullDisplayList
                ? c.useQuillLegendOptions || c.hasLegend || c.showFunnelLegendConfig
                : c.showDisplaySection && c.hasLegend,
        value: (c) => !!c.showLegend,
        onChange: (showLegend, c) =>
            c.updateInsightFilter({
                showLegend,
                // Old insights without a saved position draw the legend on the right, so turning it on seeds bottom.
                ...(c.useQuillLegendOptions && showLegend && c.legendPosition == null
                    ? { legendPosition: 'bottom' }
                    : {}),
            }),
        // A proportion bar shows its legend by default, so only the user's own choice counts as a change.
        changedCount: (c) =>
            (c.hasLegend || c.showFunnelLegendConfig) &&
            (c.display === ChartDisplayType.ActionsProportionBar
                ? c.trendsFilter?.showLegend !== undefined
                : c.showLegend),
    },
    legendPosition: {
        showCondition: (c) => c.useQuillLegendOptions && c.showLegend,
        value: (c) => (c.legendPosition ?? 'right') as DisplayOptionValue<'legendPosition'>,
        onChange: (legendPosition, c) => c.updateInsightFilter({ legendPosition }),
    },
    excludeOutliers: {
        showCondition: (c) => c.showDisplaySection && c.isBoxPlot,
        value: (c) => c.trendsFilter?.excludeBoxPlotOutliers !== false,
        onChange: (excludeBoxPlotOutliers, c) => updateTrendsFilter(c, { excludeBoxPlotOutliers }),
    },

    annotations: {
        showCondition: (c) => ((c.isTrends && !c.hideContinuousChartOptions) || c.isTrendsFunnel) && !c.isBoxPlot,
        value: (c) => (c.showAnnotations === false ? 'none' : (c.annotationsScope ?? 'all')),
        onChange: (selection, c) =>
            c.updateInsightFilter({
                showAnnotations: selection === 'none' ? false : undefined,
                annotationsScope: selection === 'all' || selection === 'none' ? undefined : selection,
            }),
        dataAttr: 'insight-annotations-picker',
        changedCount: (c) => c.showAnnotations === false || !!c.annotationsScope,
    },
    unit: {
        // Percent stacking swaps the raw values out for percentages, so there is no unit left to pick.
        // A pie is the exception: it can show the value and the percentage together.
        showCondition: (c) =>
            (!c.showPercentStackView || (c.isPie && !!c.showValuesOnSeries)) && c.isTrends && !c.isCalendarHeatmap,
        render: () => <UnitPicker />,
        changedCount: (c) =>
            !!c.trendsFilter?.aggregationAxisFormat && c.trendsFilter.aggregationAxisFormat !== 'numeric',
    },
    resultCustomizationBy: {
        showCondition: (c) => c.supportsResultCustomizationBy,
        value: (c) => c.resultCustomizationBy,
        onChange: (resultCustomizationBy, c) => c.updateInsightFilter({ resultCustomizationBy }),
    },
    decimalPlaces: {
        showCondition: (c) => c.mightContainFractionalNumbers && c.isTrends && !c.isCalendarHeatmap,
        value: (c) => c.trendsFilter?.decimalPlaces,
        onChange: (decimalPlaces, c) => {
            c.updateInsightFilter({ decimalPlaces })
            posthog.capture('decimal places changed', { decimal_places: decimalPlaces })
        },
    },
    funnelBinCount: {
        showCondition: (c) => c.todayRailNav && c.isTimeToConvertFunnel,
        render: (c) => (
            <QuillFunnelBinCountOption
                value={c.funnelBinCount}
                onChange={(binCount) => c.updateInsightFilter({ binCount })}
                disabledReason={c.editingDisabledReason}
            />
        ),
        changedCount: (c) => c.funnelBinCount !== undefined,
    },
    retentionDashboardDisplay: {
        showCondition: (c) => c.isRetention && c.canEditInsight,
        value: (c) => c.retentionFilter?.dashboardDisplay || RetentionDashboardDisplayType.TableOnly,
        onChange: (dashboardDisplay, c) => c.updateInsightFilter({ dashboardDisplay }),
    },
    retentionCohortLabelStart: {
        showCondition: (c) => c.isRetention && c.canEditInsight,
        value: (c) => c.retentionFilter?.cohortLabelStartIndex ?? 0,
        options: (c) => {
            const period = c.retentionFilter?.period || 'Day'
            return [
                { value: 0, label: `${period} 0` },
                { value: 1, label: `${period} 1` },
            ]
        },
        onChange: (cohortLabelStartIndex, c) =>
            c.updateInsightFilter({ cohortLabelStartIndex: cohortLabelStartIndex as number }),
    },

    xAxisLabel: {
        showCondition: (c) => c.isTrends && (c.isLineDisplay || c.isBarDisplay),
        value: (c) => c.trendsFilter?.xAxisLabel,
        onChange: (xAxisLabel, c) => c.updateInsightFilter({ xAxisLabel }),
        changedCount: (c) => !!normalizeAxisLabel(c.trendsFilter?.xAxisLabel),
        dataAttr: 'trends-x-axis-label-input',
    },
    yAxisLabel: {
        showCondition: (c) => c.isTrends && (c.isLineDisplay || c.isBarDisplay),
        value: (c) => c.trendsFilter?.yAxisLabel,
        onChange: (yAxisLabel, c) => c.updateInsightFilter({ yAxisLabel }),
        changedCount: (c) => !!normalizeAxisLabel(c.trendsFilter?.yAxisLabel),
        dataAttr: 'trends-y-axis-label-input',
    },
    // The minimum is hidden rather than cleared while the axis begins at zero, so the typed value
    // applies again when the toggle goes off.
    yAxisMin: {
        showCondition: (c) => c.showYAxisRange && !c.yAxisStartsAtZero,
        value: (c) => c.trendsFilter?.yAxisMin,
        onChange: (yAxisMin, c) => c.updateInsightFilter({ yAxisMin }),
        disabledReason: (c) => c.yAxisRangeDisabledReason,
        changedCount: (c) => typeof c.trendsFilter?.yAxisMin === 'number',
        dataAttr: 'trends-y-axis-min-input',
    },
    yAxisMax: {
        showCondition: (c) => c.showYAxisRange,
        value: (c) => c.trendsFilter?.yAxisMax,
        onChange: (yAxisMax, c) => c.updateInsightFilter({ yAxisMax }),
        disabledReason: (c) => c.yAxisRangeDisabledReason,
        // An inverted pair sends the chart back to its automatic range, which otherwise just looks like
        // the controls not responding.
        warning: (c) =>
            !c.yAxisStartsAtZero &&
            typeof c.trendsFilter?.yAxisMin === 'number' &&
            typeof c.trendsFilter?.yAxisMax === 'number' &&
            c.trendsFilter.yAxisMin >= c.trendsFilter.yAxisMax
                ? 'Maximum must be greater than minimum.'
                : null,
        changedCount: (c) => typeof c.trendsFilter?.yAxisMax === 'number',
        dataAttr: 'trends-y-axis-max-input',
    },
    yAxisBeginAtZero: {
        showCondition: (c) => c.showYAxisRange,
        value: (c) => c.yAxisStartsAtZero,
        onChange: (startsAtZero, c) => c.updateInsightFilter({ yAxisStartAtZero: startsAtZero ? undefined : false }),
        disabledReason: (c) => c.yAxisRangeDisabledReason,
        changedCount: (c) => !c.yAxisStartsAtZero,
        dataAttr: 'trends-y-axis-start-at-zero',
    },
    multipleYAxes: {
        showCondition: (c) => (c.isTrends || c.isStickiness) && !c.hideContinuousChartOptions && !c.isBoxPlot,
        value: (c) => !!c.showMultipleYAxes,
        onChange: (showMultipleYAxes, c) => c.updateInsightFilter({ showMultipleYAxes }),
        changedCount: (c) => c.showMultipleYAxes,
    },
    yAxisScale: {
        showCondition: (c) => c.showYAxisScale,
        value: (c) => (c.yAxisScaleType === 'log10' ? 'log' : 'linear'),
        onChange: (scale, c) => c.updateInsightFilter({ yAxisScaleType: scale === 'log' ? 'log10' : 'linear' }),
        changedCount: (c) => !!c.yAxisScaleType && c.yAxisScaleType !== 'linear',
    },

    lineStyle: {
        showCondition: (c) =>
            (c.isTrends || c.isStickiness || c.isRetention || c.isTrendsFunnel) && c.isLineChartInsight,
        value: (c) => c.lineFilter?.chartStyle?.curve || 'smooth',
        onChange: (curve, c) => c.updateInsightFilter({ chartStyle: { ...c.lineFilter?.chartStyle, curve } }),
        changedCount: (c) => c.lineFilter?.chartStyle?.curve === 'linear',
    },
    smoothing: {
        showCondition: (c) =>
            c.isTrends &&
            !hasBreakdownFilter(c.breakdownFilter) &&
            (!c.display ||
                c.display === ChartDisplayType.ActionsLineGraph ||
                c.display === ChartDisplayType.ActionsAreaGraph) &&
            !!c.interval &&
            (smoothingOptions[c.interval]?.length ?? 0) > 0,
        value: (c) => c.trendsFilter?.smoothingIntervals || 1,
        options: (c) => (c.interval ? smoothingOptions[c.interval] : []),
        onChange: (smoothingIntervals, c) =>
            c.updateInsightFilter({ smoothingIntervals: smoothingIntervals as number }),
        disabledReason: (c) => c.editingDisabledReason,
        changedCount: (c) => (c.trendsFilter?.smoothingIntervals ?? 1) !== 1,
        dataAttr: 'smoothing-filter',
    },
    retentionSeriesColorMode: {
        showCondition: (c) => c.isRetention && c.isLineChartInsight && c.canEditInsight,
        value: (c) => c.retentionFilter?.chartStyle?.seriesColorMode || 'palette',
        onChange: (seriesColorMode, c) =>
            c.updateInsightFilter({ chartStyle: { ...c.retentionFilter?.chartStyle, seriesColorMode } }),
        changedCount: (c) => c.lineFilter?.chartStyle?.seriesColorMode === 'opacity',
    },
    trendLines: {
        showCondition: (c) =>
            (c.isTrends || c.isRetention || c.isTrendsFunnel) && !c.hideContinuousChartOptions && !c.isBoxPlot,
        disabledReason: (c) =>
            !c.isTrendLineGraph
                ? 'Trend lines are only available for line graphs'
                : !c.isLinearScale
                  ? 'Trend lines are only supported for linear scale.'
                  : undefined,
        value: (c) => c.isTrendLineGraph && c.isLinearScale && !!c.showTrendLines,
        onChange: (showTrendLines, c) => {
            const source = c.querySource
            if (isRetentionQuery(source)) {
                c.updateQuerySource({ retentionFilter: { ...source.retentionFilter, showTrendLines } } as any)
            } else if (isTrendsQuery(source)) {
                c.updateQuerySource({ trendsFilter: { ...source.trendsFilter, showTrendLines } } as any)
            } else if (isFunnelsQuery(source)) {
                c.updateQuerySource({ funnelsFilter: { ...source.funnelsFilter, showTrendLines } } as any)
            }
        },
        changedCount: (c) => c.lineFilter?.showTrendLines,
    },
    movingAverage: {
        showCondition: (c) => c.showStatisticalOverlays,
        disabledReason: (c) =>
            !c.isOverlayLineGraph
                ? 'Moving average is only available for line and area graphs'
                : !c.isLinearScale
                  ? 'Moving average is only supported for linear scale.'
                  : undefined,
        value: (c) => c.showMovingAverage,
        onChange: (showMovingAverage, c) => updateTrendsFilter(c, { showMovingAverage }),
        changedCount: (c) => c.showMovingAverage,
    },
    movingAverageIntervals: {
        showCondition: (c) => c.showStatisticalOverlays && c.showMovingAverage,
        value: (c) => c.movingAverageIntervals,
        suffix: (c) => `${isTrendsQuery(c.querySource) ? c.querySource.interval || 'day' : 'day'}s`,
        onChange: (movingAverageIntervals, c) => {
            const interval = isTrendsQuery(c.querySource) ? c.querySource.interval || 'day' : 'day'
            updateTrendsFilter(c, {
                movingAverageIntervals: movingAverageIntervals ?? INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD[interval],
            })
        },
    },
    confidenceInterval: {
        showCondition: (c) => c.showStatisticalOverlays,
        disabledReason: (c) =>
            !c.isOverlayLineGraph
                ? 'Confidence intervals are only available for line graphs'
                : !c.isLinearScale
                  ? 'Confidence intervals are only supported for linear scale.'
                  : undefined,
        value: (c) => c.showConfidenceIntervals,
        onChange: (showConfidenceIntervals, c) => updateTrendsFilter(c, { showConfidenceIntervals }),
        changedCount: (c) => c.showConfidenceIntervals,
    },
    confidenceLevel: {
        showCondition: (c) => c.showStatisticalOverlays && c.showConfidenceIntervals,
        value: (c) => c.confidenceLevel,
        onChange: (confidenceLevel, c) => updateTrendsFilter(c, { confidenceLevel: confidenceLevel ?? 95 }),
    },
    alertThresholdLines: {
        showCondition: (c) => c.showAlertThresholdLinesConfig && !c.isBoxPlot,
        value: (c) => !!c.showAlertThresholdLines,
        onChange: (showAlertThresholdLines, c) => c.updateInsightFilter({ showAlertThresholdLines }),
        changedCount: (c) => c.showAlertThresholdLines,
    },
    retentionMeanLine: {
        showCondition: (c) => c.isRetention && c.isLineChartInsight && c.canEditInsight,
        disabledReason: retentionMeanLineDisabledReason,
        value: (c) => !retentionMeanLineDisabledReason(c) && !!c.retentionFilter?.showMeanLine,
        onChange: (showMeanLine, c) => c.updateInsightFilter({ showMeanLine }),
        changedCount: (c) => (c.retentionFilter as RetentionFilter | undefined)?.showMeanLine,
    },
}

// The insight editor's "Options" panel and the options menu on a dashboard tile.
export const insightDisplayOptions: DisplayOptionsAdapter<InsightDisplayContext> = {
    useDisplayContext: useInsightDisplayContext,
    bindings: INSIGHT_BINDINGS,
    // Only trends has enough options to need tabs; the other insight types keep one flat list.
    settings: (c) => ({ singleTab: !c.isTrends }),
}
