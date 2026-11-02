import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FlatList, Linking, RefreshControl, Text, View } from 'react-native'
import type { ErrorsWindow } from '@/api/errorTracking'
import { useViewer } from '@/auth/useViewer'
import { changeNavPin } from '@/features/tabs/navPinActions'
import { useIsNavPinned } from '@/features/tabs/navPinStore'
import { TABS_HEADER_BOTTOM } from '@/features/tabs/TabsHeader'
import { useTabHeader } from '@/features/tabs/tabHeaderStore'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { ViewChrome } from '@/features/views/screen/ViewChrome'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { useFeatureAccess } from '@/features/views/useViewsAccess'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { navListWebUrl } from '@/features/views/webLinks'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import { CheckCircleIcon } from '@/ui/icons/CheckCircleIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { ListPaginationFooter } from '@/ui/ListPaginationFooter'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'
import {
    type ErrorsChrome,
    trackErrorsErrorShown,
    trackErrorsFilterChanged,
    trackErrorsOpened,
    trackErrorsOpenedInWeb,
    trackErrorsWindowChanged,
} from './analytics'
import { useErrorsContext, useIssuesList } from './hooks'
import { IssueListRow } from './IssueListRow'
import { agoPhrase, emptyCopy, filterRows, type IssueFilter, type IssueRow } from './issueModel'

const WINDOWS: readonly ErrorsWindow[] = ['24h', '7d']
const FILTERS: readonly { key: Exclude<IssueFilter, 'all'>; label: string }[] = [
    { key: 'new', label: 'New' },
    { key: 'spiking', label: 'Spiking' },
    { key: 'mine', label: 'Mine' },
]
/** The bottom bar's design inset on a tab; a pushed screen has none. */
const TAB_BOTTOM = 120
const STACK_BOTTOM = 40
const STACK_TOAST_BOTTOM = 48

function keyOf(row: IssueRow): string {
    return row.id
}

export function ErrorsListScreen({ chrome }: { chrome: 'tab' | 'stack' }): ReactElement {
    const styles = useStyles()
    const content = (
        <View style={styles.screen} testID={`errors-screen-${chrome}`}>
            <ErrorsListBody chrome={chrome} />
        </View>
    )
    // A tab already sits under the tabs layout's overlay host.
    return chrome === 'stack' ? <OverlayHost>{content}</OverlayHost> : content
}

