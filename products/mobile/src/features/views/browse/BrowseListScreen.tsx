import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { useNow } from '@/lib/useNow'
import type { BrowseRow } from '@/model/views'
import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SearchField } from '@/ui/SearchField'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

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

const CHROME_TOP = 58
const CHROME_ROW_HEIGHT = 46
const CHROME_BOTTOM = CHROME_TOP + CHROME_ROW_HEIGHT
const CHROME_FADE = 16
const CHROME_SOLID = CHROME_BOTTOM / (CHROME_BOTTOM + CHROME_FADE)

function keyOf(row: BrowseRow): string {
    return `${row.kind}:${row.ref ?? row.name}`
}

/** Browse, Dashboards or Insights: every one in the project, 30 at a time, with search and a pin on each row. */
export function BrowseListScreen({ kind }: { kind: BrowseKind }): ReactElement {
    const router = useRouter()
    const insets = useScreenInsets()
    const access = useViewsAccess()
    const goBack = (): void => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace('/views')
        }
    }
    const chromeTop = topOffset(insets, CHROME_TOP)
    return (
        <View style={styles.screen} testID={`views-browse-${kind}-screen`}>
            {access.state !== 'ok' ? (
                <View
                    style={[
                        styles.fill,
                        { paddingTop: topOffset(insets, CHROME_BOTTOM), paddingBottom: bottomOffset(insets, 60) },
                    ]}
                >
                    <ViewsReauthState access={access} />
                </View>
            ) : kind === 'dashboards' ? (
                <DashboardsList />
            ) : (
                <InsightsList />
            )}
            <View style={[styles.chrome, { paddingTop: chromeTop }]}>
                <BlurEdge solid={CHROME_SOLID} />
                <FadeEdge direction="down" solid={CHROME_SOLID} opacity={layout.chromeTint} />
                <BackChip onPress={goBack} testID="views-browse-back" />
            </View>
        </View>
    )
}

// One component per kind, so each screen reads only its own list.
function DashboardsList(): ReactElement {
    return <BrowseList kind="dashboards" list={useBrowseDashboards()} />
}

function InsightsList(): ReactElement {
    return <BrowseList kind="insights" list={useBrowseInsights()} />
}

function BrowseList({ kind, list }: { kind: BrowseKind; list: BrowseListState }): ReactElement {
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
    const contentTop = topOffset(insets, CHROME_BOTTOM + 10)
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
                data={rows}
                keyExtractor={keyOf}
                renderItem={renderItem}
                ListHeaderComponent={
                    <View style={styles.listHeader}>
                        <Text style={styles.title} accessibilityRole="header">
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

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    fill: {
        flex: 1,
    },
    chrome: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: layout.inboxGutter,
        paddingBottom: CHROME_FADE,
        pointerEvents: 'box-none',
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
        marginHorizontal: 2,
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
        color: colors.white,
    },
})
