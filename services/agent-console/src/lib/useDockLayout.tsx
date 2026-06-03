/**
 * Dock layout preference — `rail` or `floating`.
 *
 * - `rail` is the original behaviour: the dock is pinned to the right
 *   edge inside the resizable panel group, full height.
 * - `floating` is a draggable, resizable, snappable panel that the
 *   user can park anywhere on screen. Snap targets:
 *     - `left` / `right` — full-height vertical strip pinned to that edge
 *     - `top-left` / `top-right` / `bottom-left` / `bottom-right` — the
 *       panel keeps its natural width + height and hugs that corner
 *   Top/bottom (full-width horizontal strips) is deliberately not
 *   supported — the drag handle would be inside the strip and hard to
 *   reach.
 *
 * State is owned by `<DockLayoutProvider>` at the app shell level so
 * the shell (which decides where to mount the dock) and the dock's
 * own header (which renders the mode toggle) read the same source.
 * Persisted to `localStorage` under a stable key.
 */

'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const STORAGE_KEY = 'agent-console:dock-layout'

export type DockMode = 'rail' | 'floating'
export type DockSnap = 'left' | 'right' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | null

const VALID_SNAPS: ReadonlySet<DockSnap> = new Set<DockSnap>([
    'left',
    'right',
    'top-left',
    'top-right',
    'bottom-left',
    'bottom-right',
    null,
])

export interface FloatingGeometry {
    /** Top-left x in viewport px when free-floating. Ignored while snapped. */
    x: number
    /** Top-left y in viewport px when free-floating. Ignored while snapped. */
    y: number
    /** Width in px when free-floating, OR when snapped (the strip's width). */
    w: number
    /** Height in px when free-floating. Snapped strips use the full viewport height. */
    h: number
    /** Snap target. `null` = free-floating. */
    snap: DockSnap
}

export interface DockLayout {
    mode: DockMode
    floating: FloatingGeometry
    /**
     * Dock visibility — when `false`, the chat panel is hidden and a
     * compact "show dock" affordance takes its place (a tab on the
     * matching screen edge for floating mode, a corner button for the
     * rail). Toggled by `Cmd/Ctrl + .` or the chrome controls.
     */
    visible: boolean
}

export interface UseDockLayout {
    layout: DockLayout
    setMode: (next: DockMode) => void
    setFloating: (next: FloatingGeometry | ((prev: FloatingGeometry) => FloatingGeometry)) => void
    setVisible: (next: boolean) => void
    toggleVisible: () => void
    /**
     * Currently-registered embed target. When non-null, the AppShell
     * portals the Dock into this node instead of the rail / floating
     * chrome — used by the overview page to put the chat front-and-
     * centre on landing instead of pinned to the side. Pages register
     * their slot via `useDockEmbedSlot()` and the registration clears
     * on unmount.
     */
    embedSlot: HTMLDivElement | null
    setEmbedSlot: (node: HTMLDivElement | null) => void
}

/** Sensible defaults if storage is empty. First float starts pinned right;
 *  if the user tears off, free-floating geometry has a reasonable size
 *  and isn't flush against the top-left. Dock is visible by default. */
const DEFAULT_LAYOUT: DockLayout = {
    mode: 'rail',
    floating: { x: 240, y: 80, w: 420, h: 600, snap: 'right' },
    visible: true,
}

const DEFAULT_STORE: UseDockLayout = {
    layout: DEFAULT_LAYOUT,
    setMode: () => {},
    setFloating: () => {},
    setVisible: () => {},
    toggleVisible: () => {},
    embedSlot: null,
    setEmbedSlot: () => {},
}

/**
 * Global keyboard shortcut for toggling the dock. `Cmd/Ctrl + .` matches
 * Slack's "close panel" convention and is unlikely to conflict with text
 * input (period is not a modifier-key shortcut in any textarea). We
 * `preventDefault` so the browser doesn't also fire its "stop loading"
 * behaviour on macOS.
 */
export const DOCK_TOGGLE_KEY_HINT = '⌘.'
export const DOCK_TOGGLE_KEY_HINT_PC = 'Ctrl+.'

function matchesToggleShortcut(e: KeyboardEvent): boolean {
    if (!(e.metaKey || e.ctrlKey)) {
        return false
    }
    if (e.altKey || e.shiftKey) {
        return false
    }
    return e.key === '.'
}

const DockLayoutContext = createContext<UseDockLayout>(DEFAULT_STORE)

