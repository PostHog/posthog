import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, FlatList, Text, View } from 'react-native'
import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { useNow } from '@/lib/useNow'
import type { BrowseRow } from '@/model/views'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { SearchField } from '@/ui/SearchField'
import { LoadingView, StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { trackViewsErrorShown } from '../analytics'
import { type BrowseListState, useBrowseDashboards, useBrowseInsights, useBrowseSearch } from '../browseHooks'
import { usePinFlows } from '../list/usePinFlows'
import { groupPosition, ViewRow } from '../list/ViewRow'
import { RowMenu } from '../list/ViewsMenu'
import { relativeDay } from '../list/viewMeta'
import { usePinActions, usePinnedKeys } from '../pinHooks'
import { useViewsAccess } from '../useViewsAccess'
import { ViewsReauthState } from '../ViewsReauthState'
import { ViewsToast } from '../ViewsToast'
import { viewHref } from '../viewRoutes'

export type BrowseKind = 'dashboards' | 'insights'

const COPY: Record<BrowseKind, { title: string; search: string; empty: string; emptyMessage: string; noun: string }> = {
    dashboards: {
        title: 'Dashboards',
        search: 'Search dashboards',
        empty: 'No dashboards yet',
        emptyMessage: 'Dashboards made in this project on the web show up here.',
        noun: 'dashboards',
    },
    insights: {
        title: 'Insights',
        search: 'Search insights',
        empty: 'No insights yet',
        emptyMessage: 'Saved insights from this project show up here.',
        noun: 'insights',
    },
}

function keyOf(row: BrowseRow): string {
    return `${row.kind}:${row.ref ?? row.name}`
}

/** Browse, Dashboards or Insights: every one in the project, 30 at a time, with search and a pin on each row. */
export function BrowseListScreen({ kind }: { kind: BrowseKind }): ReactElement {
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const access = useViewsAccess()
    const scrollTitle = useScrollTitle(COPY[kind].title)
    const goBack = (): void => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace('/views')
        }
    }
    return (
        <View style={styles.screen} testID={`views-browse-${kind}-screen`}>
            {access.state !== 'ok' ? (
                <View
                    style={[
                        styles.fill,
                        { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP), paddingBottom: bottomOffset(insets, 60) },
                    ]}
                >
                    <ViewsReauthState access={access} />
                </View>
            ) : kind === 'dashboards' ? (
                <DashboardsList scrollTitle={scrollTitle} />
            ) : (
                <InsightsList scrollTitle={scrollTitle} />
            )}
            <ScreenChrome onBack={goBack} backTestID="views-browse-back" title={scrollTitle.title} />
        </View>
    )
}

// One component per kind, so each screen reads only its own list.
function DashboardsList({ scrollTitle }: { scrollTitle: ScrollTitleState }): ReactElement {
    return <BrowseList kind="dashboards" list={useBrowseDashboards()} scrollTitle={scrollTitle} />
}

function InsightsList({ scrollTitle }: { scrollTitle: ScrollTitleState }): ReactElement {
    return <BrowseList kind="insights" list={useBrowseInsights()} scrollTitle={scrollTitle} />
}

