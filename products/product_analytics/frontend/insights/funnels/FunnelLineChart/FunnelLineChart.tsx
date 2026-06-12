import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, type ErrorInfo } from 'react'

import { funnelDataLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelDataLogic'
import { funnelPersonsModalLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelPersonsModalLogic'
import { hasBreakdown } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelUtils'
import { openPersonsModal } from '@posthog/query-frontend/persons-modal/PersonsModal'
import { isFunnelsQuery } from '@posthog/query-frontend/utils'
import { ChartLegend, TimeSeriesLineChart, legendItemsFromSeries } from '@posthog/quill-charts'
import type { PointClickData, TimeSeriesLineChartConfig, TooltipConfig, TooltipContext } from '@posthog/quill-charts'
import { buildTheme } from '@posthog/visualizations/charts/utils/theme'
import type { SeriesDatum } from '@posthog/visualizations/InsightTooltip/insightTooltipUtils'

import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import type { Noun } from '~/models/groupsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartParams, type FlattenedFunnelStepByBreakdown } from '~/types'

import { AnnotationsLayer } from '../../trends/shared/AnnotationsLayer'
import { FUNNEL_CONVERSION_SERIES_LABEL, type FunnelSeriesMeta } from '../shared/funnelSeriesMeta'
import { buildFunnelLineSeries, buildFunnelLineTimeSeriesConfig, type IndexedFunnelStep } from './funnelChartTransforms'
import { FunnelLineTooltip } from './FunnelLineTooltip'
import { type FunnelLineChartClickDeps, handleFunnelLineChartClick } from './handleFunnelLineChartClick'

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }
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
    inSharedMode,
    showPersonsModal: showPersonsModalProp = true,
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps, insight } = useValues(insightLogic)

    const {
        indexedSteps,
        goalLines,
        aggregationTargetLabel,
        incompletenessOffsetFromEnd,
        querySource,
        interval,
        insightData,
        showLegend,
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

    const series = useMemo(
        () =>
            buildFunnelLineSeries(steps, {
                incompletenessOffsetFromEnd,
                getColor: (step) =>
                    getFunnelsColor({
                        ...step,
                        breakdownIndex: step.seriesIndex,
                    } as unknown as FlattenedFunnelStepByBreakdown),
            }),
        [steps, incompletenessOffsetFromEnd, getFunnelsColor]
    )

    const legendItems = useMemo(
        () =>
            legendItemsFromSeries(series, theme).map((item) => {
                const breakdownValue = series.find((s) => s.key === item.key)?.meta?.breakdown_value
                const label = hasBreakdown(breakdownValue)
                    ? formatBreakdownLabel(
                          breakdownValue,
                          breakdownFilter ?? undefined,
                          allCohorts.results,
                          formatPropertyValueForDisplay
                      )
                    : FUNNEL_CONVERSION_SERIES_LABEL
                return { ...item, label }
            }),
        [series, theme, breakdownFilter, allCohorts.results, formatPropertyValueForDisplay]
    )

    const chartConfig: TimeSeriesLineChartConfig = useMemo(
        () =>
            buildFunnelLineTimeSeriesConfig({
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
        [
            steps,
            interval,
            timezone,
            goalLines,
            incompletenessOffsetFromEnd,
            funnelsFilter?.showTrendLines,
            showValuesOnSeries,
        ]
    )

    if (!isFunnelsQuery(querySource)) {
        return null
    }

    const resolvedGroupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel)
    const labels = steps[0]?.labels ?? EMPTY_STRINGS
    const annotationDates = steps[0]?.days ?? EMPTY_STRINGS

    const clickDeps: FunnelLineChartClickDeps = {
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
    }

    const onPointClick = (clickData: PointClickData<FunnelSeriesMeta>): void => {
        if (clickData.series.meta) {
            handleFunnelLineChartClick(clickData.series.meta, clickData.dataIndex, clickDeps)
        }
    }

    const renderTooltip = (ctx: TooltipContext<FunnelSeriesMeta>): JSX.Element => (
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

    return (
        <ChartLegend
            show={!!showLegend && legendItems.length > 1}
            items={legendItems}
            position="top"
            legendDataAttr="funnel-line-legend"
        >
            <TimeSeriesLineChart<FunnelSeriesMeta>
                series={series}
                labels={labels}
                theme={theme}
                config={chartConfig}
                tooltip={renderTooltip}
                onPointClick={showPersonsModal ? onPointClick : undefined}
                className="LineGraph"
                dataAttr="trend-line-graph-funnel"
                onError={handleChartError}
            >
                {!inSharedMode && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationDates} />}
            </TimeSeriesLineChart>
        </ChartLegend>
    )
}
