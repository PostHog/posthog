import { Edge, Position } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { NODE_GAP, NODE_HEIGHT, NODE_WIDTH } from './constants'
import type { HogFlowActionNode } from './types'

/**
 * By default, React Flow does not do any layouting of nodes or edges. This file uses the ELK Layered algorithm
 * to format node positions and (tries to) prevent edges from crossing over each other.
 *
 * https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html
 */

const getElkPortSide = (position: Position): string => {
    switch (position) {
        case Position.Top:
            return 'NORTH'
        case Position.Bottom:
            return 'SOUTH'
        case Position.Left:
            return 'WEST'
        case Position.Right:
            return 'EAST'
    }
}

const elk = new ELK()

export const getFormattedNodes = async (nodes: HogFlowActionNode[], edges: Edge[]): Promise<HogFlowActionNode[]> => {
    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': `${NODE_GAP}`,
        'elk.spacing.nodeNode': `${NODE_GAP}`,
        'elk.spacing.edgeEdge': `${NODE_GAP}`,
        'elk.spacing.edgeNode': `${NODE_GAP}`,
        'elk.direction': 'DOWN',
        'elk.layered.nodePlacement.strategy': 'SIMPLE',
        'elk.alignment': 'CENTER',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        'elk.padding': '[left=0, top=0, right=0, bottom=0]',
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: elkOptions,
        children: nodes.map((node) => {
            const handles =
                node.handles?.map((h) => ({
                    id: h.id || `${node.id}_${h.type}`,
                    properties: {
                        side: getElkPortSide(h.position),
                    },
                })) || []

            return {
                ...node,
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
                targetPosition: 'top',
                sourcePosition: 'bottom',
                properties: {
                    'org.eclipse.elk.portConstraints': 'FIXED_ORDER',
                },
                ports: [...handles],
            }
        }),
        edges: edges.map((edge) => ({
            ...edge,
            id: edge.id,
            sources: [edge.sourceHandle || edge.source],
            targets: [edge.targetHandle || edge.target],
        })) as ElkExtendedEdge[],
    }

    const layoutedGraph = await elk.layout(graph)

    /**
     * NB: ELK adjusts the positions of the nodes without taking into account the trigger node.
     * needing a consistent position. This causes jerky movement each time the graph is updated.
     * To combat that, we always give the trigger node a fixed 0,0 position and adjust the other nodes
     * relative to it.
     */

    // Find the trigger node and use its position as the offset
    const triggerNode = layoutedGraph.children?.find((node) => node.id === 'trigger_node')
    const offsetX = triggerNode?.x || 0
    const offsetY = triggerNode?.y || 0

    // Adjust all node positions relative to the trigger node
    layoutedGraph.children?.forEach((node) => {
        node.x = (node.x || 0) - offsetX
        node.y = (node.y || 0) - offsetY
    })

    return layoutedGraph.children?.map((node) => ({
        ...node,
        position: { x: node.x, y: node.y },
    })) as HogFlowActionNode[]
}
