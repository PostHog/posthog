import { useIsFocused, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Linking, Platform, RefreshControl, SectionList, Text, View, type ViewToken } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { useNow } from '@/lib/useNow'
import type { BrowseRow, InsightSnapshot, PinDisplayMode, PinView, RecentView, ViewEntry } from '@/model/views'
import { ChartCanvasBudget, useCanvasBudgetViewport } from '@/ui/chart/budget/ChartCanvasBudget'
import { ChartSelectionProvider, useChartListMotion } from '@/ui/chart/selection/ChartSelectionProvider'
import type { ChartTooltipPoint } from '@/ui/chart/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SearchField } from '@/ui/SearchField'
import { StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { NavPinMenu } from '../../tabs/NavPinMenu'
import { changeNavPin } from '../../tabs/navPinActions'
import { openNavTarget } from '../../tabs/navPinRoutes'
import { type NavPin, useNavPinStore } from '../../tabs/navPinStore'
import { TABS_HEADER_BOTTOM } from '../../tabs/TabsHeader'
import { useTabHeader } from '../../tabs/tabHeaderStore'
import {
    type EditPinsEntry,
    type PinSource,
    trackBrowseListOpened,
    trackEditPinsClosed,
    trackEditPinsOpened,
    trackPinTileSheetOpened,
    trackViewOpenedInWeb,
    trackViewsErrorShown,
} from '../analytics'
import { useViewsSearch } from '../browseHooks'
import { type DashboardSnapshot, dashboardQueryKey, insightItemKey, insightQueryKey, pinTarget } from '../items'
import { usePinHint } from '../pinHint'
import { pinModes, usePinActions, usePinData, useViewsList } from '../pinHooks'
import { ChartSheetsProvider, useChartSheets } from '../pointSheet/ChartSheetsProvider'
import { INITIAL_VISIBLE_ROWS } from '../useViewRefresh'
import { useViewsAccess, type ViewsAccess } from '../useViewsAccess'
import { useViewsContext } from '../useViewsContext'
import { ViewsReauthState } from '../ViewsReauthState'
import { useToasts, ViewsToast } from '../ViewsToast'
import { viewHref } from '../viewRoutes'
import { useSnapshot } from '../viewsCache'
import { viewWebUrl } from '../webLinks'
import { BROWSE_ENTRIES, type BrowseEntry, BrowseEntryRow, browseEntryLabel, browseEntryPin } from './BrowseEntryRow'
import { ChooseTileSheet, type ChooseTileTarget } from './ChooseTileSheet'
import { EditPinsList } from './EditPinsList'
import { EmptyPins } from './EmptyPins'
import { PinCard } from './PinCard'
import { PinHint } from './PinHint'
import { usePinFlows } from './usePinFlows'
import { type GroupPosition, groupPosition, ViewRow } from './ViewRow'
import { PinMenu, RowMenu } from './ViewsMenu'
import { ViewsSkeleton } from './ViewsSkeleton'
import { pinTargetFor, relativeDay, viewTypeLabel } from './viewMeta'

type ListView = RecentView | BrowseRow

type ListItem =
    | { type: 'pin'; key: string; shortcutId: string; pin: PinView; index: number; last: boolean }
    | { type: 'pin-hint'; key: string; last: boolean }
    | { type: 'empty-pins'; key: string }
    | { type: 'note'; key: string; text: string }
    | { type: 'view'; key: string; view: ListView; meta: string | null; position: GroupPosition; entry: ViewEntry }
    | { type: 'browse'; key: string; entry: BrowseEntry; position: GroupPosition }

interface ListSection {
    key: string
    title: string
    first: boolean
    /** The Pinned header's Edit button. */
    editable: boolean
    data: ListItem[]
}

const EMPTY_PINS: PinView[] = []
const EMPTY_RECENT: RecentView[] = []

function keyOf(item: ListItem): string {
    return item.key
}

function matchKey(view: Pick<ListView, 'kind' | 'ref'>): string {
    return `${view.kind}:${view.ref ?? ''}`
}

type MenuState =
    | { kind: 'pin'; shortcutId: string; anchor: RowAnchor }
    | { kind: 'row'; view: ListView; entry: ViewEntry; anchor: RowAnchor }
    | { kind: 'nav-pin'; entry: BrowseEntry; pin: NavPin; anchor: RowAnchor }

function isNavPinned(pin: NavPin): boolean {
    return useNavPinStore.getState().pins.includes(pin)
}

/** The Views tab: pinned views first, then Recent and Browse, with search over all of them. */
export function ViewsScreen(): ReactElement {
    const styles = useStyles()
    const access = useViewsAccess()
    // The tab stays mounted under a pushed view and behind other tabs. Its charts then give their canvases back.
    const focused = useIsFocused()
    if (access.state !== 'ok') {
        return <ViewsReauth access={access} />
    }
    return (
        <View style={styles.screen} testID="views-screen">
            <ChartSheetsProvider>
                <ChartSelectionProvider>
                    <ChartCanvasBudget active={focused}>
                        <ViewsBody />
                    </ChartCanvasBudget>
                </ChartSelectionProvider>
            </ChartSheetsProvider>
        </View>
    )
}

function ViewsReauth({ access }: { access: ViewsAccess }): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    useTabHeader('views', {
        hint: null,
        status: null,
        editing: null,
        editPins: { disabled: true, onPress: noop },
        filter: null,
    })
    return (
        <View style={styles.screen} testID="views-screen">
            <View
                style={[
                    styles.fill,
                    { paddingTop: topOffset(insets, TABS_HEADER_BOTTOM), paddingBottom: bottomOffset(insets, 120) },
                ]}
            >
                <ViewsReauthState access={access} />
            </View>
        </View>
    )
}

