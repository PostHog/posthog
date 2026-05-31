/**
 * `usePersistedWidth` — drag-to-resize sidebar width, persisted to
 * `localStorage` per `storageKey`.
 *
 * Returns the current width and an `onResizeStart` handler to wire up
 * a draggable handle. Width is committed to storage on mouseup so we
 * don't thrash localStorage during a drag. SSR-safe: the lazy
 * initializer falls back to `defaultWidth` when `window` is missing
 * and reads the persisted value via `useEffect` on mount.
 *
 * Designed for the `<FileExplorer>` left-pane resizer; reuse anywhere
 * a single width number needs persistence.
 */

'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export interface UsePersistedWidthOpts {
    /** Distinct per surface — e.g. `'file-explorer:bundle'`. */
    storageKey: string
    /** Used until a persisted value loads (and as the SSR initial value). */
    defaultWidth: number
    min: number
    max: number
}

export interface UsePersistedWidthResult {
    width: number
    /** Wire this onto the handle's `onMouseDown`. */
    onResizeStart: (e: React.MouseEvent) => void
    /** True while the user is actively dragging — useful for cursor / overlay styling. */
    isResizing: boolean
}

export function usePersistedWidth({
    storageKey,
    defaultWidth,
    min,
    max,
}: UsePersistedWidthOpts): UsePersistedWidthResult {
    const [width, setWidth] = useState<number>(defaultWidth)
    const [isResizing, setIsResizing] = useState(false)
    const widthRef = useRef(width)
    widthRef.current = width

    // Lazy-load persisted value once on mount. Skipped under SSR.
    useEffect(() => {
        if (typeof window === 'undefined') {
            return
        }
        try {
            const raw = window.localStorage.getItem(storageKey)
            if (raw == null) {
                return
            }
            const n = Number(raw)
            if (Number.isFinite(n)) {
                setWidth(clamp(n, min, max))
            }
        } catch {
            // Corrupt entry / blocked storage — keep the default.
        }
    }, [storageKey, min, max])

    const onResizeStart = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            const startX = e.clientX
            const startWidth = widthRef.current
            setIsResizing(true)

            const onMove = (ev: MouseEvent): void => {
                const next = clamp(startWidth + (ev.clientX - startX), min, max)
                setWidth(next)
            }
            const onUp = (): void => {
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
                setIsResizing(false)
                try {
                    window.localStorage.setItem(storageKey, String(widthRef.current))
                } catch {
                    // Quota / private mode — width stays in memory only.
                }
            }
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [storageKey, min, max]
    )

    return { width, onResizeStart, isResizing }
}

function clamp(n: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, n))
}