function ErrorsListBody({ chrome }: { chrome: ErrorsChrome }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const scrollTitle = useScrollTitle('Errors')
    const access = useFeatureAccess('errors')
    const context = useErrorsContext()
    const viewer = useViewer()
    const now = useNow()
    const toasts = useToasts()
    const pinned = useIsNavPinned('errors')
    const [window, setWindow] = useState<ErrorsWindow>('24h')
    const [filter, setFilter] = useState<IssueFilter>('all')
    const [menuOpen, setMenuOpen] = useState(false)
    const list = useIssuesList(window, filter)

    // Only a new visit counts, not a window change while the screen is open.
    const windowRef = useRef(window)
    windowRef.current = window
    useFocusEffect(
        useCallback(() => {
            trackErrorsOpened({ chrome, window: windowRef.current })
        }, [chrome])
    )

    const rows = useMemo(() => (list.data ? filterRows(list.data, filter) : undefined), [list.data, filter])
    const failed = list.isError && !list.data
    useEffect(() => {
        if (failed) {
            trackErrorsErrorShown({ kind: 'list_failed' })
        }
    }, [failed])

    const updated = list.updatedAt ? agoPhrase(new Date(list.updatedAt).toISOString(), now) : null
    const status =
        context.mode !== 'live' || access.state !== 'ok'
            ? null
            : list.isLoading
              ? 'Loading…'
              : `Most users first${updated ? ` · updated ${updated}` : ''}`

    const webUrl = navListWebUrl(context.scope, 'errors')
    const goBack = useViewBack()
    const openIssue = useCallback(
        (row: IssueRow) => router.push({ pathname: '/errors/[id]', params: { id: row.id, from: 'list', window } }),
        [router, window]
    )
    const changeWindow = (next: ErrorsWindow): void => {
        if (next !== window) {
            setWindow(next)
            trackErrorsWindowChanged({ window: next })
        }
    }
    const changeFilter = (next: IssueFilter): void => {
        const value = next === filter ? 'all' : next
        setFilter(value)
        trackErrorsFilterChanged({ filter: value })
    }

    const contentTop = topOffset(insets, chrome === 'tab' ? TABS_HEADER_BOTTOM : SCREEN_CONTENT_TOP)
    const contentBottom = bottomOffset(insets, chrome === 'tab' ? TAB_BOTTOM : STACK_BOTTOM)

    // A pushed screen draws its own title; on a tab the shared tabs header draws it.
    const stackTitle =
        chrome === 'stack' ? (
            <View style={styles.titleBlock}>
                <Text style={styles.title} accessibilityRole="header" onLayout={scrollTitle.onTitleLayout}>
                    Errors
                </Text>
                {status ? <Text style={styles.status}>{status}</Text> : null}
            </View>
        ) : null
    const header = (
        <View style={styles.header}>
            {stackTitle}
            <View style={styles.controls}>
                <SegmentedPill
                    height={40}
                    segmentWidth={52}
                    segments={WINDOWS.map((option) => ({
                        key: option,
                        accessibilityLabel: option === '24h' ? 'Last 24 hours' : 'Last 7 days',
                        accessibilityRole: 'tab',
                        selected: option === window,
                        onPress: () => changeWindow(option),
                        testID: `errors-window-${option}`,
                        children: <Text style={styles.segmentText}>{option}</Text>,
                    }))}
                />
                {FILTERS.map(({ key, label }) => {
                    const on = filter === key
                    const disabled = key === 'mine' && context.myUserId === null
                    return (
                        <Pressable44
                            key={key}
                            onPress={() => changeFilter(key)}
                            disabled={disabled}
                            accessibilityRole="togglebutton"
                            accessibilityLabel={label}
                            accessibilityState={{ checked: on, disabled }}
                            pressedBackground={on ? colors.inkHover : colors.pressed}
                            style={[styles.chip, on && styles.chipOn]}
                            testID={`errors-filter-${key}`}
                        >
                            <Text style={[styles.chipText, on && styles.chipTextOn, disabled && styles.chipTextOff]}>
                                {label}
                            </Text>
                        </Pressable44>
                    )
                })}
            </View>
        </View>
    )

    let body: ReactElement
    if (access.state !== 'ok') {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop, paddingBottom: contentBottom }]}>
                <View style={styles.content}>{stackTitle}</View>
                <ViewsReauthState access={access} feature="errors" />
            </View>
        )
    } else if (context.mode === 'demo') {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>{stackTitle}</View>
                <StateView
                    icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Errors aren't in the demo"
                    message="Sign in to see your project's error tracking issues."
                    testID="errors-demo"
                />
            </View>
        )
    } else if (failed) {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>{header}</View>
                <StateView
                    icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Couldn't load your errors"
                    message="Check your connection and try again."
                    actionLabel="Try again"
                    onAction={() => list.refetch()}
                    testID="errors-error"
                />
            </View>
        )
    } else if (!rows) {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>{header}</View>
                <ErrorsListSkeleton />
            </View>
        )
    } else {
        const empty = emptyCopy(filter, window, list)
        const onEmptyAction = (): void => {
            switch (empty.action?.kind) {
                case 'retry_spikes':
                    list.retrySpikes()
                    break
                case 'window':
                    changeWindow('7d')
                    break
                case 'clear_filter':
                    changeFilter('all')
                    break
            }
        }
        body = (
            <FlatList
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                data={rows}
                keyExtractor={keyOf}
                renderItem={({ item }) => <IssueListRow row={item} now={now} myName={viewer.name} onOpen={openIssue} />}
                ListHeaderComponent={header}
                ListFooterComponent={
                    <ListPaginationFooter
                        noun="errors"
                        hasMore={list.hasMore}
                        loading={list.isLoadingMore}
                        failed={list.loadMoreFailed}
                        onLoadMore={list.loadMore}
                    />
                }
                ListEmptyComponent={
                    <StateView
                        icon={<CheckCircleIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title={empty.title}
                        message={empty.message}
                        actionLabel={empty.action?.label}
                        onAction={empty.action ? onEmptyAction : undefined}
                        testID="errors-empty"
                    />
                }
                contentContainerStyle={[styles.content, { paddingTop: contentTop, paddingBottom: contentBottom }]}
                refreshControl={
                    <RefreshControl
                        refreshing={list.pulling}
                        onRefresh={list.onPull}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={contentTop}
                    />
                }
                testID="errors-list"
            />
        )
    }

    return (
        <View style={styles.fill}>
            {chrome === 'tab' ? <TabHeaderPublisher status={status} /> : null}
            {body}
            {chrome === 'stack' ? (
                <>
                    <ViewChrome title={scrollTitle.title} onBack={goBack} onMore={() => setMenuOpen(true)} />
                    <HeaderMenu
                        visible={menuOpen}
                        onClose={() => setMenuOpen(false)}
                        testID="errors-menu"
                        items={[
                            {
                                key: pinned ? 'unpin' : 'pin',
                                label: pinned ? 'Unpin from navigation' : 'Pin to navigation',
                                Icon: PinIcon,
                                onPress: () => changeNavPin('errors', !pinned, 'list_menu', toasts.show),
                            },
                            {
                                key: 'web',
                                label: 'Open on web',
                                Icon: ExternalLinkIcon,
                                disabled: !webUrl,
                                meta: webUrl ? null : 'Not in the demo',
                                onPress: () => {
                                    const safe = webUrl ? safeHttpsUrl(webUrl) : undefined
                                    if (safe) {
                                        trackErrorsOpenedInWeb({ screen: 'list' })
                                        Linking.openURL(safe).catch(() => undefined)
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
 * The pinned tab's status line in the shared tabs header. Its own component, so a pushed Errors screen never writes
 * the tab's header slot, and never clears it when it closes.
 */
function TabHeaderPublisher({ status }: { status: string | null }): null {
    useTabHeader('errors', { hint: null, status, editing: null, editPins: null, filter: null })
    return null
}

function ErrorsListSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View
            style={styles.skeleton}
            accessibilityLabel="Loading your errors"
            accessibilityRole="progressbar"
            testID="errors-loading"
        >
            {[0, 1, 2, 3, 4, 5].map((index) => (
                <View key={index} style={styles.skeletonRow}>
                    <View style={styles.skeletonLines}>
                        <View style={[styles.block, styles.lineLong]} />
                        <View style={[styles.block, styles.lineShort]} />
                    </View>
                    <View style={[styles.block, styles.spark]} />
                </View>
            ))}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    fill: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    header: {
        gap: 14,
        paddingBottom: 6,
    },
    titleBlock: {
        gap: 2,
        paddingHorizontal: 6,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
    },
    status: {
        ...type.meta,
        color: colors.tertiary,
    },
    controls: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 8,
    },
    segmentText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    chip: {
        height: 40,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    chipOn: {
        backgroundColor: colors.ink,
        borderColor: colors.ink,
    },
    chipText: {
        ...type.buttonSmall,
        fontWeight: '500',
        color: colors.ink,
    },
    chipTextOn: {
        color: colors.onInk,
    },
    chipTextOff: {
        color: colors.disabled,
    },
    skeleton: {
        paddingHorizontal: layout.inboxGutter,
    },
    skeletonRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingVertical: 16,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    skeletonLines: {
        flex: 1,
        gap: 8,
    },
    block: {
        backgroundColor: colors.sunken,
        borderRadius: 6,
    },
    lineLong: {
        height: 14,
        width: '80%',
    },
    lineShort: {
        height: 12,
        width: '55%',
    },
    spark: {
        width: 72,
        height: 32,
    },
}))