const noop = (): void => undefined

function ViewsBody(): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const context = useViewsContext()
    const demo = context.mode === 'demo'
    const list = useViewsList()
    const actions = usePinActions()
    const motion = useChartListMotion()
    const viewport = useCanvasBudgetViewport()
    const sheets = useChartSheets()
    const flows = usePinFlows(actions)
    const navToasts = useToasts()
    const { hideToast: hidePinToast } = flows
    const { show: showToast } = navToasts
    const navPins = useNavPinStore((state) => state.pins)
    const { errors, replay } = useMobileProductFlags()
    const browseEntries = useMemo(
        () => BROWSE_ENTRIES.filter((entry) => (entry === 'errors' ? errors : entry === 'replay' ? replay : true)),
        [errors, replay]
    )
    const [text, setText] = useState('')
    const [menu, setMenu] = useState<MenuState | null>(null)
    const [chooseTile, setChooseTile] = useState<ChooseTileTarget | null>(null)
    const listRef = useRef<SectionList<ListItem, ListSection>>(null)

    const pins = list.pins.data ?? EMPTY_PINS
    const edit = useEditPinsSession(pins.length)
    const { editing, start: startEditing } = edit
    const recent = list.recent.data ?? EMPTY_RECENT
    const search = useViewsSearch(editing ? '' : text, pins, recent)
    const pinnedKeys = list.pinnedKeys
    const hint = usePinHint({
        pins: list.pins.data,
        automatic: list.automaticDisplays,
        explicit: list.displayPrefs,
        enabled: !editing && !search.active,
    })
    const hintTargetId = hint.target?.shortcutId ?? null
    const { dismiss: dismissHint } = hint

    // Both the refresh rules and the canvas budget follow what the list shows, and a list takes one callback.
    const viewable = useRef({ list: list.onViewableItemsChanged, budget: viewport.onViewableItemsChanged })
    viewable.current = { list: list.onViewableItemsChanged, budget: viewport.onViewableItemsChanged }
    const onViewableItemsChanged = useRef((info: { viewableItems: ViewToken[]; changed: ViewToken[] }) => {
        viewable.current.list(info)
        viewable.current.budget(info)
    }).current

    // Row callbacks read the latest values through a ref, so they stay stable and memoized cards skip re-rendering.
    const latest = useRef({
        router,
        scope: context.scope,
        actions,
        flows,
        sheets,
        refreshItem: list.refresh.refreshItem,
        searching: search.active,
    })
    latest.current = {
        router,
        scope: context.scope,
        actions,
        flows,
        sheets,
        refreshItem: list.refresh.refreshItem,
        searching: search.active,
    }

    const openPin = useCallback((pin: PinView) => {
        const { router: nav, scope } = latest.current
        if (pin.native) {
            const href = viewHref(pin, { from: 'pinned', mode: pin.display.mode })
            if (href) {
                nav.push(href)
            }
            return
        }
        const url = viewWebUrl(scope, pin.href)
        if (url) {
            trackViewOpenedInWeb({ viewType: pin.kind, reason: 'web_only' })
            Linking.openURL(url).catch(() => undefined)
        }
    }, [])
    const openView = useCallback((view: ListView, entry: ViewEntry) => {
        const href = viewHref(view, { from: entry })
        if (href) {
            latest.current.router.push(href)
        }
    }, [])
    const openBrowse = useCallback((entry: BrowseEntry) => {
        const { router: nav } = latest.current
        if (entry === 'web') {
            const href = viewHref({ kind: 'web_analytics', ref: null }, { from: 'browse' })
            if (href) {
                nav.push(href)
            }
            return
        }
        trackBrowseListOpened({ section: entry, from: latest.current.searching ? 'search' : 'browse' })
        const pin = browseEntryPin(entry)
        if (pin) {
            openNavTarget(nav, pin, isNavPinned(pin))
            return
        }
        nav.push(`/views/browse/${entry}`)
    }, [])
    const openBrowseMenu = useCallback((entry: BrowseEntry, anchor: RowAnchor) => {
        const pin = browseEntryPin(entry)
        if (pin) {
            setMenu({ kind: 'nav-pin', entry, pin, anchor })
        }
    }, [])
    // One toast at a time across the Views pins and the nav pins: a nav pin change hides a Views pin toast.
    const showNavToast = useCallback(
        (text: string, undo?: () => void) => {
            hidePinToast()
            showToast(text, undo)
        },
        [hidePinToast, showToast]
    )
    // A Chart pin reads the saved range, so its Point sheet follows the same cache entry as the pin.
    const openPinPoint = useCallback((pin: PinView, snapshot: InsightSnapshot, point: ChartTooltipPoint) => {
        const { scope, sheets: chartSheets, refreshItem } = latest.current
        const target = pinTarget(pin)
        chartSheets.openPoint(
            {
                snapshot,
                queryKey: target ? insightQueryKey(scope, target) : null,
                itemKey: target ? insightItemKey(scope, target) : null,
                refreshItem,
                dashboardName: pin.kind === 'dashboard' ? pin.name : null,
            },
            point,
            'tooltip'
        )
    }, [])
    const openTileSheet = useCallback((target: ChooseTileTarget) => {
        setMenu(null)
        setChooseTile(target)
        trackPinTileSheetOpened({ entry: target.entry, mode: target.mode })
    }, [])
    const showAs = useCallback(
        (pin: PinView, mode: PinDisplayMode) => {
            if (latest.current.actions.setDisplayMode(pin, mode) === 'needs_tile' && mode !== 'row') {
                openTileSheet({ pin, mode, chooseFirst: true, entry: 'show_as' })
            }
        },
        [openTileSheet]
    )
    const openPinMenu = useCallback(
        (pin: PinView, anchor: RowAnchor) => {
            dismissHint('long_press')
            setMenu({ kind: 'pin', shortcutId: pin.shortcutId, anchor })
        },
        [dismissHint]
    )
    const closeHint = useCallback(() => dismissHint('close'), [dismissHint])
    const unpinPin = useCallback((pin: PinView, from: PinSource) => {
        setMenu(null)
        latest.current.flows.unpin(pin, from)
    }, [])
    const unpinFromCard = useCallback(
        (pin: PinView) => unpinPin(pin, latest.current.searching ? 'search' : 'row_menu'),
        [unpinPin]
    )
    const openChooseTile = useCallback(
        (pin: PinView, entry: 'menu' | 'removed_tile') =>
            openTileSheet({ pin, mode: pin.display.mode === 'chart' ? 'chart' : 'number', chooseFirst: false, entry }),
        [openTileSheet]
    )
    const chooseTileFromCard = useCallback((pin: PinView) => openChooseTile(pin, 'removed_tile'), [openChooseTile])

    const rowHandlers = useMemo(() => {
        const handlers = (entry: ViewEntry) => ({
            onOpen: (view: ListView) => openView(view, entry),
            onTogglePin: (view: ListView) =>
                latest.current.flows.togglePin(view, entry === 'search' ? 'search' : 'row_menu'),
            onMenu: (view: ListView, anchor: RowAnchor) => setMenu({ kind: 'row', view, entry, anchor }),
        })
        return { recent: handlers('recent'), search: handlers('search') }
    }, [openView])

    // Edit pins has nothing left to edit once the last pin goes, so the list comes back with its empty state.
    const noPins = list.pins.data !== undefined && pins.length === 0
    const { finish: finishEditing } = edit
    useEffect(() => {
        if (noPins) {
            finishEditing('no_pins')
        }
    }, [noPins, finishEditing])

    const sections = useMemo<ListSection[]>(() => {
        let index = 0
        const pinItems = (source: readonly PinView[]): ListItem[] =>
            source.map((pin, position) => ({
                type: 'pin',
                key: `pin:${pin.shortcutId}`,
                shortcutId: pin.shortcutId,
                pin,
                index: index++,
                last: position === source.length - 1,
            }))
        const viewItems = (views: readonly ListView[], entry: ViewEntry, group: string): ListItem[] =>
            views.map((view, position) => {
                index++
                const label = viewTypeLabel(view.kind)
                const at = 'viewedAt' in view ? view.viewedAt : view.at
                const verb = 'viewedAt' in view || view.kind === 'dashboard' ? 'Viewed' : 'Edited'
                const when = at ? `${verb} ${relativeDay(at, now)}` : null
                return {
                    type: 'view',
                    key: `${group}:${matchKey(view)}`,
                    view,
                    meta: [label, when].filter(Boolean).join(' · ') || null,
                    position: groupPosition(position, views.length),
                    entry,
                }
            })

        if (search.active) {
            const shown = new Set([...search.pinned.map(matchKey), ...search.recent.map(matchKey)])
            const server = (rows: readonly BrowseRow[]): BrowseRow[] => rows.filter((row) => !shown.has(matchKey(row)))
            const result: ListSection[] = []
            const add = (key: string, title: string, data: ListItem[]): void => {
                if (data.length > 0) {
                    result.push({ key, title, first: result.length === 0, editable: false, data })
                }
            }
            add('pinned', 'Pinned', pinItems(search.pinned))
            add('recent', 'Recent', viewItems(search.recent, 'search', 'recent'))
            for (const [key, title, state] of [
                ['dashboards', 'Dashboards', search.dashboards],
                ['insights', 'Insights', search.insights],
            ] as const) {
                const rows = state.data ? server(state.data) : []
                const note: ListItem | null = state.isLoading
                    ? { type: 'note', key: `${key}:loading`, text: `Searching ${title.toLowerCase()}…` }
                    : state.isError
                      ? {
                            type: 'note',
                            key: `${key}:error`,
                            text: `Couldn't search ${title.toLowerCase()}. Try again in a moment.`,
                        }
                      : null
                add(key, title, note ? [note] : viewItems(rows, 'search', key))
            }
            const browse = browseEntries.filter((entry) =>
                browseEntryLabel(entry).toLowerCase().includes(search.query.toLowerCase())
            )
            add(
                'browse',
                'Browse',
                browse.map(
                    (entry, position): ListItem => ({
                        type: 'browse',
                        key: `browse:${entry}`,
                        entry,
                        position: groupPosition(position, browse.length),
                    })
                )
            )
            if (result.length === 0) {
                result.push({
                    key: 'none',
                    title: 'Results',
                    first: true,
                    editable: false,
                    data: [{ type: 'note', key: 'no-match', text: `No views match “${search.query}”.` }],
                })
            }
            return result
        }

        const withHint = (item: ListItem): ListItem[] =>
            item.type === 'pin' && item.shortcutId === hintTargetId
                ? [
                      { ...item, last: false },
                      { type: 'pin-hint', key: `pin-hint:${item.shortcutId}`, last: item.last },
                  ]
                : [item]
        const pinned: ListItem[] =
            pins.length > 0 ? pinItems(pins).flatMap(withHint) : [{ type: 'empty-pins', key: 'empty-pins' }]
        if (list.pinsTruncated) {
            pinned.push({ type: 'note', key: 'pins-truncated', text: 'Showing 100 pins.' })
        }
        const result: ListSection[] = [
            { key: 'pinned', title: 'Pinned', first: true, editable: pins.length > 0, data: pinned },
        ]
        const recentItems = viewItems(recent, 'recent', 'recent')
        if (recentItems.length > 0) {
            result.push({ key: 'recent', title: 'Recent', first: false, editable: false, data: recentItems })
        }
        result.push({
            key: 'browse',
            title: 'Browse',
            first: false,
            editable: false,
            data: browseEntries.map(
                (entry, position): ListItem => ({
                    type: 'browse',
                    key: `browse:${entry}`,
                    entry,
                    position: groupPosition(position, browseEntries.length),
                })
            ),
        })
        return result
    }, [search, pins, recent, list.pinsTruncated, now, hintTargetId, browseEntries])

    const renderItem = useCallback(
        ({ item }: { item: ListItem }): ReactElement | null => {
            switch (item.type) {
                case 'pin':
                    return (
                        <View style={!item.last && styles.pinGap}>
                            <PinCard
                                pin={item.pin}
                                index={item.index}
                                demo={demo}
                                onOpen={openPin}
                                onMenu={openPinMenu}
                                onChooseTile={chooseTileFromCard}
                                onUnpin={unpinFromCard}
                                onPressTooltip={openPinPoint}
                            />
                        </View>
                    )
                case 'pin-hint':
                    return (
                        <View style={!item.last && styles.pinGap}>
                            <PinHint onDismiss={closeHint} />
                        </View>
                    )
                case 'empty-pins':
                    return <EmptyPins />
                case 'note':
                    return <Text style={styles.note}>{item.text}</Text>
                case 'view': {
                    const pinned = pinTargetFor(item.view) ? pinnedKeys.has(matchKey(item.view)) : null
                    const handlers = item.entry === 'search' ? rowHandlers.search : rowHandlers.recent
                    return (
                        <ViewRow
                            view={item.view}
                            meta={item.meta}
                            position={item.position}
                            pinned={pinned}
                            onOpen={handlers.onOpen}
                            onTogglePin={handlers.onTogglePin}
                            onMenu={handlers.onMenu}
                            testID={`views-${item.entry === 'recent' ? 'recent' : 'result'}-${item.view.kind}-${item.view.ref}`}
                        />
                    )
                }
                case 'browse':
                    return (
                        <BrowseEntryRow
                            entry={item.entry}
                            position={item.position}
                            enabled={browseEntryPin(item.entry) === null || context.mode === 'live'}
                            onPress={openBrowse}
                            onMenu={openBrowseMenu}
                        />
                    )
            }
        },
        [
            demo,
            openPin,
            openPinMenu,
            closeHint,
            chooseTileFromCard,
            unpinFromCard,
            openPinPoint,
            rowHandlers,
            pinnedKeys,
            openBrowse,
            openBrowseMenu,
            context.mode,
            styles,
        ]
    )

    const renderSectionHeader = useCallback(
        ({ section }: { section: ListSection }) => (
            <View style={[styles.sectionHeader, section.first ? styles.firstSection : null]}>
                <Eyebrow>{section.title}</Eyebrow>
                {section.editable ? (
                    <Pressable44
                        onPress={() => startEditing('section')}
                        accessibilityLabel="Edit pins"
                        pressedBackground={colors.sunken}
                        style={styles.edit}
                        testID="views-pinned-edit"
                    >
                        <Text style={styles.editText}>Edit</Text>
                    </Pressable44>
                ) : null}
            </View>
        ),
        [startEditing, styles, colors]
    )

    const contentTop = topOffset(insets, TABS_HEADER_BOTTOM)
    const contentBottom = bottomOffset(insets, 120)
    const { refresh } = list
    const loading = list.pins.data === undefined && !list.pins.isError
    const status = loading ? 'Loading…' : null
    useTabHeader('views', {
        refreshing: !loading && refresh.busy,
        hint: loading ? null : refresh.hint,
        status: editing ? 'Changes save as you go' : status,
        editing: editing ? { title: 'Edit pins', onDone: () => edit.finish('done') } : null,
        editPins: {
            disabled: pins.length === 0,
            onPress: () => {
                setText('')
                startEditing('menu')
            },
        },
        filter: null,
    })
    const menuPin = menu?.kind === 'pin' ? pins.find((pin) => pin.shortcutId === menu.shortcutId) : undefined
    const menuPinIndex = menuPin ? pins.indexOf(menuPin) : -1

    const listFailed = !editing && !loading && list.pins.isError && !list.pins.data
    useEffect(() => {
        if (listFailed) {
            trackViewsErrorShown({ screen: 'list', kind: 'failed' })
        }
    }, [listFailed])

    let body: ReactElement
    if (editing) {
        body = (
            <EditPinsList
                pins={pins}
                contentTop={contentTop}
                contentBottom={contentBottom}
                onReorder={(shortcutIds) => {
                    edit.noteChange()
                    actions.reorder(shortcutIds)
                }}
                onMove={(pin, direction) => {
                    edit.noteChange()
                    actions.move(pin, direction)
                }}
                onMode={(pin, mode) => {
                    if (mode !== pin.display.mode) {
                        edit.noteChange()
                    }
                    showAs(pin, mode)
                }}
                onRemove={(pin) => {
                    edit.noteChange()
                    flows.unpin(pin, 'row_menu')
                }}
            />
        )
    } else if (loading) {
        body = (
            <View style={[styles.content, { paddingTop: contentTop }]}>
                <ViewsSkeleton />
            </View>
        )
    } else if (listFailed) {
        body = (
            <View style={[styles.fill, { paddingTop: contentTop }]}>
                <StateView
                    icon={<WarningIcon size={28} color={colors.tertiary} />}
                    title="Couldn't load your views"
                    message={list.pins.error?.message ?? 'Check your connection and try again.'}
                    actionLabel="Try again"
                    onAction={() => list.pins.refetch()}
                    testID="views-error"
                />
            </View>
        )
    } else {
        body = (
            <SectionList
                ref={listRef}
                sections={sections}
                keyExtractor={keyOf}
                renderItem={renderItem}
                renderSectionHeader={renderSectionHeader}
                stickySectionHeadersEnabled={false}
                ListHeaderComponent={
                    <View style={styles.search}>
                        <SearchField
                            value={text}
                            onChangeText={setText}
                            placeholder="Search views"
                            testID="views-search"
                        />
                    </View>
                }
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                onViewableItemsChanged={onViewableItemsChanged}
                viewabilityConfig={list.viewabilityConfig}
                onScroll={motion.onScroll}
                scrollEventThrottle={16}
                initialNumToRender={INITIAL_VISIBLE_ROWS}
                windowSize={5}
                removeClippedSubviews={Platform.OS === 'android'}
                contentContainerStyle={[styles.content, { paddingTop: contentTop, paddingBottom: contentBottom }]}
                refreshControl={
                    <RefreshControl
                        refreshing={refresh.pulling}
                        onRefresh={refresh.onPull}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={contentTop}
                    />
                }
            />
        )
    }

    return (
        <View style={styles.fill}>
            {body}
            {menu?.kind === 'pin' && menuPin ? (
                <PinMenuFor
                    pin={menuPin}
                    anchor={menu.anchor}
                    position={{ index: menuPinIndex, count: pins.length }}
                    onClose={() => setMenu(null)}
                    onShowAs={(mode) => showAs(menuPin, mode)}
                    onChooseTile={() => openChooseTile(menuPin, 'menu')}
                    onMove={(direction) => {
                        setMenu(null)
                        actions.move(menuPin, direction)
                    }}
                    onUnpin={() => unpinPin(menuPin, 'row_menu')}
                />
            ) : null}
            {menu?.kind === 'row' ? (
                <RowMenu
                    visible
                    anchor={menu.anchor}
                    view={menu.view}
                    pinned={flows.canPin(menu.view) ? pinnedKeys.has(matchKey(menu.view)) : null}
                    onClose={() => setMenu(null)}
                    onTogglePin={() => {
                        setMenu(null)
                        flows.togglePin(menu.view, menu.entry === 'search' ? 'search' : 'row_menu')
                    }}
                    onOpen={() => {
                        setMenu(null)
                        openView(menu.view, menu.entry)
                    }}
                />
            ) : null}
            {menu?.kind === 'nav-pin' ? (
                <NavPinMenu
                    visible
                    anchor={menu.anchor}
                    label={browseEntryLabel(menu.entry)}
                    pinned={navPins.includes(menu.pin)}
                    onClose={() => setMenu(null)}
                    onTogglePin={() => {
                        setMenu(null)
                        changeNavPin(menu.pin, !navPins.includes(menu.pin), 'views_row', showNavToast)
                    }}
                    onOpen={() => {
                        setMenu(null)
                        openBrowse(menu.entry)
                    }}
                />
            ) : null}
            <ChooseTileSheet
                target={chooseTile}
                onClose={() => setChooseTile(null)}
                onChoose={(pin, mode, tile) => actions.chooseTile(pin, mode, tile)}
            />
            <ViewsToast
                toast={flows.toast ?? navToasts.toast}
                onHide={() => {
                    flows.hideToast()
                    navToasts.hide()
                }}
            />
        </View>
    )
}

