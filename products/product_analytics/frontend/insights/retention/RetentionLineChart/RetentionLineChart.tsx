import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { PointClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { roundToDecimal } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { retentionGraphLogic } from 'scenes/retention/retentionGraphLogic'
import { retentionModalLogic } from 'scenes/retention/retentionModalLogic'

import { groupsModel } from '~/models/groupsModel'
import type { GoalLine } from '~/queries/schema/schema-general'
import type { GroupTypeIndex, LabelGroupType } from '~/types'

import { chartStyleCurve } from '../../shared/chartStyleAdapter'
import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { INSIGHT_TOOLTIP_CONFIG } from '../../shared/tooltipConfig'
import {
    buildRetentionLineChartConfig,
    buildRetentionSeries,
    type RetentionSeriesMeta,
    type RetentionTrendSeriesEntry,
} from '../shared/retentionChartTransforms'

interface RetentionLineChartProps {
    inSharedMode?: boolean
}
const EMPTY_GOAL_LINES: GoalLine[] = []

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'retention-graph',
        componentStack: info.componentStack ?? undefined,
    })
}

function resolveGroupTypeLabel(
    labelGroupType: LabelGroupType | 'none',
    aggregationLabel: (index: GroupTypeIndex) => { plural: string }
): string {
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    return aggregationLabel(labelGroupType).plural
}

export function RetentionLineChart({ inSharedMode = false }: RetentionLineChartProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const theme = useChartTheme()

    const {
        hasValidBreakdown,
        retentionFilter,
        filteredTrendSeries,
        incompletenessOffsetFromEnd,
        labelGroupType,
        shouldShowMeanPerBreakdown,
        showTrendLines,
        xAxisLabels,
    } = useValues(retentionGraphLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const selectedInterval = retentionFilter?.selectedInterval ?? null
    const period = retentionFilter?.period
    const isPercentage = !retentionFilter?.aggregationType || retentionFilter.aggregationType === 'count'
    const isIntervalView = selectedInterval !== null
    // Shared (public) views don't have the persons modal mounted — disable click-to-open there.
    const canClick = !shouldShowMeanPerBreakdown && !inSharedMode

    const series = useMemo(
        () =>
            buildRetentionSeries(filteredTrendSeries as RetentionTrendSeriesEntry[], {
                incompletenessOffsetFromEnd,
                isIntervalView,
            }),
        [filteredTrendSeries, incompletenessOffsetFromEnd, isIntervalView]
    )

    const groupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const onRowClick = useCallback(
        (datum: SeriesDatum) => {
            if (shouldShowMeanPerBreakdown) {
                return
            }
            // In interval view each x-position is a different cohort, otherwise each series is.
            const rowIndex = isIntervalView
                ? datum.dataIndex
                : (series[datum.datasetIndex]?.meta?.rowIndex ?? datum.datasetIndex)
            if (rowIndex !== undefined) {
                openModal(rowIndex)
            }
        },
        [shouldShowMeanPerBreakdown, isIntervalView, series, openModal]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<RetentionSeriesMeta>) => {
            const altTitle =
                selectedInterval !== null
                    ? `${period ?? ''} ${selectedInterval}`
                    : (xAxisLabels[ctx.dataIndex] ?? ctx.label)
            return (
                <InsightSeriesTooltip
                    context={ctx}
                    altTitle={altTitle}
                    renderCount={(value) => (isPercentage ? `${roundToDecimal(value)}%` : `${roundToDecimal(value)}`)}
                    renderSeriesOverride={(datum) => {
                        const showCohortPrefix = selectedInterval !== null || !shouldShowMeanPerBreakdown
                        return showCohortPrefix ? `Cohort ${datum.label ?? ''}` : (datum.label ?? '')
                    }}
                    groupTypeLabel={groupTypeLabel}
                    onRowClick={canClick ? onRowClick : undefined}
                />
            )
        },
        [
            xAxisLabels,
            period,
            selectedInterval,
            shouldShowMeanPerBreakdown,
            isPercentage,
            groupTypeLabel,
            onRowClick,
            canClick,
        ]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData<RetentionSeriesMeta>) => {
            if (shouldShowMeanPerBreakdown) {
                return
            }
            const rowIndex = isIntervalView
                ? clickData.dataIndex
                : (clickData.series.meta?.rowIndex ?? clickData.seriesIndex)
            if (rowIndex !== undefined) {
                openModal(rowIndex)
            }
        },
        [shouldShowMeanPerBreakdown, isIntervalView, openModal]
    )

    const goalLines = retentionFilter?.goalLines ?? EMPTY_GOAL_LINES

    const lineConfig = useChartConfig(
        () => ({
            ...buildRetentionLineChartConfig({
                isPercentage,
                goalLines,
                showTrendLines,
                series,
                tooltip: INSIGHT_TOOLTIP_CONFIG,
            }),
            curve: chartStyleCurve(retentionFilter?.chartStyle),
        }),
        [isPercentage, goalLines, showTrendLines, series, retentionFilter?.chartStyle]
    )

    if (filteredTrendSeries.length === 0 && hasValidBreakdown) {
        return (
            <p className="w-full m-0 text-center text-sm text-gray-500">
                Select a breakdown to see the retention graph
            </p>
        )
    }

    return (
        <TimeSeriesLineChart<RetentionSeriesMeta>
            series={series}
            labels={xAxisLabels}
            theme={theme}
            config={lineConfig}
            tooltip={renderTooltip}
            onPointClick={canClick ? onPointClick : undefined}
            className="LineGraph"
            dataAttr="trend-line-graph"
            onError={handleChartError}
        />
    )
}
