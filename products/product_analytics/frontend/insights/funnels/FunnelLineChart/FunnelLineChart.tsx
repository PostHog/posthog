import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type {
    ChartLegendConfig,
    PointClickData,
    TimeSeriesLineChartConfig,
    TooltipContext,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme, useDateRangeZoom } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { hasBreakdown } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { cohortsModel } from '~/models/cohortsModel'
import type { Noun } from '~/models/groupsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { isFunnelsQuery } from '~/queries/utils'
import { ChartParams, type FlattenedFunnelStepByBreakdown } from '~/types'

import { chartStyleCurve } from '../../shared/chartStyleAdapter'
import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { INSIGHT_TOOLTIP_CONFIG, INSIGHT_TOOLTIP_CONFIG_LEGACY } from '../../shared/tooltipConfig'
import { AnnotationsLayer } from '../../trends/shared/AnnotationsLayer'
import { buildBaseLegendConfig } from '../../trends/shared/buildBaseLegendConfig'
import { FUNNEL_CONVERSION_SERIES_LABEL, type FunnelSeriesMeta } from '../shared/funnelSeriesMeta'
import { buildFunnelLineSeries, buildFunnelLineTimeSeriesConfig, type IndexedFunnelStep } from './funnelChartTransforms'
import { FunnelLineTooltip } from './FunnelLineTooltip'
import { type FunnelLineChartClickDeps, handleFunnelLineChartClick } from './handleFunnelLineChartClick'

const EMPTY_STRINGS: string[] = []

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'funnels-line-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

function resolveGroupTypeLabel(
    labelGroupType: 'people' | 'none' | number,
    aggregationLabel: (groupTypeIndex: number) => Noun
): string {
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    return aggregationLabel(labelGroupType).plural
}

