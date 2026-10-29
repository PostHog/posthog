import { type ReactElement, useCallback, useMemo } from 'react'
import { Text, View } from 'react-native'

import type { InsightSnapshot } from '@/model/views'
import { BarList } from '@/ui/chart/BarList'
import { FunnelSteps, funnelSummary } from '@/ui/chart/FunnelSteps'
import { RetentionGrid } from '@/ui/chart/RetentionGrid'
import { SqlTable } from '@/ui/chart/SqlTable'
import { SQL_TABLE_MAX_ROWS, sqlRowsText } from '@/ui/chart/sqlCellFormat'
import type { ChartAccessibilityAction, ChartCanvasSlot } from '@/ui/chart/types'
import { ExpandIcon } from '@/ui/icons/ExpandIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { FullScreenEntry } from './analytics'
import { useOpenFullScreen } from './fullScreen/useOpenFullScreen'
import { InsightChart } from './InsightChart'
import { OpensOnWeb } from './OpensOnWeb'
import { useChartSheets } from './pointSheet/ChartSheetsProvider'
import type { ChartSheetSource } from './pointSheet/chartSheetSource'
import { TileSkeleton } from './screen/ViewSkeleton'
import {
    type InsightDisplay,
    insightDisplay,
    insightRenderState,
    intervalLabel,
    noDataText,
    snapshotFormatter,
} from './snapshotChart'

/** A tile shows this many ranked values or table rows, then "+N more" opens the chart full screen. */
const TILE_ROWS = 6

const PERIOD_ADJECTIVES = { hour: 'Hourly', day: 'Daily', week: 'Weekly', month: 'Monthly' } as const

/** True for the displays that open full screen: everything the phone draws, except a big number. */
export function hasFullScreen(display: InsightDisplay): boolean {
    return (
        display === 'chart' ||
        display === 'funnel' ||
        display === 'retention' ||
        display === 'bars' ||
        display === 'table'
    )
}

/** "Weekly cohorts" for a retention insight. */
export function retentionCaption(snapshot: InsightSnapshot): string | null {
    return snapshot.retention ? `${PERIOD_ADJECTIVES[snapshot.retention.period]} cohorts` : null
}

interface InsightNoDataProps {
    snapshot: Pick<InsightSnapshot, 'resolvedRange' | 'sqlTable'>
    /** The height of the chart this line stands in for, so the layout does not jump when data arrives. */
    minHeight?: number
    testID: string
}

/** The muted line in a chart's place when its result has nothing to draw. */
export function InsightNoData({ snapshot, minHeight, testID }: InsightNoDataProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={[styles.noData, minHeight !== undefined && { minHeight }]} testID={testID}>
            <Text style={styles.noDataText}>{noDataText(snapshot)}</Text>
        </View>
    )
}

/** The line above a chart on the insight screen: what the chart shows at a glance. */
function screenCaption(snapshot: InsightSnapshot, display: InsightDisplay): string | null {
    switch (display) {
        case 'chart':
            return intervalLabel(snapshot.interval)
        case 'funnel':
            return snapshot.funnel ? funnelSummary(snapshot.funnel) : null
        case 'retention':
            return retentionCaption(snapshot)
        case 'bars':
            if (!snapshot.ranking) {
                return null
            }
            // SQL rows keep the server's order; trends rankings sort highest first.
            return snapshot.sqlTable
                ? `${snapshot.ranking.rows.length} values`
                : `${snapshot.ranking.rows.length} values, highest first`
        case 'table':
            return snapshot.sqlTable ? sqlRowsText(snapshot.sqlTable, SQL_TABLE_MAX_ROWS) : null
        default:
            return null
    }
}

interface InsightVisualProps {
    snapshot: InsightSnapshot
    /** What the Point, About and full-screen views describe. */
    source: ChartSheetSource
    /** A dashboard tile, or the insight screen with its full-screen button. */
    place: 'tile' | 'screen'
    /** Unique on the screen, for the one-selected-chart rule. */
    selectionId: string
    /** For the spoken summary, such as "last 14 days". */
    rangeText: string | null
    chartHeight?: number
    canvasSlot?: ChartCanvasSlot
    /** The chart's testID, such as `chart-demo-tile-1`. */
    testID: string
    /** The testID of the line that says the range has no data. */
    emptyTestID?: string
}

/**
 * An insight's body when it is not a big number: a line or bar chart, funnel steps, a retention grid, ranked bars, a
 * SQL table, or the card that opens it on the web. Before its result arrives it shows a placeholder, and a result
 * with nothing to draw shows "No data".
 */
