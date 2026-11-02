import { createContext, type ReactElement, type ReactNode, type RefObject, useContext, useEffect, useMemo } from 'react'
import { BackHandler, Dimensions, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native'
import { type SharedValue, useSharedValue } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'
import { createStore, type StoreApi, useStore } from 'zustand'

/** Why a pinned tooltip closed. Also the `reason` of `mobile_chart_tooltip_dismissed`. */
export type ChartDismissReason = 'tap_again' | 'outside' | 'other_chart' | 'scrolled' | 'back' | 'data'

interface ChartEntry {
    dismiss: (reason: ChartDismissReason) => void
    viewRef: RefObject<View | null>
}

interface SelectionState {
    pinnedId: string | null
}

export interface ChartSelectionScope {
    store: StoreApi<SelectionState>
    /** A chart registers while mounted, so the scope can close its tooltip. Returns the unregister function. */
    register: (id: string, entry: ChartEntry) => () => void
    /** The chart pinned a point. The chart pinned before it closes. */
    claim: (id: string) => void
    /** The chart closed its own tooltip. */
    release: (id: string) => void
    /** A touch began inside this chart or its legend, so the scope must not treat it as an outside tap. */
    markTouch: (id: string) => void
    /** Epoch ms of the last scroll event from the screen's list. Charts ignore a tap that stops a fling. */
    listMovedAt: SharedValue<number>
    /** Records list motion from JS, for a `FlatList` or `ScrollView` `onScroll`. */
    noteListScroll: () => void
    /** Records list motion from the UI thread, inside a Reanimated scroll handler. */
    noteListScrollWorklet: () => void
}

const ChartSelectionContext = createContext<ChartSelectionScope | null>(null)

// A visibility check per frame would measure on every scroll event. Ten a second is enough to close a tooltip that
// left the screen.
const VISIBILITY_CHECK_MS = 100

/**
 * One pinned chart per screen. Wrap the screen's content; the wrapper fills its parent with `flex: 1`.
 * A tap outside the pinned chart, a pin on another chart, scrolling the chart off screen and Android back close the
 * tooltip. A chart outside any provider keeps its own selection and closes only on a second tap.
 */
export function ChartSelectionProvider({
    children,
    style,
}: {
    children: ReactNode
    style?: StyleProp<ViewStyle>
}): ReactElement {
    const listMovedAt = useSharedValue(0)
    const hasPinned = useSharedValue(false)
    const lastCheckAt = useSharedValue(0)

    const scope = useMemo(() => {
        const store = createStore<SelectionState>(() => ({ pinnedId: null }))
        const entries = new Map<string, ChartEntry>()
        let touchOwner: string | null = null

        const setPinned = (id: string | null): void => {
            store.setState({ pinnedId: id })
            hasPinned.value = id !== null
        }
        const dismissPinned = (reason: ChartDismissReason): void => {
            const pinned = store.getState().pinnedId
            if (pinned === null) {
                return
            }
            setPinned(null)
            entries.get(pinned)?.dismiss(reason)
        }
        const checkPinnedVisible = (): void => {
            const pinned = store.getState().pinnedId
            const view = pinned ? entries.get(pinned)?.viewRef.current : null
            view?.measureInWindow((_x, y, _width, height) => {
                const windowHeight = Dimensions.get('window').height
                if (store.getState().pinnedId === pinned && (y + height <= 0 || y >= windowHeight)) {
                    dismissPinned('scrolled')
                }
            })
        }

        const value: ChartSelectionScope & { onTouchStart: () => void; dismissPinned: typeof dismissPinned } = {
            store,
            register: (id, entry) => {
                entries.set(id, entry)
                return () => {
                    entries.delete(id)
                    if (store.getState().pinnedId === id) {
                        setPinned(null)
                    }
                }
            },
            claim: (id) => {
                const previous = store.getState().pinnedId
                if (previous === id) {
                    return
                }
                setPinned(id)
                if (previous !== null) {
                    entries.get(previous)?.dismiss('other_chart')
                }
            },
            release: (id) => {
                if (store.getState().pinnedId === id) {
                    setPinned(null)
                }
            },
            markTouch: (id) => {
                touchOwner = id
            },
            listMovedAt,
            noteListScroll: () => {
                const now = Date.now()
                listMovedAt.value = now
                if (store.getState().pinnedId !== null && now - lastCheckAt.value > VISIBILITY_CHECK_MS) {
                    lastCheckAt.value = now
                    checkPinnedVisible()
                }
            },
            noteListScrollWorklet: () => {
                'worklet'
                const now = Date.now()
                listMovedAt.value = now
                if (hasPinned.value && now - lastCheckAt.value > VISIBILITY_CHECK_MS) {
                    lastCheckAt.value = now
                    scheduleOnRN(checkPinnedVisible)
                }
            },
            // Touch events bubble from the touched view up, so a chart's own `onTouchStart` has already run.
            onTouchStart: () => {
                const owner = touchOwner
                touchOwner = null
                const pinned = store.getState().pinnedId
                if (pinned !== null && owner !== pinned) {
                    dismissPinned(owner === null ? 'outside' : 'other_chart')
                }
            },
            dismissPinned,
        }
        return value
    }, [listMovedAt, hasPinned, lastCheckAt])

    const pinnedId = useStore(scope.store, (state) => state.pinnedId)
    useEffect(() => {
        if (pinnedId === null) {
            return
        }
        // Added after the navigator's listener, so it runs first: the first back press closes the tooltip.
        const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
            scope.dismissPinned('back')
            return true
        })
        return () => subscription.remove()
    }, [pinnedId, scope])

    return (
        <ChartSelectionContext.Provider value={scope}>
            <View style={[styles.fill, style]} onTouchStart={scope.onTouchStart}>
                {children}
            </View>
        </ChartSelectionContext.Provider>
    )
}

/** The screen's selection scope, or null outside a `ChartSelectionProvider`. */
export function useChartSelectionScope(): ChartSelectionScope | null {
    return useContext(ChartSelectionContext)
}

/** The id of the chart with a pinned tooltip on this screen. */
export function usePinnedChartId(): string | null {
    const scope = useContext(ChartSelectionContext)
    const fallback = useMemo(() => createStore<SelectionState>(() => ({ pinnedId: null })), [])
    return useStore(scope?.store ?? fallback, (state) => state.pinnedId)
}

export interface ChartListMotion {
    /** Pass as `onScroll` to a `FlatList`, `SectionList` or `ScrollView`, with `scrollEventThrottle={16}`. */
    onScroll: () => void
    /** Call inside the `onScroll` of a Reanimated `useAnimatedScrollHandler`. */
    onScrollWorklet: () => void
}

const NO_MOTION: ChartListMotion = {
    onScroll: () => undefined,
    onScrollWorklet: () => {
        'worklet'
    },
}

/** Tells the charts on this screen that the list moves, so a tap that stops a fling does not pin a point. */
export function useChartListMotion(): ChartListMotion {
    const scope = useContext(ChartSelectionContext)
    return useMemo(
        () => (scope ? { onScroll: scope.noteListScroll, onScrollWorklet: scope.noteListScrollWorklet } : NO_MOTION),
        [scope]
    )
}

const styles = StyleSheet.create({
    fill: {
        flex: 1,
    },
})
