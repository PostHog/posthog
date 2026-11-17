import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useMemo } from 'react'
import { Text, View } from 'react-native'

import { useNow } from '@/lib/useNow'
import type { DashboardTileView, InsightSnapshot } from '@/model/views'
import { funnelPercent } from '@/ui/chart/FunnelSteps'
import { ExpandIcon } from '@/ui/icons/ExpandIcon'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { DeltaPill } from '../DeltaPill'
import { isEligible } from '../freshness'
import { useOpenFullScreen } from '../fullScreen/useOpenFullScreen'
import { hasFullScreen, InsightNoData, InsightVisual, retentionCaption } from '../InsightVisual'
import type { ChartSheetSource } from '../pointSheet/chartSheetSource'
import { TileSkeleton } from '../screen/ViewSkeleton'
import {
    deltaBasisText,
    type InsightDisplay,
    insightDisplay,
    insightRenderState,
    intervalLabel,
    resolvedRangeText,
    snapshotFormatter,
    valueAtText,
} from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { type DashboardTileState, useTileData } from '../viewHooks'
import { insightHref } from '../viewRoutes'
import type { ItemErrorKind } from '../viewsCache'

/** Gives a tile's chart the testID the smoke flow selects by, such as `chart-demo-tile-1`. */
export function tileChartTestID(demo: boolean, tileId: number): string {
    return `chart-${demo ? 'demo-' : ''}tile-${tileId}`
}

const TILE_CHART_HEIGHT = 160
/** The height of a big number's row, so a tile without its number keeps the same size. */
const TILE_NUMBER_HEIGHT = 36

function bodyHeight(display: InsightDisplay | null): number {
    return display === 'number' ? TILE_NUMBER_HEIGHT : TILE_CHART_HEIGHT
}

const TILE_ERRORS: Record<ItemErrorKind, string> = {
    deleted: 'This insight was deleted.',
    no_access: "You don't have access to this insight.",
    scope: 'Sign in again to see this insight.',
    failed: "Couldn't load this tile. Pull down to try again.",
}

interface InsightTileProps {
    tile: DashboardTileState
    /** The tile's position in the list, for the canvas budget. */
    index: number
    dashboardRef: string
    dashboardName: string
    showRangeOverride: boolean
    refreshItem: (itemKey: string) => boolean
}

/** One insight on a dashboard: a big number, a chart, or a card that opens it on the web. */
export function InsightTile({
    tile,
    index,
    dashboardRef,
    dashboardName,
    showRangeOverride,
    refreshItem,
}: InsightTileProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const { mode } = useViewsContext()
    const data = useTileData(tile)
    // Eligibility moves with the server's window, so the Refresh action appears without a new read.
    useNow(30_000)
    const { view, itemKey, queryKey } = tile
    const snapshot = data.snapshot
    const source = useMemo<ChartSheetSource | null>(
        () => (snapshot ? { snapshot, queryKey, itemKey, refreshItem, dashboardName } : null),
        [snapshot, queryKey, itemKey, refreshItem, dashboardName]
    )
    const open = (): void => {
        if (view.shortId) {
            router.push(
                insightHref(view.shortId, { fromDashboard: dashboardRef, insightId: view.insightId, from: 'dashboard' })
            )
        }
    }
    const display = snapshot ? insightDisplay(snapshot) : null
    // Pending and empty tiles have nothing to refresh or open full screen. Load reads a pending tile.
    const state = snapshot ? insightRenderState(snapshot) : null
    const ready = state === 'ready'
    const openFullScreen = useOpenFullScreen()
    const expand = useCallback(() => {
        if (source) {
            openFullScreen(source, 'button')
        }
    }, [openFullScreen, source])
    // A web card shows no result, so a refresh would compute for nothing.
    const canRefresh = Boolean(
        itemKey && snapshot && ready && display !== 'web' && isEligible(snapshot) && !data.updating
    )
    const name = snapshot?.name ?? view.name

    return (
        <View style={styles.tile} testID={`view-tile-${view.tileId}`}>
            <View style={styles.head}>
                <Pressable44
                    onPress={open}
                    style={styles.headText}
                    hitSlop={0}
                    accessibilityLabel={`Open ${name}`}
                    testID={`view-tile-open-${view.tileId}`}
                >
                    <Text style={styles.title}>{name}</Text>
                    <Text style={styles.meta} numberOfLines={1}>
                        {tileMeta(snapshot, view)}
                    </Text>
                </Pressable44>
                {showRangeOverride && view.usesOwnRange ? (
                    <View style={styles.ownRange}>
                        <Text style={styles.ownRangeText}>Uses its own range</Text>
                    </View>
                ) : null}
                {canRefresh && itemKey ? (
                    <Pressable44
                        onPress={() => refreshItem(itemKey)}
                        accessibilityLabel={`Refresh ${name}`}
                        style={styles.refresh}
                        pressedBackground={colors.sunken}
                        testID={`view-tile-refresh-${view.tileId}`}
                    >
                        <RefreshIcon size={18} color={colors.secondary} />
                    </Pressable44>
                ) : null}
                {display && ready && hasFullScreen(display) ? (
                    <Pressable44
                        onPress={expand}
                        accessibilityLabel={`Open ${name} full screen`}
                        style={styles.refresh}
                        pressedBackground={colors.sunken}
                        testID={`view-tile-fullscreen-${view.tileId}`}
                    >
                        <ExpandIcon size={17} color={colors.secondary} />
                    </Pressable44>
                ) : null}
            </View>
            <View style={snapshot?.refreshFailed ? styles.dimmed : undefined}>
                {!snapshot || !source ? (
                    data.error ? (
                        <Text style={styles.message}>{TILE_ERRORS[data.error]}</Text>
                    ) : (
                        <TileSkeleton height={TILE_CHART_HEIGHT} />
                    )
                ) : state === 'pending' ? (
                    data.updating ? (
                        <TileSkeleton height={bodyHeight(display)} />
                    ) : data.error ? (
                        <Text style={styles.message}>{TILE_ERRORS[data.error]}</Text>
                    ) : (
                        <View style={[styles.pending, { minHeight: bodyHeight(display) }]}>
                            <Text style={styles.pendingText}>Not loaded yet</Text>
                            <Pressable44
                                onPress={() => {
                                    if (itemKey) {
                                        refreshItem(itemKey)
                                    }
                                }}
                                disabled={data.updating || !itemKey}
                                accessibilityLabel={`Load ${name}`}
                                style={styles.loadButton}
                                pressedBackground={colors.pressed}
                                testID={`view-tile-load-${view.tileId}`}
                            >
                                <Text style={styles.loadButtonText}>Load</Text>
                            </Pressable44>
                        </View>
                    )
                ) : display === 'number' ? (
                    state === 'empty' ? (
                        <InsightNoData
                            snapshot={snapshot}
                            minHeight={TILE_NUMBER_HEIGHT}
                            testID={`view-tile-empty-${view.tileId}`}
                        />
                    ) : (
                        <NumberBody snapshot={snapshot} onOpen={open} />
                    )
                ) : (
                    <InsightVisual
                        snapshot={snapshot}
                        source={source}
                        place="tile"
                        selectionId={`tile-${view.tileId}`}
                        rangeText={resolvedRangeText(snapshot.resolvedRange, snapshot.interval)}
                        chartHeight={TILE_CHART_HEIGHT}
                        canvasSlot={{ key: String(view.tileId), index }}
                        testID={tileChartTestID(mode === 'demo', view.tileId)}
                        emptyTestID={`view-tile-empty-${view.tileId}`}
                    />
                )}
            </View>
            {data.updating ? <View style={styles.progress} accessibilityElementsHidden /> : null}
        </View>
    )
}

