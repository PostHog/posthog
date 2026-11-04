import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useState } from 'react'
import { FlatList, Linking, RefreshControl, Text, View } from 'react-native'
import { changeNavPin } from '@/features/tabs/navPinActions'
import { useIsNavPinned } from '@/features/tabs/navPinStore'
import { TABS_HEADER_BOTTOM } from '@/features/tabs/TabsHeader'
import { useTabHeader } from '@/features/tabs/tabHeaderStore'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { ViewChrome } from '@/features/views/screen/ViewChrome'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { navListWebUrl } from '@/features/views/webLinks'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { ListPaginationFooter } from '@/ui/ListPaginationFooter'
import { OverlayHost } from '@/ui/OverlayPortal'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'

import { useReplayContext, useSessionList } from './hooks'
import {
    trackReplayErrorShown,
    trackReplayListOpened,
    trackReplayOpenedInWeb,
    trackReplayRefreshed,
} from './replayAnalytics'
import type { SessionListRow as Row } from './replayModel'
import { SessionListRow } from './SessionListRow'
import { SessionRowSkeleton } from './SessionSkeleton'

/** The bottom bar's design inset on a tab; a pushed screen has none. */
const TAB_BOTTOM = 120
const STACK_BOTTOM = 40
const STACK_TOAST_BOTTOM = 48

function keyOf(row: Row): string {
    return row.sessionId
}

export function ReplayListScreen({ chrome }: { chrome: 'tab' | 'stack' }): ReactElement {
    const styles = useStyles()
    const content = (
        <View style={styles.screen} testID={`replay-screen-${chrome}`}>
            <ReplayListBody chrome={chrome} />
        </View>
    )
    // A tab already sits under the tabs layout's overlay host.
    return chrome === 'stack' ? <OverlayHost>{content}</OverlayHost> : content
}

