import { type ReactElement, useMemo } from 'react'
import { StyleSheet, View } from 'react-native'

import type { InsightSnapshot } from '@/model/views'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { MetricChart } from '@/ui/chart/MetricChart'
import type { ChartCanvasSlot } from '@/ui/chart/types'
import { useChartSheets } from './pointSheet/ChartSheetsProvider'
import type { ChartSheetSource } from './pointSheet/chartSheetSource'
import { snapshotChartSeries, snapshotFormatter } from './snapshotChart'

interface InsightChartProps {
    snapshot: InsightSnapshot
    /** What the Point and About sheets describe. */
    source: ChartSheetSource
    /** Pairs the chart with its legend and names it for the one-pinned-chart rule. Unique on the screen. */
    selectionId: string
    /** For the spoken summary, such as "last 14 days". */
    rangeText: string | null
    height?: number
    canvasSlot?: ChartCanvasSlot
    testID?: string
}

/**
 * An insight's chart on a view screen, with its legend when it has more than one series. A tap on the pinned tooltip
 * opens the Point sheet.
 */
export function InsightChart({
    snapshot,
    source,
    selectionId,
    rangeText,
    height,
    canvasSlot,
    testID,
}: InsightChartProps): ReactElement | null {
    const sheets = useChartSheets()
    const legend = useChartLegend()
    const series = useMemo(() => snapshotChartSeries(snapshot), [snapshot])
    const formatValue = useMemo(() => snapshotFormatter(snapshot), [snapshot])
    const kind = snapshot.chartKind
    if (!kind || series.length === 0) {
        return null
    }
    const dataUntil = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : undefined
    const summary = `${snapshot.name}, ${kind} chart${rangeText ? `, ${rangeText.toLowerCase()}` : ''}`
    return (
        <View style={styles.wrap}>
            <MetricChart
                series={series}
                kind={kind}
                interval={snapshot.interval}
                label={snapshot.name}
                formatValue={formatValue}
                variant="inline"
                height={height}
                hiddenKeys={legend.state.hiddenKeys}
                dataUntil={Number.isFinite(dataUntil) ? dataUntil : undefined}
                onPressTooltip={(point) => sheets.openPoint(source, point, 'tooltip')}
                selectionId={selectionId}
                trackingContext="view"
                canvasSlot={canvasSlot}
                accessibilitySummary={summary}
                accessibilityActions={[
                    {
                        name: 'about',
                        label: 'About this chart',
                        onAction: () => sheets.openAbout(source, 'accessibility'),
                    },
                ]}
                testID={testID}
            />
            {series.length > 1 ? (
                <ChartLegend
                    series={series}
                    state={legend.state}
                    onChange={legend.setState}
                    selectionId={selectionId}
                    testID={testID ? `${testID}-legend` : undefined}
                />
            ) : null}
        </View>
    )
}

const styles = StyleSheet.create({
    wrap: {
        gap: 12,
    },
})