function tileMeta(snapshot: InsightSnapshot | undefined, view: DashboardTileView): string {
    // A SQL tile without `{filters}` has no date window, so the dashboard's dates would mislabel it.
    if (!snapshot || view.ignoresRangeOverride || insightRenderState(snapshot) === 'pending') {
        return snapshot?.kindLabel ?? view.kindLabel
    }
    const range = resolvedRangeText(snapshot.resolvedRange, snapshot.interval)
    switch (insightDisplay(snapshot)) {
        case 'chart':
            return [intervalLabel(snapshot.interval), range].filter(Boolean).join(' · ')
        case 'funnel': {
            const conversion = snapshot.funnel?.conversion ?? null
            const lead = conversion === null ? snapshot.kindLabel : `${funnelPercent(conversion)} conversion`
            return [lead, range].filter(Boolean).join(' · ')
        }
        case 'retention':
            return retentionCaption(snapshot) ?? snapshot.kindLabel
        case 'bars':
            return ['Total', range].filter(Boolean).join(' · ')
        default:
            return [snapshot.kindLabel, range].filter(Boolean).join(' · ')
    }
}

function NumberBody({ snapshot, onOpen }: { snapshot: InsightSnapshot; onOpen: () => void }): ReactElement {
    const styles = useStyles()
    const formatValue = snapshotFormatter(snapshot)
    const at = valueAtText(snapshot)
    return (
        <Pressable44 onPress={onOpen} hitSlop={0} style={styles.numberRow} accessibilityLabel={`Open ${snapshot.name}`}>
            <Text style={styles.value} numberOfLines={1} adjustsFontSizeToFit>
                {snapshot.value === null ? '–' : formatValue(snapshot.value)}
            </Text>
            {at ? <Text style={styles.meta}>{at}</Text> : null}
            {snapshot.delta ? (
                <DeltaPill
                    delta={snapshot.delta}
                    formatValue={formatValue}
                    basis={deltaBasisText(snapshot.delta, snapshot.interval)}
                />
            ) : null}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    tile: {
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    head: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
        marginBottom: 12,
    },
    headText: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        fontSize: 15,
        lineHeight: 20,
        fontWeight: '600',
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        lineHeight: 18,
        color: colors.tertiary,
    },
    ownRange: {
        height: 22,
        paddingHorizontal: 8,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        justifyContent: 'center',
    },
    ownRangeText: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.secondary,
    },
    refresh: {
        width: 32,
        height: 32,
        marginTop: -6,
        marginRight: -6,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    dimmed: {
        opacity: 0.5,
    },
    message: {
        ...type.metaSmall,
        color: colors.muted,
        paddingVertical: 8,
    },
    pending: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
    },
    pendingText: {
        ...type.bodySmall,
        color: colors.muted,
    },
    loadButton: {
        height: 36,
        justifyContent: 'center',
        paddingHorizontal: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    loadButtonText: {
        fontSize: 14,
        fontWeight: '600',
        color: colors.ink,
    },
    numberRow: {
        flexDirection: 'row',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 10,
    },
    value: {
        fontSize: 30,
        lineHeight: 36,
        fontWeight: '700',
        letterSpacing: -0.6,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
        flexShrink: 1,
    },
    progress: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 2,
        backgroundColor: colors.blueLight,
    },
}))