export function FunnelLineChart({
    context,
    inSharedMode,
    showPersonsModal: showPersonsModalProp = true,
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const theme = useChartTheme()
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]
    const TOOLTIP_CONFIG = quillTooltipEnabled ? INSIGHT_TOOLTIP_CONFIG : INSIGHT_TOOLTIP_CONFIG_LEGACY
    const { insightProps, insight, canEditInsight } = useValues(insightLogic)

    const {
        indexedSteps,
        goalLines,
        aggregationTargetLabel,
        incompletenessOffsetFromEnd,
        querySource,
        interval,
        insightData,
        showLegend,
        legendPosition,
        showValuesOnSeries,
        funnelsFilter,
        breakdownFilter,
        labelGroupType,
        getFunnelsColor,
    } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { timezone, weekStartDay } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { aggregationLabel } = useValues(groupsModel)

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const steps = useMemo(() => (indexedSteps ?? []) as IndexedFunnelStep[], [indexedSteps])

    const seriesBase = useMemo(
        () =>
            buildFunnelLineSeries(steps, {
                incompletenessOffsetFromEnd,
                getColor: (step) =>
                    getFunnelsColor({
                        ...step,
                        breakdownIndex: step.colorIndex,
                    } as unknown as FlattenedFunnelStepByBreakdown),
            }),
        [steps, incompletenessOffsetFromEnd, getFunnelsColor]
    )

    // Apply formatted breakdown labels so the chart's internal legend picks them up directly.
    const series = useMemo(
        () =>
            seriesBase.map((s) => ({
                ...s,
                label:
                    s.meta && hasBreakdown(s.meta.breakdown_value)
                        ? formatBreakdownLabel(
                              s.meta.breakdown_value,
                              breakdownFilter ?? undefined,
                              allCohorts.results,
                              formatPropertyValueForDisplay
                          )
                        : FUNNEL_CONVERSION_SERIES_LABEL,
            })),
        [seriesBase, breakdownFilter, allCohorts.results, formatPropertyValueForDisplay]
    )

    const legendConfig = useMemo<ChartLegendConfig>(
        () =>
            buildBaseLegendConfig({
                show: !!showLegend && series.length > 1,
                legendPosition,
                canEditInsight,
                inSharedMode,
            }),
        [showLegend, series.length, legendPosition, canEditInsight, inSharedMode]
    )

    const chartConfig: TimeSeriesLineChartConfig = useChartConfig(
        () => ({
            ...buildFunnelLineTimeSeriesConfig({
                indexedSteps: steps,
                interval,
                timezone,
                allDays: steps[0]?.days ?? [],
                goalLines,
                incompletenessOffsetFromEnd,
                showTrendLines: funnelsFilter?.showTrendLines ?? false,
                valueLabels: showValuesOnSeries ? { formatter: (value) => `${value}%` } : false,
                showCrosshair: true,
                tooltip: TOOLTIP_CONFIG,
            }),
            curve: chartStyleCurve(funnelsFilter?.chartStyle),
            legend: legendConfig,
        }),
        [
            steps,
            interval,
            timezone,
            goalLines,
            incompletenessOffsetFromEnd,
            funnelsFilter?.showTrendLines,
            funnelsFilter?.chartStyle,
            showValuesOnSeries,
            legendConfig,
            TOOLTIP_CONFIG,
        ]
    )

    const resolvedGroupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel)
    const labels = steps[0]?.labels ?? EMPTY_STRINGS
    const annotationDates = steps[0]?.days ?? EMPTY_STRINGS
    const showAnnotations = !inSharedMode && funnelsFilter?.showAnnotations !== false

    const clickDeps = useMemo<FunnelLineChartClickDeps>(
        () => ({
            hasPersonsModal: showPersonsModal,
            querySource,
            interval,
            timezone,
            weekStartDay,
            resolvedDateRange: insightData?.resolved_date_range ?? null,
            breakdownFilter,
            aggregationTargetLabel,
            cohorts: allCohorts.results,
            formatPropertyValueForDisplay,
            openPersonsModal,
        }),
        [
            showPersonsModal,
            querySource,
            interval,
            timezone,
            weekStartDay,
            insightData?.resolved_date_range,
            breakdownFilter,
            aggregationTargetLabel,
            allCohorts.results,
            formatPropertyValueForDisplay,
        ]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData<FunnelSeriesMeta>): void => {
            if (clickData.series.meta) {
                handleFunnelLineChartClick(clickData.series.meta, clickData.dataIndex, clickDeps)
            }
        },
        [clickDeps]
    )

    const onDateRangeZoom = useDateRangeZoom(annotationDates, context?.onDateRangeZoom, interval)

    const renderTooltip = useCallback(
        (ctx: TooltipContext<FunnelSeriesMeta>): JSX.Element => {
            if (quillTooltipEnabled) {
                return (
                    <InsightSeriesTooltip
                        context={ctx}
                        timezone={timezone}
                        interval={interval ?? undefined}
                        breakdownFilter={breakdownFilter ?? undefined}
                        dateRange={insightData?.resolved_date_range ?? undefined}
                        groupTypeLabel={resolvedGroupTypeLabel}
                        renderSeriesOverride={(datum) => datum.label ?? ''}
                        renderCount={(value) => `${value}%`}
                        onRowClick={
                            showPersonsModal
                                ? (datum) => {
                                      const meta = ctx.seriesData[datum.datasetIndex]?.series.meta
                                      if (meta) {
                                          handleFunnelLineChartClick(meta, datum.dataIndex, clickDeps)
                                      }
                                  }
                                : undefined
                        }
                    />
                )
            }
            return (
                <FunnelLineTooltip
                    context={ctx}
                    timezone={timezone}
                    interval={interval ?? undefined}
                    breakdownFilter={breakdownFilter ?? undefined}
                    dateRange={insightData?.resolved_date_range ?? undefined}
                    groupTypeLabel={resolvedGroupTypeLabel}
                    onRowClick={
                        showPersonsModal
                            ? (datum: SeriesDatum) => {
                                  const meta = ctx.seriesData[datum.datasetIndex]?.series.meta
                                  if (meta) {
                                      handleFunnelLineChartClick(meta, datum.dataIndex, clickDeps)
                                  }
                              }
                            : undefined
                    }
                />
            )
        },
        [
            quillTooltipEnabled,
            timezone,
            interval,
            breakdownFilter,
            insightData?.resolved_date_range,
            resolvedGroupTypeLabel,
            showPersonsModal,
            clickDeps,
        ]
    )

    if (!isFunnelsQuery(querySource)) {
        return null
    }

    return (
        <TimeSeriesLineChart<FunnelSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={showPersonsModal ? onPointClick : undefined}
            onDateRangeZoom={onDateRangeZoom}
            className="LineGraph"
            dataAttr="trend-line-graph-funnel"
            onError={handleChartError}
        >
            {showAnnotations && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationDates} />}
        </TimeSeriesLineChart>
    )
}