interface EditPinsSession {
    editing: boolean
    start: (from: EditPinsEntry) => void
    finish: (reason: 'done' | 'no_pins') => void
    noteChange: () => void
}

function useEditPinsSession(pinCount: number): EditPinsSession {
    const [editing, setEditing] = useState(false)
    const session = useRef<{ startedAt: number; changes: number } | null>(null)
    const count = useRef(pinCount)
    count.current = pinCount
    const start = useCallback((from: EditPinsEntry) => {
        if (session.current) {
            return
        }
        session.current = { startedAt: Date.now(), changes: 0 }
        setEditing(true)
        trackEditPinsOpened({ from, pinCount: count.current })
    }, [])
    const finish = useCallback((reason: 'done' | 'no_pins') => {
        const current = session.current
        if (!current) {
            return
        }
        session.current = null
        setEditing(false)
        trackEditPinsClosed({
            reason,
            changes: current.changes,
            durationSeconds: Math.round((Date.now() - current.startedAt) / 1000),
        })
    }, [])
    const noteChange = useCallback(() => {
        if (session.current) {
            session.current.changes++
        }
    }, [])
    return { editing, start, finish, noteChange }
}

interface PinMenuForProps {
    pin: PinView
    anchor: RowAnchor
    position: { index: number; count: number }
    onClose: () => void
    onShowAs: (mode: PinDisplayMode) => void
    onChooseTile: () => void
    onMove: (direction: -1 | 1) => void
    onUnpin: () => void
}

