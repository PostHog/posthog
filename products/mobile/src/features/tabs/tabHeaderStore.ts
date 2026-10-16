import { useLayoutEffect, useMemo, useRef } from 'react'
import { create } from 'zustand'

import type { RefreshButtonState } from '@/ui/RefreshButton'

export type TabKey = 'inbox' | 'chats' | 'views'

export interface TabHeaderRefresh {
    state: RefreshButtonState
    onPress: () => void
    blockedLabel?: string
    /** A short line under the status line, such as why a refresh did nothing. */
    hint?: string | null
}

export interface TabHeaderSlot {
    /** Null draws the refresh button disabled, for example while the screen has nothing loaded. */
    refresh: TabHeaderRefresh | null
    status: string | null
    /** An edit mode replaces the title and swaps the controls for a Done button. */
    editing: { title: string; onDone: () => void } | null
    editPins: { disabled: boolean; onPress: () => void } | null
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
    slots: { inbox: null, chats: null, views: null },
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
            refresh: (): void => latest.current.refresh?.onPress(),
            done: (): void => latest.current.editing?.onDone(),
            editPins: (): void => latest.current.editPins?.onPress(),
        }),
        []
    )

    const { refresh, status, editing, editPins } = slot
    const hasRefresh = refresh !== null
    const refreshState = refresh?.state
    const blockedLabel = refresh?.blockedLabel
    const hint = refresh?.hint ?? null
    const editingTitle = editing?.title ?? null
    const hasEditPins = editPins !== null
    const editPinsDisabled = editPins?.disabled ?? false
    useLayoutEffect(() => {
        useTabHeaderStore.getState().setSlot(tab, {
            refresh:
                hasRefresh && refreshState
                    ? { state: refreshState, onPress: callbacks.refresh, blockedLabel, hint }
                    : null,
            status,
            editing: editingTitle === null ? null : { title: editingTitle, onDone: callbacks.done },
            editPins: hasEditPins ? { disabled: editPinsDisabled, onPress: callbacks.editPins } : null,
        })
    }, [
        tab,
        callbacks,
        hasRefresh,
        refreshState,
        blockedLabel,
        hint,
        status,
        editingTitle,
        hasEditPins,
        editPinsDisabled,
    ])

    useLayoutEffect(() => () => useTabHeaderStore.getState().setSlot(tab, null), [tab])
}