function BrowseList({
    kind,
    list,
    scrollTitle,
}: {
    kind: BrowseKind
    list: BrowseListState
    scrollTitle: ScrollTitleState
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const copy = COPY[kind]
    const [text, setText] = useState('')
    const search = useBrowseSearch(kind, text)
    const actions = usePinActions()
    const pinnedKeys = usePinnedKeys()
    const flows = usePinFlows(actions)
    const [menu, setMenu] = useState<{ row: BrowseRow; anchor: RowAnchor } | null>(null)

    const rows = search.active ? (search.rows.data ?? []) : (list.data ?? [])
    const latest = useRef({ flows, router })
    latest.current = { flows, router }

    const open = useCallback(
        (row: BrowseRow) => {
            const href = viewHref(row, { from: search.active ? 'search' : 'browse' })
            if (href) {
                latest.current.router.push(href)
            }
        },
        [search.active]
    )
    const togglePin = useCallback(
        (row: BrowseRow) => latest.current.flows.togglePin(row, search.active ? 'search' : 'row_menu'),
        [search.active]
    )
    const openMenu = useCallback((row: BrowseRow, anchor: RowAnchor) => setMenu({ row, anchor }), [])

    const renderItem = useCallback(
        ({ item, index }: { item: BrowseRow; index: number }) => {
            const at = item.at ? relativeDay(item.at, now) : null
            const meta = at ? `${kind === 'dashboards' ? 'Viewed' : 'Edited'} ${at}` : item.description
            return (
                <ViewRow
                    view={item}
                    meta={meta}
                    position={groupPosition(index, rows.length)}
                    pinned={pinnedKeys.has(keyOf(item))}
                    onOpen={open}
                    onTogglePin={togglePin}
                    onMenu={openMenu}
                    testID={`views-browse-row-${item.kind}-${item.ref}`}
                />
            )
        },
        [now, kind, rows.length, pinnedKeys, open, togglePin, openMenu]
    )

    const state = search.active ? search.rows : list
    const listFailed = !search.active && list.isError
    useEffect(() => {
        if (listFailed) {
            trackViewsErrorShown({ screen: 'browse', kind: 'failed' })
        }
    }, [listFailed])
    const contentTop = topOffset(insets, SCREEN_CONTENT_TOP)
    let empty: ReactElement
    if (state.isLoading) {
        empty = <LoadingView label={`Loading ${copy.noun}`} />
    } else if (state.isError) {
        empty = (
            <StateView
                icon={<WarningIcon size={28} color={colors.tertiary} />}
                title={`Couldn't load ${copy.noun}`}
                message={state.error?.message ?? 'Check your connection and try again.'}
                actionLabel="Try again"
                onAction={() => state.refetch()}
                testID="views-browse-error"
            />
        )
    } else if (search.active) {
        empty = (
            <StateView
                icon={<SearchIcon size={28} color={colors.tertiary} />}
                title="No matches"
                message={`No ${copy.noun} match “${search.query}”.`}
                actionLabel="Clear search"
                onAction={() => setText('')}
                testID="views-browse-no-matches"
            />
        )
    } else {
        empty = <StateView title={copy.empty} message={copy.emptyMessage} testID="views-browse-empty" />
    }

    return (
        <>
            <FlatList
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                data={rows}
                keyExtractor={keyOf}
                renderItem={renderItem}
                ListHeaderComponent={
                    <View style={styles.listHeader}>
                        <Text style={styles.title} accessibilityRole="header" onLayout={scrollTitle.onTitleLayout}>
                            {copy.title}
                        </Text>
                        <SearchField
                            value={text}
                            onChangeText={setText}
                            placeholder={copy.search}
                            testID="views-browse-search"
                        />
                    </View>
                }
                ListEmptyComponent={empty}
                ListFooterComponent={
                    search.active ? null : (
                        <LoadMoreFooter
                            noun={copy.noun}
                            loading={list.isLoadingMore}
                            failed={list.loadMoreFailed}
                            onRetry={list.retryLoadMore}
                        />
                    )
                }
                onEndReached={search.active ? undefined : list.loadMore}
                onEndReachedThreshold={0.5}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                contentContainerStyle={[
                    styles.content,
                    { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 60) },
                ]}
            />
            {menu ? (
                <RowMenu
                    visible
                    anchor={menu.anchor}
                    view={menu.row}
                    pinned={pinnedKeys.has(keyOf(menu.row))}
                    onClose={() => setMenu(null)}
                    onTogglePin={() => {
                        setMenu(null)
                        flows.togglePin(menu.row, search.active ? 'search' : 'row_menu')
                    }}
                    onOpen={() => {
                        setMenu(null)
                        open(menu.row)
                    }}
                />
            ) : null}
            <ViewsToast toast={flows.toast} onHide={flows.hideToast} bottom={60} />
        </>
    )
}

interface LoadMoreFooterProps {
    noun: string
    loading: boolean
    failed: boolean
    onRetry: () => void
}

function LoadMoreFooter({ noun, loading, failed, onRetry }: LoadMoreFooterProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (loading) {
        return (
            <View style={styles.footer} accessibilityLabel={`Loading more ${noun}`} accessibilityRole="progressbar">
                <ActivityIndicator color={colors.tertiary} />
            </View>
        )
    }
    if (failed) {
        return (
            <View style={styles.footer} testID="views-browse-load-more-error">
                <Text style={styles.footerText}>Couldn't load more {noun}.</Text>
                <Pressable44 onPress={onRetry} style={styles.retry} pressedBackground={colors.inkHover}>
                    <Text style={styles.retryText}>Try again</Text>
                </Pressable44>
            </View>
        )
    }
    return null
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
        flexGrow: 1,
        paddingHorizontal: layout.inboxGutter,
    },
    listHeader: {
        gap: 14,
        marginBottom: 14,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginHorizontal: 6,
    },
    footer: {
        alignItems: 'center',
        gap: 8,
        paddingVertical: 20,
    },
    footerText: {
        ...type.bodySmall,
        color: colors.muted,
    },
    retry: {
        height: 40,
        paddingHorizontal: 18,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
