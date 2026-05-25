import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { TimeSeriesBarChart } from 'lib/hog-charts'
import type { PointClickData, TooltipConfig, TooltipContext } from 'lib/hog-charts'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { retentionGraphLogic } from 'scenes/retention/retentionGraphLogic'
import { retentionModalLogic } from 'scenes/retention/retentionModalLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import type { GoalLine } from '~/queries/schema/schema-general'
import type { GroupTypeIndex, LabelGroupType } from '~/types'

import {
    buildRetentionBarChartConfig,
    buildRetentionSeries,
    type RetentionSeriesMeta,
    type RetentionTrendSeriesEntry,
} from '../shared/retentionChartTransforms'
import { RetentionTooltip } from '../shared/RetentionTooltip'

interface RetentionBarChartProps {
    inSharedMode?: boolean
}

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }
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

export function RetentionBarChart({ inSharedMode = false }: RetentionBarChartProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const {
        hasValidBreakdown,
        retentionFilter,
        filteredTrendSeries,
        incompletenessOffsetFromEnd,
        labelGroupType,
        shouldShowMeanPerBreakdown,
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
        (ctx: TooltipContext<RetentionSeriesMeta>) => (
            <RetentionTooltip
                context={ctx}
                xAxisLabels={xAxisLabels}
                period={period}
                selectedInterval={selectedInterval}
                shouldShowMeanPerBreakdown={shouldShowMeanPerBreakdown}
                isPercentage={isPercentage}
                groupTypeLabel={groupTypeLabel}
                onRowClick={canClick ? onRowClick : undefined}
            />
        ),
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

    const barConfig = useMemo(
        () => buildRetentionBarChartConfig({ isPercentage, goalLines, series, tooltip: TOOLTIP_CONFIG }),
        [isPercentage, goalLines, series]
    )

    if (filteredTrendSeries.length === 0 && hasValidBreakdown) {
        return (
            <p className="w-full m-0 text-center text-sm text-gray-500">
                Select a breakdown to see the retention graph
            </p>
        )
    }

    return (
        <TimeSeriesBarChart<RetentionSeriesMeta>
            series={series}
            labels={xAxisLabels}
            theme={theme}
            config={barConfig}
            tooltip={renderTooltip}
            onPointClick={canClick ? onPointClick : undefined}
            className="LineGraph"
            dataAttr="trend-line-graph"
            onError={handleChartError}
        />
    )
}
