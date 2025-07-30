import { BaseEdge, EdgeProps, getSmoothStepPath, useEdges, Edge, Position, EdgeLabelRenderer } from '@xyflow/react'

const MINIMUM_EDGE_SPACING = 200 // Minimum horizontal distance between parallel edges

// Programmatic function to get smart step path with horizontal branching
// Handles both edge-to-edge spacing and edge-to-node collision avoidance
export function getSmartStepPath({
    sourceX,
    sourceY,
    sourcePosition = Position.Bottom,
    targetX,
    targetY,
    targetPosition = Position.Top,
    edges,
    currentEdgeId,
    borderRadius = 5,
}: {
    sourceX: number
    sourceY: number
    sourcePosition?: Position
    targetX: number
    targetY: number
    targetPosition?: Position
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

        // Find edges that could potentially interfere with this one
        const conflictingEdges = edges.filter((edge) => {
            if (edge.id === currentEdgeId) {
                return false
            }

            // Check if edges share source or target nodes (most likely to overlap)
            const sharesSource = edge.source === currentEdge.source
            const sharesTarget = edge.target === currentEdge.target

            // Also check for edges that are connecting between the same pair of nodes
            const sameConnection =
                (edge.source === currentEdge.source && edge.target === currentEdge.target) ||
                (edge.source === currentEdge.target && edge.target === currentEdge.source)

            return (sharesSource && sharesTarget) || sameConnection
        })

        // Initialize offset based on edge conflicts
        let horizontalOffset = 0

        if (conflictingEdges.length > 0) {
            // Create a consistent ordering for edges that respects handle order
            // Sort by source handle to ensure proper left-to-right positioning
            const sortByHandle = (a: Edge, b: Edge): number => {
                const aHandle = a.sourceHandle || 'continue'
                const bHandle = b.sourceHandle || 'continue'

                // Extract handle type and index for proper sorting
                const parseHandle = (handle: string): { type: string; index: number } => {
                    if (handle === 'continue') {
                        return { type: 'continue', index: Infinity } // Continue always goes last
                    }

                    const match = handle.match(/^branch_(\d+)$/)
                    if (match) {
                        return { type: 'branch', index: parseInt(match[1]) }
                    }

                    // For any other handle types, treat as branch with high index but before continue
                    return { type: 'other', index: 1000 }
                }

                const aParsed = parseHandle(aHandle)
                const bParsed = parseHandle(bHandle)

                // Branch edges come first (sorted by index), continue edge comes last
                if (aParsed.type === 'continue' && bParsed.type !== 'continue') {
                    return 1 // a (continue) goes after b
                }
                if (bParsed.type === 'continue' && aParsed.type !== 'continue') {
                    return -1 // a goes before b (continue)
                }

                // Both are continue or both are non-continue - sort by index
                if (aParsed.index !== bParsed.index) {
                    return aParsed.index - bParsed.index
                }

                // Fallback to edge ID for deterministic ordering
                return a.id.localeCompare(b.id)
            }

            const allRelevantEdges = [...conflictingEdges, currentEdge].sort(sortByHandle)

            const edgeIndex = allRelevantEdges.findIndex((edge) => edge.id === currentEdgeId)
            const totalEdges = allRelevantEdges.length

            // Calculate horizontal offset to distribute edges evenly
            // Center the group around zero offset
            const centerIndex = (totalEdges - 1) / 2
            const offsetMultiplier = edgeIndex - centerIndex
            horizontalOffset = offsetMultiplier * MINIMUM_EDGE_SPACING
        }

        return horizontalOffset
    }

    const horizontalOffset = calculateHorizontalOffset()

    // Determine if this edge shares a source with other edges
    const currentEdge = edges.find((edge) => edge.id === currentEdgeId)
    const hasMultipleEdgesFromSource = currentEdge
        ? edges.filter((edge) => edge.source === currentEdge.source).length > 1
        : false

    // Create custom path with horizontal branching
    if (hasMultipleEdgesFromSource) {
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

        const branchX = sourceX + horizontalOffset

        let pathCommands =
            horizontalOffset === 0
                ? [
                      `M ${sourceX} ${sourceY}`, // Move to source
                      `L ${sourceX} ${segment1EndY}`, // 1. Down from source (stopping before corner)
                      `L ${branchX} ${segment3EndY}`, // 3. Down in branch (stopping before corner)
                      `L ${targetX} ${targetY}`, // 5. Down to target
                  ]
                : [
                      `M ${sourceX} ${sourceY}`, // Move to source
                      `L ${sourceX} ${segment1EndY - borderRadius}`, // 1. Down from source (stopping before corner)
                      `Q ${sourceX} ${segment1EndY} ${
                          sourceX + (branchX > sourceX ? borderRadius : -borderRadius)
                      } ${segment1EndY}`, // Rounded corner
                      `L ${branchX - (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`, // 2. Horizontal to branch position (stopping before corner)
                      `Q ${branchX} ${segment1EndY} ${branchX} ${segment1EndY + borderRadius}`, // Rounded corner
                      `L ${branchX} ${segment3EndY - borderRadius}`, // 3. Down in branch (stopping before corner)
                      `Q ${branchX} ${segment3EndY} ${
                          branchX - (branchX > targetX ? borderRadius : -borderRadius)
                      } ${segment3EndY}`, // Rounded corner
                      `L ${targetX + (branchX > targetX ? borderRadius : -borderRadius)} ${segment3EndY}`, // 4. Horizontal back to target X (stopping before corner)
                      `Q ${targetX} ${segment3EndY} ${targetX} ${segment3EndY + borderRadius}`, // Rounded corner
                      `L ${targetX} ${targetY}`, // 5. Down to target
                  ]
        const svgPath = pathCommands.join(' ')

        // Calculate label position (middle of the branched section)
        const labelX = branchX
        const labelY = segment1EndY + (segment3EndY - segment1EndY) / 2

        // Calculate offsets
        const offsetX = Math.abs(labelX - sourceX)
        const offsetY = Math.abs(labelY - sourceY)

        return [svgPath, labelX, labelY, offsetX, offsetY]
    }

    // If no offset needed, use the standard smooth step path
    return getSmoothStepPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
        offset: 20,
        borderRadius,
    })
}

function EdgeLabel({ transform, label }: { transform: string; label: string }): JSX.Element {
    return (
        <div
            style={{
                transform,
            }}
            className="nodrag nopan absolute text-[6px] bg-surface-primary/75 p-1 rounded"
        >
            {label}
        </div>
    )
}

// Function to get a point along an SVG path at a specific distance
function getPointAtDistance(pathString: string, distance: number): { x: number; y: number } {
    // Create a temporary SVG path element to calculate the point
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', pathString)
    svg.appendChild(path)
    document.body.appendChild(svg)

    try {
        const totalLength = path.getTotalLength()
        const clampedDistance = Math.min(distance, totalLength)
        const point = path.getPointAtLength(clampedDistance)
        return { x: point.x, y: point.y }
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
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
        edges,
        currentEdgeId: id,
    })

    const labelPoint = getPointAtDistance(edgePath, 50)

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