/** The pin menu, with the name of the tile a dashboard pin shows when the dashboard is cached. */
function PinMenuFor({ pin, ...props }: PinMenuForProps): ReactElement {
    const { scope } = useViewsContext()
    const dashboard = useSnapshot<DashboardSnapshot>(
        pin.kind === 'dashboard' && pin.ref ? dashboardQueryKey(scope, pin.ref, null) : null
    )
    // A pin reads its tile's insight, so that read names the tile when the dashboard itself is not cached.
    const { snapshot } = usePinData(pin)
    const tileName =
        pin.kind !== 'dashboard' || pin.display.mode === 'row'
            ? null
            : (dashboard?.view.tiles.find((tile) => tile.tileId === pin.display.tileId)?.name ?? snapshot?.name ?? null)
    return <PinMenu visible pin={pin} modes={pinModes(pin)} tileName={tileName} {...props} />
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
    // The same top margin as the Chats search field, so the field sits at one spot across the two tabs.
    search: {
        marginTop: 4,
    },
    sectionHeader: {
        minHeight: 28,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        marginTop: 22,
        marginBottom: 8,
        marginHorizontal: 4,
    },
    firstSection: {
        marginTop: 18,
    },
    edit: {
        minHeight: 28,
        justifyContent: 'center',
        paddingHorizontal: 6,
        marginRight: -6,
        borderRadius: 8,
    },
    editText: {
        ...type.bodySmallStrong,
        color: colors.blue,
    },
    pinGap: {
        marginBottom: 8,
    },
    note: {
        ...type.meta,
        color: colors.tertiary,
        marginHorizontal: 4,
        marginTop: 2,
    },
}))
