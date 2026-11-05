import { RefObject, useEffect, useState } from 'react'

import type { Point } from './tileCanvasModel'

const VIEW_MARGIN = 12

/** Shifts a card back inside the canvas. `bottomMargin` keeps it clear of what floats over the canvas bottom. */
export function useKeepInView(ref: RefObject<HTMLElement>, active: boolean, bottomMargin: number = VIEW_MARGIN): Point {
    const [shift, setShift] = useState<Point>({ x: 0, y: 0 })
    useEffect(() => {
        const card = ref.current
        if (!card || !active) {
            setShift({ x: 0, y: 0 })
            return
        }
        const measure = (): void => {
            const canvas = card.closest('.react-flow')?.getBoundingClientRect()
            const box = card.getBoundingClientRect()
            if (!canvas || !card.offsetWidth) {
                return
            }
            // The canvas may be zoomed, so the card's screen size differs from its layout size.
            const scale = box.width / card.offsetWidth
            setShift((current) => {
                const left = box.left - current.x * scale
                const top = box.top - current.y * scale
                const overRight = left + box.width - (canvas.right - VIEW_MARGIN)
                const overBottom = top + box.height - (canvas.bottom - bottomMargin)
                const x = overRight > 0 ? -Math.min(overRight, left - canvas.left - VIEW_MARGIN) : 0
                const y = overBottom > 0 ? -Math.min(overBottom, top - canvas.top - VIEW_MARGIN) : 0
                const next = { x: x / scale, y: y / scale }
                return Math.abs(next.x - current.x) < 1 && Math.abs(next.y - current.y) < 1 ? current : next
            })
        }
        const observer = new ResizeObserver(measure)
        observer.observe(card)
        measure()
        return () => observer.disconnect()
    }, [ref, active, bottomMargin])
    return shift
}
