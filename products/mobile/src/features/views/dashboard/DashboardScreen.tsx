import { useIsFocused } from 'expo-router'
import { type ReactElement, useCallback, useRef, useState } from 'react'
import { FlatList, type ListRenderItem, RefreshControl, ScrollView, Text, View, type ViewToken } from 'react-native'
import type { DashboardView, InsightSnapshot, PinDisplayMode, ViewEntry } from '@/model/views'
import { ChartCanvasBudget, useCanvasBudgetViewport } from '@/ui/chart/budget/ChartCanvasBudget'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'
import { PinButton } from '../PinButton'
import { dashboardCompareRow } from '../range/compareRow'
import { ViewRangeControl } from '../range/ViewRangeControl'
import { RefreshFailedBanner } from '../screen/RefreshFailedBanner'
import { ViewChrome } from '../screen/ViewChrome'
import { ViewErrorState } from '../screen/ViewErrorState'
import { ViewMoreSheet } from '../screen/ViewMoreSheet'
import { useViewBack, ViewScreenFrame } from '../screen/ViewScreenFrame'
import { ViewSkeleton } from '../screen/ViewSkeleton'
import { ViewTitle } from '../screen/ViewTitle'
import { resolvedRangeText } from '../snapshotChart'
import { INITIAL_VISIBLE_ROWS } from '../useViewRefresh'
import { useViewsContext } from '../useViewsContext'
import { ViewsReauthState } from '../ViewsReauthState'
import { type DashboardScreenState, type DashboardTileState, useDashboardScreen, useTileData } from '../viewHooks'
import { viewWebUrl } from '../webLinks'
import { InsightTile } from './DashboardTile'
import { TextTile } from './TextTile'

interface DashboardScreenProps {
    /** The dashboard id as a string, or the demo ref. */
    dashboardRef: string
    from: ViewEntry
    displayMode: PinDisplayMode | null
}

/**
 * A dashboard in one column. It opens like the web: a cache-only dashboard read, then a `blocking` read for each
 * visible tile whose cached result is missing or past its `cache_target_age`.
 */
export function DashboardScreen({ dashboardRef, from, displayMode }: DashboardScreenProps): ReactElement {
    const screen = useDashboardScreen(dashboardRef, { from, displayMode })
    const scrollTitle = useScrollTitle(screen.dashboard.data?.name ?? '')
    const back = useViewBack()
    const { scope } = useViewsContext()
    const [moreOpen, setMoreOpen] = useState(false)
    // A tile opened on top of the dashboard keeps it mounted. Its charts then give their canvases back.
    const focused = useIsFocused()
    const allowed = screen.access.state === 'ok'
    const dashboard = screen.dashboard.data
    return (
        <ViewScreenFrame
            chrome={
                <ViewChrome
                    title={scrollTitle.title}
                    onBack={back}
                    onMore={allowed && dashboard ? () => setMoreOpen(true) : undefined}
                />
            }
        >
            {allowed ? (
                <ChartCanvasBudget active={focused}>
                    <DashboardBody
                        scrollTitle={scrollTitle}
                        screen={screen}
                        dashboardRef={dashboardRef}
                        onBack={back}
                    />
                </ChartCanvasBudget>
            ) : (
                <ViewsReauthState access={screen.access} />
            )}
            <ViewMoreSheet
                visible={moreOpen}
                onClose={() => setMoreOpen(false)}
                webUrl={dashboard ? viewWebUrl(scope, `/dashboard/${dashboard.id}`) : undefined}
                viewType="dashboard"
            />
        </ViewScreenFrame>
    )
}

interface DashboardBodyProps {
    scrollTitle: ScrollTitleState
    screen: DashboardScreenState
    dashboardRef: string
    onBack: () => void
}

/** Calls both visibility trackers from one callback, because a list takes one and it must never change. */
function useViewableItems(
    first: (info: { viewableItems: ViewToken[] }) => void,
    second: (info: { viewableItems: ViewToken[] }) => void
): (info: { viewableItems: ViewToken[] }) => void {
    const handlers = useRef({ first, second })
    handlers.current = { first, second }
    return useRef((info: { viewableItems: ViewToken[] }) => {
        handlers.current.first(info)
        handlers.current.second(info)
    }).current
}

