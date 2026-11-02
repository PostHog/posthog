import type { QueryKey } from '@tanstack/react-query'
import { type ReactElement, type ReactNode, useMemo, useState } from 'react'
import { ScrollView, Text, View } from 'react-native'
import type { InsightSnapshot } from '@/model/views'
import { BarList } from '@/ui/chart/BarList'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { FunnelSteps } from '@/ui/chart/FunnelSteps'
import { MetricChart } from '@/ui/chart/MetricChart'
import { RetentionGrid } from '@/ui/chart/RetentionGrid'
import { SqlTable } from '@/ui/chart/SqlTable'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { SQL_TABLE_MAX_ROWS, sqlRowsText } from '@/ui/chart/sqlCellFormat'
import type { ChartAccessibilityAction } from '@/ui/chart/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { useInsightChartModel } from '../InsightChart'
import { InsightNoData } from '../InsightVisual'
import { OpensOnWeb } from '../OpensOnWeb'
import { useChartSheets } from '../pointSheet/ChartSheetsProvider'
import type { ChartSheetSource } from '../pointSheet/chartSheetSource'
import { useViewBack, ViewScreenFrame } from '../screen/ViewScreenFrame'
import {
    type InsightDisplay,
    insightDisplay,
    insightRenderState,
    intervalLabel,
    resolvedRangeText,
    snapshotFormatter,
} from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { freshnessKey, useSnapshot, viewsKeys } from '../viewsCache'

const MIN_CHART_HEIGHT = 220
/** The legend takes the rows it needs, up to this share of the space; past that it scrolls. */
const MAX_LEGEND_SHARE = 0.38
const LEGEND_ROW_HEIGHT = 44
const LEGEND_GAP = 12
const SELECTION_ID = 'fullscreen'

interface FullScreenChartProps {
    shortId: string
    /** The cache entry of the chart that opened this screen. Null: the insight's own entry. */
    queryKey: QueryKey | null
}

/**
 * One chart on the whole screen: the line or bar chart with every legend row, or the funnel, retention grid, bar
 * list or SQL table in full. It shows the snapshot the previous screen showed and follows its cache entry; it sends
 * no request.
 */
export function FullScreenChart({ shortId, queryKey }: FullScreenChartProps): ReactElement {
    const back = useViewBack()
    const { scope } = useViewsContext()
    const key = useMemo(() => queryKey ?? viewsKeys.insight(scope, shortId, null, '-'), [queryKey, scope, shortId])
    const snapshot = useSnapshot<InsightSnapshot>(key)
    const scrollTitle = useScrollTitle(snapshot?.name ?? '')
    return (
        <ViewScreenFrame
            chrome={<ScreenChrome onBack={back} backTestID="chart-fullscreen-back" title={scrollTitle.title} />}
        >
            {snapshot && insightRenderState(snapshot) !== 'pending' ? (
                <FullScreenBody scrollTitle={scrollTitle} snapshot={snapshot} queryKey={key} />
            ) : (
                <StateView
                    title="This chart isn't loaded"
                    message="Go back and open the chart again."
                    actionLabel="Go back"
                    onAction={back}
                    testID="chart-fullscreen-missing"
                />
            )}
        </ViewScreenFrame>
    )
}

function FullScreenBody({
    snapshot,
    queryKey,
    scrollTitle,
}: {
    snapshot: InsightSnapshot
    queryKey: QueryKey
    scrollTitle: ScrollTitleState
}): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    const motion = useChartListMotion()
    const sheets = useChartSheets()
    const source = useMemo<ChartSheetSource>(
        () => ({ snapshot, queryKey, itemKey: freshnessKey(queryKey), dashboardName: null }),
        [snapshot, queryKey]
    )
    const actions = useMemo<ChartAccessibilityAction[]>(
        () => [{ name: 'about', label: 'About this chart', onAction: () => sheets.openAbout(source, 'accessibility') }],
        [sheets, source]
    )
    const display = insightDisplay(snapshot)
    const empty = insightRenderState(snapshot) === 'empty'
    const rangeText = resolvedRangeText(snapshot.resolvedRange, snapshot.interval)
    const padding = {
        paddingTop: topOffset(insets, SCREEN_CONTENT_TOP),
        paddingBottom: bottomOffset(insets, 24),
    }
    const header = (
        <View style={styles.header}>
            <View onLayout={scrollTitle.onTitleLayout} style={styles.titleBlock}>
                <Eyebrow>{`Insight · ${snapshot.kindLabel}`}</Eyebrow>
                <Text style={styles.title} numberOfLines={2} accessibilityRole="header">
                    {snapshot.name}
                </Text>
            </View>
            <Text style={styles.meta}>{[metaLead(snapshot, display), rangeText].filter(Boolean).join(' · ')}</Text>
        </View>
    )

    if (display === 'chart' && !empty) {
        return (
            <View style={[styles.fill, styles.gutter, padding]}>
                {header}
                <TimeSeries snapshot={snapshot} source={source} rangeText={rangeText} />
            </View>
        )
    }

    let body: ReactNode = null
    if (empty) {
        body = <InsightNoData snapshot={snapshot} testID="chart-fullscreen-empty" />
    } else if (display === 'funnel' && snapshot.funnel) {
        body = (
            <FunnelSteps
                funnel={snapshot.funnel}
                label={snapshot.name}
                showSummary
                selectionId={SELECTION_ID}
                trackingContext="fullscreen"
                accessibilityActions={actions}
                testID="chart-fullscreen-funnel"
            />
        )
    } else if (display === 'retention' && snapshot.retention) {
        body = (
            <RetentionGrid
                retention={snapshot.retention}
                label={snapshot.name}
                maxPeriods={Number.POSITIVE_INFINITY}
                selectionId={SELECTION_ID}
                trackingContext="fullscreen"
                accessibilityActions={actions}
                testID="chart-fullscreen-retention"
            />
        )
    } else if (display === 'bars' && snapshot.ranking) {
        body = (
            <BarList
                ranking={snapshot.ranking}
                label={snapshot.name}
                formatValue={snapshotFormatter(snapshot)}
                selectionId={SELECTION_ID}
                trackingContext="fullscreen"
                accessibilityActions={actions}
                testID="chart-fullscreen-bars"
            />
        )
    } else if (display === 'table' && snapshot.sqlTable) {
        body = (
            <SqlTable
                table={snapshot.sqlTable}
                label={snapshot.name}
                selectionId={SELECTION_ID}
                trackingContext="fullscreen"
                accessibilityActions={actions}
                testID="chart-fullscreen-table"
            />
        )
    } else if (display === 'number' && snapshot.value !== null) {
        body = <Text style={styles.number}>{snapshotFormatter(snapshot)(snapshot.value)}</Text>
    } else {
        body = <OpensOnWeb shortId={snapshot.shortId} />
    }
    return (
        <ScrollView
            contentContainerStyle={[styles.gutter, padding]}
            onScroll={(event) => {
                motion.onScroll()
                scrollTitle.onScroll(event)
            }}
            scrollEventThrottle={16}
            testID="chart-fullscreen"
        >
            {header}
            <View style={styles.card}>{body}</View>
        </ScrollView>
    )
}

