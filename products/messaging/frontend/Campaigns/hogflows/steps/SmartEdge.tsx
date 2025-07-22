import { BaseEdge, EdgeProps, getSmoothStepPath, useEdges, Edge, Position } from '@xyflow/react'

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
        const segment1EndY = sourceY + 10 // End of first down segment
        const segment3EndY = targetY - 10 // End of middle down segment
        const branchX = sourceX + horizontalOffset

        // Create path with rounded corners using quadratic curves
        const pathCommands = [
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

    return <BaseEdge {...props} path={edgePath} markerEnd={markerEnd} markerStart={markerStart} />
}

export const REACT_FLOW_EDGE_TYPES = {
    smart: SmartEdge,
}