export function DockLayoutProvider({ children }: { children: React.ReactNode }): React.ReactElement {
    const [layout, setLayout] = useState<DockLayout>(DEFAULT_LAYOUT)
    const [embedSlot, setEmbedSlotState] = useState<HTMLDivElement | null>(null)

    // Hydrate from storage on mount. SSR renders with the default; the
    // first paint after mount swaps to the persisted layout.
    useEffect(() => {
        setLayout(readStored())
    }, [])

    const setMode = useCallback((next: DockMode) => {
        setLayout((prev) => {
            const updated = { ...prev, mode: next }
            writeStored(updated)
            return updated
        })
    }, [])

    const setFloating = useCallback((next: FloatingGeometry | ((prev: FloatingGeometry) => FloatingGeometry)) => {
        setLayout((prev) => {
            const resolved = typeof next === 'function' ? next(prev.floating) : next
            const updated = { ...prev, floating: resolved }
            writeStored(updated)
            return updated
        })
    }, [])

    const setVisible = useCallback((next: boolean) => {
        setLayout((prev) => {
            if (prev.visible === next) {
                return prev
            }
            const updated = { ...prev, visible: next }
            writeStored(updated)
            return updated
        })
    }, [])

    const toggleVisible = useCallback(() => {
        setLayout((prev) => {
            const updated = { ...prev, visible: !prev.visible }
            writeStored(updated)
            return updated
        })
    }, [])

    // Global Cmd/Ctrl+. toggles the dock from anywhere — chat input
    // included, so a power user can hide the panel mid-typing.
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent): void => {
            if (!matchesToggleShortcut(e)) {
                return
            }
            e.preventDefault()
            toggleVisible()
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [toggleVisible])

    // Stable setter — pages call this from a callback ref, so it must
    // never change identity (otherwise the ref would re-fire and clear
    // itself each render).
    const setEmbedSlot = useCallback((node: HTMLDivElement | null) => setEmbedSlotState(node), [])

    const value = useMemo<UseDockLayout>(
        () => ({ layout, setMode, setFloating, setVisible, toggleVisible, embedSlot, setEmbedSlot }),
        [layout, setMode, setFloating, setVisible, toggleVisible, embedSlot, setEmbedSlot]
    )
    return <DockLayoutContext.Provider value={value}>{children}</DockLayoutContext.Provider>
}

export function useDockLayout(): UseDockLayout {
    return useContext(DockLayoutContext)
}

/**
 * Register a DOM node as the active dock embed target. Returns the
 * callback ref the page attaches to the container that should host
 * the dock. Cleared on unmount so the dock falls back to the rail /
 * floating chrome when the user navigates away.
 */
export function useDockEmbedSlot(): (node: HTMLDivElement | null) => void {
    const { setEmbedSlot } = useDockLayout()
    return setEmbedSlot
}

/* ── Storage helpers ────────────────────────────────────────────── */

function readStored(): DockLayout {
    if (typeof window === 'undefined') {
        return DEFAULT_LAYOUT
    }
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY)
        if (!raw) {
            return DEFAULT_LAYOUT
        }
        const parsed = JSON.parse(raw) as Partial<DockLayout> & { floating?: Partial<FloatingGeometry> }
        const mode: DockMode = parsed.mode === 'floating' ? 'floating' : 'rail'
        const snapRaw = parsed.floating?.snap
        // Treat anything we don't recognise (older saved values, hand-edited
        // storage, future variants we removed) as free-floating.
        const snap: DockSnap = VALID_SNAPS.has(snapRaw as DockSnap) ? (snapRaw as DockSnap) : null
        // `visible` defaults to true for backwards-compat with stored
        // layouts written before this field existed.
        const visible = parsed.visible === false ? false : true
        return {
            mode,
            visible,
            floating: {
                x: numberOr(parsed.floating?.x, DEFAULT_LAYOUT.floating.x),
                y: numberOr(parsed.floating?.y, DEFAULT_LAYOUT.floating.y),
                w: numberOr(parsed.floating?.w, DEFAULT_LAYOUT.floating.w),
                h: numberOr(parsed.floating?.h, DEFAULT_LAYOUT.floating.h),
                snap,
            },
        }
    } catch {
        return DEFAULT_LAYOUT
    }
}

function numberOr(value: unknown, fallback: number): number {
    return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function writeStored(layout: DockLayout): void {
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout))
    } catch {
        // Quota / private window — keep in-memory state only.
    }
}