function metaLead(snapshot: InsightSnapshot, display: InsightDisplay): string | null {
    if (display === 'chart') {
        return intervalLabel(snapshot.interval)
    }
    return display === 'table' && snapshot.sqlTable ? sqlRowsText(snapshot.sqlTable, SQL_TABLE_MAX_ROWS) : null
}

interface TimeSeriesProps {
    snapshot: InsightSnapshot
    source: ChartSheetSource
    rangeText: string | null
}

/**
 * The chart fills the space under the title. It does not sit in a scroll view, because a full-screen drag scrubs in
 * any direction. With several series the legend lists every one of them and scrolls on its own.
 */
function TimeSeries({ snapshot, source, rangeText }: TimeSeriesProps): ReactElement | null {
    const styles = useStyles()
    const sheets = useChartSheets()
    const legend = useChartLegend()
    const model = useInsightChartModel(snapshot, rangeText)
    const [area, setArea] = useState(0)
    const actions = useMemo<ChartAccessibilityAction[]>(
        () => [{ name: 'about', label: 'About this chart', onAction: () => sheets.openAbout(source, 'accessibility') }],
        [sheets, source]
    )
    const kind = snapshot.chartKind
    const many = model.series.length > 1
    const legendHeight = many
        ? Math.min(model.series.length * LEGEND_ROW_HEIGHT + 2, area * MAX_LEGEND_SHARE) + LEGEND_GAP
        : 0
    const chartHeight = Math.max(MIN_CHART_HEIGHT, Math.round(area - legendHeight))
    return (
        <View style={styles.fill} onLayout={(event) => setArea(event.nativeEvent.layout.height)}>
            {area > 0 && kind ? (
                <>
                    <MetricChart
                        series={model.series}
                        kind={kind}
                        interval={snapshot.interval}
                        label={snapshot.name}
                        formatValue={model.formatValue}
                        variant="fullscreen"
                        height={chartHeight}
                        hiddenKeys={legend.state.hiddenKeys}
                        dataUntil={model.dataUntil}
                        onPressTooltip={(point) => sheets.openPoint(source, point, 'tooltip')}
                        selectionId={SELECTION_ID}
                        trackingContext="fullscreen"
                        accessibilitySummary={model.summary}
                        accessibilityActions={actions}
                        testID="chart-fullscreen-chart"
                    />
                    {many ? (
                        <ScrollView style={styles.legend} contentContainerStyle={styles.legendContent}>
                            <ChartLegend
                                series={model.series}
                                state={legend.state}
                                onChange={legend.setState}
                                variant="fullscreen"
                                selectionId={SELECTION_ID}
                                testID="chart-fullscreen-legend"
                            />
                        </ScrollView>
                    ) : null}
                </>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    fill: {
        flex: 1,
    },
    gutter: {
        paddingHorizontal: layout.inboxGutter,
    },
    header: {
        gap: 4,
        marginBottom: 16,
        paddingHorizontal: 6,
    },
    titleBlock: {
        gap: 4,
    },
    title: {
        ...type.headline,
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        color: colors.secondary,
    },
    card: {
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    number: {
        fontSize: 40,
        lineHeight: 44,
        fontWeight: '700',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    legend: {
        flex: 1,
        marginTop: LEGEND_GAP,
    },
    legendContent: {
        paddingBottom: 8,
    },
}))
