import { useLayoutEffect, useMemo, useRef } from 'react'
import { create } from 'zustand'

export type TabKey = 'inbox' | 'chats' | 'views' | 'errors' | 'replay'

export interface TabHeaderSlot {
    refreshing?: boolean
    /** A short line under the status line, such as why a pull to refresh did nothing. */
    hint: string | null
    status: string | null
    /** An edit mode replaces the title and swaps the controls for a Done button. */
    editing: { title: string; onDone: () => void } | null
    editPins: { disabled: boolean; onPress: () => void } | null
    /** The Inbox publishes this; the header then shows a filter button left of More. */
    filter: { active: boolean; onPress: () => void } | null
}

interface TabHeaderState {
    focused: TabKey
    slots: Record<TabKey, TabHeaderSlot | null>
    setFocused: (tab: TabKey) => void
    setSlot: (tab: TabKey, slot: TabHeaderSlot | null) => void
}

// One slot per tab, so a screen that renders while another tab is focused never overwrites the focused tab's header.
export const useTabHeaderStore = create<TabHeaderState>()((set) => ({
    focused: 'inbox',
    slots: { inbox: null, chats: null, views: null, errors: null, replay: null },
    setFocused: (focused) => set({ focused }),
    setSlot: (tab, slot) => set((state) => ({ slots: { ...state.slots, [tab]: slot } })),
}))

export function useFocusedTabHeader(): { tab: TabKey; slot: TabHeaderSlot | null } {
    const tab = useTabHeaderStore((state) => state.focused)
    const slot = useTabHeaderStore((state) => state.slots[state.focused])
    return { tab, slot }
}

/**
 * Publishes a screen's header state to the shared tabs header. The store gets stable callbacks that call the latest
 * ones, so it changes only when something the header draws changes, not on every render of the screen.
 */
export function useTabHeader(tab: TabKey, slot: TabHeaderSlot): void {
    const latest = useRef(slot)
    latest.current = slot
    const callbacks = useMemo(
        () => ({
            done: (): void => latest.current.editing?.onDone(),
            editPins: (): void => latest.current.editPins?.onPress(),
            filter: (): void => latest.current.filter?.onPress(),
        }),
        []
    )

    const { hint, status, editing, editPins, filter, refreshing = false } = slot
    const editingTitle = editing?.title ?? null
    const hasEditPins = editPins !== null
    const editPinsDisabled = editPins?.disabled ?? false
    const hasFilter = filter !== null
    const filterActive = filter?.active ?? false
    useLayoutEffect(() => {
        useTabHeaderStore.getState().setSlot(tab, {
            refreshing,
            hint,
            status,
            editing: editingTitle === null ? null : { title: editingTitle, onDone: callbacks.done },
            editPins: hasEditPins ? { disabled: editPinsDisabled, onPress: callbacks.editPins } : null,
            filter: hasFilter ? { active: filterActive, onPress: callbacks.filter } : null,
        })
    }, [tab, callbacks, hint, status, editingTitle, hasEditPins, editPinsDisabled, hasFilter, filterActive, refreshing])

    useLayoutEffect(() => () => useTabHeaderStore.getState().setSlot(tab, null), [tab])
}
