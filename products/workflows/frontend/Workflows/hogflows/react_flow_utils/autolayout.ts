import { Edge, Position } from '@xyflow/react'
import type { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { getElk } from 'lib/elk'

import { TRIGGER_NODE_ID } from '../../workflowLogic'
import type { HogFlowActionNode } from '../types'
import { NODE_EDGE_GAP, NODE_HEIGHT, NODE_LAYER_GAP, NODE_NODE_GAP, NODE_WIDTH } from './constants'

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

export const getFormattedNodes = async (nodes: HogFlowActionNode[], edges: Edge[]): Promise<HogFlowActionNode[]> => {
    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': `${NODE_LAYER_GAP}`,
        'elk.spacing.nodeNode': `${NODE_NODE_GAP}`,
        'elk.spacing.edgeEdge': `${NODE_EDGE_GAP}`,
        'elk.spacing.edgeNode': `${NODE_EDGE_GAP}`,
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
                node.handles
                    ?.sort((a, b) => (a.id || '').localeCompare(b.id || ''))
                    .map((h) => ({
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

    const elk = await getElk()
    const layoutedGraph = await elk.layout(graph)

    /**
     * NB: ELK adjusts the positions of the nodes without taking into account the trigger node.
     * needing a consistent position. This causes jerky movement each time the graph is updated.
     * To combat that, we always give the trigger node a fixed 0,0 position and adjust the other nodes
     * relative to it.
     */

    // Find the trigger node and use its position as the offset
    const triggerNode = layoutedGraph.children?.find((node) => node.id === TRIGGER_NODE_ID)
    const offsetX = triggerNode?.x || 0
    const offsetY = triggerNode?.y || 0

    // Adjust all node positions relative to the trigger node
    layoutedGraph.children?.forEach((node) => {
        node.x = (node.x || 0) - offsetX
        node.y = (node.y || 0) - offsetY
    })

    // Rebuild from the input nodes rather than spreading elk's children: elk annotates every
    // graph element it lays out with internal bookkeeping (e.g. a `$H` hash that differs per
    // run), which would leak into ReactFlow and make deep-equal layouts look changed. Handle
    // positions come from each node's `handles`, not node-level source/targetPosition, so
    // dropping elk's copies of those fields is safe.
    const layoutedById = new Map(layoutedGraph.children?.map((child) => [child.id, child]))
    return nodes.map((node) => {
        const layouted = layoutedById.get(node.id)
        if (!layouted) {
            console.warn(`[autolayout] elk did not return a position for node "${node.id}"; defaulting to (0, 0)`)
        }
        return {
            ...node,
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
            position: { x: layouted?.x ?? 0, y: layouted?.y ?? 0 },
        }
    })
}
