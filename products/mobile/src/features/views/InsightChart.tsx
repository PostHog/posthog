import { type ReactElement, useMemo } from 'react'
import { StyleSheet, View } from 'react-native'

import type { InsightSnapshot } from '@/model/views'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { MetricChart } from '@/ui/chart/MetricChart'
import type { ChartAccessibilityAction, ChartCanvasSlot, ChartSeries } from '@/ui/chart/types'
import { useTheme } from '@/ui/theme'
import type { FullScreenEntry } from './analytics'
import { useChartSheets } from './pointSheet/ChartSheetsProvider'
import type { ChartSheetSource } from './pointSheet/chartSheetSource'
import { snapshotChartSeries, snapshotFormatter } from './snapshotChart'

interface InsightChartModel {
    series: ChartSeries[]
    formatValue: (value: number) => string
    dataUntil: number | undefined
    /** "Daily active users, line chart, last 14 days". */
    summary: string
}

/** What the inline and the full-screen chart of an insight both draw. */
export function useInsightChartModel(snapshot: InsightSnapshot, rangeText: string | null): InsightChartModel {
    const { chartPalette } = useTheme()
    return useMemo(() => {
        const dataUntil = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : Number.NaN
        const kind = snapshot.chartKind ?? 'line'
        return {
            series: snapshotChartSeries(snapshot, chartPalette),
            formatValue: snapshotFormatter(snapshot),
            dataUntil: Number.isFinite(dataUntil) ? dataUntil : undefined,
            summary: `${snapshot.name}, ${kind} chart${rangeText ? `, ${rangeText}` : ''}`,
        }
    }, [snapshot, rangeText, chartPalette])
}

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
    /** The legend's "+N" pill and the VoiceOver action. Without it neither opens full screen. */
    onOpenFullScreen?: (entry: FullScreenEntry) => void
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
    onOpenFullScreen,
    testID,
}: InsightChartProps): ReactElement | null {
    const sheets = useChartSheets()
    const legend = useChartLegend()
    const model = useInsightChartModel(snapshot, rangeText)
    const actions = useMemo<ChartAccessibilityAction[]>(
        () => [
            { name: 'about', label: 'About this chart', onAction: () => sheets.openAbout(source, 'accessibility') },
            ...(onOpenFullScreen
                ? [{ name: 'fullScreen', label: 'Open full screen', onAction: () => onOpenFullScreen('accessibility') }]
                : []),
        ],
        [sheets, source, onOpenFullScreen]
    )
    const kind = snapshot.chartKind
    if (!kind || model.series.length === 0) {
        return null
    }
    return (
        <View style={styles.wrap}>
            <MetricChart
                series={model.series}
                kind={kind}
                interval={snapshot.interval}
                label={snapshot.name}
                formatValue={model.formatValue}
                variant="inline"
                height={height}
                hiddenKeys={legend.state.hiddenKeys}
                dataUntil={model.dataUntil}
                onPressTooltip={(point) => sheets.openPoint(source, point, 'tooltip')}
                selectionId={selectionId}
                trackingContext="view"
                canvasSlot={canvasSlot}
                accessibilitySummary={model.summary}
                accessibilityActions={actions}
                testID={testID}
            />
            {model.series.length > 1 ? (
                <ChartLegend
                    series={model.series}
                    state={legend.state}
                    onChange={legend.setState}
                    onPressMore={onOpenFullScreen ? () => onOpenFullScreen('legend_more') : undefined}
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
