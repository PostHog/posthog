import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { FlatList, RefreshControl, View } from 'react-native'
import { useBootGate } from '@/auth/bootGate'
import { track } from '@/lib/analytics'
import { useNow } from '@/lib/useNow'
import type { InboxItem } from '@/model/types'
import { FilterIcon } from '@/ui/icons/FilterIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout } from '@/ui/tokens'
import { useAppLayout } from '@/ui/useAppLayout'
import { tabBottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { apiErrorKind } from '../report/reportAnalytics'
import { TABS_HEADER_BOTTOM } from '../tabs/TabsHeader'
import { useTabHeader } from '../tabs/tabHeaderStore'
import { useFeatureAccess } from '../views/useViewsAccess'
import { ViewsReauthState } from '../views/ViewsReauthState'
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

function keyFor(item: InboxItem): string {
    return item.id
}

export function InboxScreen(): ReactElement {
    const styles = useStyles()
    const { paired, inboxExtent, paneAxis, paneGap } = useAppLayout()
    const colors = useColors()
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const [focused, setFocused] = useState(false)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )
    const filters = useInboxFilters()
    const access = useFeatureAccess('inbox')
    const query = useInboxItems({ refreshWhileVisible: focused, filters })
    const prefetch = usePrefetchReports(query.data, focused && access.state === 'ok')
    const [rowMenu, setRowMenu] = useState<RowMenuTarget | null>(null)
    const [filtersOpen, setFiltersOpen] = useState(false)
    const listRef = useRef<FlatList<InboxItem>>(null)
    // A new order starts from its first row, as the old list position would land somewhere arbitrary in it.
    const sort = filters.sort
    // biome-ignore lint/correctness/useExhaustiveDependencies: runs once per sort change, not on every render.
    useEffect(() => {
        listRef.current?.scrollToOffset({ offset: 0, animated: false })
    }, [sort])

    // The native splash waits for this, so release it only after the loaded list has had a frame to paint.
    useEffect(() => {
        if (query.isLoading) {
            return
        }
        const frame = requestAnimationFrame(() => useBootGate.getState().markFirstScreenReady())
        return () => cancelAnimationFrame(frame)
    }, [query.isLoading])

    const openReport = useCallback(
        (reportId: string) => router.push({ pathname: '/report/[id]', params: { id: reportId, from: 'inbox' } }),
        [router]
    )
    const openRowMenu = useCallback((item: InboxItem, anchor: RowAnchor) => setRowMenu({ item, anchor }), [])
    const setReportRead = useSetReportRead()
    // The row changes at once; a failed post reloads the read states, so the row flips back without a message.
    const setRead = useCallback(
        (reportId: string, read: boolean) => {
            setReportRead(reportId, read).catch(() => undefined)
        },
        [setReportRead]
    )
    const refresh = (trigger: 'pull' | 'retry'): void => {
        track('mobile_inbox_refreshed', { trigger })
        void query.refetch()
    }

    const openFilters = (): void => {
        track('mobile_inbox_filters_opened')
        setFiltersOpen(true)
    }
    const { setSort, setCreatedWindow, toggleSource, clearFilters } = inboxFilterActions(filters)

    const listFailed = query.isError
    const loaded = !query.isLoading && !query.isError
    const isEmpty = loaded && query.totalCount === 0
    // While the remaining pages load, a match may still arrive, so the footer spinner shows instead of this screen.
    const isFilteredEmpty = loaded && query.totalCount > 0 && query.matchedCount === 0 && !query.isLoadingMore
    // biome-ignore lint/correctness/useExhaustiveDependencies: one event each time the error screen appears.
    useEffect(() => {
        if (listFailed) {
            track('mobile_inbox_error_shown', { kind: apiErrorKind(query.error), during: 'load' })
        }
    }, [listFailed])
    // The paging state keeps no error object, so a next-page failure has no `kind`.
    const loadMoreFailed = query.loadMoreFailed
    useEffect(() => {
        if (loadMoreFailed) {
            track('mobile_inbox_error_shown', { during: 'next_page' })
        }
    }, [loadMoreFailed])
    useEffect(() => {
        if (isEmpty) {
            track('mobile_inbox_empty_shown')
        }
    }, [isEmpty])
    useEffect(() => {
        if (isFilteredEmpty) {
            track('mobile_inbox_filtered_empty_shown')
        }
    }, [isFilteredEmpty])
    useTabHeader('inbox', {
        refreshing: query.isRefetching,
        hint: null,
        status: null,
        editing: null,
        editPins: null,
        filter: { active: !isDefaultInboxFilters(filters), onPress: openFilters },
    })

    // The header floats over the list, so the content starts below it and the pull-to-refresh spinner shows under it.
    const contentTop = topOffset(insets, TABS_HEADER_BOTTOM)

    const renderItem = useCallback(
        ({ item }: { item: InboxItem }) => (
            <InboxRow
                titleLines={paired ? 3 : 1}
                item={item}
                now={now}
                onOpen={openReport}
                onLongPress={openRowMenu}
                onSetRead={setRead}
            />
        ),
        [paired, now, openReport, openRowMenu, setRead]
    )

    const empty =
        access.state !== 'ok' ? (
            <ViewsReauthState access={access} feature="inbox" />
        ) : query.isLoading ? (
            <LoadingView label="Loading your inbox" />
        ) : query.isError ? (
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Couldn't load your inbox"
                message={query.error?.message ?? 'Check your connection and try again.'}
                actionLabel="Try again"
                onAction={() => refresh('retry')}
                testID="inbox-error"
            />
        ) : isFilteredEmpty ? (
            <StateView
                icon={<FilterIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="No reports match these filters"
                actionLabel="Clear filters"
                onAction={clearFilters}
                testID="inbox-filtered-empty"
            />
        ) : query.totalCount > 0 ? null : (
            <StateView
                icon={<InboxIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Nothing needs you right now"
                message="New reports show up here when PostHog finds something worth a look."
                testID="inbox-empty"
            />
        )

    return (
        <View style={[styles.screen, { flexDirection: paneAxis, gap: paired ? paneGap : 0 }]} testID="inbox-screen">
            <View
                style={{
                    flexGrow: paired ? 0 : 1,
                    flexShrink: paired ? 0 : 1,
                    ...(paired ? (paneAxis === 'row' ? { width: inboxExtent } : { height: inboxExtent }) : {}),
                    minWidth: 0,
                }}
            >
                <FlatList
                    ref={listRef}
                    data={access.state === 'ok' ? (query.data ?? []) : []}
                    keyExtractor={keyFor}
                    renderItem={renderItem}
                    ListEmptyComponent={empty ?? undefined}
                    ListFooterComponent={
                        <InboxListFooter
                            isLoadingMore={query.isLoadingMore}
                            loadMoreFailed={query.loadMoreFailed}
                            onRetry={query.retryLoadMore}
                        />
                    }
                    onEndReached={query.loadMore}
                    onEndReachedThreshold={0.5}
                    onViewableItemsChanged={prefetch.onViewableItemsChanged}
                    viewabilityConfig={prefetch.viewabilityConfig}
                    contentContainerStyle={[
                        styles.content,
                        { paddingTop: contentTop, paddingBottom: tabBottomOffset(insets) },
                    ]}
                    refreshControl={
                        <RefreshControl
                            refreshing={query.isRefetching}
                            onRefresh={() => refresh('pull')}
                            tintColor={colors.tertiary}
                            colors={[colors.tertiary]}
                            progressBackgroundColor={colors.surface}
                            progressViewOffset={contentTop}
                        />
                    }
                />
            </View>
            {paired ? (
                <View style={{ flex: 1, borderLeftWidth: 1, borderLeftColor: colors.border }}>
                    <StateView
                        title="Choose a report"
                        message="Open a report from your inbox to investigate it here."
                        testID="inbox-detail-placeholder"
                    />
                </View>
            ) : null}
            <InboxRowActions target={rowMenu} onClose={() => setRowMenu(null)} />
            <InboxFilterSheet
                visible={filtersOpen}
                onClose={() => setFiltersOpen(false)}
                filters={filters}
                items={query.unfiltered ?? []}
                onSortChange={setSort}
                onCreatedWindowChange={setCreatedWindow}
                onToggleSource={toggleSource}
                onClear={clearFilters}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.inboxGutter,
    },
}))