function ReplayListBody({ chrome }: { chrome: 'tab' | 'stack' }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const scrollTitle = useScrollTitle('Sessions')
    const back = useViewBack()
    const now = useNow()
    const toasts = useToasts()
    const pinned = useIsNavPinned('replay')
    const { mode, scope, access } = useReplayContext()
    const list = useSessionList()
    const [menuOpen, setMenuOpen] = useState(false)

    useFocusEffect(
        useCallback(() => {
            trackReplayListOpened(chrome)
        }, [chrome])
    )
    const failed = list.rows.isError
    useEffect(() => {
        if (failed) {
            trackReplayErrorShown('list')
        }
    }, [failed])

    const rows = list.rows.data
    const status = mode !== 'live' || access.state !== 'ok' || !rows ? null : 'Newest first · last 7 days'
    const openSession = useCallback(
        (row: Row) =>
            router.push({
                pathname: '/replay/[sessionId]',
                params: {
                    sessionId: row.sessionId,
                    source: 'list',
                    ...(row.keyMomentMs !== null ? { t: String(Math.floor(row.keyMomentMs / 1000)) } : {}),
                },
            }),
        [router]
    )
    const refresh = (): void => {
        trackReplayRefreshed(rows?.length ?? 0)
        void list.refresh()
    }
    const webUrl = navListWebUrl(scope, 'replay')
    const safeWebUrl = webUrl ? safeHttpsUrl(webUrl) : undefined

    const contentTop = topOffset(insets, chrome === 'tab' ? TABS_HEADER_BOTTOM : SCREEN_CONTENT_TOP)
    const contentBottom = bottomOffset(insets, chrome === 'tab' ? TAB_BOTTOM : STACK_BOTTOM)
    const header =
        chrome === 'stack' ? (
            <View style={styles.titleBlock}>
                <Text style={styles.title} accessibilityRole="header" onLayout={scrollTitle.onTitleLayout}>
                    Sessions
                </Text>
                {status ? <Text style={styles.status}>{status}</Text> : null}
            </View>
        ) : null

    let body: ReactElement
    if (mode === 'demo') {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>{header}</View>
                <StateView
                    icon={<RecordingIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Sessions aren't in the demo"
                    message="Sign in to see your project's recordings."
                    testID="replay-demo"
                />
            </View>
        )
    } else if (access.state !== 'ok') {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop, paddingBottom: contentBottom }]}>
                <View style={styles.content}>{header}</View>
                <ViewsReauthState access={access} feature="replay" />
            </View>
        )
    } else if (failed) {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>{header}</View>
                <StateView
                    icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Couldn't load your sessions"
                    message="Check your connection and try again."
                    actionLabel="Try again"
                    onAction={() => void list.rows.refetch()}
                    testID="replay-error"
                />
            </View>
        )
    } else if (!rows) {
        body = (
            <View style={[styles.fill, styles.content, { paddingTop: contentTop }]}>
                {header}
                <View
                    accessibilityLabel="Loading your sessions"
                    accessibilityRole="progressbar"
                    testID="replay-loading"
                >
                    {[0, 1, 2, 3, 4, 5].map((index) => (
                        <SessionRowSkeleton key={index} />
                    ))}
                </View>
            </View>
        )
    } else {
        body = (
            <FlatList
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                data={rows}
                keyExtractor={keyOf}
                renderItem={({ item }) => <SessionListRow row={item} now={now} onOpen={openSession} />}
                ListHeaderComponent={header}
                ListFooterComponent={
                    <>
                        <ListPaginationFooter
                            noun="sessions"
                            hasMore={list.hasMore}
                            loading={list.isLoadingMore}
                            failed={list.loadMoreFailed}
                            onLoadMore={list.loadMore}
                        />
                        {list.recommendations.length > 0 ? (
                            <View>
                                <Text style={styles.recommendationsTitle} accessibilityRole="header">
                                    Worth watching
                                </Text>
                                {list.recommendations.map((row) => (
                                    <SessionListRow key={row.sessionId} row={row} now={now} onOpen={openSession} />
                                ))}
                            </View>
                        ) : null}
                    </>
                }
                ListEmptyComponent={
                    list.recommendations.length > 0 ? null : (
                        <StateView
                            icon={<RecordingIcon size={iconSizes.empty} color={colors.tertiary} />}
                            title="No recordings yet"
                            message="Sessions show up here once your site or app records them with session replay turned on."
                            testID="replay-empty"
                        />
                    )
                }
                contentContainerStyle={[styles.content, { paddingTop: contentTop, paddingBottom: contentBottom }]}
                refreshControl={
                    <RefreshControl
                        refreshing={list.refreshing}
                        onRefresh={refresh}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={contentTop}
                    />
                }
                testID="replay-list"
            />
        )
    }

    return (
        <View style={styles.fill}>
            {chrome === 'tab' ? <TabHeaderPublisher status={status} /> : null}
            {body}
            {chrome === 'stack' ? (
                <>
                    <ViewChrome title={scrollTitle.title} onBack={back} onMore={() => setMenuOpen(true)} />
                    <HeaderMenu
                        visible={menuOpen}
                        onClose={() => setMenuOpen(false)}
                        testID="replay-menu"
                        items={[
                            {
                                key: pinned ? 'unpin' : 'pin',
                                label: pinned ? 'Unpin from navigation' : 'Pin to navigation',
                                Icon: PinIcon,
                                onPress: () => changeNavPin('replay', !pinned, 'list_menu', toasts.show),
                            },
                            {
                                key: 'web',
                                label: 'Open on web',
                                Icon: ExternalLinkIcon,
                                disabled: !webUrl,
                                meta: webUrl ? null : 'Not in the demo',
                                onPress: () => {
                                    if (safeWebUrl) {
                                        trackReplayOpenedInWeb('list')
                                        Linking.openURL(safeWebUrl).catch(() => undefined)
                                    }
                                },
                            },
                        ]}
                    />
                </>
            ) : null}
            <ViewsToast
                toast={toasts.toast}
                onHide={toasts.hide}
                bottom={chrome === 'tab' ? undefined : STACK_TOAST_BOTTOM}
            />
        </View>
    )
}

/**
 * The pinned tab's status line in the shared tabs header. Its own component, so a pushed Sessions screen never writes
 * the tab's header slot, and never clears it when it closes.
 */
function TabHeaderPublisher({ status }: { status: string | null }): null {
    useTabHeader('replay', { hint: null, status, editing: null, editPins: null, filter: null })
    return null
}

const useStyles = createStyles(({ colors }) => ({
    recommendationsTitle: {
        ...type.rowTitle,
        color: colors.ink,
        paddingTop: 20,
        paddingBottom: 8,
    },
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    fill: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
    },
    titleBlock: {
        marginBottom: 8,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
    },
    status: {
        ...type.metaSmall,
        color: colors.secondary,
        marginTop: 4,
    },
}))
