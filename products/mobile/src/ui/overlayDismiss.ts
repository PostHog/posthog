import { createContext, useContext } from 'react'
import { create } from 'zustand'

export const OverlayDismissContext = createContext<{
    set: (key: string, close: (() => void) | null) => void
    close: (() => void) | null
} | null>(null)

export function useOverlayDismiss(): (() => void) | null {
    return useContext(OverlayDismissContext)?.close ?? null
}

export const useNavigationOverlayStore = create<{
    keys: string[]
    set: (key: string, visible: boolean) => void
}>()((set) => ({
    keys: [],
    set: (key, visible) =>
        set((state) => ({
            keys: visible
                ? [...state.keys.filter((item) => item !== key), key]
                : state.keys.filter((item) => item !== key),
        })),
}))
