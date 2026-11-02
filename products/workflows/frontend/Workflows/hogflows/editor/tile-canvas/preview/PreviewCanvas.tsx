import './WorkflowCanvasPreview.css'

import { RefObject, useEffect, useMemo, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { StepGraph } from '../stepFacts'
import { computeVisibleGraph, type Point, type VisibleGraph } from '../tileCanvasModel'
import { PreviewEdges } from './PreviewEdges'
import { PreviewStepNode } from './PreviewStepNode'
import { type PreviewLayout, usePreviewLayout } from './usePreviewLayout'
import { usePreviewViewport } from './usePreviewViewport'
import type { WorkflowCanvasPreviewProps } from './workflowCanvasPreviewContract'

const PADDING = 24
const ORIGIN: Point = { x: 0, y: 0 }

type ReadyLayout = Extract<PreviewLayout, { kind: 'ready' }>

export function PreviewCanvas({
    actions,
    edges,
    exitCondition,
    isDarkModeOn,
}: WorkflowCanvasPreviewProps): JSX.Element {
    // The API returns the same actions and edges the editor reads, typed from the serializer instead of the schema.
    const workflow = useMemo(
        () => ({ actions, edges, exit_condition: exitCondition }) as unknown as StepGraph,
        [actions, edges, exitCondition]
    )
    const graph = useMemo(() => computeVisibleGraph(workflow, [], []), [workflow])
    const [expandedId, setExpandedId] = useState<string | null>(null)
    const ref = useRef<HTMLDivElement>(null)
    const scroller = useRef<HTMLDivElement>(null)
    const placed = usePreviewLayout(ref, graph, expandedId)
    const ready = placed.kind === 'ready' ? placed : null
    const trigger = ready && triggerPoint(graph, ready)
    const zoom = usePreviewViewport(scroller, ready?.bounds ?? null, trigger, PADDING, expandedId !== null)
    useShowExpandedStep(scroller, ready, expandedId, zoom)

    if (placed.kind === 'failed') {
        throw new Error('The workflow steps could not be laid out')
    }
    const shift = ready ? { x: PADDING - ready.bounds.x, y: PADDING - ready.bounds.y } : ORIGIN
    const toggle = (actionId: string): void => setExpandedId((current) => (current === actionId ? null : actionId))

    const size = ready && { width: ready.bounds.width + PADDING * 2, height: ready.bounds.height + PADDING * 2 }

    return (
        <div
            ref={scroller}
            className={cn(
                'WorkflowCanvasPreview max-h-150 overflow-auto rounded-md border',
                ready && ready.moves > 0 && 'WorkflowCanvasPreview--moving'
            )}
        >
            <div
                className={cn('relative mx-auto', !size && 'invisible h-40')}
                style={size ? { width: size.width * zoom, height: size.height * zoom } : {}}
            >
                <div
                    ref={ref}
                    className="WorkflowCanvasPreview__zoom absolute left-0 top-0 origin-top-left"
                    style={size ? { ...size, transform: `scale(${zoom})` } : {}}
                >
                    {ready && (
                        <PreviewEdges key={ready.moves} edges={graph.edges} layout={ready.layout} shift={shift} />
                    )}
                    {graph.nodes.map((node) => {
                        if (node.kind !== 'step') {
                            return null
                        }
                        const position = ready?.layout.positions[node.id]
                        const offset = ready?.sizes[node.id]?.offset ?? ORIGIN
                        const at = position
                            ? { x: position.x + offset.x + shift.x, y: position.y + offset.y + shift.y }
                            : ORIGIN
                        return (
                            <PreviewStepNode
                                key={node.id}
                                action={node.action}
                                workflow={workflow}
                                isDarkModeOn={isDarkModeOn}
                                expanded={expandedId === node.id}
                                at={at}
                                onToggle={toggle}
                            />
                        )
                    })}
                </div>
            </div>
        </div>
    )
}

const VIEW_MARGIN = 12

/** The scroll offset that brings `start` to `end` into a view of `visible` length, or `scrolled` when it already shows. */
function scrollToShow(start: number, end: number, scrolled: number, visible: number): number {
    return start < scrolled || end > scrolled + visible ? Math.min(start, end - visible) : scrolled
}

/** An expanded step grows past the edge of a long or wide workflow, so the canvas scrolls until all of it shows. */
function useShowExpandedStep(
    scroller: RefObject<HTMLElement>,
    ready: ReadyLayout | null,
    expandedId: string | null,
    zoom: number
): void {
    useEffect(() => {
        const element = scroller.current
        const position = expandedId ? ready?.layout.positions[expandedId] : undefined
        const size = expandedId ? ready?.sizes[expandedId] : undefined
        if (!element || !ready || !position || !size) {
            return
        }
        const x = (position.x + PADDING - ready.bounds.x) * zoom
        const y = (position.y + PADDING - ready.bounds.y) * zoom
        const left = scrollToShow(
            x - VIEW_MARGIN,
            x + size.width * zoom + VIEW_MARGIN,
            element.scrollLeft,
            element.clientWidth
        )
        const top = scrollToShow(
            y - VIEW_MARGIN,
            y + size.height * zoom + VIEW_MARGIN,
            element.scrollTop,
            element.clientHeight
        )
        if (left !== element.scrollLeft || top !== element.scrollTop) {
            element.scrollTo?.({ left, top, behavior: 'smooth' })
        }
    }, [scroller, ready, expandedId, zoom])
}

function triggerPoint(graph: VisibleGraph, ready: ReadyLayout): Point | null {
    const trigger = graph.nodes.find((node) => node.kind === 'step' && node.action.type === 'trigger')
    const position = trigger && ready.layout.positions[trigger.id]
    const anchor = trigger && ready.sizes[trigger.id]?.anchor
    return position && anchor ? { x: position.x + anchor.x, y: position.y + anchor.y } : null
}
