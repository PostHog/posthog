import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useState } from 'react'
import { FlatList, Linking, RefreshControl, StyleSheet, View } from 'react-native'

import { projectWebUrl } from '@/api/client'
import { useAuthStore } from '@/auth/authStore'
import { useBootGate } from '@/auth/bootGate'
import { useViewer } from '@/auth/useViewer'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { useNow } from '@/lib/useNow'
import type { InboxItem } from '@/model/types'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, layout } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { useExitDemo, useSignOutAction } from '../settings/useSignOut'
import { BottomBar } from './BottomBar'
import type { RowAnchor } from './contextMenuPlacement'
import { useInboxItems } from './hooks'
import { INBOX_HEADER_BOTTOM, InboxHeader } from './InboxHeader'
import { InboxRow } from './InboxRow'
import { InboxRowActions, type RowMenuTarget } from './InboxRowActions'
import { NavMenu } from './NavMenu'

function keyFor(item: InboxItem): string {
    return item.id
}

export function InboxScreen(): ReactElement {
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const viewer = useViewer()
    const query = useInboxItems()
    const signedIn = useAuthStore((state) => state.signedIn)
    const demo = useDemoMode((state) => state.enabled)
    const exitDemo = useExitDemo()
    const signOut = useSignOutAction()
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmingSignOut, setConfirmingSignOut] = useState(false)
    const [rowMenu, setRowMenu] = useState<RowMenuTarget | null>(null)

    useEffect(() => {
        track('mobile_inbox_opened')
    }, [])

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
    const refresh = (): void => {
        void query.refetch()
    }
    const closeMenu = (): void => {
        if (signOut.pending) {
            return
        }
        setMenuOpen(false)
        setConfirmingSignOut(false)
    }
    // The app has no product screens, so Products opens the web app's product library for this project.
    const openProducts = (): void => {
        const url = projectWebUrl('library')
        if (!url) {
            return
        }
        track('mobile_products_opened')
        Linking.openURL(url).catch(() => undefined)
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
            <InboxRow item={item} now={now} onOpen={openReport} onLongPress={openRowMenu} />
        ),
        [now, openReport, openRowMenu]
    )

    const empty = query.isLoading ? (
        <LoadingView label="Loading your inbox" />
    ) : query.isError ? (
        <StateView
            icon={<WarningIcon size={28} color={colors.tertiary} />}
            title="Couldn't load your inbox"
            message={query.error?.message ?? 'Check your connection and try again.'}
            actionLabel="Try again"
            onAction={refresh}
            testID="inbox-error"
        />
    ) : (
        <StateView
            icon={<InboxIcon size={28} color={colors.tertiary} />}
            title="Nothing needs you right now"
            message="New reports show up here when PostHog finds something worth a look."
            testID="inbox-empty"
        />
    )

    return (
        <View style={styles.screen} testID="inbox-screen">
            <FlatList
                data={query.data ?? []}
                keyExtractor={keyFor}
                renderItem={renderItem}
                ListEmptyComponent={empty}
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
            <InboxHeader onRefresh={refresh} refreshing={query.isRefetching} onOpenMenu={() => setMenuOpen(true)} />
            <BottomBar onChat={() => router.push('/chat')} onProducts={openProducts} productsDisabled={demo} />
            <NavMenu
                visible={menuOpen}
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
