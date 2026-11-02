import { MouseEvent, useEffect, useRef, useState } from 'react'

import { HOVER_CARD_CLOSE_MS, HOVER_CARD_OPEN_DELAY_MS } from '../TileHoverCard'
import { isPointerMove } from '../useHoverIntent'

export interface PreviewCard {
    mounted: boolean
    open: boolean
    onMouseMove: (event: MouseEvent) => void
    onMouseLeave: () => void
}

/**
 * Hover opens the card as the editor does, and an expanded step keeps it open. After a collapse under the pointer the
 * card stays closed until the pointer leaves, so it does not open again under a pointer that has not moved away.
 */
export function usePreviewCard(expanded: boolean): PreviewCard {
    const [hovered, setHovered] = useState(false)
    const [present, setPresent] = useState(false)
    const [open, setOpen] = useState(false)
    const resting = useRef(false)
    const pointerInside = useRef(false)
    const wasExpanded = useRef(expanded)
    const timer = useRef<number>()
    const pending = useRef(false)
    const wanted = expanded || hovered

    useEffect(() => {
        window.clearTimeout(timer.current)
        pending.current = false
        if (wasExpanded.current && !expanded) {
            resting.current = pointerInside.current
            setHovered(false)
        }
        wasExpanded.current = expanded
    }, [expanded])

    useEffect(() => {
        if (!wanted) {
            setOpen(false)
            const closing = window.setTimeout(() => setPresent(false), HOVER_CARD_CLOSE_MS)
            return () => window.clearTimeout(closing)
        }
        setPresent(true)
        let frame = requestAnimationFrame(() => {
            frame = requestAnimationFrame(() => setOpen(true))
        })
        return () => cancelAnimationFrame(frame)
    }, [wanted])

    useEffect(() => () => window.clearTimeout(timer.current), [])

    return {
        mounted: wanted || present,
        open: wanted && open,
        onMouseMove: (event) => {
            pointerInside.current = true
            if (expanded || hovered || resting.current || pending.current || !isPointerMove(event)) {
                return
            }
            pending.current = true
            timer.current = window.setTimeout(() => {
                pending.current = false
                setHovered(true)
            }, HOVER_CARD_OPEN_DELAY_MS)
        },
        onMouseLeave: () => {
            pointerInside.current = false
            resting.current = false
            pending.current = false
            window.clearTimeout(timer.current)
            setHovered(false)
        },
    }
}
