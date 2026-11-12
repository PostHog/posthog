import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { FlatList, Linking, type ListViewToken, RefreshControl, Text, View } from 'react-native'

import type { ExperimentListSegment } from '@/api/experiments'
import { useAuthStore } from '@/auth/authStore'
import { DEMO_ME } from '@/demo/fixtures'
import { changeNavPin } from '@/features/tabs/navPinActions'
import { type NavChrome, useIsNavPinned } from '@/features/tabs/navPinStore'
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
import { FlaskIcon } from '@/ui/icons/FlaskIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { ListPaginationFooter } from '@/ui/ListPaginationFooter'
import { OverlayHost } from '@/ui/OverlayPortal'
import { SearchField } from '@/ui/SearchField'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets, useTabBottomOffset } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'

import { useLaunchAction } from './actionHooks'
import {
    trackExperimentsErrorShown,
    trackExperimentsOpened,
    trackExperimentsOpenedInWeb,
    trackExperimentsSearched,
    trackExperimentsSegmentChanged,
} from './analytics'
import { ExperimentListRow } from './ExperimentListRow'
import type { ExperimentRow } from './experimentModel'
import { headlineKey } from './experimentModel'
import { useExperiment, useExperimentsContext, useExperimentsList, useLastSeenHeadlines } from './hooks'
import { LaunchSheet } from './LaunchSheet'
import { emptyCopy, listStatus, SEGMENT_LABELS } from './listCopy'

const SEGMENTS: readonly ExperimentListSegment[] = ['running', 'complete', 'draft']
const STACK_BOTTOM = 40
const STACK_TOAST_BOTTOM = 48
/** A search counts once the person stops typing for this long. */
const SEARCH_TRACK_MS = 1200
const VIEWABILITY = { itemVisiblePercentThreshold: 10, minimumViewTime: 120 }
const SKELETON_ROWS = [0, 1, 2, 3, 4, 5] as const
/** Fixed segments: a flex segment in a content-sized pill has no width to share, and collapses on native. */
const SEGMENT_WIDTH = 88

function keyOf(row: ExperimentRow): string {
    return row.id
}

export function ExperimentsListScreen({ chrome }: { chrome: NavChrome }): ReactElement {
    const styles = useStyles()
    const content = (
        <View style={styles.screen} testID={`experiments-screen-${chrome}`}>
            <ExperimentsListBody chrome={chrome} />
        </View>
    )
    // A tab already sits under the tabs layout's overlay host.
    return chrome === 'stack' ? <OverlayHost>{content}</OverlayHost> : content
}

function useMyUuid(demo: boolean): string | null {
    const uuid = useAuthStore((state) => state.user?.uuid ?? null)
    return demo ? DEMO_ME.uuid : uuid
}

/** Ids of the rows on screen, kept stable so the row reads do not restart on every scroll frame. */
function useVisibleIds(): {
    ids: readonly string[]
    onViewableItemsChanged: (info: { viewableItems: ListViewToken[] }) => void
} {
    const [ids, setIds] = useState<readonly string[]>([])
    const onViewableItemsChanged = useRef((info: { viewableItems: ListViewToken[] }): void => {
        const next = info.viewableItems
            .map((token) => (token.item as ExperimentRow | undefined)?.id)
            .filter((id): id is string => typeof id === 'string')
        setIds((current) =>
            current.length === next.length && current.every((id, index) => id === next[index]) ? current : next
        )
    }).current
    return { ids, onViewableItemsChanged }
}

