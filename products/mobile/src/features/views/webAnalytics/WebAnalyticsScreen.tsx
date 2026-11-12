import { useRouter } from 'expo-router'
import { type ReactElement, useState } from 'react'
import { RefreshControl, ScrollView, Text, View } from 'react-native'

import { changeNavPin } from '@/features/tabs/navPinActions'
import { type NavChrome, useIsNavPinned } from '@/features/tabs/navPinStore'
import { TabHeaderPublisher } from '@/features/tabs/TabHeaderPublisher'
import { TABS_HEADER_BOTTOM } from '@/features/tabs/TabsHeader'
import { useTabVisit } from '@/features/tabs/useTabVisit'
import type { ViewEntry, WebTileId } from '@/model/views'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { Eyebrow } from '@/ui/Eyebrow'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, lineHeight, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets, useTabBottomOffset } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { ViewRangeControl } from '../range/ViewRangeControl'
import { RefreshFailedBanner } from '../screen/RefreshFailedBanner'
import { ViewChrome } from '../screen/ViewChrome'
import { ViewErrorState } from '../screen/ViewErrorState'
import { ViewMoreSheet } from '../screen/ViewMoreSheet'
import { useViewBack, ViewScreenFrame } from '../screen/ViewScreenFrame'
import { ViewSkeleton } from '../screen/ViewSkeleton'
import { ViewTitle } from '../screen/ViewTitle'
import { resolvedRangeText } from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { ViewsReauthState } from '../ViewsReauthState'
import { type Toasts, useToasts, ViewsToast } from '../ViewsToast'
import { webAnalyticsListHref } from '../viewRoutes'
import { viewWebUrl } from '../webLinks'
import { ActiveHoursCard } from './ActiveHoursCard'
import { trackWebListOpened } from './analytics'
import { BreakdownCard } from './BreakdownCard'
import { BreakdownSheet } from './BreakdownSheet'
import { FilterChips } from './FilterChips'
import { useWebAnalyticsActions, useWebAnalyticsScreen, type WebAnalyticsScreenState } from './hooks'
import { LiveChip } from './LiveChip'
import { MoreOnWeb } from './MoreOnWeb'
import { OverviewGrid } from './OverviewGrid'
import { RetentionCard } from './RetentionCard'
import { TrendCard } from './TrendCard'

/** A pushed screen has no bottom bar, so the toast sits low. */
const TOAST_BOTTOM = 48

export function WebAnalyticsScreen({ from, chrome }: { from: ViewEntry; chrome: NavChrome }): ReactElement {
    const styles = useStyles()
    const tab = chrome === 'tab'
    const visit = useTabVisit(tab)
    const screen = useWebAnalyticsScreen({ from, chrome, visit })
    const scrollTitle = useScrollTitle('Web analytics')
    const back = useViewBack()
    const insets = useScreenInsets()
    const tabBottom = useTabBottomOffset()
    const { scope } = useViewsContext()
    // The screen owns the toasts, so the More sheet's pin change shows one while the body still loads.
    const toasts = useToasts()
    const pinned = useIsNavPinned('web_analytics')
    const [moreOpen, setMoreOpen] = useState(false)
    const allowed = screen.access.state === 'ok'
    const { refresh } = screen
    let body: ReactElement
    if (allowed) {
        body = (
            <WebAnalyticsBody chrome={chrome} scrollTitle={scrollTitle} screen={screen} toasts={toasts} onBack={back} />
        )
    } else if (tab) {
        body = (
            <View
                style={[styles.fill, { paddingTop: topOffset(insets, TABS_HEADER_BOTTOM), paddingBottom: tabBottom }]}
            >
                <ViewsReauthState access={screen.access} />
            </View>
        )
    } else {
        body = <ViewsReauthState access={screen.access} />
    }
    return (
        <ViewScreenFrame
            overlayHost={!tab}
            chrome={
                tab ? null : (
                    <ViewChrome
                        title={scrollTitle.title}
                        onBack={back}
                        onMore={allowed ? () => setMoreOpen(true) : undefined}
                    />
                )
            }
        >
            {tab ? (
                <TabHeaderPublisher
                    tab="web_analytics"
                    status={allowed ? refresh.status.text : null}
                    hint={allowed ? refresh.hint : null}
                    refreshing={allowed && refresh.busy}
                />
            ) : null}
            {body}
            {tab ? null : (
                <ViewMoreSheet
                    visible={moreOpen}
                    onClose={() => setMoreOpen(false)}
                    webUrl={viewWebUrl(scope, '/web')}
                    viewType="web_analytics"
                    navPin={{
                        pinned,
                        onToggle: () => changeNavPin('web_analytics', !pinned, 'list_menu', toasts.show),
                    }}
                />
            )}
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={tab ? undefined : TOAST_BOTTOM} />
        </ViewScreenFrame>
    )
}

