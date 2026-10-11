import { BaseEdge, EdgeLabelRenderer, EdgeProps } from '@xyflow/react'
import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowActionEdge, HogFlowEdge } from '../types'
import { MINIMUM_EDGE_SPACING } from './constants'

// Spreads edges that share a source evenly around the source handle: branches first by index, then continue.
// Runs once per edges change in O(E log E), so each edge does not scan the whole edge list on render.
export function getEdgeHorizontalOffsets(
    edges: HogFlowEdge[],
    getId: (edge: HogFlowEdge) => string
): Map<string, number> {
    const edgesBySource = new Map<string, HogFlowEdge[]>()
    for (const edge of edges) {
        const siblings = edgesBySource.get(edge.from)
        if (siblings) {
            siblings.push(edge)
        } else {
            edgesBySource.set(edge.from, [edge])
        }
    }

    const offsets = new Map<string, number>()
    for (const siblings of edgesBySource.values()) {
        const sortedEdges = [...siblings].sort((a, b) => {
            if (a.type === 'branch' && b.type === 'branch') {
                return (a.index || 0) - (b.index || 0)
            }
            return a.type === 'continue' ? 1 : -1
        })
        const centerIndex = (sortedEdges.length - 1) / 2
        sortedEdges.forEach((edge, edgeIndex) => {
            offsets.set(getId(edge), (edgeIndex - centerIndex) * MINIMUM_EDGE_SPACING)
        })
    }
    return offsets
}

