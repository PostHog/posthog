import { useReactFlow } from '@xyflow/react'
import { useValues } from 'kea'
import { MutableRefObject, RefObject, useEffect, useRef } from 'react'

import { canvasBounds, tileEntry } from './tileCanvasLayout'
import { tileCanvasLogic } from './tileCanvasLogic'
import {
    Point,
    readableFitViewport,
    Size,
    viewportAfterResize,
    viewportAnchoredOn,
    viewportShowing,
    viewportToFit,
} from './tileCanvasModel'

const FOCUS_MS = 400

const sizeOf = (element: HTMLElement): Size => ({ width: element.clientWidth, height: element.clientHeight })

function useSelectedStepBox(): MutableRefObject<(Point & Size) | undefined> {
    const { layout, measuredSizes, selectedNodeId } = useValues(tileCanvasLogic)
    const box = useRef<(Point & Size) | undefined>()
    const position = selectedNodeId ? layout?.positions[selectedNodeId] : undefined
    const size = selectedNodeId ? measuredSizes?.[selectedNodeId] : undefined
    box.current = position && size ? { ...position, width: size.width, height: size.height } : undefined
    return box
}

/** Without this, the graph stays pinned to the left edge as the docked panel opens and closes, so it
 * slides out of view or off centre. */
function useViewportFollowsResize(wrapperRef: RefObject<HTMLDivElement>): void {
    const reactFlow = useReactFlow()
    const selectedStepBox = useSelectedStepBox()
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }
        let previous = sizeOf(wrapper)
        const observer = new ResizeObserver(() => {
            const next = sizeOf(wrapper)
            if (next.width === previous.width && next.height === previous.height) {
                return
            }
            if (previous.width > 0 && previous.height > 0) {
                void reactFlow.setViewport(
                    viewportAfterResize(reactFlow.getViewport(), previous, next, selectedStepBox.current)
                )
            }
            previous = next
        })
        observer.observe(wrapper)
        return () => observer.disconnect()
    }, [reactFlow, wrapperRef, selectedStepBox])
}

/** A step picked off screen, such as one just added, has no position until the next layout, so it is shown once that lands. */
function useSelectedStepInView(wrapperRef: RefObject<HTMLDivElement>): void {
    const reactFlow = useReactFlow()
    const { selectedNodeId } = useValues(tileCanvasLogic)
    const selectedStepBox = useSelectedStepBox()
    const shownStepId = useRef<string | null>(null)
    const box = selectedStepBox.current
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!selectedNodeId) {
            shownStepId.current = null
            return
        }
        if (!wrapper || !box || shownStepId.current === selectedNodeId) {
            return
        }
        shownStepId.current = selectedNodeId
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        void reactFlow.setViewport(viewportShowing(reactFlow.getViewport(), sizeOf(wrapper), box), {
            duration: reduceMotion ? 0 : FOCUS_MS,
        })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedNodeId, box?.x, box?.y, box?.width, box?.height])
}

/** Edits keep the viewport the person panned or zoomed to; only an explicit fit request moves it. */
function useFitOnRequest(wrapperRef: RefObject<HTMLDivElement>): void {
    const reactFlow = useReactFlow()
    const { fitRequest, layout, measuredSizes, visibleGraph } = useValues(tileCanvasLogic)
    useEffect(() => {
        const wrapper = wrapperRef.current
        const bounds = layout && measuredSizes ? canvasBounds(layout, measuredSizes) : undefined
        if (wrapper && layout && measuredSizes && bounds) {
            const trigger = visibleGraph.nodes.find((node) => node.kind === 'step' && node.action.type === 'trigger')
            const position = trigger && layout.positions[trigger.id]
            const size = trigger && measuredSizes[trigger.id]
            const entry = position && size ? tileEntry(position, size) : { x: bounds.x + bounds.width / 2, y: bounds.y }
            void reactFlow.setViewport(readableFitViewport(bounds, sizeOf(wrapper), entry))
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fitRequest])
}

function useFocusOnPath(wrapperRef: RefObject<HTMLDivElement>): void {
    const reactFlow = useReactFlow()
    const { viewportFocus } = useValues(tileCanvasLogic)
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper || !viewportFocus) {
            return
        }
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        const viewport = reactFlow.getViewport()
        const canvas = sizeOf(wrapper)
        const target = viewportFocus.anchor
            ? viewportAnchoredOn(viewportFocus.anchor, viewportFocus.place, viewport, canvas)
            : viewportToFit(viewportFocus.place, canvas, viewport.zoom)
        // An anchored move runs while the path motion moves the nodes, and the canvas's own transition then moves the
        // view in step with them. A second, animated move on top would let the path drift away from its anchor.
        void reactFlow.setViewport(target, { duration: reduceMotion || viewportFocus.anchor ? 0 : FOCUS_MS })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [viewportFocus?.request])
}

export function useCanvasViewport(wrapperRef: RefObject<HTMLDivElement>): void {
    useViewportFollowsResize(wrapperRef)
    useSelectedStepInView(wrapperRef)
    useFitOnRequest(wrapperRef)
    useFocusOnPath(wrapperRef)
}
