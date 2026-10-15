import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useBootGate } from '@/auth/bootGate'
import { useViewer } from '@/auth/useViewer'
import { useNow } from '@/lib/useNow'
import type { InboxItem } from '@/model/types'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, iconSizes, layout } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { useExitDemo, useSignOutAction } from '../settings/useSignOut'
import type { RowAnchor } from './contextMenuPlacement'
import { useInboxItems, useSetReportRead } from './hooks'
import { INBOX_HEADER_BOTTOM, InboxHeader } from './InboxHeader'
import { InboxListFooter } from './InboxListFooter'
import { InboxRow } from './InboxRow'
import { InboxRowActions, type RowMenuTarget } from './InboxRowActions'
import { NavMenu } from './NavMenu'
import { usePrefetchReports } from './usePrefetchReports'

function keyFor(item: InboxItem): string {
    return item.id
}

export function InboxScreen(): ReactElement {
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const viewer = useViewer()
    const [focused, setFocused] = useState(false)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )
    const query = useInboxItems({ refreshWhileVisible: focused })
    const prefetch = usePrefetchReports(query.data)
    const signedIn = useAuthStore((state) => state.signedIn)
    const exitDemo = useExitDemo()
    const signOut = useSignOutAction()
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmingSignOut, setConfirmingSignOut] = useState(false)
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

    const openReport = useCallback((reportId: string) => router.push(`/report/${reportId}`), [router])
    const openRowMenu = useCallback((item: InboxItem, anchor: RowAnchor) => setRowMenu({ item, anchor }), [])
    const setReportRead = useSetReportRead()
    // The row changes at once; a failed post reloads the read states, so the row flips back without a message.
    const setRead = useCallback(
        (reportId: string, read: boolean) => {
            setReportRead(reportId, read).catch(() => undefined)
        },
        [setReportRead]
    )
    const refresh = (): void => {
        void query.refetch()
    }
    // A refresh keeps only the first page, so the header button also brings the list back to the top.
    const refreshFromHeader = (): void => {
        listRef.current?.scrollToOffset({ offset: 0, animated: true })
        refresh()
    }
    const closeMenu = (): void => {
        if (signOut.pending) {
            return
        }
        setMenuOpen(false)
        setConfirmingSignOut(false)
    }
    const startSignOut = (): void => {
        if (signedIn) {
            setConfirmingSignOut(true)
            return
        }
        setMenuOpen(false)
        exitDemo()
    }

    // The header floats over the list, so the content starts below it and the pull-to-refresh spinner shows under it.
    const contentTop = topOffset(insets, INBOX_HEADER_BOTTOM)

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
            onAction={refresh}
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
                        onRefresh={refresh}
                        tintColor={colors.tertiary}
                        progressViewOffset={contentTop}
                    />
                }
            />
            <InboxHeader
                onRefresh={refreshFromHeader}
                refreshing={query.isRefetching}
                onOpenMenu={() => setMenuOpen(true)}
            />
            <NavMenu
                visible={menuOpen}
                unreadCount={(query.data ?? []).filter((item) => !item.read).length}
                projectName={viewer.projectName}
                onClose={closeMenu}
                onSettings={() => {
                    setMenuOpen(false)
                    router.push('/settings')
                }}
                onSignOut={startSignOut}
                confirmingSignOut={confirmingSignOut}
                signOutPending={signOut.pending}
                onCancelSignOut={() => setConfirmingSignOut(false)}
                onConfirmSignOut={() => void signOut.run()}
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
