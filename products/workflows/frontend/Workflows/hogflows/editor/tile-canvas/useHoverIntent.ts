import { MouseEvent, useEffect, useRef, useState } from 'react'

/**
 * The browser also reports the pointer entering a tile when the tile moves under a pointer at rest, as when a path
 * opens or collapses in place. Only a pointer that moved means someone is pointing at the tile.
 */
export function isPointerMove(event: MouseEvent): boolean {
    return event.movementX !== 0 || event.movementY !== 0
}

/** `open` turns on a frame after `mounted`, so the card's CSS transition runs from its closed state. */
export function useHoverIntent(
    enabled: boolean,
    openDelayMs: number,
    closeMs: number
): { mounted: boolean; open: boolean; onMouseMove: (event: MouseEvent) => void; onMouseLeave: () => void } {
    const [mounted, setMounted] = useState(false)
    const [open, setOpen] = useState(false)
    const timer = useRef<number>()
    const pending = useRef(false)

    useEffect(() => () => window.clearTimeout(timer.current), [])
    useEffect(() => {
        if (!enabled) {
            window.clearTimeout(timer.current)
            pending.current = false
            setOpen(false)
            setMounted(false)
        }
    }, [enabled])

    return {
        mounted: enabled && mounted,
        open: enabled && open,
        onMouseMove: (event) => {
            if (!enabled || open || pending.current || !isPointerMove(event)) {
                return
            }
            pending.current = true
            window.clearTimeout(timer.current)
            timer.current = window.setTimeout(
                () => {
                    pending.current = false
                    setMounted(true)
                    requestAnimationFrame(() => requestAnimationFrame(() => setOpen(true)))
                },
                mounted ? 0 : openDelayMs
            )
        },
        onMouseLeave: () => {
            pending.current = false
            window.clearTimeout(timer.current)
            setOpen(false)
            timer.current = window.setTimeout(() => setMounted(false), closeMs)
        },
    }
}
