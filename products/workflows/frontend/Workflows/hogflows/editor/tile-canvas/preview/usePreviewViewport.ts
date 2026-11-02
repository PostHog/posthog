import { RefObject, useLayoutEffect, useRef, useState } from 'react'

import type { Box } from '../tileCanvasLayout'
import { type Point, readableFitViewport } from '../tileCanvasModel'

/**
 * Zooms the preview the way the editor fits a workflow, never below a readable size. A workflow still too wide
 * for the chat scrolls sideways, and starts at its trigger, which usually sits above the middle of its paths.
 */
export function usePreviewViewport(
    scroller: RefObject<HTMLElement>,
    bounds: Box | null,
    trigger: Point | null,
    padding: number,
    keepZoom: boolean
): number {
    const [width, setWidth] = useState(0)
    const zoom = useRef(1)
    const startedAtTrigger = useRef(false)

    useLayoutEffect(() => {
        const element = scroller.current
        if (!element) {
            return
        }
        setWidth(element.clientWidth)
        if (typeof ResizeObserver === 'undefined') {
            return
        }
        const observer = new ResizeObserver(() => setWidth(element.clientWidth))
        observer.observe(element)
        return () => observer.disconnect()
    }, [scroller])

    const view =
        bounds && width
            ? readableFitViewport(
                  {
                      x: bounds.x - padding,
                      y: bounds.y - padding,
                      width: bounds.width + padding * 2,
                      height: bounds.height + padding * 2,
                  },
                  { width, height: Number.MAX_SAFE_INTEGER },
                  trigger ?? { x: bounds.x + bounds.width / 2, y: bounds.y }
              )
            : null
    if (view && !keepZoom) {
        zoom.current = view.zoom
    }

    useLayoutEffect(() => {
        const element = scroller.current
        if (!element || !view || !bounds || startedAtTrigger.current) {
            return
        }
        startedAtTrigger.current = true
        element.scrollLeft = (padding - bounds.x) * view.zoom - view.x
    }, [scroller, view, bounds, padding])

    return zoom.current
}