function ExperimentsListBody({ chrome }: { chrome: NavChrome }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const tabBottom = useTabBottomOffset()
    const scrollTitle = useScrollTitle('Experiments')
    const context = useExperimentsContext()
    const { access, mode } = context
    const now = useNow().getTime()
    const toasts = useToasts()
    const pinned = useIsNavPinned('experiments')
    const myUuid = useMyUuid(mode === 'demo')
    const [segment, setSegment] = useState<ExperimentListSegment>('running')
    const [search, setSearch] = useState('')
    const [menuOpen, setMenuOpen] = useState(false)
    const visible = useVisibleIds()
    const list = useExperimentsList(segment, search, visible.ids)
    const lastSeen = useLastSeenHeadlines()

    // Only a new visit counts, not a segment change while the screen is open.
    const segmentRef = useRef(segment)
    segmentRef.current = segment
    useFocusEffect(
        useCallback(() => {
            trackExperimentsOpened({ chrome, segment: segmentRef.current })
        }, [chrome])
    )

    const text = search.trim()
    useEffect(() => {
        if (!text) {
            return
        }
        const timer = setTimeout(() => trackExperimentsSearched({ text, segment }), SEARCH_TRACK_MS)
        return () => clearTimeout(timer)
    }, [text, segment])

    const failed = list.isError && !list.data
    useEffect(() => {
        if (failed) {
            trackExperimentsErrorShown({ kind: 'list_failed' })
        }
    }, [failed])
    useEffect(() => {
        if (list.loadMoreFailed) {
            trackExperimentsErrorShown({ kind: 'load_more_failed' })
        }
    }, [list.loadMoreFailed])

    const status =
        access.state !== 'ok' || failed
            ? null
            : listStatus(
                  segment,
                  { loading: !list.data, oldestResultsAt: list.oldestResultsAt, rowsSettled: list.rowsSettled },
                  now
              )

    const webUrl = navListWebUrl(context.scope, 'experiments')
    const goBack = useViewBack()
    const { mark } = lastSeen
    const openExperiment = useCallback(
        (row: ExperimentRow) => {
            const key = headlineKey(row.headline)
            if (key) {
                mark(row.id, key)
            }
            router.push({
                pathname: '/experiments/[id]',
                params: {
                    id: row.id,
                    source: 'list',
                    ...(context.scope
                        ? { project: String(context.scope.projectId), host: new URL(context.scope.host).host }
                        : {}),
                },
            })
        },
        [router, mark, context.scope]
    )

    const [launchId, setLaunchId] = useState<string | null>(null)
    const launchTarget = useExperiment(launchId ?? '')
    const launch = useLaunchAction(launchId ?? '')
    // The sheet opens once the draft's detail loads. A failed read says so and frees the button for another tap.
    const launchFailed = launchId !== null && launchTarget.isError
    const { show: showToast } = toasts
    useEffect(() => {
        if (launchFailed) {
            setLaunchId(null)
            showToast("Couldn't load this draft. Try again.")
        }
    }, [launchFailed, showToast])
    const openLaunch = useCallback((row: ExperimentRow) => setLaunchId(row.id), [])

    const changeSegment = (next: ExperimentListSegment): void => {
        if (next !== segment) {
            setSegment(next)
            trackExperimentsSegmentChanged({ segment: next })
        }
    }

    const contentTop = topOffset(insets, chrome === 'tab' ? TABS_HEADER_BOTTOM : SCREEN_CONTENT_TOP)
    const contentBottom = chrome === 'tab' ? tabBottom : bottomOffset(insets, STACK_BOTTOM)
    const rows = list.data
    const showSearch = text !== '' || (rows !== undefined && rows.length > 0)

    // A pushed screen draws its own title; on a tab the shared tabs header draws it.
    const stackTitle =
        chrome === 'stack' ? (
            <View style={styles.titleBlock}>
                <Text style={styles.title} accessibilityRole="header" onLayout={scrollTitle.onTitleLayout}>
                    Experiments
                </Text>
                {status ? (
                    <Text style={styles.status} testID="experiments-status">
                        {status}
                    </Text>
                ) : null}
            </View>
        ) : null
    const segments = (
        <SegmentedPill
            height={44}
            segmentWidth={SEGMENT_WIDTH}
            style={styles.segments}
            segments={SEGMENTS.map((option) => ({
                key: option,
                accessibilityLabel: SEGMENT_LABELS[option],
                accessibilityRole: 'tab',
                selected: option === segment,
                onPress: () => changeSegment(option),
                testID: `experiments-segment-${option}`,
                children: (
                    <Text style={styles.segmentText} numberOfLines={1}>
                        {SEGMENT_LABELS[option]}
                    </Text>
                ),
            }))}
        />
    )
    const header = (
        <View style={styles.header}>
            {stackTitle}
            {showSearch ? (
                <SearchField
                    value={search}
                    onChangeText={setSearch}
                    placeholder="Search experiments"
                    testID="experiments-search"
                />
            ) : null}
            {segments}
        </View>
    )

    let body: ReactElement
    if (access.state !== 'ok') {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop, paddingBottom: contentBottom }]}>
                <View style={styles.content}>{stackTitle}</View>
                <ViewsReauthState access={access} feature="experiments" />
            </View>
        )
    } else if (failed) {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>
                    <View style={styles.header}>
                        {stackTitle}
                        {segments}
                    </View>
                </View>
                <StateView
                    icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Couldn't load your experiments"
                    message={list.error?.message ?? 'Check your connection and try again.'}
                    actionLabel="Try again"
                    onAction={() => list.refetch()}
                    testID="experiments-error"
                />
            </View>
        )
    } else if (!rows) {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <View style={styles.content}>
                    <View style={styles.header}>
                        {stackTitle}
                        {segments}
                    </View>
                </View>
                <ExperimentsListSkeleton />
            </View>
        )
    } else {
        const empty = emptyCopy(segment, list.searching ? '' : search)
        const onEmptyAction = (): void => {
            if (empty.action?.kind === 'clear_search') {
                setSearch('')
            } else if (empty.action?.kind === 'drafts') {
                changeSegment('draft')
            }
        }
        body = (
            <FlatList
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                data={rows}
                keyExtractor={keyOf}
                renderItem={({ item }) => (
                    <ExperimentListRow
                        row={item}
                        now={now}
                        myUuid={myUuid}
                        onOpen={openExperiment}
                        onLaunch={item.status === 'draft' ? openLaunch : undefined}
                    />
                )}
                onViewableItemsChanged={visible.onViewableItemsChanged}
                viewabilityConfig={VIEWABILITY}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                ListHeaderComponent={header}
                ListFooterComponent={
                    <ListPaginationFooter
                        noun="experiments"
                        hasMore={list.hasMore}
                        loading={list.isLoadingMore}
                        failed={list.loadMoreFailed}
                        onLoadMore={list.loadMore}
                    />
                }
                ListEmptyComponent={
                    list.searching ? (
                        <ExperimentsListSkeleton count={2} />
                    ) : (
                        <StateView
                            icon={
                                text ? (
                                    <SearchIcon size={iconSizes.empty} color={colors.tertiary} />
                                ) : (
                                    <FlaskIcon size={iconSizes.empty} color={colors.tertiary} />
                                )
                            }
                            title={empty.title}
                            message={empty.message}
                            actionLabel={empty.action?.label}
                            onAction={empty.action ? onEmptyAction : undefined}
                            testID={text ? 'experiments-search-empty' : `experiments-empty-${segment}`}
                        />
                    )
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
                testID="experiments-list"
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
                        testID="experiments-menu"
                        items={[
                            {
                                key: pinned ? 'unpin' : 'pin',
                                label: pinned ? 'Unpin from navigation' : 'Pin to navigation',
                                Icon: PinIcon,
                                onPress: () => changeNavPin('experiments', !pinned, 'list_menu', toasts.show),
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
                                        trackExperimentsOpenedInWeb()
                                        Linking.openURL(safe).catch(() => undefined)
                                    }
                                },
                            },
                        ]}
                    />
                </>
            ) : null}
            <LaunchSheet
                visible={launchId !== null}
                experiment={launchId !== null ? (launchTarget.data ?? null) : null}
                pending={launch.pending}
                onClose={() => setLaunchId(null)}
                onConfirm={() =>
                    launch.run(() => {
                        setLaunchId(null)
                        toasts.show('Experiment launched')
                    })
                }
            />
            <ViewsToast
                toast={toasts.toast}
                onHide={toasts.hide}
                bottom={chrome === 'tab' ? undefined : STACK_TOAST_BOTTOM}
            />
        </View>
    )
}