export function InsightVisual({
    snapshot,
    source,
    place,
    selectionId,
    rangeText,
    chartHeight,
    canvasSlot,
    testID,
    emptyTestID = 'view-insight-empty',
}: InsightVisualProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const sheets = useChartSheets()
    const openFullScreen = useOpenFullScreen()
    const display = insightDisplay(snapshot)
    const open = useCallback((entry: FullScreenEntry) => openFullScreen(source, entry), [openFullScreen, source])
    const actions = useMemo<ChartAccessibilityAction[]>(
        () => [
            { name: 'about', label: 'About this chart', onAction: () => sheets.openAbout(source, 'accessibility') },
            { name: 'fullScreen', label: 'Open full screen', onAction: () => open('accessibility') },
        ],
        [sheets, source, open]
    )
    const formatValue = useMemo(() => snapshotFormatter(snapshot), [snapshot])

    const state = insightRenderState(snapshot)
    if (state === 'pending') {
        return (
            <View testID="view-insight-pending">
                <TileSkeleton height={chartHeight} />
            </View>
        )
    }
    if (state === 'empty') {
        return place === 'screen' ? (
            <View style={styles.card}>
                <InsightNoData snapshot={snapshot} testID={emptyTestID} />
            </View>
        ) : (
            <InsightNoData snapshot={snapshot} minHeight={chartHeight} testID={emptyTestID} />
        )
    }

    const body = ((): ReactElement | null => {
        switch (display) {
            case 'chart':
                return (
                    <InsightChart
                        snapshot={snapshot}
                        source={source}
                        selectionId={selectionId}
                        rangeText={rangeText}
                        height={chartHeight}
                        canvasSlot={canvasSlot}
                        onOpenFullScreen={open}
                        testID={testID}
                    />
                )
            case 'funnel':
                return snapshot.funnel ? (
                    <FunnelSteps
                        funnel={snapshot.funnel}
                        label={snapshot.name}
                        selectionId={selectionId}
                        trackingContext="view"
                        accessibilityActions={actions}
                        testID={testID}
                    />
                ) : null
            case 'retention':
                return snapshot.retention ? (
                    <RetentionGrid
                        retention={snapshot.retention}
                        label={snapshot.name}
                        selectionId={selectionId}
                        trackingContext="view"
                        accessibilityActions={actions}
                        testID={testID}
                    />
                ) : null
            case 'bars':
                return snapshot.ranking ? (
                    <BarList
                        ranking={snapshot.ranking}
                        label={snapshot.name}
                        formatValue={formatValue}
                        maxRows={place === 'tile' ? TILE_ROWS : undefined}
                        onPressMore={() => open('rows_more')}
                        selectionId={selectionId}
                        trackingContext="view"
                        accessibilityActions={actions}
                        testID={testID}
                    />
                ) : null
            case 'table':
                return snapshot.sqlTable ? (
                    <SqlTable
                        table={snapshot.sqlTable}
                        label={snapshot.name}
                        maxRows={place === 'tile' ? TILE_ROWS : undefined}
                        onPressMore={() => open('rows_more')}
                        selectionId={selectionId}
                        trackingContext="view"
                        accessibilityActions={actions}
                        testID={testID}
                    />
                ) : null
            case 'web':
                return place === 'screen' ? (
                    <View style={styles.card}>
                        <OpensOnWeb shortId={snapshot.shortId} />
                    </View>
                ) : (
                    <OpensOnWeb shortId={snapshot.shortId} />
                )
            default:
                return null
        }
    })()

    if (place === 'tile' || !hasFullScreen(display)) {
        return body
    }
    const caption = screenCaption(snapshot, display)
    return (
        <View>
            <View style={styles.toolbar}>
                <Text style={styles.caption} numberOfLines={2}>
                    {caption}
                </Text>
                <Pressable44
                    onPress={() => open('button')}
                    accessibilityLabel="Open full screen"
                    pressedBackground={colors.sunken}
                    style={styles.expand}
                    testID="view-fullscreen"
                >
                    <ExpandIcon size={18} color={colors.secondary} />
                </Pressable44>
            </View>
            {body}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    toolbar: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        marginBottom: 6,
    },
    caption: {
        ...type.metaSmall,
        flex: 1,
        color: colors.secondary,
    },
    expand: {
        width: 36,
        height: 36,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    card: {
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    noData: {
        justifyContent: 'center',
    },
    noDataText: {
        ...type.bodySmall,
        color: colors.muted,
    },
}))
