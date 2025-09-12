import { BaseEdge, Edge, EdgeLabelRenderer, EdgeProps, useEdges } from '@xyflow/react'

import { LemonTag } from '@posthog/lemon-ui'

import { MINIMUM_EDGE_SPACING } from '../constants'
import { HogFlowEdge } from '../types'

// Programmatic function to get smart step path with horizontal branching
// Handles both edge-to-edge spacing and edge-to-node collision avoidance
export function getSmartStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    edges,
    currentEdgeId,
    borderRadius = 5,
}: {
    sourceX: number
    sourceY: number
    targetX: number
    targetY: number
    edges: Edge[]
    currentEdgeId: string
    borderRadius?: number
}): [string, number, number, number, number] {
    // Calculate smart horizontal offset for this edge
    const calculateHorizontalOffset = (): number => {
        if (!currentEdgeId || edges.length === 0) {
            return 0
        }

        // Find the current edge if it exists
        const currentEdge = edges.find((edge) => edge.id === currentEdgeId)
        if (!currentEdge) {
            return 0
        }

        // Find edges that share the same source, including the current edge
        const conflictingEdges = edges.filter((edge) => edge.source === currentEdge.source)

        // Initialize offset based on edge conflicts
        let horizontalOffset = 0

        if (conflictingEdges.length > 0) {
            // Sort edges by source handle position to ensure consistent ordering
            const sortedEdges = conflictingEdges.sort((a, b) => {
                const aEdgeData = a.data!.edge as HogFlowEdge
                const bEdgeData = b.data!.edge as HogFlowEdge

                if (aEdgeData.type === 'branch' && bEdgeData.type === 'branch') {
                    return (aEdgeData.index || 0) - (bEdgeData.index || 0)
                }

                return aEdgeData.type === 'continue' ? 1 : -1
            })
            const edgeIndex = sortedEdges.findIndex((edge) => edge.id === currentEdgeId)
            const totalEdges = sortedEdges.length

            // Calculate horizontal offset to distribute edges evenly
            // Center the group around zero offset
            const centerIndex = (totalEdges - 1) / 2
            const offsetMultiplier = edgeIndex - centerIndex
            horizontalOffset = offsetMultiplier * MINIMUM_EDGE_SPACING
        }

        return horizontalOffset
    }

    const horizontalOffset = calculateHorizontalOffset()

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

function findXAtY(path: SVGPathElement, targetY: number, totalLength: number): number | null {
    const tolerance = 1 // Y tolerance for finding intersection
    const step = totalLength / 1000 // Sample the path at 1000 points

    for (let distance = 0; distance <= totalLength; distance += step) {
        const point = path.getPointAtLength(distance)
        if (Math.abs(point.y - targetY) <= tolerance) {
            return point.x
        }
    }

    return null
}

function getPointAtYValue(pathString: string, distance: number, targetY?: number): { x: number; y: number } {
    // Create a temporary SVG path element to calculate the point
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', pathString)
    svg.appendChild(path)
    document.body.appendChild(svg)

    try {
        const totalLength = path.getTotalLength()

        // Calculate the Y value to use
        let yValue: number
        if (targetY !== undefined) {
            yValue = targetY
        } else {
            // Calculate Y based on distance along path (25% minimum)
            const percentageDistance = totalLength * 0.25
            const effectiveDistance = Math.max(distance, percentageDistance)
            const clampedDistance = Math.min(effectiveDistance, totalLength)
            const point = path.getPointAtLength(clampedDistance)
            yValue = point.y
        }

        // Find the X coordinate at the Y value
        const xAtY = findXAtY(path, yValue, totalLength)

        return {
            x: xAtY !== null ? xAtY : 0, // Fallback to 0 if no intersection found
            y: yValue,
        }
    } finally {
        document.body.removeChild(svg)
    }
}

export function SmartEdge({
    id,
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
    const edges = useEdges()

    // Use the programmatic function to get the smart step path
    const [edgePath] = getSmartStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        edges,
        currentEdgeId: id,
    })

    const labelPoint = getPointAtYValue(edgePath, 20, sourceY + 20)

    return (
        <>
            <BaseEdge {...props} path={edgePath} markerEnd={markerEnd} markerStart={markerStart} />
            <EdgeLabelRenderer>
                {data?.label && (
                    <EdgeLabel
                        transform={`translate(-50%, -50%) translate(${labelPoint.x}px,${labelPoint.y}px)`}
                        label={(data?.label as string) || ''}
                    />
                )}
            </EdgeLabelRenderer>
        </>
    )
}

export const REACT_FLOW_EDGE_TYPES = {
    smart: SmartEdge,
}
