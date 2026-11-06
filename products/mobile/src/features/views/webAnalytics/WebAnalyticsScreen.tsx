import { useRouter } from 'expo-router'
import { type ReactElement, useState } from 'react'
import { RefreshControl, ScrollView, Text, View } from 'react-native'

import type { ViewEntry, WebTileId } from '@/model/views'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { Eyebrow } from '@/ui/Eyebrow'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
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
import { useToasts, ViewsToast } from '../ViewsToast'
import { webAnalyticsListHref } from '../viewRoutes'
import { viewWebUrl } from '../webLinks'
import { ActiveHoursCard } from './ActiveHoursCard'
import { trackWebListOpened } from './analytics'
import { BreakdownCard } from './BreakdownCard'
import { BreakdownSheet } from './BreakdownSheet'
import { FilterChips } from './FilterChips'
import { useWebAnalyticsActions, useWebAnalyticsScreen, type WebAnalyticsScreenState } from './hooks'
import { MoreOnWeb } from './MoreOnWeb'
import { OverviewGrid } from './OverviewGrid'
import { RetentionCard } from './RetentionCard'
import { TrendCard } from './TrendCard'

/** A pushed screen has no bottom bar, so the toast sits low. */
const TOAST_BOTTOM = 48

export function WebAnalyticsScreen({ from }: { from: ViewEntry }): ReactElement {
    const screen = useWebAnalyticsScreen({ from })
    const scrollTitle = useScrollTitle('Web analytics')
    const back = useViewBack()
    const { scope } = useViewsContext()
    const [moreOpen, setMoreOpen] = useState(false)
    const allowed = screen.access.state === 'ok'
    return (
        <ViewScreenFrame
            chrome={
                <ViewChrome
                    title={scrollTitle.title}
                    onBack={back}
                    onMore={allowed ? () => setMoreOpen(true) : undefined}
                />
            }
        >
            {allowed ? (
                <WebAnalyticsBody scrollTitle={scrollTitle} screen={screen} onBack={back} />
            ) : (
                <ViewsReauthState access={screen.access} />
            )}
            <ViewMoreSheet
                visible={moreOpen}
                onClose={() => setMoreOpen(false)}
                webUrl={viewWebUrl(scope, '/web')}
                viewType="web_analytics"
            />
        </ViewScreenFrame>
    )
}

function WebAnalyticsBody({
    screen,
    onBack,
    scrollTitle,
}: {
    screen: WebAnalyticsScreenState
    onBack: () => void
    scrollTitle: ScrollTitleState
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const motion = useChartListMotion()
    const router = useRouter()
    const { scope } = useViewsContext()
    const toasts = useToasts()
    const actions = useWebAnalyticsActions(toasts)
    const [tabsFor, setTabsFor] = useState<WebTileId | null>(null)
    const { refresh } = screen
    const overview = screen.overview.data
    const contentTop = topOffset(insets, SCREEN_CONTENT_TOP)
    const contentStyle = [styles.content, { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 48) }]
    const rangeDetail = overview ? resolvedRangeText(overview.resolvedRange, 'day') : null
    const sheetTile = screen.tiles.find((tile) => tile.def.id === tabsFor) ?? null
    const title = (
        <ViewTitle
            onTitleLayout={scrollTitle.onTitleLayout}
            title="Web analytics"
            refresh={refresh}
            range={
                // No compare row: every card compares with the previous period, as the web's tiles do.
                <ViewRangeControl
                    range={screen.range}
                    resolved={overview?.resolvedRange ?? null}
                    loading={screen.rangeLoading}
                    detail={rangeDetail}
                    compare={null}
                />
            }
            rangeDetail={rangeDetail}
        />
    )

    if (!overview) {
        return (
            <ScrollView contentContainerStyle={[contentStyle, styles.grow]}>
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
                <FilterChips filters={screen.filters} onRemove={actions.removeFilter} onClear={actions.clearFilters} />
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
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={TOAST_BOTTOM} />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingHorizontal: layout.inboxGutter,
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