function WebAnalyticsBody({
    chrome,
    screen,
    toasts,
    onBack,
    scrollTitle,
}: {
    chrome: NavChrome
    screen: WebAnalyticsScreenState
    toasts: Toasts
    onBack: () => void
    scrollTitle: ScrollTitleState
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const tabBottom = useTabBottomOffset()
    const motion = useChartListMotion()
    const router = useRouter()
    const { scope } = useViewsContext()
    const actions = useWebAnalyticsActions(toasts)
    const [tabsFor, setTabsFor] = useState<WebTileId | null>(null)
    const { refresh } = screen
    const overview = screen.overview.data
    const tab = chrome === 'tab'
    const contentTop = topOffset(insets, tab ? TABS_HEADER_BOTTOM : SCREEN_CONTENT_TOP)
    const contentBottom = tab ? tabBottom : bottomOffset(insets, 48)
    const contentStyle = [styles.content, { paddingTop: contentTop, paddingBottom: contentBottom }]
    const rangeDetail = overview ? resolvedRangeText(overview.resolvedRange, 'day') : null
    const sheetTile = screen.tiles.find((tile) => tile.def.id === tabsFor) ?? null
    const liveChip = (
        <View style={styles.liveChip}>
            <LiveChip />
        </View>
    )
    // No compare row: every card compares with the previous period, as the web's tiles do.
    const rangeControl = (
        <ViewRangeControl
            range={screen.range}
            resolved={overview?.resolvedRange ?? null}
            loading={screen.rangeLoading}
            detail={rangeDetail}
            compare={null}
            style={tab ? styles.tabRange : undefined}
            trailing={tab ? liveChip : undefined}
        />
    )
    // On a tab the shared tabs header draws the title and the status line, so only the range stays in the content.
    const title = tab ? (
        <View style={styles.tabTitle}>
            {rangeControl}
            {rangeDetail ? <Text style={styles.rangeText}>{rangeDetail}</Text> : null}
        </View>
    ) : (
        <ViewTitle
            onTitleLayout={scrollTitle.onTitleLayout}
            title="Web analytics"
            accessories={liveChip}
            refresh={refresh}
            range={rangeControl}
            rangeDetail={rangeDetail}
        />
    )

    const filterChips = (
        <FilterChips filters={screen.filters} onRemove={actions.removeFilter} onClear={actions.clearFilters} />
    )

    if (!overview) {
        return (
            <ScrollView contentContainerStyle={[contentStyle, styles.grow]}>
                {filterChips}
                {screen.overview.isError && screen.error ? (
                    <ViewErrorState
                        kind={screen.error}
                        noun="view"
                        match={{ kind: 'web_analytics', ref: null }}
                        onRetry={() => screen.overview.refetch()}
                        onBack={onBack}
                    />
                ) : (
                    <ViewSkeleton cards={3} />
                )}
            </ScrollView>
        )
    }

    return (
        <>
            <ScrollView
                contentContainerStyle={contentStyle}
                onScroll={(event) => {
                    motion.onScroll()
                    scrollTitle.onScroll(event)
                }}
                scrollEventThrottle={16}
                refreshControl={
                    <RefreshControl
                        refreshing={refresh.pulling}
                        onRefresh={refresh.onPull}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={contentTop}
                    />
                }
                testID="web-analytics-scroll"
            >
                {title}
                <RefreshFailedBanner status={refresh.status} />
                {filterChips}
                {overview.metrics.length === 0 ? (
                    <Text style={styles.empty}>No web analytics data for this range.</Text>
                ) : (
                    <OverviewGrid
                        metrics={overview.metrics}
                        selected={screen.metric}
                        onSelect={actions.selectMetric}
                        stale={overview.refreshFailed}
                    />
                )}
                <View style={styles.cards}>
                    <TrendCard
                        data={screen.trend}
                        metric={screen.metric}
                        interval={screen.interval}
                        rangeText={rangeDetail}
                    />
                    {screen.tiles.map((tile) => (
                        <View key={tile.def.id} style={styles.section}>
                            <Eyebrow>{tile.def.title}</Eyebrow>
                            <BreakdownCard
                                tile={tile}
                                filters={screen.filters}
                                onOpenTabs={() => setTabsFor(tile.def.id)}
                                onPressRow={(row) => {
                                    if (row.filter) {
                                        actions.tapRow(tile.def.id, tile.breakdown, row.filter, 'card')
                                    }
                                }}
                                onOpenList={() => {
                                    trackWebListOpened({ tile: tile.def.id, breakdown: tile.breakdown })
                                    router.push(webAnalyticsListHref(tile.def.id, tile.breakdown))
                                }}
                            />
                        </View>
                    ))}
                    <RetentionCard data={screen.retention} />
                    <ActiveHoursCard data={screen.activeHours} />
                    <MoreOnWeb webUrl={viewWebUrl(scope, '/web')} />
                </View>
            </ScrollView>
            <BreakdownSheet
                tile={sheetTile?.def ?? null}
                selected={sheetTile?.breakdown ?? null}
                onPick={(breakdown) => {
                    if (sheetTile) {
                        actions.setTab(sheetTile.def.id, breakdown, 'card')
                    }
                }}
                onClose={() => setTabsFor(null)}
            />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    fill: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    tabTitle: {
        paddingHorizontal: 6,
        marginBottom: 16,
        gap: 8,
    },
    tabRange: {
        marginTop: 0,
    },
    liveChip: {
        marginLeft: 'auto',
        paddingLeft: 8,
    },
    rangeText: {
        ...type.meta,
        lineHeight: lineHeight(13),
        color: colors.tertiary,
    },
    grow: {
        flexGrow: 1,
    },
    cards: {
        gap: 16,
        marginTop: 16,
    },
    section: {
        gap: 8,
    },
    empty: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
        paddingVertical: 32,
    },
}))
