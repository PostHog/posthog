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
    edges = [],
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
                        return { type: 'continue', index: -1 }
                    }
                    if (handle === 'target') {
                        return { type: 'target', index: -1 }
                    }

                    const match = handle.match(/^(.+)_(\d+)$/)
                    if (match) {
                        return { type: match[1], index: parseInt(match[2]) }
                    }
                    return { type: handle, index: -1 }
                }

                const aParsed = parseHandle(aHandle)
                const bParsed = parseHandle(bHandle)

                // First sort by type priority (continue first, then branch, then others)
                const typeOrder = { continue: 0, branch: 1, target: 2 }
                const aTypePriority = typeOrder[aParsed.type as keyof typeof typeOrder] ?? 3
                const bTypePriority = typeOrder[bParsed.type as keyof typeof typeOrder] ?? 3

                if (aTypePriority !== bTypePriority) {
                    return aTypePriority - bTypePriority
                }

                // Then sort by index for same type (branch_0, branch_1, etc.)
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

    // Create custom path with horizontal branching
    if (Math.abs(horizontalOffset) > 0) {
        // Define key points for the 5-segment path
        // Ensure adequate spacing between segments, especially for vertically close nodes
        const verticalDistance = targetY - sourceY
        const absVerticalDistance = Math.abs(verticalDistance)

        // Handle both normal (sourceY < targetY) and inverted (sourceY > targetY) cases
        let segment1EndY, segment3EndY

        if (verticalDistance >= 0) {
            // Normal case: source above target
            segment1EndY = sourceY + Math.max(10, absVerticalDistance * 0.2)
            segment3EndY = targetY - Math.max(10, absVerticalDistance * 0.2)
        } else {
            // Inverted case: source below target - we need to go up then down
            segment1EndY = sourceY - Math.max(10, absVerticalDistance * 0.2)
            segment3EndY = targetY + Math.max(10, absVerticalDistance * 0.2)
        }

        const branchX = sourceX + horizontalOffset

        const pathCommands = [
            `M ${sourceX} ${sourceY}`, // Move to source
            `L ${sourceX} ${segment1EndY}`, // 1. Vertical from source
            `L ${branchX} ${segment1EndY}`, // 2. Horizontal to branch position
            `L ${branchX} ${segment3EndY}`, // 3. Vertical in branch
            `L ${targetX} ${segment3EndY}`, // 4. Horizontal back to target X
            `L ${targetX} ${targetY}`, // 5. Vertical to target
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
                position: 'absolute',
                background: 'rgba(255, 255, 255, 0.75)',
                padding: '5px 10px',
                color: '#ff5050',
                fontSize: 12,
                fontWeight: 700,
                transform,
            }}
            className="nodrag nopan"
        >
            {label}
        </div>
    )
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

    return (
        <>
            <BaseEdge {...props} path={edgePath} markerEnd={markerEnd} markerStart={markerStart} />
            <EdgeLabelRenderer>
                {data?.label && (
                    <EdgeLabel
                        transform={`translate(-50%, 0%) translate(${sourceX}px,${sourceY}px)`}
                        label={data?.label || ''}
                    />
                )}
            </EdgeLabelRenderer>
        </>
    )
}

export const REACT_FLOW_EDGE_TYPES = {
    smart: SmartEdge,
}
