import { type ReactElement, useState } from 'react'
import { RefreshControl, ScrollView, Text } from 'react-native'

import { BREAKDOWN_LABELS, breakdownFilters } from '@/model/adapters/webAnalyticsBreakdowns'
import type { WebBreakdown, WebBreakdownSnapshot, WebTileId } from '@/model/views'
import { useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import { Pressable44 } from '@/ui/Pressable44'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'

import { ViewRangeControl } from '../range/ViewRangeControl'
import { RefreshFailedBanner } from '../screen/RefreshFailedBanner'
import { ViewChrome } from '../screen/ViewChrome'
import { ViewMoreSheet } from '../screen/ViewMoreSheet'
import { useViewBack, ViewScreenFrame } from '../screen/ViewScreenFrame'
import { ViewTitle } from '../screen/ViewTitle'
import { resolvedRangeText } from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { ViewsReauthState } from '../ViewsReauthState'
import { useToasts, ViewsToast } from '../ViewsToast'
import { viewWebUrl } from '../webLinks'
import { rowIsActive } from './BreakdownCard'
import { BreakdownColumns, BreakdownRows } from './BreakdownRows'
import { FilterChips } from './FilterChips'
import { LIST_LIMIT, useWebAnalyticsActions, useWebBreakdownList, useWebItemData } from './hooks'
import { WebCard, webCardState } from './WebCard'

const TOAST_BOTTOM = 48

interface WebBreakdownListScreenProps {
    tile: WebTileId
    /** The tab the card showed, for a deep link. The session's choice for the tile wins. */
    breakdown: WebBreakdown | null
}

export function WebBreakdownListScreen({ tile, breakdown }: WebBreakdownListScreenProps): ReactElement {
    const list = useWebBreakdownList(tile, breakdown)
    const scrollTitle = useScrollTitle(list.tile.title)
    const back = useViewBack()
    const { scope } = useViewsContext()
    const [moreOpen, setMoreOpen] = useState(false)
    const allowed = list.access.state === 'ok'
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
                <ListBody list={list} fallback={breakdown} scrollTitle={scrollTitle} />
            ) : (
                <ViewsReauthState access={list.access} />
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

function ListBody({
    list,
    fallback,
    scrollTitle,
}: {
    list: ReturnType<typeof useWebBreakdownList>
    fallback: WebBreakdown | null
    scrollTitle: ReturnType<typeof useScrollTitle>
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const motion = useChartListMotion()
    const toasts = useToasts()
    const actions = useWebAnalyticsActions(toasts, fallback)
    const item = useWebItemData<WebBreakdownSnapshot>(list.data)
    const { refresh } = list
    const snapshot = item.snapshot
    const rows = snapshot?.rows ?? []
    const contentTop = topOffset(insets, SCREEN_CONTENT_TOP)
    const rangeDetail = snapshot ? resolvedRangeText(snapshot.resolvedRange, 'day') : null
    const tabLabel = BREAKDOWN_LABELS[list.breakdown]
    return (
        <>
            <ScrollView
                contentContainerStyle={[
                    styles.content,
                    { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 48) },
                ]}
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
                testID="web-list-scroll"
            >
                <ViewTitle
                    onTitleLayout={scrollTitle.onTitleLayout}
                    eyebrow="Web analytics"
                    title={list.tile.title}
                    refresh={refresh}
                    range={
                        <ViewRangeControl
                            range={list.range}
                            resolved={snapshot?.resolvedRange ?? null}
                            loading={item.held}
                            detail={rangeDetail}
                            compare={null}
                        />
                    }
                    rangeDetail={rangeDetail}
                />
                <ScrollView
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    style={styles.tabsScroll}
                    contentContainerStyle={styles.tabs}
                    accessibilityRole="tablist"
                >
                    {list.tile.tabs.map((tab) => {
                        const selected = tab === list.breakdown
                        return (
                            <Pressable44
                                key={tab}
                                onPress={() => actions.setTab(list.tile.id, tab, 'list')}
                                accessibilityRole="tab"
                                accessibilityState={{ selected }}
                                accessibilityLabel={BREAKDOWN_LABELS[tab]}
                                pressedBackground={selected ? undefined : colors.pressed}
                                style={[styles.tab, selected && styles.tabSelected]}
                                testID={`web-list-tab-${tab}`}
                            >
                                <Text style={[styles.tabText, selected && styles.tabTextSelected]}>
                                    {BREAKDOWN_LABELS[tab]}
                                </Text>
                            </Pressable44>
                        )
                    })}
                </ScrollView>
                <RefreshFailedBanner status={refresh.status} />
                <FilterChips filters={list.filters} onRemove={actions.removeFilter} onClear={actions.clearFilters} />
                <WebCard
                    title={tabLabel}
                    meta={rows.length > 0 ? `Top ${rows.length}` : null}
                    accessory={
                        snapshot && rows.length > 0 ? (
                            <BreakdownColumns secondaryLabel={snapshot.secondaryLabel} />
                        ) : null
                    }
                    state={webCardState(item, rows.length > 0)}
                    error={item.error}
                    stale={snapshot?.refreshFailed ?? false}
                    updating={item.updating}
                    loadingHeight={10 * 44}
                    testID="web-list"
                >
                    <BreakdownRows
                        rows={rows}
                        secondaryLabel={snapshot?.secondaryLabel ?? null}
                        ranked
                        isActive={(row) => rowIsActive(list.filters, row)}
                        onPressRow={(row) => {
                            if (row.filter) {
                                actions.tapRow(list.tile.id, list.breakdown, row.filter, 'list')
                            }
                        }}
                        testID="web-list"
                    />
                    {snapshot?.hasMore ? (
                        <Text style={styles.caption}>
                            Showing the top {LIST_LIMIT}. Open web analytics on the web to see the rest.
                        </Text>
                    ) : null}
                    {breakdownFilters(list.breakdown) ? null : (
                        <Text style={styles.caption}>Outbound clicks can't be used as a filter.</Text>
                    )}
                </WebCard>
            </ScrollView>
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={TOAST_BOTTOM} />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    tabsScroll: {
        marginHorizontal: -layout.inboxGutter,
        marginBottom: 14,
    },
    tabs: {
        gap: 8,
        paddingHorizontal: layout.inboxGutter,
    },
    tab: {
        height: 36,
        paddingHorizontal: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    tabSelected: {
        backgroundColor: colors.ink,
        borderColor: colors.ink,
    },
    tabText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    tabTextSelected: {
        color: colors.onInk,
    },
    caption: {
        ...type.meta,
        marginTop: 8,
        color: colors.tertiary,
    },
}))