/**
 * The pinned tab's status line in the shared tabs header. Its own component, so a pushed Experiments screen never
 * writes the tab's header slot, and never clears it when it closes.
 */
function TabHeaderPublisher({ status }: { status: string | null }): null {
    useTabHeader('experiments', { hint: null, status, editing: null, editPins: null, filter: null })
    return null
}

function ExperimentsListSkeleton({ count = 6 }: { count?: number }): ReactElement {
    const styles = useStyles()
    return (
        <View
            style={styles.skeleton}
            accessibilityLabel="Loading your experiments"
            accessibilityRole="progressbar"
            testID="experiments-loading"
        >
            {SKELETON_ROWS.slice(0, count).map((index) => (
                <View key={index} style={styles.skeletonRow}>
                    <View style={[styles.block, styles.lineTitle, { width: `${48 + ((index * 17) % 30)}%` }]} />
                    <View style={[styles.block, styles.lineResult, { width: `${60 + ((index * 11) % 25)}%` }]} />
                    <View style={[styles.block, styles.lineMeta, { width: `${70 + ((index * 7) % 20)}%` }]} />
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
    segments: {
        alignSelf: 'flex-start',
    },
    segmentText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    skeleton: {
        paddingHorizontal: layout.inboxGutter,
    },
    skeletonRow: {
        gap: 7,
        paddingVertical: 15,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    block: {
        backgroundColor: colors.sunken,
        borderRadius: 6,
    },
    lineTitle: {
        height: 16,
    },
    lineResult: {
        height: 13,
    },
    lineMeta: {
        height: 12,
    },
}))
