import { type ReactElement, useMemo } from 'react'
import { StyleSheet, View } from 'react-native'

import { WEB_TREND_LABELS } from '@/model/adapters/webAnalytics'
import type { MetricInterval } from '@/model/types'
import type { InsightSnapshot, WebTrendMetric } from '@/model/views'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { MetricChart } from '@/ui/chart/MetricChart'
import { useTheme } from '@/ui/theme'
import { useChartSheets } from '../pointSheet/ChartSheetsProvider'
import type { ChartSheetSource } from '../pointSheet/chartSheetSource'
import { intervalLabel, snapshotChartSeries, snapshotFormatter } from '../snapshotChart'
import { useWebItemData, type WebItemRef } from './hooks'
import { WebCard, webCardState } from './WebCard'

const CHART_HEIGHT = 144

interface TrendCardProps {
    data: WebItemRef
    metric: WebTrendMetric
    interval: MetricInterval
    rangeText: string | null
}

export function TrendCard({ data, metric, interval, rangeText }: TrendCardProps): ReactElement {
    const { chartPalette } = useTheme()
    const item = useWebItemData<InsightSnapshot>(data)
    const legend = useChartLegend()
    const sheets = useChartSheets()
    const label = WEB_TREND_LABELS[metric]
    const snapshot = item.snapshot
    const source = useMemo<ChartSheetSource | null>(
        () =>
            snapshot
                ? {
                      snapshot,
                      // A held snapshot belongs to the previous range, so the sheet must not follow the new entry.
                      queryKey: item.held ? null : data.queryKey,
                      itemKey: data.itemKey,
                      web: { path: '/web', viewType: 'web_analytics' },
                      about: false,
                  }
                : null,
        [snapshot, item.held, data.queryKey, data.itemKey]
    )
    const series = useMemo(
        () =>
            snapshot
                ? snapshotChartSeries(snapshot, chartPalette).map((entry) =>
                      entry.compareOf ? entry : { ...entry, label }
                  )
                : [],
        [snapshot, chartPalette, label]
    )
    const hasContent = Boolean(
        snapshot?.allSeries.some((entry) => entry.compare !== 'previous' && entry.points.length > 0)
    )
    const dataUntil = snapshot?.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : Number.NaN
    return (
        <WebCard
            title={label}
            meta={intervalLabel(interval)}
            state={webCardState(item, hasContent && series.length > 0)}
            error={item.error}
            stale={snapshot?.refreshFailed ?? false}
            updating={item.updating}
            loadingHeight={CHART_HEIGHT + 44}
            testID="web-trend"
        >
            {snapshot ? (
                <View style={styles.wrap}>
                    <MetricChart
                        series={series}
                        kind="line"
                        interval={snapshot.interval}
                        label={label}
                        formatValue={snapshotFormatter(snapshot)}
                        variant="inline"
                        height={CHART_HEIGHT}
                        hiddenKeys={legend.state.hiddenKeys}
                        dataUntil={Number.isFinite(dataUntil) ? dataUntil : undefined}
                        onPressTooltip={source ? (point) => sheets.openPoint(source, point, 'tooltip') : undefined}
                        selectionId="web-trend"
                        trackingContext="view"
                        accessibilitySummary={`${label}, line chart${rangeText ? `, ${rangeText}` : ''}`}
                        testID="web-trend-chart"
                    />
                    {series.length > 1 ? (
                        <ChartLegend
                            series={series}
                            state={legend.state}
                            onChange={legend.setState}
                            selectionId="web-trend"
                            testID="web-trend-legend"
                        />
                    ) : null}
                </View>
            ) : null}
        </WebCard>
    )
}

const styles = StyleSheet.create({
    wrap: {
        gap: 12,
    },
})
