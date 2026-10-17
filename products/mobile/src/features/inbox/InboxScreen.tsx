import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native'

import { useBootGate } from '@/auth/bootGate'
import { track } from '@/lib/analytics'
import { useNow } from '@/lib/useNow'
import type { InboxItem } from '@/model/types'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, iconSizes, layout } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { apiErrorKind } from '../report/reportAnalytics'
import { TABS_HEADER_BOTTOM } from '../tabs/TabsHeader'
import { useTabHeader } from '../tabs/tabHeaderStore'
import type { RowAnchor } from './contextMenuPlacement'
import { useInboxItems, useSetReportRead } from './hooks'
import { InboxListFooter } from './InboxListFooter'
import { InboxRow } from './InboxRow'
import { InboxRowActions, type RowMenuTarget } from './InboxRowActions'
import { usePrefetchReports } from './usePrefetchReports'

function keyFor(item: InboxItem): string {
    return item.id
}

export function InboxScreen(): ReactElement {
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
    const query = useInboxItems({ refreshWhileVisible: focused })
    const prefetch = usePrefetchReports(query.data)
    const [rowMenu, setRowMenu] = useState<RowMenuTarget | null>(null)
    const listRef = useRef<FlatList<InboxItem>>(null)

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
    const refresh = (trigger: 'pull' | 'button' | 'retry'): void => {
        track('mobile_inbox_refreshed', { trigger })
        void query.refetch()
    }
    // A refresh keeps only the first page, so the header button also brings the list back to the top.
    const refreshFromHeader = (): void => {
        listRef.current?.scrollToOffset({ offset: 0, animated: true })
        refresh('button')
    }

    const listFailed = query.isError
    const isEmpty = !query.isLoading && !query.isError && (query.data?.length ?? 0) === 0
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
    useTabHeader('inbox', {
        refresh: { state: query.isRefetching ? 'busy' : 'idle', onPress: refreshFromHeader },
        status: null,
        editing: null,
        editPins: null,
    })

    // The header floats over the list, so the content starts below it and the pull-to-refresh spinner shows under it.
    const contentTop = topOffset(insets, TABS_HEADER_BOTTOM)

    const renderItem = useCallback(
        ({ item }: { item: InboxItem }) => (
            <InboxRow item={item} now={now} onOpen={openReport} onLongPress={openRowMenu} onSetRead={setRead} />
        ),
        [now, openReport, openRowMenu, setRead]
    )

    const empty = query.isLoading ? (
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
    ) : (
        <StateView
            icon={<InboxIcon size={iconSizes.empty} color={colors.tertiary} />}
            title="Nothing needs you right now"
            message="New reports show up here when PostHog finds something worth a look."
            testID="inbox-empty"
        />
    )

    return (
        <View style={styles.screen} testID="inbox-screen">
            <FlatList
                ref={listRef}
                data={query.data ?? []}
                keyExtractor={keyFor}
                renderItem={renderItem}
                ListEmptyComponent={empty}
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
                    { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 120) },
                ]}
                refreshControl={
                    <RefreshControl
                        refreshing={query.isRefetching}
                        onRefresh={() => refresh('pull')}
                        tintColor={colors.tertiary}
                        progressViewOffset={contentTop}
                    />
                }
            />
            <InboxRowActions target={rowMenu} onClose={() => setRowMenu(null)} />
        </View>
    )
}

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.inboxGutter,
    },
})
