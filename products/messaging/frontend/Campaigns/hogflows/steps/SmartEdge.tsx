import { BaseEdge, EdgeProps, getSmoothStepPath, useEdges, useNodes, Edge, Node, Position } from '@xyflow/react'

import { NODE_HEIGHT, NODE_WIDTH } from '../constants'

const MINIMUM_EDGE_SPACING = 100 // Minimum horizontal distance between parallel edges
const NODE_COLLISION_PADDING = 50 // Minimum distance to keep from nodes

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
    nodes = [],
    currentEdgeId,
    borderRadius = 5,
}: {
    sourceX: number
    sourceY: number
    sourcePosition?: Position
    targetX: number
    targetY: number
    targetPosition?: Position
    edges?: Edge[]
    nodes?: Node[]
    currentEdgeId?: string
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

            return sharesSource || sharesTarget || sameConnection
        })

        // Initialize offset based on edge conflicts
        let horizontalOffset = 0

        if (conflictingEdges.length > 0) {
            // Create a consistent ordering for edges to prevent layout shifts
            // Sort by edge ID to ensure deterministic ordering
            const allRelevantEdges = [...conflictingEdges, currentEdge].sort((a, b) => a.id.localeCompare(b.id))

            const edgeIndex = allRelevantEdges.findIndex((edge) => edge.id === currentEdgeId)
            const totalEdges = allRelevantEdges.length

            // Calculate horizontal offset to distribute edges evenly
            // Center the group around zero offset
            const centerIndex = (totalEdges - 1) / 2
            const offsetMultiplier = edgeIndex - centerIndex
            horizontalOffset = offsetMultiplier * MINIMUM_EDGE_SPACING
        }

        // Check for node collisions and adjust offset if necessary
        // This applies even when there are no conflicting edges to avoid node overlaps
        if (nodes.length > 0) {
            horizontalOffset = avoidNodeCollisions(horizontalOffset, sourceX, sourceY, targetY, nodes)
        }

        return horizontalOffset
    }

    // Function to check and avoid collisions with other nodes
    const avoidNodeCollisions = (
        initialOffset: number,
        sourceX: number,
        sourceY: number,
        targetY: number,
        nodes: Node[]
    ): number => {
        // Calculate the proposed branch X position
        const proposedBranchX = sourceX + initialOffset

        // Define the vertical range where collision could occur (edge path area)
        const edgeMinY = Math.min(sourceY, targetY)
        const edgeMaxY = Math.max(sourceY, targetY)

        // Check each node for potential collision
        for (const node of nodes) {
            // Skip nodes that don't have position data
            if (!node.position) {
                continue
            }

            const nodeX = node.position.x
            const nodeY = node.position.y
            const nodeWidth = node.width || NODE_WIDTH // Default width from constants
            const nodeHeight = node.height || NODE_HEIGHT // Default height from constants

            // Check if node overlaps with the edge's vertical range
            const nodeMinY = nodeY
            const nodeMaxY = nodeY + nodeHeight
            const verticalOverlap = nodeMaxY >= edgeMinY && nodeMinY <= edgeMaxY

            if (verticalOverlap) {
                // Check if the proposed branch X would collide with this node
                const nodeMinX = nodeX - NODE_COLLISION_PADDING
                const nodeMaxX = nodeX + nodeWidth + NODE_COLLISION_PADDING

                if (proposedBranchX >= nodeMinX && proposedBranchX <= nodeMaxX) {
                    // Collision detected, adjust offset
                    // Choose the direction that requires less movement
                    const leftDistance = Math.abs(proposedBranchX - nodeMinX)
                    const rightDistance = Math.abs(proposedBranchX - nodeMaxX)

                    if (leftDistance < rightDistance) {
                        // Move to the left of the node
                        const newOffset = nodeMinX - sourceX
                        return Math.min(newOffset, initialOffset - MINIMUM_EDGE_SPACING)
                    }
                    // Move to the right of the node
                    const newOffset = nodeMaxX - sourceX
                    return Math.max(newOffset, initialOffset + MINIMUM_EDGE_SPACING)
                }
            }
        }

        return initialOffset
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
    const nodes = useNodes()

    // Use the programmatic function to get the smart step path
    const [edgePath] = getSmartStepPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
        edges,
        nodes,
        currentEdgeId: id,
    })

    return <BaseEdge path={edgePath} markerEnd={markerEnd} markerStart={markerStart} {...props} />
}

export const REACT_FLOW_EDGE_TYPES = {
    smart: SmartEdge,
}
