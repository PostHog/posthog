import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useState } from 'react'
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useViewer } from '@/auth/useViewer'
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
import { useInboxItems } from './hooks'
import { InboxHeader } from './InboxHeader'
import { InboxRow } from './InboxRow'
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
    const exitDemo = useExitDemo()
    const signOut = useSignOutAction()
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmingSignOut, setConfirmingSignOut] = useState(false)

    useEffect(() => {
        track('mobile_inbox_opened')
    }, [])

    const openReport = useCallback((reportId: string) => router.push(`/report/${reportId}`), [router])
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
    const startSignOut = (): void => {
        if (signedIn) {
            setConfirmingSignOut(true)
            return
        }
        setMenuOpen(false)
        exitDemo()
    }

    const renderItem = useCallback(
        ({ item }: { item: InboxItem }) => <InboxRow item={item} now={now} onOpen={openReport} />,
        [now, openReport]
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
                ListHeaderComponent={
                    <View style={styles.header}>
                        <InboxHeader
                            onRefresh={refresh}
                            refreshing={query.isRefetching}
                            onOpenMenu={() => setMenuOpen(true)}
                        />
                    </View>
                }
                ListEmptyComponent={empty}
                contentContainerStyle={[
                    styles.content,
                    { paddingTop: topOffset(insets, 64), paddingBottom: bottomOffset(insets, 120) },
                ]}
                refreshControl={
                    <RefreshControl refreshing={query.isRefetching} onRefresh={refresh} tintColor={colors.tertiary} />
                }
            />
            <BottomBar onChat={() => router.push('/chat')} />
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
    header: {
        marginBottom: 12,
    },
})