// Programmatic function to get smart step path with horizontal branching
export function getSmartStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    horizontalOffset = 0,
    borderRadius = 5,
}: {
    sourceX: number
    sourceY: number
    targetX: number
    targetY: number
    horizontalOffset?: number
    borderRadius?: number
}): [string, number, number, number, number] {
    // Define key points for the 5-segment path
    // Ensure adequate spacing between segments, especially for vertically close nodes
    const verticalDistance = targetY - sourceY

    // Handle both normal (sourceY < targetY) and inverted (sourceY > targetY) cases
    let segment1EndY, segment3EndY

    if (verticalDistance >= 0) {
        // Normal case: source above target
        segment1EndY = sourceY + 10
        segment3EndY = targetY - 10
    } else {
        // Inverted case: source below target - we need to go up then down
        segment1EndY = sourceY - 10
        segment3EndY = targetY + 10
    }

    // The x value that the main "usable" (i.e. vertical, droppable, label-able) segment of the path will travel along
    const branchX = sourceX + horizontalOffset

    let pathCommands: string[]

    const NEGLIGIBLE_DRIFT = 10

    // There are 4 types of line segments that can be drawn:

    // Case 1: Straight vertical line
    if (Math.abs(sourceX - targetX) < NEGLIGIBLE_DRIFT && horizontalOffset === 0) {
        pathCommands = [`M ${sourceX} ${sourceY}`, `L ${targetX} ${targetY}`]
    }
    // Case 2: L-shaped path that branches outwards and then straight down to target
    else if (Math.abs(targetX - branchX) < NEGLIGIBLE_DRIFT) {
        pathCommands = [
            `M ${sourceX} ${sourceY}`,
            `L ${sourceX} ${segment1EndY - borderRadius}`,
            `Q ${sourceX} ${segment1EndY} ${sourceX + (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `L ${branchX - (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `Q ${branchX} ${segment1EndY} ${branchX} ${segment1EndY + borderRadius}`,
            `L ${targetX} ${targetY}`,
        ]
    }
    // Case 3: Reverse L-shaped path that goes straight down and then branches back inwards to target
    else if (Math.abs(targetX - sourceX) > NEGLIGIBLE_DRIFT && horizontalOffset === 0) {
        pathCommands = [
            `M ${sourceX} ${sourceY}`,
            `L ${sourceX} ${segment3EndY - borderRadius}`,
            `Q ${sourceX} ${segment3EndY} ${sourceX + (targetX > sourceX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `L ${targetX - (targetX > sourceX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `Q ${targetX} ${segment3EndY} ${targetX} ${segment3EndY + borderRadius}`,
            `L ${targetX} ${targetY}`,
        ]
    }
    // Case 4: 5-segment path that branches outwards, travels down, then branches back inwards to target
    else {
        pathCommands = [
            `M ${sourceX} ${sourceY}`,
            `L ${sourceX} ${segment1EndY - borderRadius}`,
            `Q ${sourceX} ${segment1EndY} ${sourceX + (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `L ${branchX - (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `Q ${branchX} ${segment1EndY} ${branchX} ${segment1EndY + borderRadius}`,
            `L ${branchX} ${segment3EndY - borderRadius}`,
            `Q ${branchX} ${segment3EndY} ${branchX - (branchX > targetX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `L ${targetX + (branchX > targetX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `Q ${targetX} ${segment3EndY} ${targetX} ${segment3EndY + borderRadius}`,
            `L ${targetX} ${targetY}`,
        ]
    }
    const svgPath = pathCommands.join(' ')

    // Calculate label position (middle of the branched section)
    const labelX = branchX
    const labelY = segment1EndY + (segment3EndY - segment1EndY) / 2

    // Calculate offsets
    const offsetX = Math.abs(labelX - sourceX)
    const offsetY = Math.abs(labelY - sourceY)

    return [svgPath, labelX, labelY, offsetX, offsetY]
}

function EdgeLabel({ transform, label }: { transform: string; label: string }): JSX.Element {
    return (
        <LemonTag
            style={{
                transform,
            }}
            size="small"
            className="nodrag nopan absolute text-[0.45rem] font-sans font-medium"
            type="muted"
        >
            {label}
        </LemonTag>
    )
}

// Returns the first point where the path crosses targetY. The path only holds M, L and Q commands, and each
// Q only rounds a corner of borderRadius, so straight lines between command end points are close enough.
// This avoids a temporary DOM SVG, which forces a browser layout on every edge render.
export function getPointAtYValue(pathString: string, targetY: number): { x: number; y: number } {
    const points: [number, number][] = []
    for (const command of pathString.match(/[MLQ][^MLQ]*/g) ?? []) {
        const numbers = command.slice(1).trim().split(/\s+/).map(Number)
        points.push([numbers[numbers.length - 2], numbers[numbers.length - 1]])
    }

    for (let i = 1; i < points.length; i++) {
        const [x1, y1] = points[i - 1]
        const [x2, y2] = points[i]
        if ((targetY - y1) * (targetY - y2) <= 0) {
            const x = y1 === y2 ? x1 : x1 + ((targetY - y1) / (y2 - y1)) * (x2 - x1)
            return { x, y: targetY }
        }
    }

    return { x: points[0]?.[0] ?? 0, y: targetY }
}

const ANIMATION_DURATION_S = 1.5

export function SmartEdge({
    id,
    source,
    target,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
    markerStart,
    data,
    ...props
}: EdgeProps): JSX.Element {
    const { animatingEdgePair, mode } = useValues(hogFlowEditorLogic)

    const isAnimating = mode === 'test' && animatingEdgePair === `${source}->${target}`
    const animPathRef = useRef<SVGPathElement>(null)

    // Use the programmatic function to get the smart step path
    const [edgePath] = getSmartStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        horizontalOffset: (data as HogFlowActionEdge['data'])?.horizontalOffset,
    })

    useEffect(() => {
        let animation: Animation | null = null
        if (isAnimating && animPathRef.current) {
            animation = animPathRef.current.animate(
                [
                    { strokeDashoffset: '1', opacity: 0.8 },
                    { strokeDashoffset: '0', opacity: 0.8, offset: 0.7 },
                    { strokeDashoffset: '0', opacity: 0 },
                ],
                { duration: ANIMATION_DURATION_S * 1000, easing: 'ease-out', fill: 'forwards' }
            )
        }
        return () => animation?.cancel()
    }, [isAnimating, edgePath])

    const labelPoint = getPointAtYValue(edgePath, sourceY + 20)

    return (
        <>
            <BaseEdge {...props} path={edgePath} markerEnd={markerEnd} markerStart={markerStart} />
            {isAnimating && (
                <path
                    ref={animPathRef}
                    d={edgePath}
                    pathLength={1}
                    stroke="var(--success)"
                    strokeWidth={1.5}
                    fill="none"
                    strokeDasharray={1}
                    strokeDashoffset={1}
                />
            )}
            <EdgeLabelRenderer>
                {data?.label ? (
                    <EdgeLabel
                        transform={`translate(-50%, -50%) translate(${labelPoint.x}px,${labelPoint.y}px)`}
                        label={(data?.label as string) || ''}
                    />
                ) : null}
            </EdgeLabelRenderer>
        </>
    )
}

export const REACT_FLOW_EDGE_TYPES = {
    smart: SmartEdge,
}
