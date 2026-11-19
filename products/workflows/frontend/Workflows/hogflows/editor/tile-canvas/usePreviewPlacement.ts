import { RefObject, useEffect, useState } from 'react'

import { FIT_MARGIN } from './tileCanvasModel'

const VIEW_MARGIN = 12

export interface PreviewPlacement {
    x: number
    above: boolean
}

/**
 * Keeps a card that hangs below a step inside the canvas: it shifts sideways off the canvas edges, and moves
 * above the step when the room below, clear of the controls over the canvas bottom, is too short. A card that
 * moved above stays there, so one that grows as its preview opens does not flip back and forth.
 */
export function usePreviewPlacement(ref: RefObject<HTMLElement>, stepHeight: number): PreviewPlacement {
    const [placement, setPlacement] = useState<PreviewPlacement>({ x: 0, above: false })
    useEffect(() => {
        const card = ref.current
        if (!card) {
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
            setPlacement((current) => {
                const left = box.left - current.x * scale
                const overLeft = canvas.left + VIEW_MARGIN - left
                const overRight = left + box.width - (canvas.right - VIEW_MARGIN)
                const x = (overLeft > 0 ? overLeft : overRight > 0 ? -overRight : 0) / scale
                let above = current.above
                if (!above) {
                    const roomBelow = canvas.bottom - FIT_MARGIN.bottom - box.top
                    const roomAbove = box.top - stepHeight * scale - canvas.top - VIEW_MARGIN
                    above = box.height > roomBelow && roomAbove > roomBelow
                }
                return Math.abs(x - current.x) < 1 && above === current.above ? current : { x, above }
            })
        }
        const observer = new ResizeObserver(measure)
        observer.observe(card)
        measure()
        return () => observer.disconnect()
    }, [ref, stepHeight])
    return placement
}
