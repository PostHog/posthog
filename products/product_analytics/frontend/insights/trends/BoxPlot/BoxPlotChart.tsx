import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { BoxPlot } from '@posthog/quill-charts'
import type { BoxPlotClickData, BoxPlotConfig, BoxPlotSeries } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'
import { DateDisplay } from 'lib/components/DateDisplay'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartParams } from '~/types'

import { boxPlotChartLogic } from './boxPlotChartLogic'

export function BoxPlotChart({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { boxplotData, seriesGroups, dateLabels, yAxisScaleType, querySource, interval, insightData, trendsFilter } =
        useValues(boxPlotChartLogic(insightProps))
    const { timezone, weekStartDay } = useValues(teamLogic)

    const theme = useChartTheme()

    const series = useMemo<BoxPlotSeries[]>(
        () =>
            seriesGroups.map((group) => ({
                key: String(group.seriesIndex),
                label: group.seriesLabel,
                // Explicit color keeps boxes in sync with BoxPlotLegend / BoxPlotResultsTable.
                color: getSeriesColor(group.seriesIndex),
                // Feed whisker bounds as min/max — quill draws whiskers at min/max, so this
                // preserves the exclude-outliers (±1.5·IQR) behaviour computed in the logic.
                data: group.rawData.map((raw, i) => ({
                    min: group.data[i].whiskerMin,
                    p25: raw.p25,
                    median: raw.median,
                    mean: raw.mean,
                    p75: raw.p75,
                    max: group.data[i].whiskerMax,
                    day: raw.day,
                })),
            })),
        [seriesGroups]
    )

    const formatValue = useCallback((value: number) => formatAggregationAxisValue(trendsFilter, value), [trendsFilter])

    const config = useChartConfig<BoxPlotConfig>(
        () => ({
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            yTickFormatter: formatValue,
            showGrid: true,
            tooltip: { pinnable: true, placement: 'cursor' },
        }),
        [yAxisScaleType, formatValue]
    )

    const handleBoxClick = useCallback(
        (data: BoxPlotClickData): void => {
            if (!showPersonsModal || !querySource) {
                return
            }
            const day = seriesGroups[0]?.rawData[data.dataIndex]?.day
            if (!day) {
                return
            }

            const actorsQuery: InsightActorsQuery = {
                kind: NodeKind.InsightActorsQuery,
                source: querySource,
                day,
                series: 0,
                includeRecordings: true,
            }

            openPersonsModal({
                title: (label: string) => (
                    <>
                        {label} on{' '}
                        <DateDisplay
                            interval={interval || 'day'}
                            resolvedDateRange={insightData?.resolved_date_range}
                            timezone={timezone}
                            weekStartDay={weekStartDay}
                            date={day}
                        />
                    </>
                ),
                query: actorsQuery,
                additionalSelect: {
                    value_at_data_point: 'event_count',
                    matched_recordings: 'matched_recordings',
                },
                orderBy: ['event_count DESC, actor_id DESC'],
            })
        },
        [showPersonsModal, querySource, seriesGroups, interval, insightData, timezone, weekStartDay]
    )

    if (!boxplotData || boxplotData.length === 0) {
        return <div className="flex items-center justify-center h-full text-muted">No data for this time range</div>
    }

    return (
        <div className="w-full grow relative overflow-hidden flex flex-col">
            <BoxPlot
                series={series}
                labels={dateLabels}
                theme={theme}
                config={config}
                onBoxClick={handleBoxClick}
                dataAttr="box-plot-graph"
            />
        </div>
    )
}
