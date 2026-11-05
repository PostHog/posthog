import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { FlatList, RefreshControl, Text, View } from 'react-native'
import { track } from '@/lib/analytics'
import { useNow } from '@/lib/useNow'
import type { InboxItem } from '@/model/types'
import { AnimatedLogomark } from '@/ui/icons/AnimatedLogomark'
import { FilterIcon } from '@/ui/icons/FilterIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { LoadingView, StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'
import type { RowAnchor } from './contextMenuPlacement'
import { isDefaultInboxFilters } from './filters'
import { useInboxItems, useSetReportRead } from './hooks'
import { InboxFilterSheet } from './InboxFilterSheet'
import { InboxListFooter } from './InboxListFooter'
import { InboxRow } from './InboxRow'
import { InboxRowActions, type RowMenuTarget } from './InboxRowActions'
import { inboxFilterActions } from './inboxFilterActions'
import { useInboxFilters } from './inboxFiltersStore'
import { usePrefetchReports } from './usePrefetchReports'

export function ReportInbox({ selectedReportId, active }: { selectedReportId: string; active: boolean }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const insets = useScreenInsets()
    const router = useRouter()
    const now = useNow()
    const filters = useInboxFilters()
    const query = useInboxItems({ filters, refreshWhileVisible: active })
    const prefetch = usePrefetchReports(query.data, active)
    const setRead = useSetReportRead()
    const filterActions = inboxFilterActions(filters)
    const [filtersOpen, setFiltersOpen] = useState(false)
    const listRef = useRef<FlatList<InboxItem>>(null)
    const revealed = useRef(false)
    const revealFailed = useRef(false)
    const revealFrame = useRef<number | null>(null)
    const revealSelected = useCallback((): void => {
        if (!active || revealed.current || !query.data || !listRef.current) return
        const index = query.data.findIndex((item) => item.reportId === selectedReportId)
        if (index < 0) return
        revealFailed.current = false
        if (index > 0) listRef.current.scrollToIndex({ index, animated: false, viewPosition: 0.4 })
        revealed.current = !revealFailed.current
    }, [active, query.data, selectedReportId])
    const cancelRevealFrame = useCallback((): void => {
        if (revealFrame.current !== null) {
            cancelAnimationFrame(revealFrame.current)
            revealFrame.current = null
        }
    }, [])
    const scheduleReveal = useCallback((): void => {
        if (!active || revealed.current || revealFrame.current !== null) return
        revealFrame.current = requestAnimationFrame(() => {
            revealFrame.current = requestAnimationFrame(() => {
                revealFrame.current = null
                revealSelected()
            })
        })
    }, [active, revealSelected])
    useEffect(() => {
        revealSelected()
        return cancelRevealFrame
    }, [revealSelected, cancelRevealFrame])
    const [menu, setMenu] = useState<RowMenuTarget | null>(null)
    const open = useCallback((id: string): void => router.setParams({ id, from: 'inbox' }), [router])
    const onMenu = useCallback((item: InboxItem, anchor: RowAnchor): void => setMenu({ item, anchor }), [])
    const onRead = useCallback(
        (id: string, read: boolean): void => {
            setRead(id, read).catch(() => undefined)
        },
        [setRead]
    )
    return (
        <View style={styles.pane} testID="report-inbox">
            <View style={[styles.header, { paddingTop: insets.top + 16 }]}>
                <AnimatedLogomark height={18} animate={query.isRefetching} />
                <View style={{ flex: 1 }}>
                    <Text style={styles.title} accessibilityRole="header">
                        Inbox
                    </Text>
                    {!isDefaultInboxFilters(filters) ? (
                        <Text style={{ color: colors.secondary }}>Filters on</Text>
                    ) : null}
                </View>
                <Pressable44
                    accessibilityLabel="Filter and sort"
                    testID="report-inbox-filter"
                    onPress={() => {
                        track('mobile_inbox_filters_opened')
                        setFiltersOpen(true)
                    }}
                    style={{ padding: 10 }}
                >
                    <FilterIcon size={22} />
                </Pressable44>
            </View>
            <FlatList
                ref={listRef}
                onScrollBeginDrag={() => {
                    revealed.current = true
                    cancelRevealFrame()
                }}
                onScrollToIndexFailed={({ averageItemLength, index }) => {
                    revealFailed.current = true
                    listRef.current?.scrollToOffset({ offset: averageItemLength * index, animated: false })
                }}
                onContentSizeChange={scheduleReveal}
                onLayout={scheduleReveal}
                data={query.data ?? []}
                onViewableItemsChanged={prefetch.onViewableItemsChanged}
                viewabilityConfig={prefetch.viewabilityConfig}
                keyExtractor={(item) => item.id}
                renderItem={({ item }) => (
                    <View style={item.reportId === selectedReportId && styles.selected} onLayout={scheduleReveal}>
                        <InboxRow
                            titleLines={3}
                            item={item}
                            now={now}
                            onOpen={open}
                            onLongPress={onMenu}
                            onSetRead={onRead}
                        />
                    </View>
                )}
                ListEmptyComponent={
                    query.isLoading || query.isRefetching ? (
                        <LoadingView label="Loading your inbox" />
                    ) : query.isError ? (
                        <StateView
                            title="Couldn't load your inbox"
                            actionLabel="Try again"
                            onAction={() => void query.refetch()}
                        />
                    ) : (
                        <StateView
                            title="No reports match this inbox"
                            message="Change your filters to see more reports."
                        />
                    )
                }
                ListFooterComponent={
                    <InboxListFooter
                        isLoadingMore={query.isLoadingMore}
                        loadMoreFailed={query.loadMoreFailed}
                        onRetry={query.retryLoadMore}
                    />
                }
                onEndReached={query.loadMore}
                onEndReachedThreshold={0.5}
                refreshControl={
                    <RefreshControl
                        refreshing={query.isRefetching}
                        onRefresh={() => void query.refetch()}
                        tintColor={colors.tertiary}
                    />
                }
                contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 20 }]}
            />
            <InboxFilterSheet
                visible={filtersOpen}
                onClose={() => setFiltersOpen(false)}
                filters={filters}
                items={query.unfiltered ?? []}
                onSortChange={filterActions.setSort}
                onCreatedWindowChange={filterActions.setCreatedWindow}
                onToggleSource={filterActions.toggleSource}
                onClear={filterActions.clearFilters}
            />
            <InboxRowActions target={menu} onClose={() => setMenu(null)} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    pane: { flex: 1, borderRightWidth: 1, borderRightColor: colors.border, backgroundColor: colors.background },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: layout.inboxGutter,
        paddingBottom: 20,
    },
    title: { ...type.screenTitle, color: colors.ink },
    content: { paddingHorizontal: 8, flexGrow: 1 },
    selected: { backgroundColor: colors.sunken, borderRadius: 12 },
}))