function DashboardBody({ screen, dashboardRef, onBack, scrollTitle }: DashboardBodyProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const motion = useChartListMotion()
    const viewport = useCanvasBudgetViewport()
    const onViewableItemsChanged = useViewableItems(screen.onViewableItemsChanged, viewport.onViewableItemsChanged)
    const { refresh, tiles } = screen
    const dashboard = screen.dashboard.data
    const hasDashboardRange = tiles.some((tile) => tile.view.kind === 'insight' && !tile.view.usesOwnRange)
    const contentStyle = [
        styles.content,
        { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP), paddingBottom: bottomOffset(insets, 48) },
    ]

    const renderItem = useCallback<ListRenderItem<DashboardTileState>>(
        ({ item, index }) =>
            item.view.kind === 'text' ? (
                <TextTile text={item.view.text} tileId={item.view.tileId} />
            ) : (
                <InsightTile
                    tile={item}
                    index={index}
                    dashboardRef={dashboardRef}
                    dashboardName={dashboard?.name ?? ''}
                    showRangeOverride={hasDashboardRange}
                    refreshItem={refresh.refreshItem}
                />
            ),
        [dashboardRef, dashboard?.name, hasDashboardRange, refresh.refreshItem]
    )

    if (!dashboard) {
        return (
            <ScrollView contentContainerStyle={[contentStyle, styles.grow]}>
                {screen.dashboard.isError && screen.error ? (
                    <ViewErrorState
                        kind={screen.error}
                        noun="dashboard"
                        match={{ kind: 'dashboard', ref: dashboardRef }}
                        onRetry={() => screen.dashboard.refetch()}
                        onBack={onBack}
                    />
                ) : (
                    <ViewSkeleton />
                )}
            </ScrollView>
        )
    }

    return (
        <FlatList
            data={tiles}
            keyExtractor={(tile) => String(tile.view.tileId)}
            renderItem={renderItem}
            ListHeaderComponent={
                <DashboardHeader
                    onTitleLayout={scrollTitle.onTitleLayout}
                    screen={screen}
                    dashboard={dashboard}
                    dashboardRef={dashboardRef}
                />
            }
            ListEmptyComponent={
                <Text style={styles.empty}>This dashboard has no tiles yet. Add insights to it on the web.</Text>
            }
            ItemSeparatorComponent={TileGap}
            contentContainerStyle={contentStyle}
            onViewableItemsChanged={onViewableItemsChanged}
            viewabilityConfig={screen.viewabilityConfig}
            onScroll={(event) => {
                motion.onScroll()
                scrollTitle.onScroll(event)
            }}
            scrollEventThrottle={16}
            initialNumToRender={INITIAL_VISIBLE_ROWS}
            windowSize={5}
            refreshControl={
                <RefreshControl
                    refreshing={refresh.pulling}
                    onRefresh={refresh.onPull}
                    tintColor={colors.tertiary}
                    progressBackgroundColor={colors.surface}
                    colors={[colors.tertiary]}
                    progressViewOffset={topOffset(insets, SCREEN_CONTENT_TOP)}
                />
            }
            testID="dashboard-tiles"
        />
    )
}

function TileGap(): ReactElement {
    const styles = useStyles()
    return <View style={styles.gap} />
}

interface DashboardHeaderProps {
    onTitleLayout: ScrollTitleState['onTitleLayout']
    screen: DashboardScreenState
    dashboard: DashboardView
    dashboardRef: string
}

const NO_TILE = { itemKey: null, queryKey: null }

function DashboardHeader({ screen, dashboard, dashboardRef, onTitleLayout }: DashboardHeaderProps): ReactElement {
    const styles = useStyles()
    // The dashboard response has no resolved dates, so the header uses those of the first tile that follows the range.
    const rangeTile = screen.tiles.find((tile) => tile.view.kind === 'insight' && !tile.view.usesOwnRange)
    const { snapshot } = useTileData(rangeTile ?? NO_TILE)
    const resolved = snapshot?.resolvedRange ?? null
    const { item } = useViewsContext()
    // Every tile resolves in the project timezone, also one with its own range, so any of them gives today's date.
    const zoneHint =
        screen.tiles
            .map((tile) =>
                tile.queryKey ? item.client.getQueryData<InsightSnapshot>(tile.queryKey)?.resolvedRange?.to : undefined
            )
            .find((to) => typeof to === 'string') ?? null
    // While a new range loads, the tile has no snapshot yet, so the dates of the previous range stay in place.
    const shownDates = useRef<string | null>(null)
    if (snapshot) {
        shownDates.current = resolvedRangeText(snapshot.resolvedRange, snapshot.interval)
    }
    const detail = rangeTile ? shownDates.current : null
    return (
        <View>
            <ViewTitle
                onTitleLayout={onTitleLayout}
                title={dashboard.name}
                accessories={
                    <PinButton
                        target={{ kind: 'dashboard', id: dashboard.id, name: dashboard.name }}
                        match={{ kind: 'dashboard', ref: dashboardRef }}
                    />
                }
                refresh={screen.refresh}
                range={
                    rangeTile ? (
                        <ViewRangeControl
                            range={screen.range}
                            resolved={resolved}
                            detail={detail}
                            zoneHint={zoneHint}
                            compare={dashboardCompareRow(screen.range, screen.compareSupported)}
                        />
                    ) : null
                }
                rangeDetail={detail ? <Text style={styles.rangeDetail}>{detail}</Text> : null}
            />
            <RefreshFailedBanner status={screen.refresh.status} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    grow: {
        flexGrow: 1,
    },
    gap: {
        height: 10,
    },
    empty: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
        paddingVertical: 32,
        paddingHorizontal: 20,
    },
    rangeDetail: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
