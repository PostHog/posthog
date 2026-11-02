import { RefObject, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { type Box, canvasBounds, type CanvasLayout, layoutTileCanvas, type NodeSize } from '../tileCanvasLayout'
import type { Point, VisibleGraph } from '../tileCanvasModel'
import { useFontsLoaded } from '../useFontsLoaded'

export interface PreviewNodeSize extends NodeSize {
    /** Where the step sits inside its measured box, which grows past it when the step's card is open. */
    offset: Point
}

export type PreviewLayout =
    | { kind: 'measuring' }
    | { kind: 'failed' }
    | { kind: 'ready'; layout: CanvasLayout; sizes: Record<string, PreviewNodeSize>; bounds: Box; moves: number }

const NO_BOUNDS: Box = { x: 0, y: 0, width: 0, height: 0 }

/** The canvas may be zoomed out, so screen sizes are divided back into layout sizes. */
function sizeOf(node: HTMLElement, expanded: boolean): PreviewNodeSize {
    const own = node.getBoundingClientRect()
    const scale = node.offsetWidth ? own.width / node.offsetWidth : 1
    const card = expanded ? node.querySelector<HTMLElement>('[data-tile-card]')?.getBoundingClientRect() : undefined
    const left = Math.min(own.left, card?.left ?? own.left)
    const top = Math.min(own.top, card?.top ?? own.top)
    const right = Math.max(own.right, card?.right ?? own.right)
    const bottom = Math.max(own.bottom, card?.bottom ?? own.bottom)
    const anchor = node.querySelector<HTMLElement>('[data-tile-anchor]')?.getBoundingClientRect()
    return {
        width: (right - left) / scale,
        height: (bottom - top) / scale,
        offset: { x: (own.left - left) / scale, y: (own.top - top) / scale },
        anchor: anchor && {
            x: (anchor.left - left + anchor.width / 2) / scale,
            y: (anchor.top - top + anchor.height / 2) / scale,
            width: anchor.width / scale,
            height: anchor.height / scale,
        },
    }
}

function measureNodes(root: HTMLElement, expandedId: string | null): Record<string, PreviewNodeSize> {
    return Object.fromEntries(
        [...root.querySelectorAll<HTMLElement>('[data-preview-node]')].map((node) => {
            const id = node.dataset.previewNode as string
            return [id, sizeOf(node, id === expandedId)]
        })
    )
}

export function usePreviewLayout(
    root: RefObject<HTMLElement>,
    graph: VisibleGraph,
    expandedId: string | null
): PreviewLayout {
    const [layout, setLayout] = useState<PreviewLayout>({ kind: 'measuring' })
    const [resizes, setResizes] = useState(0)
    const fontsLoaded = useFontsLoaded()
    const lastInput = useRef<string>()
    const run = useRef(0)

    useLayoutEffect(() => {
        const container = root.current
        if (!container) {
            return
        }
        const sizes = measureNodes(container, expandedId)
        const input = JSON.stringify([sizes, graph.edges])
        if (input === lastInput.current) {
            return
        }
        lastInput.current = input
        const current = ++run.current
        layoutTileCanvas(sizes, graph.edges, []).then(
            (next) =>
                current === run.current &&
                setLayout((previous) => ({
                    kind: 'ready',
                    layout: next,
                    sizes,
                    bounds: canvasBounds(next, sizes) ?? NO_BOUNDS,
                    moves: previous.kind === 'ready' ? previous.moves + 1 : 0,
                })),
            () => current === run.current && setLayout({ kind: 'failed' })
        )
    }, [root, graph, expandedId, fontsLoaded, resizes])

    useEffect(() => {
        const container = root.current
        if (!container || typeof ResizeObserver === 'undefined') {
            return
        }
        const observer = new ResizeObserver(() => setResizes((count) => count + 1))
        container.querySelectorAll('[data-preview-node], [data-tile-card]').forEach((node) => observer.observe(node))
        return () => observer.disconnect()
    }, [root, graph, expandedId])

    return layout
}
